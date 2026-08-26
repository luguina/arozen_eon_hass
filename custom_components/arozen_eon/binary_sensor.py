"""The two things the device reports about itself as an on/off: misting, and charging.

Both are status DPs the device owns and we only read. They are otherwise unrelated — one is
the nozzle's duty cycle, the other is the cable — and they share a module only because Home
Assistant sorts entities by platform.

**Misting.** This platform exists because DP 103 turned out to be a status DP, not a command
one. The device runs a duty cycle — nozzle open for DP 105 seconds (fixed at 30), then
closed for DP 106 seconds (60 at L1, up to 2400 at L6) — and 103 is how it reports which
half of that cycle it is in. Measured untouched on 2026-08-21: a 30.5 s burst, then nothing
for the rest of the interval, with no write involved.

Reading it is genuinely useful — it is the only way to see the device working from Home
Assistant, and it makes "on but not currently misting" legible rather than looking like a
fault. Writing it is not: see switch.py and dp.py.

One correction the raw DP needs: the device freezes this datapoint while powered off, so
it must be gated on power. See ``is_on``.

**Charging.** DP 102 is the battery's charging state (#16), and it earns an entity for a
reason the battery percentage cannot supply on its own: a number that falls, then rises, with
no indication why is the half that makes people distrust the other half.

It is a three-state string in a two-state device class, which is the whole design question —
see ``ArozenChargingBinarySensor``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    entities: list[BinarySensorEntity] = []
    if dp.DP_MISTING is None:
        _LOGGER.warning("misting is unmapped in dp.py — no misting binary sensor")
    else:
        entities.append(ArozenMistingBinarySensor(entry.runtime_data))
    if dp.DP_CHARGING is None:
        _LOGGER.warning("charging is unmapped in dp.py — no charging binary sensor")
    else:
        entities.append(ArozenChargingBinarySensor(entry.runtime_data))
    async_add_entities(entities)


class ArozenMistingBinarySensor(ArozenEntity, BinarySensorEntity):
    """True while the nozzle is open (DP 103 == "kai")."""

    _attr_translation_key = "misting"

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "misting")

    @property
    def is_on(self) -> bool | None:
        """Whether the nozzle is open. None until the first successful read.

        **Gated on power, and that gate is not cosmetic.** The device freezes its status
        datapoints when it is switched off: DP 103 keeps whatever value it held at the
        moment power went away, indefinitely. Switch the diffuser off mid-burst and it
        reports ``"kai"`` for as long as it sits idle — measured still ``"kai"`` minutes
        later, with DP 2 false throughout. Reporting that raw would mean an idle diffuser
        claiming to be misting until someone switched it on again.

        So a device that is not running is not misting, full stop. This is not inventing
        state; it is refusing to read a frozen register as a live one. The same freeze
        affects DP 106 (see dp.py), and the raw string stays visible on the recon sensor.

        Comparison against the known-on value, not truthiness: the DP reports the strings
        "kai"/"guan", and a bare bool("guan") is True — the classic string-enum-as-boolean
        bug. An unrecognised value reads as off rather than raising.
        """
        if self.coordinator.data is None:
            return None
        if dp.get(self.coordinator.data, dp.DP_POWER) is False:
            return False
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


class ArozenChargingBinarySensor(ArozenEntity, BinarySensorEntity):
    """Whether the battery is taking charge right now (DP 102 == "zzcd").

    **Three device states into a two-state device class, and the third is kept rather than
    lost.** ``BinarySensorDeviceClass.BATTERY_CHARGING`` has room for two of the three, so
    ``cdwc`` collapses into "not charging" — true, but it loses the difference between *on
    the cable, not currently drawing* and *running on the battery*, which is the half an
    automation wants. The device class therefore gets the bool and ``charge_state`` keeps all
    three values, which is the habit the selects already follow: decode for the user, keep
    the raw value visible for whoever needs to check the decode.

    The alternative was a plain three-state sensor, which would put all three in the state
    where an automation matches them directly, at the cost of the device class. It was
    declined because it carries nothing this entity does not already expose, and two entities
    off one DP are two things to keep in step. **What would change it:** if triggering on an
    attribute proves awkward in practice, adding that sensor later is purely additive.

    ⚠️ **Expect this to flap while the diffuser runs on mains, and do not read that as a
    fault.** Measured 2026-08-22 (docs/captures/charging-cdwc-2026-08-22.txt): sitting at
    ``cdwc`` with DP 101 at 100, the next mist burst took the gauge to 96 and DP 102 to
    ``zzcd`` in the same poll. It stayed charging at 99 for the following eight minutes and
    two further bursts without returning to ``cdwc``. So ``cdwc`` is a state a burst
    breaks, not a resting place — an automation keyed on it should expect long absences.

    ``cdwc`` is also **not a synonym for 100 %**: the control walk recorded it at DP 101 = 99
    with the gauge still climbing to 100 twenty seconds later
    (docs/captures/dp-watch-2026-08-21.txt). Whatever the firmware means by "complete", it is
    not "the number reached its maximum", and nothing here should be built as though it were.
    """

    _attr_translation_key = "charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, coordinator: ArozenCoordinator) -> None:
        super().__init__(coordinator, "charging")

    @property
    def is_on(self) -> bool | None:
        """Whether the battery is taking charge. None until the first successful read.

        **An unrecognised value reads as unknown, not as off** — the contract select.py
        documents, and a deliberate divergence from the misting sensor above, which reads an
        unknown value as off. The difference is that misting is genuinely binary at the
        device, so anything that is not ``kai`` is not misting; charging is not, so a fourth
        value would be a state we have never seen rather than a synonym for "no". Membership
        in ``CHARGING_STATES`` is therefore checked before the comparison. If a firmware
        update ever adds one, this says "unknown" until dp.py learns about it, which is the
        answer that gets noticed.

        **Not gated on power**, unlike misting — and unlike misting, that is supported rather
        than merely assumed. DP 102 read ``cdwc`` at the end of the control walk, in the same
        record that took DP 2 to false, and ``wcd`` four and a half hours later in a session
        that opened with DP 2 still false. The value moved between two observations that both
        have the device off, and the stimulus it tracks — a charger being unplugged — needs
        no device at all. That is not proof it updates while off (nothing rules out somebody
        running the diffuser in between), but it points one way, and it is the opposite way
        from DP 103's demonstrated freeze.

        Gating would blank the entity exactly when it is most wanted, since charging an idle
        diffuser is the ordinary case. The measurement that would settle it is in
        docs/datapoints.md; if the freeze is ever shown, the gate belongs here.

        The ``isinstance`` check is not decoration: a non-scalar DP value would make the
        membership test raise ``TypeError`` out of a property, which Home Assistant surfaces
        as a broken entity rather than an unknown one. Misting cannot hit this because it
        compares rather than looks up; this one looks up, so it guards.
        """
        if self.coordinator.data is None:
            return None
        value = dp.get(self.coordinator.data, dp.DP_CHARGING)
        if not isinstance(value, str) or value not in dp.CHARGING_STATES:
            return None
        return value == dp.CHARGING_ACTIVE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The third state the bool cannot hold, and the raw DP behind it.

        Rule 3 of tools/README.md: showing the interpretation without the raw value makes a
        wrong interpretation invisible. ``charge_state`` is None for a value dp.py does not
        recognise, matching ``is_on`` rather than guessing at it — and ``raw_value`` is then
        the only place the unrecognised string is visible at all.
        """
        if self.coordinator.data is None:
            return {}
        value = dp.get(self.coordinator.data, dp.DP_CHARGING)
        return {
            "raw_value": value,
            # Guarded for the same reason as is_on, and it matters more here: this attribute
            # is where an unrecognised value is supposed to stay visible, so it is the last
            # place that should be able to raise on one.
            "charge_state": dp.CHARGING_STATES.get(value) if isinstance(value, str) else None,
        }
