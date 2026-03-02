"""Server fixtures for E2E tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from clawstrike.classifier import ClassifierResult


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
