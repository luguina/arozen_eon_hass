"""Shared entity base for the Arozen EON Pro 2."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import ArozenCoordinator


class ArozenEntity(CoordinatorEntity[ArozenCoordinator]):
    """Base class wiring every entity to one diffuser."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ArozenCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device.device_id)},
            name="Arozen EON Pro 2",
            manufacturer=MANUFACTURER,
            model=MODEL,
            # The Tuya status payload carries no firmware version we can trust yet, so none
            # is reported. Leaving it unset is honest; inventing it is not.
        )

    @property
    def available(self) -> bool:
        """Fresh, or stale by no more than the tolerated number of missed polls.

        Unlike the sibling project there is no presence signal cheaper than the poll itself, so this
        is only the second of the sibling project's two gates: a single failed poll holds the previous
        reading instead of going unavailable for a full interval (see PollHealth for why
        that is honest rather than a lie).

        ``data is not None`` is the precondition: tolerating a failure *means* holding the
        previous reading, so with no previous reading there is nothing to hold.
        """
        if super().available:
            return True
        return self.coordinator.data is not None and self.coordinator.health.may_hold_reading
