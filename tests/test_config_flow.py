"""Exercise config and options flows with Home Assistant's real flow manager."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

if sys.platform == "win32":
    pytest.skip(
        "Home Assistant integration tests require Linux", allow_module_level=True
    )

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.goxlr_utility.const import (
    CONF_LIGHTS,
    CONF_SMOOTHING,
    DEFAULT_PORT,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integration")


async def test_form_and_duplicate(hass):
    info = {"title": "GoXLR", "identifier": "SERIAL"}
    with (
        patch(
            "custom_components.goxlr_utility.config_flow.validate_input",
            return_value=info,
        ),
        patch("custom_components.goxlr_utility.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "localhost", CONF_PORT: DEFAULT_PORT}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_HOST: "localhost", CONF_PORT: DEFAULT_PORT},
        )
        assert duplicate["type"] == FlowResultType.ABORT
        assert duplicate["reason"] == "already_configured"


async def test_validation_always_disconnects(hass):
    from custom_components.goxlr_utility.config_flow import validate_input
    from custom_components.goxlr_utility.helper import CannotConnect

    client = SimpleNamespace(get_status=AsyncMock(), disconnect=AsyncMock(), mixer=None)
    with patch(
        "custom_components.goxlr_utility.config_flow.setup_connection",
        return_value=client,
    ):
        with pytest.raises(CannotConnect):
            await validate_input(
                hass, {CONF_HOST: "localhost", CONF_PORT: DEFAULT_PORT}
            )
    client.disconnect.assert_awaited_once()


async def test_options(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "localhost", CONF_PORT: DEFAULT_PORT},
        unique_id="SERIAL",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"a": "light.desk", "b": "light.desk"}
    )
    assert result["errors"] == {"base": "duplicate_light"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"a": "light.desk"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_LIGHTS: {"a": "light.desk"}, CONF_SMOOTHING: 0.2}
