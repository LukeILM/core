"""Support for Automation Device Specification (ADS)."""

from datetime import timedelta
from functools import partial
import logging

import probatio
import pyads

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DEVICE,
    CONF_IP_ADDRESS,
    CONF_PLATFORM,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ADS_CLIENTS, DATA_ADS, DEFAULT_ADS_CLIENT, DOMAIN
from .hub import AdsHub
from .services import SERVICE_WRITE_DATA_BY_NAME, async_setup_services

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
    if not hass.services.has_service(DOMAIN, SERVICE_WRITE_DATA_BY_NAME):
        async_setup_services(hass)

    hass.data.setdefault(DATA_ADS, {})
    if DOMAIN not in config:
        return True

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

    hass.data[DATA_ADS].update(ads_hubs)
    for client_id, ads in ads_hubs.items():
        _register_hub(hass, client_id, ads)

    return True


def _register_hub(
    hass: HomeAssistant,
    client_id: str,
    ads: AdsHub,
    config_entry: ConfigEntry | None = None,
) -> None:
    """Register connection shutdown and health-check callbacks."""
    stop_listener = hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, ads.shutdown)
    cancel_health_check = async_track_time_interval(
        hass,
        partial(ads.async_check_connection, hass),
        timedelta(seconds=10),
        cancel_on_shutdown=True,
        name=f"ADS {client_id}",
    )
    if config_entry is not None:
        config_entry.async_on_unload(stop_listener)
        config_entry.async_on_unload(cancel_health_check)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an ADS client configured through the UI."""
    client = pyads.Connection(
        entry.data[CONF_DEVICE], entry.data[CONF_PORT], entry.data[CONF_IP_ADDRESS]
    )
    try:
        ads = await hass.async_add_executor_job(AdsHub, client, entry.entry_id)
    except pyads.ADSError:
        _LOGGER.error(
            "Could not connect to ADS host (netid=%s, ip=%s, port=%s)",
            entry.data[CONF_DEVICE],
            entry.data[CONF_IP_ADDRESS],
            entry.data[CONF_PORT],
        )
        return False

    hass.data.setdefault(DATA_ADS, {})[entry.entry_id] = ads
    _register_hub(hass, entry.entry_id, ads, entry)

    platforms = list(
        {Platform(symbol[CONF_PLATFORM]) for symbol in entry.data["symbols"]}
    )
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an ADS client configured through the UI."""
    platforms = list(
        {Platform(symbol[CONF_PLATFORM]) for symbol in entry.data["symbols"]}
    )
    if platforms and not await hass.config_entries.async_unload_platforms(
        entry, platforms
    ):
        return False

    ads = hass.data[DATA_ADS].pop(entry.entry_id)
    await hass.async_add_executor_job(ads.shutdown)
    return True
