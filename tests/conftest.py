"""Home Assistant integration fixtures (Linux integration tests only)."""

import pytest


@pytest.fixture
def enable_custom_integration(enable_custom_integrations):
    """Enable loading our custom component."""
    return enable_custom_integrations
