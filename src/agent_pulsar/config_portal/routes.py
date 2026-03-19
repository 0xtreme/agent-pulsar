"""Config Portal API routes — credential onboarding endpoints."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from agent_pulsar.config_portal.schemas import (  # noqa: TC001
    ConnectedService,
    GenerateLinkRequest,
    GenerateLinkResponse,
)

if TYPE_CHECKING:
    from agent_pulsar.config_portal.link_manager import LinkManager
    from agent_pulsar.security.vault_client import VaultClient

logger = logging.getLogger(__name__)

router = APIRouter()

_link_manager: LinkManager | None = None
_vault: VaultClient | None = None
_base_url: str = "http://localhost:8102"

templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates")
)


def configure(
    link_manager: LinkManager,
    vault: VaultClient,
    base_url: str,
) -> None:
    """Inject dependencies (called during app lifespan)."""
    global _link_manager, _vault, _base_url  # noqa: PLW0603
    _link_manager = link_manager
    _vault = vault
    _base_url = base_url


def _get_link_manager() -> LinkManager:
    if _link_manager is None:
        raise RuntimeError("LinkManager not initialized")
    return _link_manager


def _get_vault() -> VaultClient:
    if _vault is None:
        raise RuntimeError("VaultClient not initialized")
    return _vault


# --- API Routes ---


@router.post("/api/links/generate")
async def generate_link(req: GenerateLinkRequest) -> GenerateLinkResponse:
    """Generate a one-time onboarding link for a user + service."""
    lm = _get_link_manager()
    token = await lm.generate(req.user_id, req.service)
    url = f"{_base_url}/connect/{token}"
    return GenerateLinkResponse(
        url=url,
        token=token,
        expires_in_seconds=lm._ttl,
    )


@router.get("/api/connections/{user_id}")
async def list_connections(user_id: str) -> list[ConnectedService]:
    """List connected services for a user."""
    vault = _get_vault()
    services = await vault.list_secrets(f"users/{user_id}")
    return [ConnectedService(service=s) for s in services]


@router.delete("/api/connections/{user_id}/{service}")
async def disconnect_service(user_id: str, service: str) -> dict[str, str]:
    """Revoke/disconnect a service for a user."""
    vault = _get_vault()
    # Delete all scopes under this service
    scopes = await vault.list_secrets(f"users/{user_id}/{service}")
    for scope in scopes:
        await vault.delete_secret(f"users/{user_id}/{service}/{scope}")
    # Also try deleting the service-level secret directly
    await vault.delete_secret(f"users/{user_id}/{service}")
    return {"status": "disconnected"}


# --- Web Routes (HTML) ---


@router.get("/connect/{token}", response_class=HTMLResponse)
async def connect_form(token: str, request: Request) -> HTMLResponse:
    """Render the credential submission form."""
    lm = _get_link_manager()
    meta = await lm.validate(token)
    if meta is None:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"message": "This link has expired or is invalid."},
            status_code=400,
        )
    return templates.TemplateResponse(
        request=request,
        name="connect.html",
        context={"token": token, "service": meta["service"]},
    )


@router.post("/connect/{token}", response_class=HTMLResponse)
async def submit_credentials(
    token: str,
    request: Request,
) -> HTMLResponse:
    """Handle credential form submission."""
    lm = _get_link_manager()
    meta = await lm.consume(token)
    if meta is None:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"message": "This link has expired or already been used."},
            status_code=400,
        )

    # Parse form data
    form = await request.form()
    api_key = str(form.get("api_key", ""))
    api_secret = str(form.get("api_secret", ""))

    if not api_key:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"message": "API key is required."},
            status_code=400,
        )

    # Write to Vault
    vault = _get_vault()
    vault_path = f"users/{meta['user_id']}/{meta['service']}"
    secret_data: dict[str, Any] = {"api_key": api_key}
    if api_secret:
        secret_data["api_secret"] = api_secret

    await vault.write_secret(vault_path, secret_data)

    logger.info(
        "Stored credentials for user=%s service=%s",
        meta["user_id"], meta["service"],
    )

    return templates.TemplateResponse(
        request=request,
        name="success.html",
        context={"service": meta["service"]},
    )
