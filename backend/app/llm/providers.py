from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import httpx
from openai import AsyncOpenAI

from app.config import settings

ModelTier = Literal["primary", "local"]


class ProviderHealth(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    UNCONFIGURED = "unconfigured"


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    tier: ModelTier
    base_url: str
    api_key: str
    default_model: str
    label: str


class OpenAICompatibleProvider:
    def __init__(self, spec: ProviderSpec) -> None:
        self.spec = spec
        self._client = AsyncOpenAI(
            api_key=spec.api_key or "not-set",
            base_url=spec.base_url,
        )

    @property
    def tier(self) -> ModelTier:
        return self.spec.tier

    async def health(self) -> ProviderHealth:
        if not self.spec.api_key and self.spec.tier == "primary":
            return ProviderHealth.UNCONFIGURED
        try:
            async with httpx.AsyncClient(timeout=settings.llm_health_timeout_s) as client:
                resp = await client.get(
                    f"{self.spec.base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {self.spec.api_key or 'local'}"},
                )
            if resp.status_code < 500:
                return ProviderHealth.OK
            return ProviderHealth.DEGRADED
        except httpx.HTTPError:
            if self.spec.tier == "local" and not self.spec.api_key:
                return ProviderHealth.DEGRADED
            return ProviderHealth.DEGRADED

    async def ping_chat(self) -> bool:
        health = await self.health()
        return health == ProviderHealth.OK


def _provider_key(spec: ProviderSpec) -> str:
    """Registry key is (tier, id) so primary and local can share the same vendor id."""
    return f"{spec.tier}:{spec.id}"


def build_providers() -> dict[str, OpenAICompatibleProvider]:
    specs = [
        ProviderSpec(
            id=settings.primary_llm_provider_id,
            tier="primary",
            base_url=settings.primary_llm_base_url,
            api_key=settings.primary_llm_api_key,
            default_model=settings.primary_llm_model,
            label=settings.primary_llm_label,
        ),
        ProviderSpec(
            id=settings.local_llm_provider_id,
            tier="local",
            base_url=settings.local_llm_base_url,
            api_key=settings.local_llm_api_key,
            default_model=settings.local_llm_model,
            label=settings.local_llm_label,
        ),
    ]
    return {_provider_key(s): OpenAICompatibleProvider(s) for s in specs}
