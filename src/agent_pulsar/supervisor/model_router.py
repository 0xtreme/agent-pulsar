"""Model Router — classifies task complexity and assigns the cheapest viable model.

Uses Haiku (via LiteLLM) for fast, cheap classification. Respects worker
minimum capability floors — e.g., a payroll worker may require Opus even
if the Model Router classifies a sub-task as "simple".
"""

from __future__ import annotations

import json
import logging
from typing import Any, ClassVar

from litellm import Router

from agent_pulsar.schemas.enums import ComplexityTier

logger = logging.getLogger(__name__)

# Maps complexity tiers to default model assignments
MODEL_TIERS: dict[ComplexityTier, str] = {
    ComplexityTier.SIMPLE: "claude-haiku-4-5-20250414",
    ComplexityTier.MODERATE: "claude-sonnet-4-0-20250514",
    ComplexityTier.COMPLEX: "claude-opus-4-0-20250514",
}

# Ordered by capability (lowest to highest)
TIER_ORDER: list[ComplexityTier] = [
    ComplexityTier.SIMPLE,
    ComplexityTier.MODERATE,
    ComplexityTier.COMPLEX,
]

CLASSIFICATION_PROMPT = """\
You are a task complexity classifier. Given a task type and parameters,
classify the complexity as one of: simple, moderate, complex.

Guidelines:
- simple: Single-step operations, lookups, sends, quick reads. Examples: send email, check calendar, simple search.
- moderate: Multi-step reasoning, research, drafting, document processing. Examples: summarize research, draft report, analyze data.
- complex: Sensitive operations, financial transactions, code generation, multi-system coordination. Examples: run payroll, file taxes, deploy code.

Task type: {task_type}
Parameters: {params}

Respond with ONLY a JSON object: {{"complexity": "simple"|"moderate"|"complex"}}
"""


class ModelRouter:
    """Classifies task complexity and assigns the cheapest viable model."""

    def __init__(
        self,
        litellm_router: Router,
        classification_model: str = "claude-haiku-4-5-20250414",
    ) -> None:
        self._router = litellm_router
        self._classification_model = classification_model

    async def classify_and_assign(
        self,
        task_type: str,
        params: dict[str, Any],
        worker_min_capability: ComplexityTier | None = None,
    ) -> tuple[ComplexityTier, str]:
        """Classify complexity and return (tier, model_name).

        If worker_min_capability is set, the returned tier will be at least
        that level (e.g., a payroll worker requiring COMPLEX will always get Opus).
        """
        classified = await self._classify_complexity(task_type, params)
        return self._resolve_model(classified, worker_min_capability)

    async def _classify_complexity(
        self, task_type: str, params: dict[str, Any]
    ) -> ComplexityTier:
        """Call Haiku to classify task complexity."""
        try:
            prompt = CLASSIFICATION_PROMPT.format(
                task_type=task_type,
                params=json.dumps(params, default=str)[:500],  # Truncate large params
            )
            response = await self._router.acompletion(
                model=self._classification_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=50,
            )
            content = response.choices[0].message.content.strip()

            # Parse the JSON response
            parsed = json.loads(content)
            tier_str = parsed.get("complexity", "moderate")
            return ComplexityTier(tier_str)

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(
                "Failed to parse complexity classification: %s. Defaulting to MODERATE.",
                e,
            )
            return ComplexityTier.MODERATE
        except Exception as e:
            logger.error(
                "LLM classification call failed: %s. Defaulting to MODERATE.", e
            )
            return ComplexityTier.MODERATE

    def _resolve_model(
        self,
        classified: ComplexityTier,
        worker_floor: ComplexityTier | None,
    ) -> tuple[ComplexityTier, str]:
        """Take the max of classified and worker_floor, return (tier, model)."""
        if worker_floor is None:
            return classified, MODEL_TIERS[classified]

        classified_idx = TIER_ORDER.index(classified)
        floor_idx = TIER_ORDER.index(worker_floor)
        effective_tier = TIER_ORDER[max(classified_idx, floor_idx)]

        if effective_tier != classified:
            logger.info(
                "Worker floor elevated %s → %s", classified.value, effective_tier.value
            )

        return effective_tier, MODEL_TIERS[effective_tier]
