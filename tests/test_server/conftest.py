"""Shared pytest fixtures for test_server/ tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawstrike.classifier import ClassifierResult
from clawstrike.config import ClawStrikeConfig, load_config

from .helpers import minimal_config, write_yaml


@pytest.fixture
def cfg(tmp_path: Path) -> ClawStrikeConfig:
    """Return a minimal validated config with a per-test isolated DB path."""
    data = minimal_config()
    data["clawstrike"]["audit"] = {"db_path": str(tmp_path / "test.db")}
    return load_config(write_yaml(tmp_path, data))


@pytest.fixture(autouse=True)
def reset_server_config():
    """Reset module globals and mock create_classifier for each test.

    Patching create_classifier prevents any attempt to download real HF models.
    The mock classifier returns a fixed benign ClassifierResult by default;
    individual tests may override mock_clf.classify.return_value to set a
    specific score.

    Yields the mock classifier so tests can configure score/label per-scenario.
    """
    import clawstrike.mcpserver as srv

    mock_clf = MagicMock()
    mock_clf.classify.return_value = ClassifierResult(
        score=0.0, label="benign", model="mock-model", latency_ms=1.0
    )

    with patch("clawstrike.mcpserver.create_classifier", return_value=mock_clf):
        yield mock_clf

    srv._config = None
    srv._classifier = None
    srv._elevated_sessions.clear()
    srv._mismatch_sessions.clear()
    srv._db_path = None
