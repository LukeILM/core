"""Services for the ADS integration."""

import probatio

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ADS_TYPEMAP,
    CONF_ADS_TYPE,
    CONF_ADS_VALUE,
    CONF_ADS_VAR,
    DOMAIN,
    AdsType,
)
from .entity import ADS_CLIENT_SCHEMA, get_ads_hub

SERVICE_WRITE_DATA_BY_NAME = "write_data_by_name"

SCHEMA_SERVICE_WRITE_DATA_BY_NAME = probatio.Schema(
    {
        **ADS_CLIENT_SCHEMA,
        probatio.Required(CONF_ADS_TYPE): probatio.Coerce(AdsType),
        probatio.Required(CONF_ADS_VALUE): probatio.Coerce(int),
        probatio.Required(CONF_ADS_VAR): cv.string,
    }
)


def _handle_write_data_by_name(call: ServiceCall) -> None:
    """Write a value to the connected ADS device."""
    ads = get_ads_hub(call.hass, call.data)
    ads_var: str = call.data[CONF_ADS_VAR]
    ads_type: AdsType = call.data[CONF_ADS_TYPE]
    value: int = call.data[CONF_ADS_VALUE]

    ads.write_by_name(ads_var, value, ADS_TYPEMAP[ads_type])


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the ADS services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_DATA_BY_NAME,
        _handle_write_data_by_name,
        schema=SCHEMA_SERVICE_WRITE_DATA_BY_NAME,
    )
