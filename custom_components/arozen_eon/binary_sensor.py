"""Whether the nozzle is misting right now.

This platform exists because DP 103 turned out to be a status DP, not a command one. The
device runs a duty cycle — nozzle open for DP 105 seconds (fixed at 30), then closed for
DP 106 seconds (60 at L1, up to 2400 at L6) — and 103 is how it reports which half of that
cycle it is in. Measured untouched on 2026-08-21: a 30.5 s burst, then nothing for the
rest of the interval, with no write involved.

Reading it is genuinely useful — it is the only way to see the device working from Home
Assistant, and it makes "on but not currently misting" legible rather than looking like a
fault. Writing it is not: see switch.py and dp.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant

from . import dp
from .coordinator import ArozenConfigEntry, ArozenCoordinator

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from .entity import ArozenEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArozenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if dp.DP_MISTING is None:
        _LOGGER.warning("misting is unmapped in dp.py — no binary sensor entity")
        return
    async_add_entities([ArozenMistingBinarySensor(entry.runtime_data)])


class ArozenMistingBinarySensor(ArozenEntity, BinarySensorEntity):
    """True while the nozzle is open (DP 103 == "kai")."""

    _attr_name = "Misting"
    _attr_icon = "mdi:air-humidifier"

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "misting")

    @property
    def is_on(self) -> bool | None:
        """Whether the nozzle is open. None until the first successful read.

        Comparison against the known-on value, not truthiness: the DP reports the strings
        "kai"/"guan", and a bare bool("guan") is True — the classic string-enum-as-boolean
        bug. An unrecognised value reads as off rather than raising; the raw string is
        still visible on the recon sensor if a third state ever shows up.
        """
        if self.coordinator.data is None:
            return None
        value = dp.get(self.coordinator.data, dp.DP_MISTING)
        return None if value is None else value == dp.MISTING_ON

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The duty cycle this state belongs to, so the pattern is readable at a glance."""
        if self.coordinator.data is None:
            return {}
        return {
            "work_seconds": dp.get(self.coordinator.data, dp.DP_WORK_S),
            "pause_seconds": dp.get(self.coordinator.data, dp.DP_PAUSE_S),
        }
