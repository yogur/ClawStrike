FROM ghcr.io/openclaw/openclaw:2026.3.2

USER root

# ── 1. Install uv ──────────────────────────────────────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=ghcr.io/astral-sh/uv:latest /uvx /usr/local/bin/uvx

# ── 2. Install Python 3.12 via uv ──────────────────
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN uv python install 3.12

# ── 3. Install ClawStrike and its dependencies ────────────────────────────────
WORKDIR /clawstrike
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# Copy only the CLI skill — entrypoint installs it into OpenClaw at runtime
COPY skills/clawstrike-cli ./skills/clawstrike-cli
RUN uv sync --no-dev --frozen && \
    ln -sf /clawstrike/.venv/bin/clawstrike /usr/local/bin/clawstrike

# ── 4. Copy entrypoint ────────────────────────────────────────────────────────
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh && \
    git config --system credential.helper store

# ── 5. Pre-create HF cache dir so the named volume is initialised with node ownership ──
RUN mkdir -p /home/node/.cache/huggingface && \
    chown -R node:node /home/node/.cache/huggingface

USER node

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["node", "/app/dist/index.js", "gateway", "--bind", "lan", "--port", "18789", "--allow-unconfigured"]
