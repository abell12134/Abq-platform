from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.agents.specs import AgentSpec
from app.config import settings

if TYPE_CHECKING:
    from app.models.analysis import AnalyzeRequest

_AGENTS_DIR = settings.data_dir / "agents"
_PROMPTS_DIR = settings.data_dir / "prompts"


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"invalid yaml root in {path}")
    return data


def load_prompt(prompt_id: str) -> dict[str, str]:
    path = _PROMPTS_DIR / f"{prompt_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"prompt not found: {prompt_id}")
    data = _read_yaml(path)
    return {
        "persona": str(data.get("persona", "")).strip(),
        "instructions": str(data.get("instructions", "")).strip(),
    }


def load_agent(agent_id: str, *, prompt_id: str | None = None) -> AgentSpec:
    path = _AGENTS_DIR / f"{agent_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"agent not found: {agent_id}")
    data = _read_yaml(path)
    pid = (prompt_id or "").strip() or str(data["prompt_id"])
    prompt = load_prompt(pid)
    return AgentSpec(
        id=str(data["id"]),
        name=str(data.get("name", agent_id)),
        model_tier=data.get("model_tier", "primary"),
        tool_names=list(data.get("tools") or []),
        persona=prompt["persona"],
        instructions=prompt["instructions"],
        prompt_id=pid,
    )


_ROUTED_PROMPTS: dict[str, str] = {
    "sentiment-instructions": "sentiment",
    "tech-instructions": "tech",
    "fundamental-instructions": "fundamental",
    "market-instructions": "market",
    "portfolio-instructions": "portfolio",
}


def prompt_id_for_agent(agent_id: str, req: AnalyzeRequest | None) -> str | None:
    if req is None or not req.prompt_id:
        return None
    if _ROUTED_PROMPTS.get(req.prompt_id) == agent_id:
        return req.prompt_id
    return None


def list_agents() -> list[dict[str, Any]]:
    from app.persistence.library_store import library_store

    return [a.model_dump() for a in library_store.list_agents()]


def list_prompts() -> list[dict[str, Any]]:
    from app.persistence.library_store import library_store

    return [p.model_dump() for p in library_store.list_prompts()]
