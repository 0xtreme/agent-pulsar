"""Setup Wizard routes — step-by-step guided setup."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from agent_pulsar.setup_wizard.checks import run_all_checks

router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates")
)

# Project root is assumed to be CWD
PROJECT_ROOT = os.getcwd()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> RedirectResponse:
    """Redirect to step 1."""
    return RedirectResponse("/setup/1")


@router.get("/setup/1", response_class=HTMLResponse)
async def step_prerequisites(request: Request) -> HTMLResponse:
    """Step 1: Prerequisites check."""
    return templates.TemplateResponse(
        request=request, name="prerequisites.html", context={"step": 1},
    )


@router.post("/setup/1/check")
async def check_prerequisites() -> JSONResponse:
    """Run prerequisite checks and return results."""
    results = await run_all_checks(PROJECT_ROOT)
    return JSONResponse({
        "checks": [
            {
                "name": r.name,
                "passed": r.passed,
                "message": r.message,
                "fix_hint": r.fix_hint,
            }
            for r in results
        ],
        "all_passed": all(r.passed for r in results),
    })


@router.get("/setup/2", response_class=HTMLResponse)
async def step_configure(request: Request) -> HTMLResponse:
    """Step 2: Configuration."""
    # Read current .env if it exists
    env_path = Path(PROJECT_ROOT) / ".env"
    current_key = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("AP_ANTHROPIC_API_KEY="):
                current_key = line.split("=", 1)[1]
                break
    return templates.TemplateResponse(
        request=request,
        name="configure.html",
        context={"step": 2, "has_key": bool(current_key and current_key.startswith("sk-"))},
    )


@router.post("/setup/2/save")
async def save_config(request: Request) -> JSONResponse:
    """Save LLM configuration to .env file."""
    form = await request.form()
    provider = str(form.get("provider", "anthropic"))

    # Validate based on provider
    settings: dict[str, str] = {}
    if provider == "anthropic":
        api_key = str(form.get("api_key", ""))
        if not api_key.startswith("sk-"):
            return JSONResponse({"error": "API key must start with sk-"}, status_code=400)
        settings["AP_ANTHROPIC_API_KEY"] = api_key
        settings["AP_LLM_PROVIDER"] = "anthropic"
    elif provider == "openai":
        api_key = str(form.get("openai_api_key", ""))
        if not api_key.startswith("sk-"):
            return JSONResponse({"error": "API key must start with sk-"}, status_code=400)
        settings["AP_LLM_PROVIDER"] = "openai"
        settings["AP_OPENAI_API_KEY"] = api_key
    elif provider == "gemini":
        api_key = str(form.get("gemini_api_key", ""))
        if not api_key:
            return JSONResponse({"error": "Gemini API key is required"}, status_code=400)
        settings["AP_LLM_PROVIDER"] = "gemini"
        settings["AP_GEMINI_API_KEY"] = api_key
    else:
        return JSONResponse({"error": f"Unknown provider: {provider}"}, status_code=400)

    # Write to .env
    env_path = Path(PROJECT_ROOT) / ".env"
    example_path = Path(PROJECT_ROOT) / ".env.example"

    if not env_path.exists() and example_path.exists():
        env_path.write_text(example_path.read_text())
    elif not env_path.exists():
        env_path.write_text("")

    lines = env_path.read_text().splitlines()
    for key, value in settings.items():
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
                lines[i] = f"{key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")
    return JSONResponse({"status": "saved"})


@router.get("/setup/3", response_class=HTMLResponse)
async def step_start(request: Request) -> HTMLResponse:
    """Step 3: Start services."""
    return templates.TemplateResponse(request=request, name="start.html", context={"step": 3})


@router.get("/setup/4", response_class=HTMLResponse)
async def step_test(request: Request) -> HTMLResponse:
    """Step 4: Test & connect."""
    return templates.TemplateResponse(request=request, name="test.html", context={"step": 4})
