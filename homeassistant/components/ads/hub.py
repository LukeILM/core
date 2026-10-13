"""Support for Automation Device Specification (ADS)."""

from collections import namedtuple
from collections.abc import Callable
from contextlib import suppress
import ctypes
from datetime import datetime
import logging
import struct
import threading
from typing import Any

import pyads

from homeassistant.core import HomeAssistant

from .const import DEFAULT_ADS_CLIENT

_LOGGER = logging.getLogger(__name__)

# Tuple to hold data needed for notification
NotificationItem = namedtuple(  # noqa: PYI024
    "NotificationItem", "hnotify huser name plc_datatype callback"
)
type NotificationSubscription = tuple[str, type, Callable[[str, Any], None]]


class AdsHub:
    """Representation of an ADS connection."""

    def __init__(self, ads_client, client_id: str = DEFAULT_ADS_CLIENT) -> None:
        """Initialize the ADS hub."""
        self._client = ads_client
        self._client_id = client_id
        self._client.open()

        # All ADS devices are registered here
        self._devices: list[object] = []
        self._notification_items: dict[int, NotificationItem] = {}
        self._notification_subscriptions: list[NotificationSubscription] = []
        self._pending_subscriptions: list[NotificationSubscription] = []
        self._last_state: tuple[int, int] | None = None
        self._lock = threading.Lock()

    def entity_unique_id(self, ads_var: str) -> str:
        """Return an entity ID scoped to this client when it is not the default."""
        if self._client_id == DEFAULT_ADS_CLIENT:
            return ads_var
        return f"{self._client_id}_{ads_var}"

    def shutdown(self, *args, **kwargs):
        """Shutdown ADS connection."""

        _LOGGER.debug("Shutting down ADS")
        with self._lock:
            for notification_item in self._notification_items.values():
                _LOGGER.debug(
                    "Deleting device notification %d, %d",
                    notification_item.hnotify,
                    notification_item.huser,
                )
                try:
                    self._client.del_device_notification(
                        notification_item.hnotify, notification_item.huser
                    )
                except pyads.ADSError as err:
                    _LOGGER.error(err)
            try:
                self._client.close()
            except pyads.ADSError as err:
                _LOGGER.error(err)

    def register_device(self, device):
        """Register a new device."""
        self._devices.append(device)

    def write_by_name(self, name, value, plc_datatype):
        """Write a value to the device."""

        with self._lock:
            try:
                return self._client.write_by_name(name, value, plc_datatype)
            except pyads.ADSError as err:
                _LOGGER.error("Error writing %s: %s", name, err)

    def read_by_name(self, name, plc_datatype):
        """Read a value from the device."""

        with self._lock:
            try:
                return self._client.read_by_name(name, plc_datatype)
            except pyads.ADSError as err:
                _LOGGER.error("Error reading %s: %s", name, err)

    def add_device_notification(self, name, plc_datatype, callback):
        """Add a notification to the ADS devices."""

        subscription = (name, plc_datatype, callback)
        with self._lock:
            self._notification_subscriptions.append(subscription)
            if not self._register_notification(subscription):
                self._pending_subscriptions.append(subscription)

    def _register_notification(self, subscription: NotificationSubscription) -> bool:
        """Register one notification and store its active handles."""
        name, plc_datatype, callback = subscription
        attr = pyads.NotificationAttrib(ctypes.sizeof(plc_datatype))

        try:
            handles = self._client.add_device_notification(
                name, attr, self._device_notification_callback
            )
        except pyads.ADSError as err:
            _LOGGER.error("Error subscribing to %s: %s", name, err)
            return False

        if handles is None:
            return False

        hnotify, huser = handles
        hnotify = int(hnotify)
        self._notification_items[hnotify] = NotificationItem(
            hnotify, huser, name, plc_datatype, callback
        )
        _LOGGER.debug("Added device notification %d for variable %s", hnotify, name)
        return True

    def _register_pending_subscriptions(self) -> None:
        """Retry subscriptions that were not active after connecting."""
        pending_subscriptions = self._pending_subscriptions
        self._pending_subscriptions = []
        for subscription in pending_subscriptions:
            if not self._register_notification(subscription):
                self._pending_subscriptions.append(subscription)

    def _check_connection(self) -> None:
        """Check the PLC connection and reconnect if it was interrupted."""
        with self._lock:
            try:
                state = self._client.read_state()
            except pyads.ADSError:
                state = None

            if state is None:
                self._last_state = None
                self._reconnect()
            elif self._last_state is not None and state != self._last_state:
                self._last_state = state
                self._reconnect()
            else:
                self._last_state = state
                self._register_pending_subscriptions()

    def _reconnect(self) -> None:
        """Reconnect to the PLC and restore its device notifications."""
        _LOGGER.debug("ADS connection lost; reconnecting")
        for notification_item in self._notification_items.values():
            with suppress(pyads.ADSError):
                self._client.del_device_notification(
                    notification_item.hnotify, notification_item.huser
                )

        self._notification_items.clear()
        self._pending_subscriptions = self._notification_subscriptions.copy()

        try:
            self._client.close()
            self._client.open()
            state = self._client.read_state()
            if state is None:
                self._last_state = None
                return
            self._last_state = state
        except pyads.ADSError as err:
            self._last_state = None
            _LOGGER.debug("ADS reconnect failed: %s", err)
            return

        self._register_pending_subscriptions()
        _LOGGER.info("Reconnected to ADS client %s", self._client_id)

    async def async_check_connection(self, hass: HomeAssistant, _now: datetime) -> None:
        """Check the ADS connection without blocking Home Assistant."""
        await hass.async_add_executor_job(self._check_connection)

    def _device_notification_callback(self, notification, name):
        """Handle device notifications."""
        contents = notification.contents
        hnotify = int(contents.hNotification)
        _LOGGER.debug("Received notification %d", hnotify)

        # Get dynamically sized data array
        data_size = contents.cbSampleSize
        data_address = (
            ctypes.addressof(contents)
            + pyads.structs.SAdsNotificationHeader.data.offset
        )
        data = (ctypes.c_ubyte * data_size).from_address(data_address)

        # Acquire notification item
        with self._lock:
            notification_item = self._notification_items.get(hnotify)

        if not notification_item:
            _LOGGER.error("Unknown device notification handle: %d", hnotify)
            return

        # Data parsing based on PLC data type
        plc_datatype = notification_item.plc_datatype
        unpack_formats = {
            pyads.PLCTYPE_BYTE: "<b",
            pyads.PLCTYPE_INT: "<h",
            pyads.PLCTYPE_UINT: "<H",
            pyads.PLCTYPE_SINT: "<b",
            pyads.PLCTYPE_USINT: "<B",
            pyads.PLCTYPE_DINT: "<i",
            pyads.PLCTYPE_UDINT: "<I",
            pyads.PLCTYPE_WORD: "<H",
            pyads.PLCTYPE_DWORD: "<I",
            pyads.PLCTYPE_LREAL: "<d",
            pyads.PLCTYPE_REAL: "<f",
            pyads.PLCTYPE_TOD: "<i",  # Treat as DINT
            pyads.PLCTYPE_DATE: "<i",  # Treat as DINT
            pyads.PLCTYPE_DT: "<i",  # Treat as DINT
            pyads.PLCTYPE_TIME: "<i",  # Treat as DINT
        }

        if plc_datatype == pyads.PLCTYPE_BOOL:
            value = bool(struct.unpack("<?", bytearray(data))[0])
        elif plc_datatype == pyads.PLCTYPE_STRING:
            value = (
                bytearray(data).split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
            )
        elif plc_datatype in unpack_formats:
            value = struct.unpack(unpack_formats[plc_datatype], bytearray(data))[0]
        else:
            value = bytearray(data)
            _LOGGER.warning("No callback available for this datatype")

        notification_item.callback(notification_item.name, value)
