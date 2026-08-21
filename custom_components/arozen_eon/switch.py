"""Power switch for the Arozen EON Pro 2.

Power is DP 2, a plain bool, write-verified both ways on the device 2026-08-21: ``True``
starts it misting within ~2 s, ``False`` stops it.

Not DP 103, which an earlier revision of this file drove. 103 is the *valve* — the device
cycles it open for 30 s and closed for the intensity's pause interval, on its own — so
writing it produced a switch that appeared to work in the off direction (it interrupts the
burst) and silently failed in the on direction (the firmware reasserts the real state).
See dp.py for the measurement and docs/datapoints.md §Datapoints for the evidence. The
valve now has its own read-only entity in binary_sensor.py.

⚠️ Turning the device **on** puts the firmware back to its power-on defaults, and the
integration does not hide that, because pretending otherwise would make the entity lie:

* intensity is cleared to L1.
* the countdown is reset — DP 4 to "3h", DP 5 to 240 minutes — overwriting a deliberate
  setting, not just filling an empty one.

Both land in the same status record as the power change. Turning **off** never touches
intensity or the countdown -- unanimous across all six captured off-edges -- though two of
those six also took DP 7 (the LED) down with DP 2. The established claim is about the
settings this entity would otherwise be blamed for losing, not about DP 2 moving alone.

This was measured on the physical remote with the phone app closed, and then on the app
itself (docs/captures/remote-walk-2026-08-21.jsonl): three power-ons from two sources, all
identical. That is what makes it firmware behaviour rather than ours — it happens whoever
turns the device on.

An earlier revision of this docstring blamed the **off** edge and said the phone app
"preserves" intensity. Both were wrong. The off is innocent, and the app resets intensity
exactly like we do — it simply redraws its own screen from local state afterwards, which is
what looked like preservation. The reset was pinned on the off because the off is what you
do just before you notice, which is the same mistake that once made DP 103 look like the
power switch: the action that precedes an observation is not necessarily its cause.

Restoring intensity across a power cycle is therefore a coordinator job on the *on* edge,
and a capability the phone app does not have. Tracked as issue #14, deliberately not done
here.
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
    """On/off for the diffuser.

    "On" means the duty cycle is running, not that the nozzle is misting at this instant —
    the device spends most of an interval paused. The instantaneous state is the Misting
    binary sensor; conflating the two is precisely the bug this entity was rebuilt to fix.
    """

    # The device's primary control, so it takes the device's own name rather than a suffix.
    _attr_name = None
    _attr_icon = "mdi:scent"

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "power")

    @property
    def is_on(self) -> bool | None:
        """Whether the diffuser is running. None until the first successful read."""
        if self.coordinator.data is None:
            return None
        value = dp.get(self.coordinator.data, dp.DP_POWER)
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        assert dp.DP_POWER is not None  # the entity is not created otherwise
        try:
            await self.coordinator.async_set_dp(dp.DP_POWER, value)
        except ArozenError as err:
            raise HomeAssistantError(
                f"Failed to turn the Arozen EON Pro 2 {'on' if value else 'off'}: {err}"
            ) from err
