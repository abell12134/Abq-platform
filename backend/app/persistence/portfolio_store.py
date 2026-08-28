"""File-backed portfolio / watchlist store."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.models.portfolio import (
    PortfolioCreate,
    PortfolioMember,
    PortfolioRecord,
    PortfolioSnapshot,
    PortfolioUpdate,
    TrackRecord,
    TrackRecordCreate,
)

DEFAULT_PORTFOLIO_ID = "default"
DEFAULT_MEMBERS = [
    PortfolioMember(symbol="sh600519", note="茅台"),
    PortfolioMember(symbol="sh600363", note="联创光电"),
    PortfolioMember(symbol="sz300750", note="宁德时代"),
]


class PortfolioStoreError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class PortfolioStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        root = data_dir or settings.data_dir
        self.root = root / "portfolios"
        self.index_path = self.root / "_index.json"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        default_dir = self.root / DEFAULT_PORTFOLIO_ID
        meta_path = default_dir / "meta.json"
        if not meta_path.exists():
            now = _now()
            rec = PortfolioRecord(
                id=DEFAULT_PORTFOLIO_ID,
                name="默认自选",
                realm="a-share",
                members=DEFAULT_MEMBERS,
                created_at=now,
                updated_at=now,
            )
            self._save_record(rec)
        self._rebuild_index()

    def _portfolio_dir(self, portfolio_id: str) -> Path:
        return self.root / portfolio_id

    def _load_meta(self, portfolio_id: str) -> PortfolioRecord | None:
        path = self._portfolio_dir(portfolio_id) / "meta.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return PortfolioRecord.model_validate(data)

    def _save_record(self, rec: PortfolioRecord) -> None:
        directory = self._portfolio_dir(rec.id)
        directory.mkdir(parents=True, exist_ok=True)
        _atomic_write(directory / "meta.json", rec.model_dump_json(indent=2) + "\n")
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        rows: list[dict] = []
        for path in sorted(self.root.iterdir()):
            if not path.is_dir() or path.name.startswith("_"):
                continue
            rec = self._load_meta(path.name)
            if rec:
                rows.append(
                    {
                        "id": rec.id,
                        "name": rec.name,
                        "realm": rec.realm,
                        "member_count": len(rec.members),
                        "updated_at": rec.updated_at,
                    }
                )
        _atomic_write(self.index_path, json.dumps({"portfolios": rows}, ensure_ascii=False, indent=2) + "\n")

    def list_portfolios(self) -> list[PortfolioRecord]:
        self.ensure()
        out: list[PortfolioRecord] = []
        for path in sorted(self.root.iterdir()):
            if not path.is_dir() or path.name.startswith("_"):
                continue
            rec = self._load_meta(path.name)
            if rec:
                out.append(rec)
        return out

    def get(self, portfolio_id: str) -> PortfolioRecord | None:
        self.ensure()
        return self._load_meta(portfolio_id)

    def create(self, body: PortfolioCreate) -> PortfolioRecord:
        self.ensure()
        if self.get(body.id):
            raise PortfolioStoreError(f"组合已存在: {body.id}")
        now = _now()
        rec = PortfolioRecord(
            id=body.id,
            name=body.name,
            realm=body.realm,
            members=body.members,
            created_at=now,
            updated_at=now,
        )
        self._save_record(rec)
        return rec

    def update(self, portfolio_id: str, body: PortfolioUpdate) -> PortfolioRecord:
        existing = self.get(portfolio_id)
        if existing is None:
            raise FileNotFoundError(portfolio_id)
        data = existing.model_dump()
        if body.name is not None:
            data["name"] = body.name
        if body.members is not None:
            data["members"] = [m.model_dump() if isinstance(m, PortfolioMember) else m for m in body.members]
        data["updated_at"] = _now()
        rec = PortfolioRecord.model_validate(data)
        self._save_record(rec)
        return rec

    def delete(self, portfolio_id: str) -> None:
        if portfolio_id == DEFAULT_PORTFOLIO_ID:
            raise PortfolioStoreError("默认自选组合不可删除")
        directory = self._portfolio_dir(portfolio_id)
        if not directory.exists():
            raise FileNotFoundError(portfolio_id)
        import shutil

        shutil.rmtree(directory)
        self._rebuild_index()

    def symbols_for(self, portfolio_id: str | None, *, fallback: list[str] | None = None) -> list[str]:
        pid = (portfolio_id or "").strip() or DEFAULT_PORTFOLIO_ID
        rec = self.get(pid)
        if rec and rec.members:
            return [m.symbol for m in rec.members]
        if fallback:
            return fallback
        return [m.symbol for m in DEFAULT_MEMBERS]

    def _tracks_path(self, portfolio_id: str) -> Path:
        return self._portfolio_dir(portfolio_id) / "track-records.json"

    def list_tracks(self, portfolio_id: str) -> list[TrackRecord]:
        self.ensure()
        path = self._tracks_path(portfolio_id)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("records") or []
        return [TrackRecord.model_validate(r) for r in rows]

    def _save_tracks(self, portfolio_id: str, records: list[TrackRecord]) -> None:
        path = self._tracks_path(portfolio_id)
        payload = {"records": [r.model_dump() for r in records]}
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    def append_track(
        self,
        portfolio_id: str,
        snapshot: PortfolioSnapshot,
        body: TrackRecordCreate | None = None,
    ) -> TrackRecord:
        rec = self.get(portfolio_id)
        if rec is None:
            raise FileNotFoundError(portfolio_id)
        now = _now()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        best = snapshot.best_today
        worst = snapshot.worst_today
        row = TrackRecord(
            id=uuid4().hex[:12],
            date=today,
            recorded_at=now,
            equal_weight_pct_1d=snapshot.equal_weight_pct_1d,
            equal_weight_chg_5d=snapshot.equal_weight_chg_5d,
            member_count=snapshot.member_count,
            best_symbol=best.symbol if best else None,
            best_name=best.name if best else None,
            best_pct=best.pct_change if best else None,
            worst_symbol=worst.symbol if worst else None,
            worst_name=worst.name if worst else None,
            worst_pct=worst.pct_change if worst else None,
            note=(body.note if body else None),
            path_id=(body.path_id if body else None),
        )
        existing = self.list_tracks(portfolio_id)
        existing.insert(0, row)
        self._save_tracks(portfolio_id, existing[:120])
        return row


portfolio_store = PortfolioStore()
