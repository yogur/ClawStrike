"""Tests for US-002: Skill Mode MCP Server Startup."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastmcp.exceptions import ToolError

from clawstrike.classifier import ClassifierResult
from clawstrike.config import ClawStrikeConfig, load_config

# ---------------------------------------------------------------------------
# Helpers (mirrored from test_config.py)
# ---------------------------------------------------------------------------


def write_yaml(tmp_path: Path, data: dict) -> Path:
    cfg_file = tmp_path / "clawstrike.yaml"
    cfg_file.write_text(yaml.dump(data))
    return cfg_file


def minimal_config(extra: dict | None = None) -> dict:
    base: dict = {"clawstrike": {"classifier": {"model": "multilingual"}}}
    if extra:
        base["clawstrike"].update(extra)
    return base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg(tmp_path: Path) -> ClawStrikeConfig:
    """Return a minimal validated config."""
    return load_config(write_yaml(tmp_path, minimal_config()))


@pytest.fixture(autouse=True)
def reset_server_config():
    """Reset module globals and mock create_classifier for each test.

    Patching create_classifier prevents any attempt to download real HF models.
    The mock classifier returns a fixed benign ClassifierResult.
    """
    import clawstrike.mcpserver as srv

    mock_clf = MagicMock()
    mock_clf.classify.return_value = ClassifierResult(
        score=0.0, label="benign", model="mock-model", latency_ms=1.0
    )

    with patch("clawstrike.mcpserver.create_classifier", return_value=mock_clf):
        yield

    srv._config = None
    srv._classifier = None


# ---------------------------------------------------------------------------
# AC: server exposes health tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_ok(cfg: ClawStrikeConfig) -> None:
    import clawstrike.mcpserver as srv

    srv.init_server(cfg)
    result = await srv.mcp.call_tool("health", {})
    data = result.structured_content
    assert data["status"] == "ok"
    assert data["mode"] == "skill"
    assert data["classifier"] == "multilingual"


@pytest.mark.asyncio
async def test_health_raises_if_not_initialized() -> None:
    import clawstrike.mcpserver as srv

    # _config is None (reset by autouse fixture).
    # FastMCP wraps RuntimeError in ToolError at the protocol boundary.
    with pytest.raises(ToolError, match="not configured"):
        await srv.mcp.call_tool("health", {})


# ---------------------------------------------------------------------------
# AC: server exposes classify tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_returns_result(cfg: ClawStrikeConfig) -> None:
    import clawstrike.mcpserver as srv

    srv.init_server(cfg)
    result = await srv.mcp.call_tool(
        "classify",
        {
            "text": "Hello, what is the weather today?",
            "source_id": "user@example.com",
            "channel_type": "email_body",
        },
    )
    data = result.structured_content
    assert "decision" in data
    assert data["decision"] in ("pass", "flag", "block")
    assert "score" in data
    assert isinstance(data["score"], float)
    assert "label" in data
    assert data["label"] in ("benign", "injection", "jailbreak")
    assert "model" in data
    assert "latency_ms" in data


@pytest.mark.asyncio
async def test_classify_echoes_source_metadata(cfg: ClawStrikeConfig) -> None:
    import clawstrike.mcpserver as srv

    srv.init_server(cfg)
    result = await srv.mcp.call_tool(
        "classify",
        {
            "text": "some text",
            "source_id": "discord:12345",
            "channel_type": "public_group",
        },
    )
    data = result.structured_content
    assert data["source_id"] == "discord:12345"
    assert data["channel_type"] == "public_group"


@pytest.mark.asyncio
async def test_classify_raises_if_not_initialized() -> None:
    import clawstrike.mcpserver as srv

    with pytest.raises(ToolError, match="not configured"):
        await srv.mcp.call_tool(
            "classify",
            {"text": "x", "source_id": "s", "channel_type": "webhook"},
        )


# ---------------------------------------------------------------------------
# AC: server exposes gate tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_returns_recommendation(cfg: ClawStrikeConfig) -> None:
    import clawstrike.mcpserver as srv

    srv.init_server(cfg)
    result = await srv.mcp.call_tool(
        "gate",
        {
            "action_description": "Read the calendar for today",
            "action_type": "calendar_read",
            "session_id": "session-abc-123",
            "source_id": "owner@example.com",
            "channel_type": "owner_dm",
        },
    )
    data = result.structured_content
    assert "risk_level" in data
    assert data["risk_level"] in ("critical", "high", "medium", "low")
    assert "recommendation" in data
    assert data["recommendation"] in ("allow", "block", "prompt_user")
    assert "trust_level" in data
    assert "reason" in data


@pytest.mark.asyncio
async def test_gate_echoes_session_and_source(cfg: ClawStrikeConfig) -> None:
    import clawstrike.mcpserver as srv

    srv.init_server(cfg)
    result = await srv.mcp.call_tool(
        "gate",
        {
            "action_description": "Send an email",
            "action_type": "send_email",
            "session_id": "s-xyz",
            "source_id": "contact@example.com",
            "channel_type": "email_body",
        },
    )
    data = result.structured_content
    assert data["session_id"] == "s-xyz"
    assert data["source_id"] == "contact@example.com"
    assert data["channel_type"] == "email_body"
    assert data["action_type"] == "send_email"


@pytest.mark.asyncio
async def test_gate_raises_if_not_initialized() -> None:
    import clawstrike.mcpserver as srv

    with pytest.raises(ToolError, match="not configured"):
        await srv.mcp.call_tool(
            "gate",
            {
                "action_description": "do something",
                "action_type": "shell_exec",
                "session_id": "s",
                "source_id": "x",
                "channel_type": "webhook",
            },
        )


# ---------------------------------------------------------------------------
# AC: init_server wires config correctly
# ---------------------------------------------------------------------------


def test_init_server_sets_config(cfg: ClawStrikeConfig) -> None:
    import clawstrike.mcpserver as srv

    assert srv._config is None
    srv.init_server(cfg)
    assert srv._config is cfg


def test_init_server_overrides_previous_config(
    tmp_path: Path, cfg: ClawStrikeConfig
) -> None:
    import clawstrike.mcpserver as srv

    srv.init_server(cfg)

    cfg2 = load_config(
        write_yaml(tmp_path, minimal_config({"classifier": {"model": "english-only"}}))
    )
    srv.init_server(cfg2)
    assert srv._config is cfg2


# ---------------------------------------------------------------------------
# AC: health reflects the configured classifier model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_reflects_english_only_model(tmp_path: Path) -> None:
    import clawstrike.mcpserver as srv

    cfg = load_config(
        write_yaml(tmp_path, minimal_config({"classifier": {"model": "english-only"}}))
    )
    srv.init_server(cfg)
    result = await srv.mcp.call_tool("health", {})
    assert result.structured_content["classifier"] == "english-only"


# ---------------------------------------------------------------------------
# AC: tool listing confirms all three tools are registered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_three_tools_are_registered(cfg: ClawStrikeConfig) -> None:
    import clawstrike.mcpserver as srv

    srv.init_server(cfg)

    from fastmcp import Client

    async with Client(srv.mcp) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}

    assert "health" in tool_names
    assert "classify" in tool_names
    assert "gate" in tool_names
