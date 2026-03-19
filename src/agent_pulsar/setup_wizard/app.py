"""Setup Wizard FastAPI application.

Standalone lightweight app that runs before Redis/PostgreSQL are available.
Guides users through first-time setup of Agent Pulsar.
"""

from __future__ import annotations

from fastapi import FastAPI

from agent_pulsar.setup_wizard.routes import router

app = FastAPI(title="Agent Pulsar Setup Wizard")
app.include_router(router)
