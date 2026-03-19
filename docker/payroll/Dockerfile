FROM python:3.12-slim

WORKDIR /app

# Install only the agent_pulsar package
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir . && \
    rm -rf /root/.cache

# Run as non-root
RUN useradd --create-home appuser
USER appuser

ENTRYPOINT ["python", "-m", "agent_pulsar.workers.cold_entrypoint"]
