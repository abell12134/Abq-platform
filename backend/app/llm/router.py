from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.llm.providers import ModelTier, OpenAICompatibleProvider, ProviderHealth, build_providers


@dataclass
class ResolvedLlm:
    tier: ModelTier
    provider_id: str
    model: str
    provider: OpenAICompatibleProvider


class LlmRouter:
    def __init__(self) -> None:
        self._providers = build_providers()
        self._default_primary = settings.primary_llm_provider_id
        self._default_local = settings.local_llm_provider_id

    def list_providers(self) -> list[dict]:
        return [
            {
                "id": p.spec.id,
                "tier": p.spec.tier,
                "label": p.spec.label,
                "model": p.spec.default_model,
                "base_url": p.spec.base_url,
            }
            for p in self._providers.values()
        ]

    def _lookup(self, *, tier: ModelTier, provider_id: str) -> OpenAICompatibleProvider | None:
        keyed = self._providers.get(f"{tier}:{provider_id}")
        if keyed:
            return keyed
        for provider in self._providers.values():
            if provider.spec.id == provider_id:
                return provider
        return None

    async def health(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for tier in ("primary", "local"):
            provider = self._pick_by_tier(tier)  # type: ignore[arg-type]
            status = await provider.health()
            out[tier] = {
                "ok": status == ProviderHealth.OK,
                "status": status.value,
                "provider": provider.spec.id,
                "model": provider.spec.default_model,
                "label": provider.spec.label,
            }
        return out

    def resolve(
        self,
        *,
        tier: ModelTier,
        agent_id: str | None = None,
        role: str | None = None,
        primary_override: str | None = None,
    ) -> ResolvedLlm:
        if role == "compaction":
            tier = "local"
        del agent_id
        if tier == "primary" and primary_override and ":" in primary_override:
            provider_id, model = primary_override.split(":", 1)
            provider = self._lookup(tier="primary", provider_id=provider_id) or self._pick_by_tier(
                "primary"
            )
            return ResolvedLlm(
                tier="primary",
                provider_id=provider.spec.id,
                model=model or provider.spec.default_model,
                provider=provider,
            )
        provider = self._pick_by_tier(tier)
        return ResolvedLlm(
            tier=tier,
            provider_id=provider.spec.id,
            model=provider.spec.default_model,
            provider=provider,
        )

    def _pick_by_tier(self, tier: ModelTier) -> OpenAICompatibleProvider:
        pid = self._default_primary if tier == "primary" else self._default_local
        provider = self._lookup(tier=tier, provider_id=pid)
        if provider is None:
            raise KeyError(f"LLM provider not registered: {tier}:{pid}")
        return provider


llm_router = LlmRouter()
