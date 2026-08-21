"""Diagnostics about the integration, plus the device's own read-only readings.

Three kinds of sensor, deliberately:

* **Failed polls** — the measurement channel that tolerated failures would otherwise erase.
  Same reasoning as sibling_beacon's sensor.py: a fix that hides a fault must ship with the
  meter that still records it.
* **Battery** (DP 101) and **countdown remaining** (DP 5) — real device readings,
  write-verified as mirrors on 2026-08-21 (docs/datapoints.md). These go unavailable with
  the device, unlike the diagnostics.
* **Datapoints** — the raw DP set, exposed as attributes. This was the recon phase's primary
  instrument inside Home Assistant, before the map existed. It stays as scaffolding while
  docs/datapoints.md has open questions (DP 2, 102, 104) — it is how new DPs would be
  noticed — and can be deleted once the map settles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant

from . import dp
from .coordinator import ArozenConfigEntry, ArozenCoordinator

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from .entity import ArozenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArozenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ArozenFailedPollsSensor(coordinator),
            ArozenBatterySensor(coordinator),
            ArozenCountdownRemainingSensor(coordinator),
            ArozenDatapointsSensor(coordinator),
        ]
    )


class ArozenDiagnosticSensor(ArozenEntity, SensorEntity):
    """A counter or readout about the integration itself.

    Always available, and that is the point: a diagnostic that goes `unavailable` whenever
    the device does hides its most interesting readings — including the second consecutive
    failure, which is the exact event that takes every other entity down.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """Always. This reports on the integration, not on the diffuser."""
        return True


class ArozenFailedPollsSensor(ArozenDiagnosticSensor):
    """How many status polls have failed since the integration loaded."""

    _attr_name = "Failed polls"
    _attr_icon = "mdi:radar"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "failed_polls")

    @property
    def native_value(self) -> int:
        """Total failures since the config entry loaded. Resets on reload, deliberately."""
        return self.coordinator.health.total

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        health = self.coordinator.health
        return {
            "consecutive": health.consecutive,
            "tolerated": health.tolerated,
            "last_error": health.last_error,
            "last_failure": health.last_failure.isoformat() if health.last_failure else None,
        }


class ArozenBatterySensor(ArozenEntity, SensorEntity):
    """Battery percent (DP 101). The unit is mains-powered but has a battery too."""

    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "battery")

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return dp.get(self.coordinator.data, dp.DP_BATTERY)


class ArozenCountdownRemainingSensor(ArozenEntity, SensorEntity):
    """Minutes left on the auto-off timer (DP 5). Zero when untimed."""

    _attr_name = "Timer remaining"
    _attr_icon = "mdi:timer-outline"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "timer_remaining")

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return dp.get(self.coordinator.data, dp.DP_COUNTDOWN_REMAINING)


class ArozenDatapointsSensor(ArozenDiagnosticSensor):
    """The raw DP set, as reported by the last successful poll.

    Scaffolding for the recon phase: docs/datapoints.md is empty and this is the way to
    watch the DPs change while toggling controls in the Tuya app, from the Home Assistant
    UI. State is the count of DPs seen; the set itself is in the attributes. Delete this
    entity once real entities exist for the mapped functions.
    """

    _attr_name = "Datapoints (recon)"
    _attr_icon = "mdi:database-search-outline"

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "datapoints")

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The raw dps dict, keyed by DP id as the device reports it. No interpretation."""
        if self.coordinator.data is None:
            return {}
        return {"dps": dict(sorted(self.coordinator.data.items(), key=lambda kv: int(kv[0])))}
