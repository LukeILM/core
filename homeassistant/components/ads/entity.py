"""Support for Automation Device Specification (ADS)."""

import asyncio
from asyncio import timeout
import logging
from typing import Any, override

import probatio

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ADS_CLIENT, DATA_ADS, DEFAULT_ADS_CLIENT, STATE_KEY_STATE
from .hub import AdsHub

_LOGGER = logging.getLogger(__name__)

ADS_CLIENT_SCHEMA = {
    probatio.Optional(CONF_ADS_CLIENT): probatio.All(cv.string, probatio.Length(min=1))
}


def get_ads_hub(hass: HomeAssistant, config: ConfigType) -> AdsHub:
    """Get the ADS hub selected by an entity or service configuration."""
    ads_hubs = hass.data[DATA_ADS]
    client_id = config.get(CONF_ADS_CLIENT)

    if client_id is None:
        if DEFAULT_ADS_CLIENT in ads_hubs:
            client_id = DEFAULT_ADS_CLIENT
        elif len(ads_hubs) == 1:
            return next(iter(ads_hubs.values()))
        else:
            raise HomeAssistantError(
                "The ads_client field is required when multiple ADS clients are configured"
            )

    if client_id not in ads_hubs:
        raise HomeAssistantError(f"ADS client {client_id!r} is not configured")

    return ads_hubs[client_id]


class AdsEntity(Entity):
    """Representation of ADS entity."""

    _attr_should_poll = False

    def __init__(self, ads_hub: AdsHub, name: str, ads_var: str) -> None:
        """Initialize ADS binary sensor."""
        self._state_dict: dict[str, Any] = {}
        self._state_dict[STATE_KEY_STATE] = None
        self._ads_hub = ads_hub
        self._ads_var = ads_var
        self._event: asyncio.Event | None = None
        self._attr_unique_id = ads_hub.entity_unique_id(ads_var)
        self._attr_name = name

    async def async_initialize_device(
        self,
        ads_var: str,
        plctype: type,
        state_key: str = STATE_KEY_STATE,
        factor: int | None = None,
    ) -> None:
        """Register device notification."""

        def update(name, value):
            """Handle device notifications."""
            _LOGGER.debug("Variable %s changed its value to %d", name, value)

            if factor is None:
                self._state_dict[state_key] = value
            else:
                self._state_dict[state_key] = value / factor

            asyncio.run_coroutine_threadsafe(async_event_set(), self.hass.loop)
            self.schedule_update_ha_state()

        async def async_event_set():
            """Set event in async context."""
            self._event.set()

        self._event = asyncio.Event()

        await self.hass.async_add_executor_job(
            self._ads_hub.add_device_notification, ads_var, plctype, update
        )
        try:
            async with timeout(10):
                await self._event.wait()
        except TimeoutError:
            _LOGGER.debug("Variable %s: Timeout during first update", ads_var)

    @property
    @override
    def available(self) -> bool:
        """Return False if state has not been updated yet."""
        return self._state_dict[STATE_KEY_STATE] is not None
