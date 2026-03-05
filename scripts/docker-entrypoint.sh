#!/usr/bin/env bash
set -euo pipefail

# ── 1. Config: fail fast if not provided ──────────────────────────────────────
CONFIG_FILE="${CLAWSTRIKE_CONFIG:-/clawstrike/clawstrike.yaml}"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[clawstrike] ERROR: Config file not found at $CONFIG_FILE" >&2
    echo "[clawstrike] Create one by running:" >&2
    echo "[clawstrike]   cp clawstrike.example.yaml clawstrike.yaml  (then customize)" >&2
    echo "[clawstrike]   OR: uv run clawstrike init  (generates defaults)" >&2
    echo "[clawstrike] Then bind-mount it in docker-compose.yml and restart." >&2
    exit 1
fi

# ── 2. Install ClawStrike skill into OpenClaw's skills directory ───────────────
# /home/node/.openclaw is a host bind-mount (live only at runtime, not build time)
SKILLS_DIR="/home/node/.openclaw/skills"
mkdir -p "$SKILLS_DIR"
cp -r /clawstrike/skills/clawstrike-cli "$SKILLS_DIR/"
echo "[clawstrike] Skill installed at $SKILLS_DIR/clawstrike-cli" >&2

# ── 2b. Configure gateway mode and Control UI allowedOrigins ──────────────────
# Required when --bind is non-loopback: OpenClaw refuses to start without an
# explicit allowedOrigins list in that case.
OPENCLAW_GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
node /app/dist/index.js config set gateway.mode local >/dev/null 2>&1 || true
_current_origins=$(node /app/dist/index.js config get gateway.controlUi.allowedOrigins 2>/dev/null || true)
if [ -z "$_current_origins" ] || [ "$_current_origins" = "null" ] || [ "$_current_origins" = "[]" ]; then
    _origins="[\"http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}\"]"
    node /app/dist/index.js config set gateway.controlUi.allowedOrigins "$_origins" --strict-json >/dev/null 2>&1 || true
    echo "[clawstrike] Set gateway.controlUi.allowedOrigins to $_origins" >&2
else
    echo "[clawstrike] gateway.controlUi.allowedOrigins already configured; leaving unchanged." >&2
fi

# ── 3. HF auth (skip if no token) ─────────────────────────────────────────────
if [ -n "${HF_TOKEN:-}" ]; then
    echo "[clawstrike] Authenticating with Hugging Face..." >&2
    uvx hf auth login --token "$HF_TOKEN" --add-to-git-credential >&2 || true
fi

# ── 4. Model warmup (triggers download on first run) ──────────────────────────
echo "[clawstrike] Warming up classifier (may take several minutes on first run)..." >&2
clawstrike health --config "$CONFIG_FILE" >&2 || {
    echo "[clawstrike] WARNING: Model warmup failed. Check HF_TOKEN and Meta license acceptance:" >&2
    echo "[clawstrike]   22M: https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M" >&2
    echo "[clawstrike]   86M: https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M" >&2
}

# ── 5. Exec OpenClaw ───────────────────────────────────────────────────────────
exec "$@"
