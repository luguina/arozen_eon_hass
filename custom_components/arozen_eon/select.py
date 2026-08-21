"""Intensity and timer selects for the Arozen EON Pro 2.

Two enum DPs, both write-verified on the device 2026-08-21 (docs/datapoints.md):

* **Intensity** — DP 3, ``L1``…``L6``. There is no intensity *number* on this device: the
  level is the whole surface, and the device mirrors it as pause seconds on DP 106
  (L1=60 s … L6=2400 s) with a fixed 30 s burst (DP 105). Same physics as the sibling project's
  work/pause pair, one DP instead of two. Shown as "L1 · every 1 min" because the level
  number counts *pause* — L1 is the strongest setting, which "L1…L6" alone would hide.
* **Timer** — DP 4, four settings, mirrored as remaining minutes on DP 5. The firmware's
  ``"3h"`` arms **240 minutes**, which the manual calls the 4-hour setting: the string is
  simply wrong, so the select labels these by duration ("4 hours") rather than repeating a
  value that would mislead. An earlier revision also offered ``2h`` and ``4h``; the device
  has never acknowledged either and they are gone.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import dp
from .coordinator import ArozenConfigEntry, ArozenCoordinator

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from .device import ArozenError
from .entity import ArozenEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArozenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ArozenIntensitySelect(coordinator),
            ArozenTimerSelect(coordinator),
        ]
    )


class ArozenDpSelect(ArozenEntity, SelectEntity):
    """Shared behaviour for a select backed by one enum DP.

    The device's own enum values are not fit to show a user - ``L1``…``L6`` hide the fact
    that the number counts *pause* (so it runs strongest to weakest), and the countdown's
    ``"3h"`` is mislabelled by the firmware and actually arms four hours. So this class
    keeps a label↔value map: Home Assistant shows the label, the device gets the value.

    Both directions are looked up rather than parsed, and an unrecognised value from the
    device reads as ``None`` (unknown) instead of being shown raw. If the firmware ever
    grows a seventh intensity level, the entity says "unknown" until dp.py learns about it,
    which is the honest answer and the one that gets noticed.
    """

    _dp: int
    _label: str
    #: device value -> label shown in Home Assistant
    _labels: dict[str, str]

    @property
    def _values(self) -> dict[str, str]:
        """label -> device value. Derived, so it cannot drift from _labels."""
        return {label: value for value, label in self._labels.items()}

    @property
    def current_option(self) -> str | None:
        """The label for the device's current value, or None if we cannot name it."""
        if self.coordinator.data is None:
            return None
        return self._labels.get(dp.get(self.coordinator.data, self._dp))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The raw DP value, always. Rule 3 of tools/README.md applies to entities too:
        showing the interpretation without the raw value makes a wrong interpretation
        invisible."""
        if self.coordinator.data is None:
            return {}
        return {"raw_value": dp.get(self.coordinator.data, self._dp)}

    async def async_select_option(self, option: str) -> None:
        value = self._values.get(option)
        if value is None:
            # Home Assistant validates against _attr_options before calling, so this is a
            # bug in the map rather than bad user input - fail loudly, do not write a guess.
            raise HomeAssistantError(
                f"{option!r} is not a known Arozen EON Pro 2 {self._label} setting"
            )
        try:
            await self.coordinator.async_set_dp(self._dp, value)
        except ArozenError as err:
            raise HomeAssistantError(
                f"Failed to set the Arozen EON Pro 2 {self._label} to {option}: {err}"
            ) from err


class ArozenIntensitySelect(ArozenDpSelect):
    """Scent intensity, L1 (most frequent bursts) to L6 (weakest)."""

    _attr_name = "Intensity"
    _attr_icon = "mdi:air-filter"
    _attr_options = list(dp.INTENSITY_LABELS.values())
    _labels = dp.INTENSITY_LABELS
    _dp = dp.DP_INTENSITY
    _label = "intensity"

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "intensity")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The timing behind the level: pause seconds, and the fixed burst length.

        The pause mirror (DP 106) is the device's own report; the level->seconds table is
        ours, kept in dp.py and confirmed against the manual. Showing both makes a
        divergence between them visible instead of silent - and DP 106 does lag, since it
        only follows an intensity change while the device is running.
        """
        if self.coordinator.data is None:
            return {}
        return {
            **super().extra_state_attributes,
            "pause_seconds": dp.get(self.coordinator.data, dp.DP_PAUSE_S),
            "work_seconds": dp.get(self.coordinator.data, dp.DP_WORK_S),
        }


class ArozenTimerSelect(ArozenDpSelect):
    """Auto-off countdown: untimed, or 1-8 hours."""

    _attr_name = "Timer"
    _attr_icon = "mdi:timer-cog-outline"
    _attr_options = list(dp.COUNTDOWN_LABELS.values())
    _labels = dp.COUNTDOWN_LABELS
    _dp = dp.DP_COUNTDOWN
    _label = "timer"

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "timer")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Remaining minutes, plus the raw DP.

        The remaining count is worth watching independently of the setting: switching the
        device on arms 240 minutes by itself, so this can be counting down while the
        select still reads "Continuous".
        """
        if self.coordinator.data is None:
            return {}
        return {
            **super().extra_state_attributes,
            "remaining_minutes": dp.get(self.coordinator.data, dp.DP_COUNTDOWN_REMAINING),
        }
