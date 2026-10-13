"""Tests for the ADS integration setup."""

from typing import cast
from unittest.mock import Mock, call, patch

import pytest

from homeassistant.components.ads.const import (
    CONF_ADS_CLIENT,
    CONF_ADS_CLIENTS,
    DATA_ADS,
    DOMAIN,
)
from homeassistant.components.ads.entity import get_ads_hub
from homeassistant.components.ads.hub import AdsHub
from homeassistant.const import CONF_DEVICE, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import ConfigType
from homeassistant.setup import async_setup_component


@pytest.mark.parametrize(
    ("config", "client_ids"),
    [
        pytest.param(
            {DOMAIN: {CONF_DEVICE: "1.2.3.4.5.6", CONF_PORT: 851}},
            ["default"],
            id="legacy-single-client",
        ),
        pytest.param(
            {
                DOMAIN: {
                    CONF_ADS_CLIENTS: {
                        "default": {CONF_DEVICE: "1.2.3.4.5.6", CONF_PORT: 851},
                        "secondary": {CONF_DEVICE: "2.3.4.5.6.7", CONF_PORT: 852},
                    }
                }
            },
            ["default", "secondary"],
            id="named-clients",
        ),
    ],
)
async def test_async_setup_supports_client_configurations(
    hass: HomeAssistant, config: ConfigType, client_ids: list[str]
) -> None:
    """Set up a legacy client or multiple named clients."""
    clients = [Mock() for _ in client_ids]
    hubs = [Mock() for _ in client_ids]

    with (
        patch(
            "homeassistant.components.ads.pyads.Connection", side_effect=clients
        ) as connection,
        patch("homeassistant.components.ads.AdsHub", side_effect=hubs) as ads_hub,
    ):
        assert await async_setup_component(hass, DOMAIN, config)

    assert hass.data[DATA_ADS] == dict(zip(client_ids, hubs, strict=True))
    assert ads_hub.call_args_list == [
        call(client, client_id)
        for client, client_id in zip(clients, client_ids, strict=True)
    ]
    assert connection.call_count == len(client_ids)


def test_get_ads_hub_selects_named_client(hass: HomeAssistant) -> None:
    """Select the requested hub and default to the legacy client."""
    default_hub = cast(AdsHub, Mock())
    secondary_hub = cast(AdsHub, Mock())
    hass.data[DATA_ADS] = {"default": default_hub, "secondary": secondary_hub}

    assert get_ads_hub(hass, {CONF_ADS_CLIENT: "secondary"}) is secondary_hub
    assert get_ads_hub(hass, {}) is default_hub


def test_get_ads_hub_requires_client_when_ambiguous(hass: HomeAssistant) -> None:
    """Require an explicit client when no default exists."""
    hass.data[DATA_ADS] = {
        "first": cast(AdsHub, Mock()),
        "second": cast(AdsHub, Mock()),
    }

    with pytest.raises(HomeAssistantError, match="ads_client field is required"):
        get_ads_hub(hass, {})


def test_entity_unique_id_is_scoped_to_client() -> None:
    """Keep default IDs stable and separate IDs from other clients."""
    default_hub = AdsHub(Mock())
    secondary_hub = AdsHub(Mock(), "secondary")

    assert default_hub.entity_unique_id("GVL.value") == "GVL.value"
    assert secondary_hub.entity_unique_id("GVL.value") == "secondary_GVL.value"
