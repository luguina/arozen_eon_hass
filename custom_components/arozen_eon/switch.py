"""Power switch for the Arozen EON Pro 2.

Power is DP 103, a string DP: "kai" (开, on) / "guan" (关, off) — not the boolean DP 1 the
standard xxj set would suggest. Observed on the device 2026-08-21 (docs/datapoints.md):
the state tracks every app power toggle, and off-writes are verified to stick.

⚠️ The on-write is the one unverified command on the device: acknowledged but reverted
during the write tests, pending physical observation (docs/datapoints.md "Still unknown").
The entity writes it anyway — it is the best candidate the evidence offers — but if the
device ever answers an on-write by actually turning on, delete this comment.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
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
    if dp.DP_POWER is None:
        _LOGGER.warning("power is unmapped in dp.py — no switch entity until the DP dump")
        return
    async_add_entities([ArozenPowerSwitch(entry.runtime_data)])


class ArozenPowerSwitch(ArozenEntity, SwitchEntity):
    """On/off for the diffuser."""

    # The device's primary control, so it takes the device's own name rather than a suffix.
    _attr_name = None
    _attr_icon = "mdi:scent"

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "power")

    @property
    def is_on(self) -> bool | None:
        """Whether the diffuser is on. None until the first successful read.

        Comparison, not truthiness: the DP reports the strings "kai"/"guan", and a bare
        bool("guan") is True — the classic string-enum-as-boolean bug.
        """
        if self.coordinator.data is None:
            return None
        value = dp.get(self.coordinator.data, dp.DP_POWER)
        return None if value is None else value == dp.POWER_ON

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(dp.POWER_ON)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(dp.POWER_OFF)

    async def _async_set(self, value: str) -> None:
        assert dp.DP_POWER is not None  # the entity is not created otherwise
        try:
            await self.coordinator.async_set_dp(dp.DP_POWER, value)
        except ArozenError as err:
            raise HomeAssistantError(
                f"Failed to turn the Arozen EON Pro 2 "
                f"{'on' if value == dp.POWER_ON else 'off'}: {err}"
            ) from err
