"""Config flow for the ADS integration."""

from typing import Any, override

import probatio
import pyads

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE, CONF_IP_ADDRESS, CONF_PLATFORM, CONF_PORT
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_ADS_TYPE, CONF_ADS_VAR, DOMAIN, AdsType

_SENSOR_TYPES = {
    AdsType.BYTE,
    AdsType.INT,
    AdsType.UINT,
    AdsType.SINT,
    AdsType.USINT,
    AdsType.DINT,
    AdsType.UDINT,
    AdsType.WORD,
    AdsType.DWORD,
    AdsType.LREAL,
    AdsType.REAL,
}
_SUPPORTED_TYPES = _SENSOR_TYPES | {AdsType.BOOL}


def _get_symbols(net_id: str, ip_address: str, port: int) -> dict[str, AdsType]:
    """Connect to an ADS device and return symbols supported by this integration."""
    connection = pyads.Connection(net_id, port, ip_address)
    try:
        connection.open()
        symbols: dict[str, AdsType] = {}
        for symbol in connection.get_all_symbols():
            try:
                ads_type = AdsType(symbol.symbol_type.lower())
            except ValueError:
                continue
            if ads_type in _SUPPORTED_TYPES and symbol.name:
                symbols[symbol.name] = ads_type
        return symbols
    finally:
        connection.close()


class AdsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure ADS devices and assign discovered symbols to platforms."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow state."""
        self._connection_data: dict[str, Any] = {}
        self._available_symbols: dict[str, AdsType] = {}
        self._configured_symbols: list[dict[str, str]] = []
        self._selected_symbol: str | None = None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect connection details and discover PLC symbols."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_DEVICE]}:{user_input[CONF_PORT]}"
            )
            self._abort_if_unique_id_configured()

            try:
                self._available_symbols = await self.hass.async_add_executor_job(
                    _get_symbols,
                    user_input[CONF_DEVICE],
                    user_input[CONF_IP_ADDRESS],
                    user_input[CONF_PORT],
                )
            except OSError, pyads.ADSError:
                errors["base"] = "cannot_connect"
            else:
                if not self._available_symbols:
                    errors["base"] = "no_supported_symbols"
                else:
                    self._connection_data = user_input
                    return await self.async_step_add_symbol()

        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_IP_ADDRESS): cv.string,
                    probatio.Required(CONF_DEVICE): cv.string,
                    probatio.Required(CONF_PORT, default=851): probatio.Port(),
                }
            ),
            errors=errors,
        )

    async def async_step_add_symbol(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose whether to assign another symbol or finish setup."""
        menu_options = ["finish"]
        if self._available_symbols:
            menu_options.insert(0, "select_symbol")
        return self.async_show_menu(step_id="add_symbol", menu_options=menu_options)

    async def async_step_select_symbol(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a discovered PLC symbol."""
        if user_input is not None:
            self._selected_symbol = user_input[CONF_ADS_VAR]
            return await self.async_step_select_platform()

        options = [
            SelectOptionDict(value=name, label=f"{name} ({ads_type.value})")
            for name, ads_type in self._available_symbols.items()
        ]
        return self.async_show_form(
            step_id="select_symbol",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_ADS_VAR): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_select_platform(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Assign the selected symbol to a Home Assistant platform."""
        assert self._selected_symbol is not None
        if user_input is not None:
            symbol = self._selected_symbol
            ads_type = self._available_symbols[symbol]
            self._configured_symbols.append(
                {
                    CONF_ADS_VAR: symbol,
                    CONF_ADS_TYPE: ads_type.value,
                    CONF_PLATFORM: user_input[CONF_PLATFORM],
                }
            )
            del self._available_symbols[symbol]
            self._selected_symbol = None
            return await self.async_step_add_symbol()

        symbol_type = self._available_symbols[self._selected_symbol]
        if symbol_type is AdsType.BOOL:
            platforms = ["binary_sensor", "light", "switch", "valve"]
        else:
            platforms = ["sensor"]

        return self.async_show_form(
            step_id="select_platform",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_PLATFORM): SelectSelector(
                        SelectSelectorConfig(
                            options=platforms,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the ADS config entry."""
        return self.async_create_entry(
            title=self._connection_data[CONF_DEVICE],
            data={
                **self._connection_data,
                "symbols": self._configured_symbols,
            },
        )
