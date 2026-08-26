"""The two things on this device that are written rather than read: power, and the LED.

Power is DP 2 and the LED is DP 7. Both are **command DPs**, and on this device that word
has to be earned by a write test rather than inferred from a DP moving when you press
something — see below, and see ``ArozenLedSwitch`` for how DP 7 earned it.

Power is DP 2, a plain bool, write-verified both ways on the device 2026-08-21: ``True``
starts it misting within ~2 s, ``False`` stops it.

Not DP 103, which an earlier revision of this file drove. 103 is the *valve* — the device
cycles it open for 30 s and closed for the intensity's pause interval, on its own — so
writing it produced a switch that appeared to work in the off direction (it interrupts the
burst) and silently failed in the on direction (the firmware reasserts the real state).
See dp.py for the measurement and docs/datapoints.md §Datapoints for the evidence. The
valve now has its own read-only entity in binary_sensor.py.

⚠️ Turning the device **on** puts the firmware back to its power-on defaults, both in the
same status record as the power change:

* intensity is cleared to L1 — and **the coordinator writes it back** (#14). See
  IntensityMemory: the level the device held before is restored inside the same exchange when
  this switch causes the power-on, so `switch.turn_on` returns with it already right, and on
  the next poll when the remote or the phone app causes it.
* the countdown is reset — DP 4 to "3h", DP 5 to 240 minutes — overwriting a deliberate
  setting, not just filling an empty one. This one is **left alone**, and the asymmetry is a
  decision rather than an unfinished half: ADR-006 has it. Losing the intensity you chose is
  a defect; an auto-off falling back to four hours is a safety default, and overriding a
  safety default is not obviously right.

Turning **off** never touches
intensity or the countdown -- unanimous across all six captured off-edges -- though two of
those six also took DP 7 (the LED) down with DP 2. The established claim is about the
settings this entity would otherwise be blamed for losing, not about DP 2 moving alone.

This was measured on the physical remote with the phone app closed, and then on the app
itself (docs/captures/remote-walk-2026-08-21.jsonl): three power-ons from two sources, all
identical. That is what makes it firmware behaviour rather than ours — it happens whoever
turns the device on, which is also why the restore is not conditional on this entity having
been the cause.

An earlier revision of this docstring blamed the **off** edge and said the phone app
"preserves" intensity. Both were wrong. The off is innocent, and the app resets intensity
exactly like we do — it simply redraws its own screen from local state afterwards, which is
what looked like preservation. The reset was pinned on the off because the off is what you
do just before you notice, which is the same mistake that once made DP 103 look like the
power switch: the action that precedes an observation is not necessarily its cause.

Restoring intensity across a power cycle is therefore a capability neither the device nor
the vendor app has, and the restore never fakes it: if the write fails, the intensity select
goes on reporting L1, because L1 is what the device is running at. The "Intensity restores"
diagnostic sensor counts both outcomes and carries the error.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import dp
from .const import DOMAIN
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
    # The two switches below repeat is_on / turn_on / turn_off / _async_set almost verbatim,
    # and that is deliberate for now rather than unnoticed. select.py factors a base class at
    # two entities, so "only two, leave it" is not this repo's rule - the difference is what
    # is shared. ArozenDpSelect holds a *contract*: a label<->value map read in both
    # directions, and the rule that an unrecognised device value reads as unknown. Duplicating
    # that risks the two selects drifting apart on the contract. These switches share
    # *mechanics*: read a bool, write a bool, wrap the error. Nothing there can drift silently,
    # and the cross-write tests pin the wiring.
    #
    # What would justify the base: a third command DP, or wanting "non-optimistic" stated once
    # instead of twice - it is load-bearing for the LED (see below) and currently relies on
    # both classes independently continuing to read their DP.
    entities: list[SwitchEntity] = []
    if dp.DP_POWER is None:
        _LOGGER.warning("power is unmapped in dp.py — no power switch until the DP dump")
    else:
        entities.append(ArozenPowerSwitch(entry.runtime_data))
    if dp.DP_LED is None:
        _LOGGER.warning("the LED is unmapped in dp.py — no LED switch")
    else:
        entities.append(ArozenLedSwitch(entry.runtime_data))
    async_add_entities(entities)


class ArozenPowerSwitch(ArozenEntity, SwitchEntity):
    """On/off for the diffuser.

    "On" means the duty cycle is running, not that the nozzle is misting at this instant —
    the device spends most of an interval paused. The instantaneous state is the Misting
    binary sensor; conflating the two is precisely the bug this entity was rebuilt to fix.
    """

    # The device's primary control, so it takes the device's own name rather than a suffix.
    # ``_attr_name`` wins outright: `Entity._name_internal` returns it the moment the attribute
    # exists, before it ever looks at a translation key, so setting None here still means "the
    # device's name" and the key below cannot quietly override it. The key is here for
    # `icons.json`, which is addressed by translation key and has no other way to reach an
    # entity - the alternative was leaving one static icon behind in Python for no reason
    # except that this entity has no name of its own.
    _attr_name = None
    _attr_translation_key = "power"

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
                translation_domain=DOMAIN,
                translation_key="turn_on_failed" if value else "turn_off_failed",
                translation_placeholders={"entity_id": self.entity_id, "error": str(err)},
            ) from err


class ArozenLedSwitch(ArozenEntity, SwitchEntity):
    """The frontal LED (DP 7). A command DP — and that was measured, not assumed.

    **Why this is a switch and not a read-only sensor.** DP 103 is the standing warning that
    this device will acknowledge a write and then reassert its own value, which is how the
    valve state was mistaken for the power control. So the LED was not given an entity until
    someone wrote to it: on 2026-08-22 both directions were accepted *and still held five
    reads later, 30 s on*. Thirty seconds is chosen rather than incidental — it spans a full
    DP_WORK_S burst, which is the window in which DP 103 does its reverting. Had it snapped
    back, this would have shipped as a `binary_sensor` and the revert would have been
    documented rather than fought.

    **The integration does not own this value, and that is deliberate.** The device moves DP 7
    by itself: two power cycles out of three took it down with the power and brought it back
    up, and plugging in the charger produced four transitions in about forty seconds. The
    condition has *not* been established — "follows power" fits two observations out of three
    — so this entity reports what the device says and never argues with it.

    In particular there is **no memory and no restore here**, which is the opposite of what
    the intensity select gets, and the asymmetry is the point. Intensity is *reset* by the
    firmware on a known edge, destroying a choice the user made; that is a defect, and
    ADR-006 is why correcting it is legitimate. The LED moving is not a defect we can
    demonstrate — it may well be intended behaviour tied to charging — and writing state back
    at a device over a rule that fits two thirds of the evidence would be inventing a
    correction rather than making one.

    **Not optimistic.** ``is_on`` reads the DP. If a write ever stops sticking, the entity
    shows what the device reports, which is the honest answer and the one that gets noticed;
    an optimistic switch would paper over exactly the failure mode this entity was gated on.
    """

    _attr_translation_key = "led"

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "led")

    @property
    def icon(self) -> str:
        """Named for the state it is showing, unlike the static icons elsewhere here.

        Every other icon in the integration is a fixed string in ``icons.json``, which is
        fine when the icon names a *thing* — a scent, a timer, a humidifier. These ones name
        a *state*, so a static ``mdi:led-on`` sitting next to a switch that reads off would
        be a small lie. Unknown gets its own outline rather than being drawn as off, for the
        same reason ``is_on`` returns None rather than False.

        **It stays in Python, and the reason is not that `icons.json` cannot express it.** It
        can: `default` plus a `state` block mapping `on` and `off` reproduces this exactly,
        with `unknown` falling through to the outline the same way it does here — 611 entity
        icons in core use that block, some of them keying `unknown` explicitly. What a JSON
        file cannot do is sit next to `is_on`. These two properties have to agree about what
        `None` means, and the next person to give `is_on` a third meaning will be reading this
        file, not a manifest three directories away. So the one icon whose value depends on a
        reading stays where the reading is defined (#50).
        """
        if self.is_on is None:
            return "mdi:led-outline"
        return "mdi:led-on" if self.is_on else "mdi:led-off"

    @property
    def is_on(self) -> bool | None:
        """Whether the frontal LED is lit. None until the first successful read."""
        if self.coordinator.data is None:
            return None
        value = dp.get(self.coordinator.data, dp.DP_LED)
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        assert dp.DP_LED is not None  # the entity is not created otherwise
        try:
            await self.coordinator.async_set_dp(dp.DP_LED, value)
        except ArozenError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="turn_on_failed" if value else "turn_off_failed",
                translation_placeholders={"entity_id": self.entity_id, "error": str(err)},
            ) from err
