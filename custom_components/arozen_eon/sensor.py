"""Diagnostics about the integration, plus the device's own read-only readings.

Three kinds of sensor, deliberately:

* **Failed polls** and **Intensity restores** — the two measurement channels that the
  fixes above them would otherwise erase. Same reasoning as sibling_beacon's sensor.py: a fix
  that hides a fault must ship with the meter that still records it. A tolerated poll failure
  leaves no visible trace, and a *successful* intensity restore leaves no visible trace that
  the firmware threw the level away at all — so both get counted.
* **Battery** (DP 101) and **countdown remaining** (DP 5) — real device readings,
  write-verified as mirrors on 2026-08-21 (docs/datapoints.md). These go unavailable with
  the device, unlike the diagnostics.
* **Datapoints** — the raw DP set, exposed as attributes. This was the recon phase's primary
  instrument inside Home Assistant, before the map existed, and it is the one entity here that
  ships **disabled** (#51): it is scaffolding for whoever is still chasing DP 104, on a device
  page belonging to someone who just wants a diffuser. DP 2 came off that list the hard way:
  it was the power switch all along, sitting unidentified while the switch entity wrote to
  the valve.
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
            ArozenIntensityRestoresSensor(coordinator),
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


class ArozenIntensityRestoresSensor(ArozenDiagnosticSensor):
    """How often the firmware's power-on intensity reset has been undone (#14).

    The device clears intensity to L1 every time it is switched on, by any source, and the
    coordinator writes the level back. That fix works, which is precisely why it needs a
    meter: once the level is right again there is nothing left to show it was ever wrong.
    A counter in the recorder is where "this fired forty times last night" becomes visible,
    and forty restores in a night means something is power-cycling the diffuser.

    The failures are the other half. A restore that does not land leaves the device running at
    L1 with the user's level lost, and the intensity select will show L1 — which is the truth,
    not a lie, but says nothing about why. ``last_error`` says why.
    """

    _attr_name = "Intensity restores"
    _attr_icon = "mdi:backup-restore"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "intensity_restores")

    @property
    def native_value(self) -> int:
        """Restores the device accepted since the config entry loaded."""
        return self.coordinator.intensity.restored

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        memory = self.coordinator.intensity
        return {
            "failed": memory.failures,
            "last_error": memory.last_error,
            # The level that would be written after the next power-on, and None when nothing
            # has taught us one yet. Worth showing: it is the whole state of the memory, and
            # a restore that declines because it remembers nothing looks identical from
            # outside to one that declines because the level is already right.
            "remembered_level": memory.wanted,
            # Named for the state it actually reports: whether a restore has been written and
            # not yet seen back. An earlier revision exposed the inverse as `confirmed`, which
            # read as "the last restore was confirmed" on a fresh load where no restore had
            # ever been attempted - true by vacuum, and misleading to anyone reading it next
            # to a count of zero.
            "restore_unconfirmed": memory.unconfirmed,
        }


class ArozenBatterySensor(ArozenEntity, SensorEntity):
    """Battery percent (DP 101). The unit is rechargeable and genuinely runs off this — it
    discharged one point per 61 s of runtime through the remote walk — rather than carrying a
    cell as backup to mains. DP 102 reports which of the two it is on.
    """

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
    """The raw DP set, as reported by the last successful poll. Ships disabled (#51).

    State is the count of DPs seen; the set itself is in the attributes. Two jobs, and only
    the first of them is finished:

    * **the recon instrument** — watch DPs move while toggling controls in the phone app,
      from the Home Assistant UI rather than by running tools/ scripts at a device three
      rooms away. That workflow is *done*: docs/datapoints.md records every control the app
      exposes as mapped to some other DP, so there is no untried stimulus left to aim at
      DP 104, and the leading explanation for it is now a firmware constant rather than a
      control nobody has pressed;
    * **a tripwire on the count** — a firmware update that starts reporting a new DP, or
      DP 104 finally moving, changes numbers the recorder has been keeping all along. That
      job has no end date, which is why the "delete this entity once the map settles" note
      that used to close this docstring is gone: the map is as settled as toggling can make
      it, and the trigger that note named was never going to fire.

    **Why disabled rather than deleted, or put behind an option (#51).** Deleting it takes
    away the only *live* view of the raw dps — diagnostics.py carries the same dict into the
    download, but a download is a snapshot and this is a watch. An options-flow flag
    defaulting off was the alternative, and it is the wrong shape for precisely the reason
    this is the right one: ``entity_registry_enabled_default`` is read only when an entity is
    registered for the *first* time — ``async_get_or_create`` returns early for a unique_id it
    already knows, and does not forward ``disabled_by`` on that path — so this change is inert
    on every install that already has the entity, including the one where the tripwire is
    actually being watched. A default-off option would have reached back and switched it off
    there too, which is the opposite of what the issue asked for: spare the installer, do not
    disarm the maintainer.

    Turning it on is one toggle in the entity's settings, and Home Assistant reloads the entry
    itself. Nothing is recorded while it is off — true of every way of hiding it, since the
    recorder cannot keep history for an entity that is not reporting.
    """

    _attr_name = "Datapoints (recon)"
    _attr_icon = "mdi:database-search-outline"
    #: Deliberately not ``entity_registry_visible_default``, which is the other way to keep it
    #: off the device page. Hidden is worse than disabled here: a hidden entity still holds a
    #: state, still fills the recorder and still answers to automations, so it costs the
    #: installer everything about this sensor except the sight of it.
    _attr_entity_registry_enabled_default = False

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
