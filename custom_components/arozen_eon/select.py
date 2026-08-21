"""Intensity and timer selects for the Arozen EON Pro 2.

Two enum DPs, both write-verified on the device 2026-08-21 (docs/datapoints.md):

* **Intensity** — DP 3, ``L1``…``L6``. There is no intensity *number* on this device: the
  level is the whole surface, and the device mirrors it as pause seconds on DP 106
  (L1=60 s … L6=2400 s) with a fixed 30 s burst (DP 105). Same physics as the sibling project's
  work/pause pair, one DP instead of two.
* **Timer** — DP 4, ``untime``/``1h``…``8h``, mirrored as remaining minutes on DP 5.
  Note the firmware's own quirk: ``3h`` arms 240 minutes. The select shows the device's
  labels; lying about them would desynchronise with the app.
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
    """Shared behaviour for a select backed by one enum DP."""

    _dp: int
    _label: str

    @property
    def current_option(self) -> str | None:
        """The raw DP value, or None when we have not heard from the device."""
        if self.coordinator.data is None:
            return None
        value = dp.get(self.coordinator.data, self._dp)
        return value if value in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.async_set_dp(self._dp, option)
        except ArozenError as err:
            raise HomeAssistantError(
                f"Failed to set the Arozen EON Pro 2 {self._label} to {option}: {err}"
            ) from err


class ArozenIntensitySelect(ArozenDpSelect):
    """Scent intensity, L1 (most frequent bursts) to L6 (weakest)."""

    _attr_name = "Intensity"
    _attr_icon = "mdi:air-filter"
    _attr_options = list(dp.INTENSITY_LEVELS)
    _dp = dp.DP_INTENSITY
    _label = "intensity"

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "intensity")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The timing behind the level: pause seconds, and the fixed burst length.

        The pause mirror (DP 106) is the device's own report; the level->seconds table is
        ours, kept in dp.py. Showing both makes a divergence between them visible instead
        of silent.
        """
        if self.coordinator.data is None:
            return {}
        return {
            "pause_seconds": dp.get(self.coordinator.data, dp.DP_PAUSE_S),
            "work_seconds": dp.get(self.coordinator.data, dp.DP_WORK_S),
        }


class ArozenTimerSelect(ArozenDpSelect):
    """Auto-off countdown: untimed, or 1-8 hours."""

    _attr_name = "Timer"
    _attr_icon = "mdi:timer-cog-outline"
    _attr_options = list(dp.COUNTDOWN_OPTIONS)
    _dp = dp.DP_COUNTDOWN
    _label = "timer"

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "timer")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        return {"remaining_minutes": dp.get(self.coordinator.data, dp.DP_COUNTDOWN_REMAINING)}
