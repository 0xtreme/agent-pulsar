"""Unified LLM client wrapping native SDKs.

Provides the same interface regardless of provider:
    client = LLMClient.from_settings(settings)
    response = await client.acompletion(model=..., messages=..., ...)
    text = response.choices[0].message.content

Supports role-based model aliases (fast-model, balanced-model, capable-model)
so workers don't need to know specific model names.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response objects — lightweight, match the shape workers already expect
# ---------------------------------------------------------------------------
@dataclass
class MessageContent:
    content: str | None = None
    role: str = "assistant"


@dataclass
class Choice:
    message: MessageContent = field(default_factory=MessageContent)
    index: int = 0


@dataclass
class CompletionResponse:
    choices: list[Choice] = field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Provider model maps
# ---------------------------------------------------------------------------
ANTHROPIC_MODELS = {
    "fast-model": "claude-haiku-4-5-20250414",
    "balanced-model": "claude-sonnet-4-0-20250514",
    "capable-model": "claude-opus-4-0-20250514",
}

OPENAI_MODELS = {
    "fast-model": "gpt-4o-mini",
    "balanced-model": "gpt-4o",
    "capable-model": "gpt-4o",
}

GEMINI_MODELS = {
    "fast-model": "gemini-2.0-flash",
    "balanced-model": "gemini-2.5-pro",
    "capable-model": "gemini-2.5-pro",
}


class LLMClient:
    """Unified async LLM client using native SDKs."""

    def __init__(
        self,
        provider: str,
        api_key: str | None = None,
        oauth_token: str | None = None,
        model_aliases: dict[str, str] | None = None,
        num_retries: int = 2,
        timeout: int = 120,
    ) -> None:
        self.provider = provider
        self._api_key = api_key
        self._oauth_token = oauth_token
        self._aliases = model_aliases or {}
        self._num_retries = num_retries
        self._timeout = timeout
        self._client: Any = None

        self._init_client()

    def _init_client(self) -> None:
        """Initialize the native SDK client."""
        if self.provider == "anthropic":
            self._init_anthropic()
        elif self.provider == "openai":
            self._init_openai()
        elif self.provider == "gemini":
            self._init_gemini()
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def _init_anthropic(self) -> None:
        """Initialize Anthropic client — supports API key or OAuth token."""
        import anthropic

        if self._oauth_token:
            # OAuth token: use Authorization: Bearer header
            self._client = anthropic.AsyncAnthropic(
                api_key=self._oauth_token,
                timeout=self._timeout,
                max_retries=self._num_retries,
            )
            self._auth_method = "oauth"
            logger.info("Anthropic client initialized with OAuth token")
        elif self._api_key:
            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key,
                timeout=self._timeout,
                max_retries=self._num_retries,
            )
            self._auth_method = "api_key"
            logger.info("Anthropic client initialized with API key")
        else:
            raise ValueError(
                "Anthropic requires either AP_ANTHROPIC_API_KEY or "
                "CLAUDE_CODE_OAUTH_TOKEN. Run: claude setup-token"
            )

    def _init_openai(self) -> None:
        """Initialize OpenAI client."""
        import openai

        if not self._api_key:
            raise ValueError("OpenAI requires AP_OPENAI_API_KEY")
        self._client = openai.AsyncOpenAI(
            api_key=self._api_key,
            timeout=self._timeout,
            max_retries=self._num_retries,
        )
        self._auth_method = "api_key"
        logger.info("OpenAI client initialized with API key")

    def _init_gemini(self) -> None:
        """Initialize Google Gemini client."""
        from google import genai

        if not self._api_key:
            raise ValueError("Gemini requires AP_GEMINI_API_KEY")
        self._client = genai.Client(api_key=self._api_key)
        self._auth_method = "api_key"
        logger.info("Gemini client initialized with API key")

    def _resolve_model(self, model: str) -> str:
        """Resolve role-based alias to actual model name."""
        return self._aliases.get(model, model)

    async def acompletion(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> CompletionResponse:
        """Call the LLM and return a unified response object.

        This is the single interface all workers use. Drop-in replacement
        for litellm_router.acompletion().
        """
        actual_model = self._resolve_model(model)

        if self.provider == "anthropic":
            return await self._anthropic_completion(
                actual_model, messages, temperature, max_tokens
            )
        elif self.provider == "openai":
            return await self._openai_completion(
                actual_model, messages, temperature, max_tokens
            )
        elif self.provider == "gemini":
            return await self._gemini_completion(
                actual_model, messages, temperature, max_tokens
            )
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    async def _anthropic_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> CompletionResponse:
        """Call Anthropic Messages API."""
        # Anthropic expects system message separate from user messages
        system_msg = None
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                api_messages.append(msg)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg

        response = await self._client.messages.create(**kwargs)

        # Extract text from content blocks
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        return CompletionResponse(
            choices=[Choice(message=MessageContent(content=text))],
            model=response.model,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )

    async def _openai_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> CompletionResponse:
        """Call OpenAI Chat Completions API."""
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content if response.choices else None

        return CompletionResponse(
            choices=[Choice(message=MessageContent(content=content))],
            model=response.model or model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        )

    async def _gemini_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> CompletionResponse:
        """Call Google Gemini API."""
        # Convert messages to Gemini format
        contents = []
        for msg in messages:
            role = "user" if msg["role"] in ("user", "system") else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        response = await self._client.aio.models.generate_content(
            model=model,
            contents=contents,
            config={
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        )

        text = response.text if response.text else ""

        return CompletionResponse(
            choices=[Choice(message=MessageContent(content=text))],
            model=model,
        )

    @classmethod
    def from_settings(cls, settings: Any) -> LLMClient:
        """Create an LLMClient from application settings.

        Checks for OAuth token first (subscription-based auth),
        then falls back to API key.
        """
        provider = settings.llm_provider

        # Check for Claude OAuth token (subscription users)
        oauth_token = getattr(settings, "claude_oauth_token", "") or os.environ.get(
            "CLAUDE_CODE_OAUTH_TOKEN", ""
        )

        if provider == "anthropic":
            aliases = ANTHROPIC_MODELS.copy()
            # Also register by full model name (identity mapping)
            for model_name in ANTHROPIC_MODELS.values():
                aliases[model_name] = model_name
            return cls(
                provider="anthropic",
                api_key=settings.anthropic_api_key or None,
                oauth_token=oauth_token or None,
                model_aliases=aliases,
            )
        elif provider == "openai":
            aliases = OPENAI_MODELS.copy()
            for model_name in set(OPENAI_MODELS.values()):
                aliases[model_name] = model_name
            return cls(
                provider="openai",
                api_key=settings.openai_api_key or None,
                model_aliases=aliases,
            )
        elif provider == "gemini":
            aliases = GEMINI_MODELS.copy()
            for model_name in set(GEMINI_MODELS.values()):
                aliases[model_name] = model_name
            return cls(
                provider="gemini",
                api_key=settings.gemini_api_key or None,
                model_aliases=aliases,
            )
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")
