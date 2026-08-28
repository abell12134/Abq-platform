"""LLM router registry tests."""

from __future__ import annotations

import unittest

from app.llm.providers import build_providers
from app.llm.router import llm_router


class ProviderRegistryTests(unittest.TestCase):
    def test_primary_and_local_both_registered(self) -> None:
        providers = build_providers()
        self.assertGreaterEqual(len(providers), 2)
        tiers = {p.spec.tier for p in providers.values()}
        self.assertIn("primary", tiers)
        self.assertIn("local", tiers)

    def test_resolve_primary_and_local(self) -> None:
        primary = llm_router.resolve(tier="primary")
        local = llm_router.resolve(tier="local", role="compaction")
        self.assertEqual(primary.tier, "primary")
        self.assertEqual(local.tier, "local")
        self.assertIsNotNone(primary.provider)
        self.assertIsNotNone(local.provider)


if __name__ == "__main__":
    unittest.main()
