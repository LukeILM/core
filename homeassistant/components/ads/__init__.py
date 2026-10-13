"""Support for Automation Device Specification (ADS)."""

import logging

import probatio
import pyads

from homeassistant.const import (
    CONF_DEVICE,
    CONF_IP_ADDRESS,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ADS_CLIENTS, DATA_ADS, DEFAULT_ADS_CLIENT, DOMAIN
from .hub import AdsHub
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


ADS_CLIENT_CONFIG_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_DEVICE): cv.string,
        probatio.Required(CONF_PORT): probatio.Port(),
        probatio.Optional(CONF_IP_ADDRESS): cv.string,
    }
)

CONFIG_SCHEMA = probatio.Schema(
    {
        DOMAIN: probatio.Any(
            ADS_CLIENT_CONFIG_SCHEMA,
            probatio.Schema(
                {
                    probatio.Required(CONF_ADS_CLIENTS): probatio.All(
                        probatio.Schema({cv.slug: ADS_CLIENT_CONFIG_SCHEMA}),
                        probatio.Length(min=1),
                    )
                }
            ),
        )
    },
    extra=probatio.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ADS component."""
    async_setup_services(hass)

    conf = config[DOMAIN]
    client_confs = conf.get(CONF_ADS_CLIENTS, {DEFAULT_ADS_CLIENT: conf})
    ads_hubs: dict[str, AdsHub] = {}

    for client_id, client_conf in client_confs.items():
        net_id = client_conf[CONF_DEVICE]
        ip_address = client_conf.get(CONF_IP_ADDRESS)
        port = client_conf[CONF_PORT]
        client = pyads.Connection(net_id, port, ip_address)

        try:
            ads = await hass.async_add_executor_job(AdsHub, client, client_id)
        except pyads.ADSError:
            _LOGGER.error(
                "Could not connect to ADS host (netid=%s, ip=%s, port=%s)",
                net_id,
                ip_address,
                port,
            )
            for connected_hub in ads_hubs.values():
                await hass.async_add_executor_job(connected_hub.shutdown)
            return False

        ads_hubs[client_id] = ads

    hass.data[DATA_ADS] = ads_hubs
    for ads in ads_hubs.values():
        hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, ads.shutdown)

    return True
