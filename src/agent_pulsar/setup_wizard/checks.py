"""Prerequisite checks for the setup wizard."""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    """Result of a single prerequisite check."""

    name: str
    passed: bool
    message: str
    fix_hint: str = ""


async def check_docker() -> CheckResult:
    """Check if Docker is installed and the daemon is running."""
    if not shutil.which("docker"):
        return CheckResult(
            "Docker", False,
            "Docker not found in PATH",
            "Install Docker Desktop: https://docker.com/get-started",
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "info",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode == 0:
            return CheckResult("Docker", True, "Docker is running")
        return CheckResult(
            "Docker", False,
            "Docker daemon is not running",
            "Start Docker Desktop and try again",
        )
    except Exception as e:
        return CheckResult("Docker", False, str(e), "Install Docker Desktop")


async def check_uv() -> CheckResult:
    """Check if uv is installed."""
    if shutil.which("uv"):
        return CheckResult("uv", True, "uv is installed")
    # Check common install locations
    home_uv = Path.home() / ".local" / "bin" / "uv"
    if home_uv.exists():
        return CheckResult("uv", True, f"uv found at {home_uv}")
    return CheckResult(
        "uv", False,
        "uv not found",
        "Install: curl -LsSf https://astral.sh/uv/install.sh | sh",
    )


async def check_llm_auth(project_root: str = ".") -> CheckResult:
    """Check if any LLM provider is configured."""
    # Check environment variables
    env_checks = {
        "AP_ANTHROPIC_API_KEY": ("Anthropic", "sk-"),
        "AP_OPENAI_API_KEY": ("OpenAI", "sk-"),
        "AP_GEMINI_API_KEY": ("Gemini", ""),
    }
    for var, (provider, prefix) in env_checks.items():
        val = os.environ.get(var, "")
        if val and (not prefix or val.startswith(prefix)):
            return CheckResult("LLM Auth", True, f"{provider} configured via environment")

    # Check .env file
    env_path = Path(project_root) / ".env"
    if env_path.exists():
        content = env_path.read_text()
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#"):
                continue
            if line.startswith("AP_ANTHROPIC_API_KEY=sk-"):
                return CheckResult("LLM Auth", True, "Anthropic API key set in .env")
            if line.startswith("AP_OPENAI_API_KEY=sk-"):
                return CheckResult("LLM Auth", True, "OpenAI API key set in .env")
            if line.startswith("AP_GEMINI_API_KEY=") and not line.endswith("="):
                return CheckResult("LLM Auth", True, "Gemini API key set in .env")

    return CheckResult(
        "LLM Auth", True,
        "Not yet configured — you'll set this up in the next step",
        "",
    )


async def check_redis() -> CheckResult:
    """Check if Redis is reachable."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url("redis://localhost:6379/0")
        await r.ping()  # type: ignore[misc]
        await r.aclose()
        return CheckResult("Redis", True, "Redis is running on localhost:6379")
    except Exception:
        return CheckResult(
            "Redis", False,
            "Redis not reachable on localhost:6379",
            "Run: docker compose up -d",
        )


async def check_postgres() -> CheckResult:
    """Check if PostgreSQL is reachable."""
    try:
        import asyncpg  # type: ignore[import-untyped]

        conn = await asyncpg.connect(
            "postgresql://agent_pulsar:agent_pulsar@localhost:5432/agent_pulsar"
        )
        await conn.close()
        return CheckResult("PostgreSQL", True, "PostgreSQL is running on localhost:5432")
    except Exception:
        return CheckResult(
            "PostgreSQL", False,
            "PostgreSQL not reachable on localhost:5432",
            "Run: docker compose up -d",
        )


async def run_all_checks(project_root: str = ".") -> list[CheckResult]:
    """Run all prerequisite checks."""
    results = await asyncio.gather(
        check_docker(),
        check_uv(),
        check_llm_auth(project_root),
        check_redis(),
        check_postgres(),
    )
    return list(results)
