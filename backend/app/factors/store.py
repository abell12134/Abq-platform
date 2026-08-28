"""File-backed factor library: catalog/*.yaml + discovered.yaml + _index.json."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.config import settings
from app.factors.ir import (
    FactorExprError,
    expr_from_dict,
    expr_to_dict,
    parse_formula,
    print_expr,
    validate_factor_id,
)
from app.factors.seeds import seed_payloads
from app.models.factors import FactorCreate, FactorRecord, FactorUpdate

STATUSES = {
    "candidate",
    "rejected",
    "passed_auto",
    "paper_tracking",
    "frozen",
    "retired",
    "live",
}


class FactorStoreError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


class FactorStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        root = data_dir or settings.data_dir
        self.root = root / "factors"
        self.catalog_dir = self.root / "catalog"
        self.discovered_path = self.root / "discovered.yaml"
        self.index_path = self.root / "_index.json"
        self.runs_dir = self.root / "runs"

    def ensure(self) -> None:
        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        if not self.discovered_path.exists():
            _atomic_write_text(self.discovered_path, _dump_yaml({"factors": {}}))
        for payload in seed_payloads():
            path = self.catalog_dir / f"{payload['id']}.yaml"
            if path.exists():
                continue
            rec = self._normalize(payload, builtin=True, created=_now())
            _atomic_write_text(path, _dump_yaml(rec.model_dump()))
        self._rebuild_index()

    def _normalize(self, data: dict[str, Any], *, builtin: bool, created: str | None = None) -> FactorRecord:
        factor_id = str(data.get("id", "")).strip()
        validate_factor_id(factor_id)
        formula = str(data.get("formula", "")).strip()
        expr_raw = data.get("expr")
        if expr_raw:
            expr = expr_from_dict(expr_raw)
        elif formula:
            expr = parse_formula(formula)
        else:
            raise FactorStoreError("缺少 formula / expr")
        formula = print_expr(expr)
        now = _now()
        return FactorRecord(
            id=factor_id,
            name=str(data.get("name") or factor_id),
            origin=data.get("origin", "manual"),
            status=data.get("status", "candidate"),
            theme=list(data.get("theme") or []),
            universe=data.get("universe", "csi300"),
            formula=formula,
            expr=expr_to_dict(expr),
            hypothesis=str(data.get("hypothesis") or ""),
            forward_days=int(data.get("forward_days") or 5),
            metrics=dict(data.get("metrics") or {}),
            reject_reason=str(data.get("reject_reason") or ""),
            builtin=builtin or bool(data.get("builtin")),
            created_at=str(data.get("created_at") or created or now),
            updated_at=str(data.get("updated_at") or now),
        )

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise FactorStoreError(f"invalid yaml: {path}")
        return raw

    def _load_catalog(self) -> dict[str, FactorRecord]:
        out: dict[str, FactorRecord] = {}
        if not self.catalog_dir.is_dir():
            return out
        for path in sorted(self.catalog_dir.glob("*.yaml")):
            data = self._read_yaml(path)
            rec = self._normalize(data, builtin=True)
            out[rec.id] = rec
        return out

    def _load_discovered(self) -> dict[str, FactorRecord]:
        if not self.discovered_path.exists():
            return {}
        data = self._read_yaml(self.discovered_path)
        factors = data.get("factors") or {}
        out: dict[str, FactorRecord] = {}
        if not isinstance(factors, dict):
            return out
        for fid, raw in factors.items():
            if not isinstance(raw, dict):
                continue
            raw = {**raw, "id": raw.get("id", fid)}
            rec = self._normalize(raw, builtin=False)
            out[rec.id] = rec
        return out

    def _save_discovered(self, items: dict[str, FactorRecord]) -> None:
        payload = {"factors": {k: v.model_dump() for k, v in sorted(items.items())}}
        _atomic_write_text(self.discovered_path, _dump_yaml(payload))
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        rows = []
        for rec in self._merged_records():
            ic = (rec.metrics or {}).get("ic_stats") or {}
            rows.append(
                {
                    "id": rec.id,
                    "name": rec.name,
                    "origin": rec.origin,
                    "status": rec.status,
                    "universe": rec.universe,
                    "builtin": rec.builtin,
                    "ic_mean": ic.get("ic_mean"),
                    "updated_at": rec.updated_at,
                }
            )
        _atomic_write_text(
            self.index_path,
            json.dumps({"factors": rows}, ensure_ascii=False, indent=2) + "\n",
        )

    def _merged_records(self) -> list[FactorRecord]:
        merged = {**self._load_discovered(), **self._load_catalog()}
        items = list(merged.values())
        items.sort(key=lambda f: (0 if f.builtin else 1, f.id))
        return items

    def list_factors(
        self,
        *,
        status: str | None = None,
        origin: str | None = None,
        theme: str | None = None,
    ) -> list[FactorRecord]:
        self.ensure()
        items = self._merged_records()
        if status:
            items = [f for f in items if f.status == status]
        if origin:
            items = [f for f in items if f.origin == origin]
        if theme:
            items = [f for f in items if theme in (f.theme or [])]
        items.sort(key=lambda f: (0 if f.builtin else 1, f.id))
        return items

    def get(self, factor_id: str) -> FactorRecord | None:
        self.ensure()
        cat = self._load_catalog()
        if factor_id in cat:
            return cat[factor_id]
        return self._load_discovered().get(factor_id)

    def create(self, body: FactorCreate) -> FactorRecord:
        self.ensure()
        validate_factor_id(body.id)
        if self.get(body.id) is not None:
            raise FactorStoreError(f"因子已存在: {body.id}")
        try:
            expr = parse_formula(body.formula)
        except FactorExprError as exc:
            raise FactorStoreError(str(exc)) from exc

        now = _now()
        rec = FactorRecord(
            id=body.id,
            name=body.name,
            origin=body.origin if body.origin != "catalog" else "manual",
            status="candidate",
            theme=body.theme,
            universe=body.universe,
            formula=print_expr(expr),
            expr=expr_to_dict(expr),
            hypothesis=body.hypothesis,
            builtin=False,
            created_at=now,
            updated_at=now,
        )
        discovered = self._load_discovered()
        discovered[rec.id] = rec
        self._save_discovered(discovered)
        return rec

    def update(self, factor_id: str, body: FactorUpdate) -> FactorRecord:
        existing = self.get(factor_id)
        if existing is None:
            raise FileNotFoundError(factor_id)
        if existing.builtin and body.formula is not None:
            raise FactorStoreError("内置种子不可改公式")
        data = existing.model_dump()
        if body.name is not None:
            data["name"] = body.name
        if body.hypothesis is not None:
            data["hypothesis"] = body.hypothesis
        if body.status is not None:
            if body.status not in STATUSES:
                raise FactorStoreError(f"非法状态: {body.status}")
            data["status"] = body.status
        if body.theme is not None:
            data["theme"] = body.theme
        if body.formula is not None:
            try:
                expr = parse_formula(body.formula)
            except FactorExprError as exc:
                raise FactorStoreError(str(exc)) from exc
            data["formula"] = print_expr(expr)
            data["expr"] = expr_to_dict(expr)
        data["updated_at"] = _now()
        rec = self._normalize(data, builtin=existing.builtin, created=existing.created_at)
        if existing.builtin:
            _atomic_write_text(self.catalog_dir / f"{factor_id}.yaml", _dump_yaml(rec.model_dump()))
            self._rebuild_index()
        else:
            discovered = self._load_discovered()
            discovered[factor_id] = rec
            self._save_discovered(discovered)
        return rec

    def save_eval(self, rec: FactorRecord) -> FactorRecord:
        data = rec.model_dump()
        data["updated_at"] = _now()
        stored = self._normalize(data, builtin=rec.builtin, created=rec.created_at)
        if rec.builtin:
            _atomic_write_text(self.catalog_dir / f"{rec.id}.yaml", _dump_yaml(stored.model_dump()))
            self._rebuild_index()
        else:
            discovered = self._load_discovered()
            discovered[rec.id] = stored
            self._save_discovered(discovered)
        return stored

    def put_discovered(self, rec: FactorRecord) -> FactorRecord:
        """Insert or replace a discovered (non-catalog) factor record."""
        self.ensure()
        if rec.builtin:
            raise FactorStoreError("内置种子请用 save_eval")
        validate_factor_id(rec.id)
        data = rec.model_dump()
        data["updated_at"] = _now()
        stored = self._normalize(data, builtin=False, created=rec.created_at)
        discovered = self._load_discovered()
        discovered[stored.id] = stored
        self._save_discovered(discovered)
        return stored

    def delete(self, factor_id: str) -> bool:
        existing = self.get(factor_id)
        if existing is None:
            return False
        if existing.builtin or existing.origin == "catalog":
            raise FactorStoreError("种子因子不可删除")
        discovered = self._load_discovered()
        if factor_id not in discovered:
            return False
        del discovered[factor_id]
        self._save_discovered(discovered)
        return True


factor_store = FactorStore()
