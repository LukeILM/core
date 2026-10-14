"""Support for ADS switch platform."""

from typing import Any, override

import probatio
import pyads

from homeassistant.components.switch import (
    PLATFORM_SCHEMA as SWITCH_PLATFORM_SCHEMA,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    AddEntitiesCallback,
)
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import CONF_ADS_VAR, DATA_ADS, STATE_KEY_STATE
from .entity import ADS_CLIENT_SCHEMA, AdsEntity, get_ads_hub

DEFAULT_NAME = "ADS Switch"

PLATFORM_SCHEMA = SWITCH_PLATFORM_SCHEMA.extend(
    {
        probatio.Required(CONF_ADS_VAR): cv.string,
        probatio.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
).extend(ADS_CLIENT_SCHEMA)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up switch platform for ADS."""
    ads_hub = get_ads_hub(hass, config)

    name: str = config[CONF_NAME]
    ads_var: str = config[CONF_ADS_VAR]

    add_entities([AdsSwitch(ads_hub, name, ads_var)])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up ADS switches selected in the config flow."""
    ads_hub = hass.data[DATA_ADS][entry.entry_id]
    async_add_entities(
        [
            AdsSwitch(ads_hub, symbol[CONF_ADS_VAR], symbol[CONF_ADS_VAR])
            for symbol in entry.data["symbols"]
            if symbol["platform"] == "switch"
        ]
    )


class AdsSwitch(AdsEntity, SwitchEntity):
    """Representation of an ADS switch device."""

    @override
    async def async_added_to_hass(self) -> None:
        """Register device notification."""
        await self.async_initialize_device(self._ads_var, pyads.PLCTYPE_BOOL)

    @property
    @override
    def is_on(self) -> bool:
        """Return True if the entity is on."""
        return self._state_dict[STATE_KEY_STATE]

    @override
    def turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._ads_hub.write_by_name(self._ads_var, True, pyads.PLCTYPE_BOOL)

    @override
    def turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._ads_hub.write_by_name(self._ads_var, False, pyads.PLCTYPE_BOOL)
