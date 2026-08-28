from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from app.config import settings
from app.models.library import (
    AgentCreate,
    AgentRecord,
    AgentUpdate,
    PromptCreate,
    PromptRecord,
    PromptUpdate,
    ToolRecord,
)
from app.tools.langchain_tools import TOOL_BY_NAME

_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_BANNED_WORDS = re.compile(r"必涨|稳赚|保证收益|一定赚钱|满仓干|梭哈")
_KNOWN_VARS = frozenset(
    {"model", "as_of", "realm", "symbol", "company_name", "focus", "path_kind", "tool"}
)

_BUILTIN_PROMPT_IDS = frozenset(
    {
        "bear-instructions",
        "bull-instructions",
        "compaction-instructions",
        "extract-instructions",
        "format-instructions",
        "fundamental-instructions",
        "judge-instructions",
        "market-instructions",
        "portfolio-instructions",
        "sentiment-instructions",
        "supervisor-instructions",
        "tech-instructions",
    }
)

_BUILTIN_AGENT_IDS = frozenset(
    {
        "bear",
        "bull",
        "extract",
        "format",
        "fundamental",
        "judge",
        "market",
        "portfolio",
        "sentiment",
        "supervisor",
        "tech",
    }
)


class LibraryValidationError(ValueError):
    pass


class LibraryStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        root = data_dir or settings.data_dir
        self.agents_dir = root / "agents"
        self.prompts_dir = root / "prompts"

    def ensure(self) -> None:
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.prompts_dir.mkdir(parents=True, exist_ok=True)

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise LibraryValidationError(f"invalid yaml root in {path}")
        return data

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
        os.replace(tmp, path)

    def _validate_id(self, item_id: str) -> None:
        if not _ID_RE.match(item_id):
            raise LibraryValidationError(
                "id 须以小写字母开头，仅含小写字母、数字与连字符",
            )

    def _validate_prompt_text(self, persona: str, instructions: str) -> None:
        combined = f"{persona}\n{instructions}"
        if _BANNED_WORDS.search(combined):
            raise LibraryValidationError("提示词含禁词（必涨/稳赚/保证收益等），请修改后保存")
        unknown = set(re.findall(r"\{\{(\w+)\}\}", combined)) - _KNOWN_VARS
        if unknown:
            raise LibraryValidationError(
                f"未知模板变量: {', '.join(sorted(unknown))}。"
                f"可用: {', '.join(sorted(_KNOWN_VARS))}",
            )

    def _validate_tools(self, tools: list[str]) -> None:
        unknown = [t for t in tools if t not in TOOL_BY_NAME]
        if unknown:
            raise LibraryValidationError(f"未知工具: {', '.join(unknown)}")

    def _prompt_from_file(self, path: Path) -> PromptRecord:
        data = self._read_yaml(path)
        prompt_id = str(data.get("id", path.stem))
        return PromptRecord(
            id=prompt_id,
            category=data.get("category", "analysis"),
            persona=str(data.get("persona", "")).rstrip(),
            instructions=str(data.get("instructions", "")).rstrip(),
            complete=bool(data.get("complete", False)),
            builtin=prompt_id in _BUILTIN_PROMPT_IDS,
        )

    def _agent_from_file(self, path: Path) -> AgentRecord:
        data = self._read_yaml(path)
        agent_id = str(data.get("id", path.stem))
        return AgentRecord(
            id=agent_id,
            name=str(data.get("name", agent_id)),
            model_tier=data.get("model_tier", "primary"),
            tools=list(data.get("tools") or []),
            prompt_id=str(data.get("prompt_id", "")),
            status=data.get("status", "active"),
            builtin=agent_id in _BUILTIN_AGENT_IDS,
        )

    # --- Prompts ---

    def list_prompts(self) -> list[PromptRecord]:
        self.ensure()
        if not self.prompts_dir.is_dir():
            return []
        return [self._prompt_from_file(p) for p in sorted(self.prompts_dir.glob("*.yaml"))]

    def get_prompt(self, prompt_id: str) -> PromptRecord | None:
        path = self.prompts_dir / f"{prompt_id}.yaml"
        if not path.is_file():
            return None
        return self._prompt_from_file(path)

    def create_prompt(self, body: PromptCreate) -> PromptRecord:
        self.ensure()
        self._validate_id(body.id)
        path = self.prompts_dir / f"{body.id}.yaml"
        if path.exists():
            raise LibraryValidationError(f"提示词已存在: {body.id}")
        self._validate_prompt_text(body.persona, body.instructions)
        data = {
            "id": body.id,
            "category": body.category,
            "complete": body.complete,
            "persona": body.persona.rstrip() + ("\n" if body.persona and not body.persona.endswith("\n") else ""),
            "instructions": body.instructions.rstrip()
            + ("\n" if body.instructions and not body.instructions.endswith("\n") else ""),
        }
        self._write_yaml(path, data)
        return self._prompt_from_file(path)

    def update_prompt(self, prompt_id: str, body: PromptUpdate) -> PromptRecord:
        existing = self.get_prompt(prompt_id)
        if existing is None:
            raise FileNotFoundError(prompt_id)
        persona = body.persona if body.persona is not None else existing.persona
        instructions = (
            body.instructions if body.instructions is not None else existing.instructions
        )
        self._validate_prompt_text(persona, instructions)
        data = {
            "id": prompt_id,
            "category": body.category if body.category is not None else existing.category,
            "complete": body.complete if body.complete is not None else existing.complete,
            "persona": persona.rstrip() + ("\n" if persona and not persona.endswith("\n") else ""),
            "instructions": instructions.rstrip()
            + ("\n" if instructions and not instructions.endswith("\n") else ""),
        }
        self._write_yaml(self.prompts_dir / f"{prompt_id}.yaml", data)
        return self._prompt_from_file(self.prompts_dir / f"{prompt_id}.yaml")

    def delete_prompt(self, prompt_id: str) -> bool:
        if prompt_id in _BUILTIN_PROMPT_IDS:
            raise LibraryValidationError("内置提示词不可删除")
        path = self.prompts_dir / f"{prompt_id}.yaml"
        if not path.is_file():
            return False
        for agent in self.list_agents():
            if agent.prompt_id == prompt_id:
                raise LibraryValidationError(
                    f"仍有 agent「{agent.id}」引用此提示词，请先修改或删除该 agent",
                )
        path.unlink()
        return True

    # --- Agents ---

    def list_agents(self) -> list[AgentRecord]:
        self.ensure()
        if not self.agents_dir.is_dir():
            return []
        return [self._agent_from_file(p) for p in sorted(self.agents_dir.glob("*.yaml"))]

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        path = self.agents_dir / f"{agent_id}.yaml"
        if not path.is_file():
            return None
        return self._agent_from_file(path)

    def create_agent(self, body: AgentCreate) -> AgentRecord:
        self.ensure()
        self._validate_id(body.id)
        path = self.agents_dir / f"{body.id}.yaml"
        if path.exists():
            raise LibraryValidationError(f"agent 已存在: {body.id}")
        if self.get_prompt(body.prompt_id) is None:
            raise LibraryValidationError(f"提示词不存在: {body.prompt_id}")
        self._validate_tools(body.tools)
        data = {
            "id": body.id,
            "name": body.name,
            "model_tier": body.model_tier,
            "tools": body.tools,
            "prompt_id": body.prompt_id,
            "status": body.status,
        }
        self._write_yaml(path, data)
        return self._agent_from_file(path)

    def update_agent(self, agent_id: str, body: AgentUpdate) -> AgentRecord:
        existing = self.get_agent(agent_id)
        if existing is None:
            raise FileNotFoundError(agent_id)
        prompt_id = body.prompt_id if body.prompt_id is not None else existing.prompt_id
        tools = body.tools if body.tools is not None else existing.tools
        if self.get_prompt(prompt_id) is None:
            raise LibraryValidationError(f"提示词不存在: {prompt_id}")
        self._validate_tools(tools)
        data = {
            "id": agent_id,
            "name": body.name if body.name is not None else existing.name,
            "model_tier": body.model_tier if body.model_tier is not None else existing.model_tier,
            "tools": tools,
            "prompt_id": prompt_id,
            "status": body.status if body.status is not None else existing.status,
        }
        self._write_yaml(self.agents_dir / f"{agent_id}.yaml", data)
        return self._agent_from_file(self.agents_dir / f"{agent_id}.yaml")

    def delete_agent(self, agent_id: str) -> bool:
        if agent_id in _BUILTIN_AGENT_IDS:
            raise LibraryValidationError("内置 agent 不可删除")
        path = self.agents_dir / f"{agent_id}.yaml"
        if not path.is_file():
            return False
        path.unlink()
        return True

    # --- Tools (read-only catalog) ---

    def list_tools(self) -> list[ToolRecord]:
        from app.prompts.segments import TOOL_GUIDANCE

        out: list[ToolRecord] = []
        for name, tool in sorted(TOOL_BY_NAME.items()):
            desc = (tool.description or "").strip()
            out.append(
                ToolRecord(
                    id=name,
                    name=name,
                    description=desc,
                    guidance=TOOL_GUIDANCE.get(name, ""),
                )
            )
        return out


library_store = LibraryStore()
