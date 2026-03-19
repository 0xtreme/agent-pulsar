#!/usr/bin/env python3
"""Launch the Agent Pulsar Setup Wizard.

Usage:
    python scripts/run_setup_wizard.py
    uv run python scripts/run_setup_wizard.py

Opens a browser to http://localhost:8103 for guided setup.
"""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Start the setup wizard server."""
    print("Starting Agent Pulsar Setup Wizard...")  # noqa: T201
    print("Open http://localhost:8103 in your browser")  # noqa: T201
    print()  # noqa: T201
    uvicorn.run(
        "agent_pulsar.setup_wizard.app:app",
        host="0.0.0.0",
        port=8103,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
