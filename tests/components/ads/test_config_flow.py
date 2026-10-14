"""Tests for the ADS config flow."""

from unittest.mock import AsyncMock, Mock, patch

from homeassistant.components.ads.const import (
    CONF_ADS_TYPE,
    CONF_ADS_VAR,
    DATA_ADS,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_DEVICE, CONF_IP_ADDRESS, CONF_PLATFORM, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry


async def test_config_flow_discovers_symbols_and_assigns_platforms(
    hass: HomeAssistant,
) -> None:
    """Discover PLC symbols and assign them to supported platforms."""
    temperature = Mock(name="temperature")
    temperature.name = "GVL.temperature"
    temperature.symbol_type = "DINT"
    pump = Mock(name="pump")
    pump.name = "GVL.pump"
    pump.symbol_type = "BOOL"

    with patch(
        "homeassistant.components.ads.config_flow.pyads.Connection"
    ) as connection:
        connection.return_value.get_all_symbols.return_value = [temperature, pump]
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "192.0.2.10",
                CONF_DEVICE: "1.2.3.4.5.6",
                CONF_PORT: 851,
            },
        )
        assert result["step_id"] == "add_symbol"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "select_symbol"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADS_VAR: "GVL.temperature"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PLATFORM: "sensor"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "select_symbol"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADS_VAR: "GVL.pump"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PLATFORM: "switch"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "1.2.3.4.5.6"
    assert result["result"].unique_id == "1.2.3.4.5.6:851"
    assert result["data"]["symbols"] == [
        {
            CONF_ADS_VAR: "GVL.temperature",
            CONF_ADS_TYPE: "dint",
            CONF_PLATFORM: "sensor",
        },
        {
            CONF_ADS_VAR: "GVL.pump",
            CONF_ADS_TYPE: "bool",
            CONF_PLATFORM: "switch",
        },
    ]
    assert connection.return_value.open.called
    assert connection.return_value.close.called


async def test_config_entry_sets_up_and_unloads(hass: HomeAssistant) -> None:
    """Set up and unload an ADS entry with a selected sensor."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE: "1.2.3.4.5.6",
            CONF_IP_ADDRESS: "192.0.2.10",
            CONF_PORT: 851,
            "symbols": [
                {
                    CONF_ADS_VAR: "GVL.temperature",
                    CONF_ADS_TYPE: "dint",
                    CONF_PLATFORM: "sensor",
                }
            ],
        },
        unique_id="1.2.3.4.5.6:851",
    )
    entry.add_to_hass(hass)

    with (
        patch("homeassistant.components.ads.pyads.Connection") as connection,
        patch(
            "homeassistant.components.ads.sensor.AdsSensor.async_added_to_hass",
            new_callable=AsyncMock,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert entry.entry_id in hass.data[DATA_ADS]
        assert await hass.config_entries.async_unload(entry.entry_id)

    assert entry.entry_id not in hass.data[DATA_ADS]
    assert connection.return_value.open.called
    assert connection.return_value.close.called
