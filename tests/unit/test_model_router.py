"""Unit tests for the Model Router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from agent_pulsar.schemas.enums import ComplexityTier
from agent_pulsar.supervisor.model_router import MODEL_TIERS, ModelRouter


def _make_mock_router(response_content: str) -> MagicMock:
    """Create a mock LiteLLM Router that returns the given content."""
    mock = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = response_content
    mock.acompletion = AsyncMock(return_value=mock_response)
    return mock


class TestModelRouterClassification:
    async def test_simple_classification(self) -> None:
        router = ModelRouter(_make_mock_router('{"complexity": "simple"}'))
        tier, model = await router.classify_and_assign("email.send", {"to": "a@b.com"})
        assert tier == ComplexityTier.SIMPLE
        assert model == MODEL_TIERS[ComplexityTier.SIMPLE]

    async def test_moderate_classification(self) -> None:
        router = ModelRouter(_make_mock_router('{"complexity": "moderate"}'))
        tier, model = await router.classify_and_assign("research.summarize", {})
        assert tier == ComplexityTier.MODERATE
        assert model == MODEL_TIERS[ComplexityTier.MODERATE]

    async def test_complex_classification(self) -> None:
        router = ModelRouter(_make_mock_router('{"complexity": "complex"}'))
        tier, model = await router.classify_and_assign("payroll.run", {})
        assert tier == ComplexityTier.COMPLEX
        assert model == MODEL_TIERS[ComplexityTier.COMPLEX]

    async def test_invalid_response_defaults_to_moderate(self) -> None:
        router = ModelRouter(_make_mock_router("not valid json"))
        tier, model = await router.classify_and_assign("unknown.task", {})
        assert tier == ComplexityTier.MODERATE

    async def test_llm_error_defaults_to_moderate(self) -> None:
        mock = MagicMock()
        mock.acompletion = AsyncMock(side_effect=RuntimeError("API down"))
        router = ModelRouter(mock)
        tier, model = await router.classify_and_assign("email.send", {})
        assert tier == ComplexityTier.MODERATE


class TestModelRouterFloor:
    async def test_worker_floor_elevates_simple_to_complex(self) -> None:
        router = ModelRouter(_make_mock_router('{"complexity": "simple"}'))
        tier, model = await router.classify_and_assign(
            "payroll.calculate", {}, worker_min_capability=ComplexityTier.COMPLEX
        )
        assert tier == ComplexityTier.COMPLEX
        assert model == MODEL_TIERS[ComplexityTier.COMPLEX]

    async def test_worker_floor_does_not_downgrade(self) -> None:
        router = ModelRouter(_make_mock_router('{"complexity": "complex"}'))
        tier, model = await router.classify_and_assign(
            "research.deep", {}, worker_min_capability=ComplexityTier.SIMPLE
        )
        assert tier == ComplexityTier.COMPLEX

    async def test_no_floor_uses_classification(self) -> None:
        router = ModelRouter(_make_mock_router('{"complexity": "simple"}'))
        tier, model = await router.classify_and_assign("email.send", {})
        assert tier == ComplexityTier.SIMPLE


class TestResolveModel:
    def test_all_tiers_have_models(self) -> None:
        for tier in ComplexityTier:
            assert tier in MODEL_TIERS
