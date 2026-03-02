"""Shared fixtures available to all test tiers."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawstrike.config import ClawStrikeConfig, load_config

from .helpers import minimal_config, write_yaml


@pytest.fixture
def cfg(tmp_path: Path) -> ClawStrikeConfig:
    """Return a minimal validated config with a per-test isolated DB path."""
    data = minimal_config()
    data["clawstrike"]["audit"] = {"db_path": str(tmp_path / "test.db")}
    return load_config(write_yaml(tmp_path, data))
