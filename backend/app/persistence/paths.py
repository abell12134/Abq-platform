from __future__ import annotations

import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import aiofiles

from app.config import settings
from app.models.analysis import AnalysisPathIndexEntry, PathStatus

# SSE 断开 / 后端热重载后，running 不会自动收口；超过该分钟数视为已中断
STALE_RUNNING_MINUTES = 10


class PathStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or settings.data_dir
        self.paths_dir = self.data_dir / "paths"
        self.index_file = self.paths_dir / "_index.json"

    async def ensure(self) -> None:
        self.paths_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_file.exists():
            await self._write_index([])

    async def list_entries(self) -> list[AnalysisPathIndexEntry]:
        await self.ensure()
        await self.reconcile_stale_running()
        raw = await self._read_index()
        return [AnalysisPathIndexEntry.model_validate(item) for item in raw]

    def _last_activity_mtime(self, path_id: str) -> float:
        path_dir = self._path_dir(path_id)
        mtimes: list[float] = []
        meta = path_dir / "meta.json"
        if meta.exists():
            mtimes.append(meta.stat().st_mtime)
        steps_dir = path_dir / "steps"
        if steps_dir.exists():
            for fp in steps_dir.glob("*.json"):
                mtimes.append(fp.stat().st_mtime)
        return max(mtimes) if mtimes else 0.0

    async def reconcile_stale_running(self, *, idle_minutes: int = STALE_RUNNING_MINUTES) -> int:
        """Mark long-idle `running` paths as `error` (client disconnected mid-stream)."""
        raw = await self._read_index()
        entries = [AnalysisPathIndexEntry.model_validate(item) for item in raw]
        cutoff = time.time() - idle_minutes * 60
        changed = 0
        for entry in entries:
            if entry.status != "running":
                continue
            if self._last_activity_mtime(entry.id) >= cutoff:
                continue
            entry.status = "error"
            entry.updated = datetime.now(UTC).isoformat()
            changed += 1
            await self._sync_meta(entry)
        if changed:
            await self._write_index([e.model_dump() for e in entries])
        return changed

    async def touch_activity(self, path_id: str) -> None:
        """Bump index `updated` without reconcile — keeps long LLM runs from looking stale."""
        raw = await self._read_index()
        entries = [AnalysisPathIndexEntry.model_validate(item) for item in raw]
        now = datetime.now(UTC).isoformat()
        touched = False
        for entry in entries:
            if entry.id == path_id:
                entry.updated = now
                touched = True
                break
        if touched:
            await self._write_index([e.model_dump() for e in entries])

    async def is_actively_running(self, path_id: str, *, idle_minutes: int = STALE_RUNNING_MINUTES) -> bool:
        from app.orchestration.analysis_registry import analysis_registry

        if analysis_registry.is_active(path_id):
            return True
        entry = await self.get_entry_raw(path_id)
        if entry is None or entry.status != "running":
            return False
        return self._last_activity_mtime(path_id) >= time.time() - idle_minutes * 60

    async def get_entry_raw(self, path_id: str) -> AnalysisPathIndexEntry | None:
        """Lookup without reconcile — internal use."""
        raw = await self._read_index()
        for item in raw:
            if item.get("id") == path_id:
                return AnalysisPathIndexEntry.model_validate(item)
        return None

    async def create_entry(
        self,
        *,
        title: str,
        kind: str,
        realm: str,
        status: PathStatus = "running",
        target: str | None = None,
        focus: str | None = None,
    ) -> AnalysisPathIndexEntry:
        now = datetime.now(UTC).isoformat()
        entry = AnalysisPathIndexEntry(
            id=uuid4().hex[:12],
            title=title[:80] or "新对话",
            kind=kind,  # type: ignore[arg-type]
            realm=realm,  # type: ignore[arg-type]
            status=status,
            created=now,
            updated=now,
            target=target,
            focus=(focus or "").strip() or None,
        )
        await self.ensure()
        raw = await self._read_index()
        entries = [AnalysisPathIndexEntry.model_validate(item) for item in raw]
        entries.insert(0, entry)
        await self._write_index([e.model_dump() for e in entries])
        path_dir = self.paths_dir / entry.id
        path_dir.mkdir(parents=True, exist_ok=True)
        meta_file = path_dir / "meta.json"
        async with aiofiles.open(meta_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(entry.model_dump(), ensure_ascii=False, indent=2))
        return entry

    async def get_entry(self, path_id: str) -> AnalysisPathIndexEntry | None:
        await self.reconcile_stale_running()
        raw = await self._read_index()
        for item in raw:
            if item.get("id") == path_id:
                return AnalysisPathIndexEntry.model_validate(item)
        return None

    async def _sync_meta(self, entry: AnalysisPathIndexEntry) -> None:
        meta_file = self._path_dir(entry.id) / "meta.json"
        async with aiofiles.open(meta_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(entry.model_dump(), ensure_ascii=False, indent=2))

    async def update_status(self, path_id: str, status: PathStatus) -> None:
        raw = await self._read_index()
        entries = [AnalysisPathIndexEntry.model_validate(item) for item in raw]
        now = datetime.now(UTC).isoformat()
        changed: AnalysisPathIndexEntry | None = None
        for entry in entries:
            if entry.id == path_id:
                entry.status = status
                entry.updated = now
                changed = entry
                break
        if changed:
            await self._write_index([e.model_dump() for e in entries])
            await self._sync_meta(changed)

    async def update_session_meta(
        self,
        path_id: str,
        *,
        focus: str | None = None,
        target: str | None = None,
    ) -> AnalysisPathIndexEntry | None:
        raw = await self._read_index()
        entries = [AnalysisPathIndexEntry.model_validate(item) for item in raw]
        now = datetime.now(UTC).isoformat()
        changed: AnalysisPathIndexEntry | None = None
        for entry in entries:
            if entry.id != path_id:
                continue
            if focus is not None:
                entry.focus = focus.strip() or None
            if target is not None:
                entry.target = target or None
            entry.updated = now
            changed = entry
            break
        if changed is None:
            return None
        await self._write_index([e.model_dump() for e in entries])
        await self._sync_meta(changed)
        return changed

    async def update_memory_meta(
        self,
        path_id: str,
        *,
        symbols: list[str] | None = None,
        judge_stance: str | None = None,
        judge_one_liner: str | None = None,
        data_as_of: str | None = None,
        tags: list[str] | None = None,
    ) -> AnalysisPathIndexEntry | None:
        raw = await self._read_index()
        entries = [AnalysisPathIndexEntry.model_validate(item) for item in raw]
        now = datetime.now(UTC).isoformat()
        changed: AnalysisPathIndexEntry | None = None
        for entry in entries:
            if entry.id != path_id:
                continue
            if symbols is not None:
                entry.symbols = symbols
            if judge_stance is not None:
                entry.judge_stance = judge_stance
            if judge_one_liner is not None:
                entry.judge_one_liner = judge_one_liner
            if data_as_of is not None:
                entry.data_as_of = data_as_of
            if tags is not None:
                entry.tags = tags
            entry.updated = now
            changed = entry
            break
        if changed is None:
            return None
        await self._write_index([e.model_dump() for e in entries])
        await self._sync_meta(changed)
        return changed

    async def search_entries(
        self,
        *,
        symbol: str | None = None,
        kind: str | None = None,
        since: str | None = None,
        limit: int = 10,
    ) -> list[AnalysisPathIndexEntry]:
        entries = await self.list_entries()
        out: list[AnalysisPathIndexEntry] = []
        sym = symbol.lower() if symbol else None
        for entry in entries:
            if entry.status != "done":
                continue
            if kind and entry.kind != kind:
                continue
            if since and entry.updated < since:
                continue
            if sym:
                entry_syms = {s.lower() for s in entry.symbols}
                if entry.target and entry.target.lower() == sym:
                    pass
                elif sym not in entry_syms:
                    continue
            if not entry.judge_one_liner and not entry.judge_stance:
                continue
            out.append(entry)
        out.sort(key=lambda e: e.updated, reverse=True)
        return out[:limit]

    def _path_dir(self, path_id: str) -> Path:
        return self.paths_dir / path_id

    async def next_step_seq(self, path_id: str) -> int:
        steps_dir = self._path_dir(path_id) / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)
        existing = list(steps_dir.glob("*.json"))
        return len(existing) + 1

    async def append_step(self, path_id: str, step: dict, seq: int | None = None) -> int:
        steps_dir = self._path_dir(path_id) / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)
        if seq is None:
            seq = await self.next_step_seq(path_id)
        fname = f"{seq:02d}-{step.get('agent', 'step')[:24]}.json"
        step_file = steps_dir / fname
        tmp = step_file.with_suffix(".tmp")
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(json.dumps(step, ensure_ascii=False, indent=2))
        os.replace(tmp, step_file)
        now = datetime.now(UTC).isoformat()
        raw = await self._read_index()
        entries = [AnalysisPathIndexEntry.model_validate(item) for item in raw]
        for entry in entries:
            if entry.id == path_id:
                entry.updated = now
                break
        await self._write_index([e.model_dump() for e in entries])
        return seq

    async def load_steps(self, path_id: str) -> list[dict]:
        steps_dir = self._path_dir(path_id) / "steps"
        if not steps_dir.exists():
            return []
        files = sorted(steps_dir.glob("*.json"))
        out: list[dict] = []
        for fp in files:
            async with aiofiles.open(fp, encoding="utf-8") as f:
                out.append(json.loads(await f.read()))
        return out

    async def save_snapshot(self, path_id: str, snapshot: dict) -> str:
        context_dir = self._path_dir(path_id) / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(context_dir.glob("snapshot-*.json"))
        n = len(existing) + 1
        fname = context_dir / f"snapshot-{n:03d}.json"
        async with aiofiles.open(fname, "w", encoding="utf-8") as f:
            await f.write(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return fname.name

    async def load_snapshots(self, path_id: str) -> list[dict]:
        context_dir = self._path_dir(path_id) / "context"
        if not context_dir.exists():
            return []
        out: list[dict] = []
        for fp in sorted(context_dir.glob("snapshot-*.json")):
            async with aiofiles.open(fp, encoding="utf-8") as f:
                out.append(json.loads(await f.read()))
        return out

    async def save_reports(self, path_id: str, reports: dict) -> None:
        path_dir = self._path_dir(path_id)
        path_dir.mkdir(parents=True, exist_ok=True)
        reports_file = path_dir / "reports.json"
        async with aiofiles.open(reports_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(reports, ensure_ascii=False, indent=2))

    async def load_reports(self, path_id: str) -> dict | None:
        reports_file = self._path_dir(path_id) / "reports.json"
        if not reports_file.exists():
            return None
        async with aiofiles.open(reports_file, encoding="utf-8") as f:
            return json.loads(await f.read())

    async def get_path(self, path_id: str) -> dict | None:
        meta_file = self._path_dir(path_id) / "meta.json"
        if not meta_file.exists():
            return None
        async with aiofiles.open(meta_file, encoding="utf-8") as f:
            meta = json.loads(await f.read())
        steps = await self.load_steps(path_id)
        return {"meta": meta, "steps": steps}

    async def delete_entry(self, path_id: str) -> bool:
        entries = await self.list_entries()
        kept = [e for e in entries if e.id != path_id]
        if len(kept) == len(entries):
            return False
        await self._write_index([e.model_dump() for e in kept])
        path_dir = self._path_dir(path_id)
        if path_dir.exists():
            shutil.rmtree(path_dir)
        return True

    async def _read_index(self) -> list[dict]:
        async with aiofiles.open(self.index_file, encoding="utf-8") as f:
            content = await f.read()
        data = json.loads(content or "[]")
        return data if isinstance(data, list) else []

    async def _write_index(self, items: list[dict]) -> None:
        tmp = self.index_file.with_suffix(".tmp")
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(json.dumps(items, ensure_ascii=False, indent=2))
        os.replace(tmp, self.index_file)


path_store = PathStore()
