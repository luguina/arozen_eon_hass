"""Tests for poll-health rules and the entities built on them.

The rules worth pinning before the DP dump lands, because everything after it builds on them:

* **one missed poll must not take the entities down** — it holds the previous reading;
  the *second* consecutive miss does. That tolerance is what keeps a flaky minute from
  reading as a dead diffuser;
* **holding a reading requires having one** — with no successful read at all there is
  nothing to hold, and the honest state is unavailable;
* **a write clears the streak too** — a command the user just watched succeed must not
  leave the entities one missed poll from unavailable.

The coordinator itself needs a real hass to construct, so PollHealth is tested directly and
the entities are exercised against a fake coordinator, which is enough because they hold no
state of their own.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant", reason="entity tests need Home Assistant installed")

from custom_components.arozen_eon.coordinator import PollHealth
from custom_components.arozen_eon import binary_sensor
from custom_components.arozen_eon.binary_sensor import (
    ArozenChargingBinarySensor,
    ArozenMistingBinarySensor,
)
from custom_components.arozen_eon.switch import ArozenPowerSwitch


class FakeDevice:
    host = "-test-device"
    device_id = "test-device-id"


class FakeCoordinator:
    """Just enough of ArozenCoordinator for the entities to sit on."""

    def __init__(self, data=None, last_update_success=True):
        self.data = data
        self.last_update_success = last_update_success
        self.health = PollHealth()
        self.device = FakeDevice()
        self.writes: list[tuple[int, object]] = []

    async def async_set_dp(self, dp, value):
        self.writes.append((dp, value))

    def async_add_listener(self, *args, **kwargs):
        return lambda: None


# -- PollHealth ---------------------------------------------------------------------------


def test_health_starts_healthy():
    health = PollHealth()
    assert health.may_hold_reading
    assert health.consecutive == 0
    assert health.total == 0


def test_health_single_failure_still_holds():
    health = PollHealth()
    health.failed("boom")
    assert health.may_hold_reading
    assert health.consecutive == 1
    assert health.total == 1


def test_health_second_consecutive_failure_does_not_hold():
    health = PollHealth()
    health.failed("boom")
    health.failed("boom")
    assert not health.may_hold_reading
    assert health.total == 2  # the total keeps counting even when tolerance is spent


def test_health_success_clears_the_streak_but_not_the_total():
    health = PollHealth()
    health.failed("boom")
    health.succeeded()
    assert health.may_hold_reading
    assert health.consecutive == 0
    assert health.total == 1  # deliberate: the total is the trace a tolerated miss leaves


# -- Power switch -------------------------------------------------------------------------


def test_switch_is_none_before_first_read():
    switch = ArozenPowerSwitch(FakeCoordinator(data=None))
    assert switch.is_on is None


def test_switch_reads_power_dp():
    # Power is the bool DP 2, write-verified both ways on the device.
    assert ArozenPowerSwitch(FakeCoordinator(data={"2": True})).is_on is True
    assert ArozenPowerSwitch(FakeCoordinator(data={"2": False})).is_on is False


def test_switch_is_none_when_power_dp_absent():
    # The device answered, but not with the DP we mapped - unknown, not a guess.
    assert ArozenPowerSwitch(FakeCoordinator(data={"101": 90})).is_on is None


def test_switch_ignores_the_valve_dp():
    """The regression this whole entity was rebuilt for.

    DP 103 is the valve, which the device opens for 30 s and closes for the pause
    interval on its own. A switch reading it reports the diffuser as off for most of
    every cycle while it is running perfectly well - and, worse, writing it never turned
    the device on at all. Power must come from DP 2 and nothing else.
    """
    running_but_between_bursts = FakeCoordinator(data={"2": True, "103": "guan"})
    assert ArozenPowerSwitch(running_but_between_bursts).is_on is True

    off_but_valve_stale = FakeCoordinator(data={"2": False, "103": "kai"})
    assert ArozenPowerSwitch(off_but_valve_stale).is_on is False


@pytest.mark.asyncio
async def test_switch_turn_on_writes_power_dp_true():
    coordinator = FakeCoordinator(data={"2": False})
    switch = ArozenPowerSwitch(coordinator)
    await switch.async_turn_on()
    assert coordinator.writes == [(2, True)]


@pytest.mark.asyncio
async def test_switch_turn_off_writes_power_dp_false():
    coordinator = FakeCoordinator(data={"2": True})
    switch = ArozenPowerSwitch(coordinator)
    await switch.async_turn_off()
    assert coordinator.writes == [(2, False)]


@pytest.mark.asyncio
async def test_switch_never_writes_the_valve_dp():
    # Belt and braces on the same regression: whatever the switch does, DP 103 is not
    # part of it. The device owns that DP.
    for action in ("async_turn_on", "async_turn_off"):
        coordinator = FakeCoordinator(data={"2": True, "103": "kai"})
        await getattr(ArozenPowerSwitch(coordinator), action)()
        assert all(written_dp != 103 for written_dp, _ in coordinator.writes)


# -- Misting binary sensor ----------------------------------------------------------------


def test_misting_is_none_before_first_read():
    assert ArozenMistingBinarySensor(FakeCoordinator(data=None)).is_on is None


def test_misting_reads_the_valve_dp():
    # bool("guan") is True, which is exactly the bug this comparison avoids.
    assert ArozenMistingBinarySensor(FakeCoordinator(data={"103": "kai"})).is_on is True
    assert ArozenMistingBinarySensor(FakeCoordinator(data={"103": "guan"})).is_on is False


def test_misting_is_false_when_power_is_off_even_if_the_dp_says_kai():
    """The device freezes DP 103 when switched off, so the raw value goes stale.

    Switch it off mid-burst and it reports "kai" indefinitely - measured still "kai"
    minutes later with DP 2 false. Without this gate an idle diffuser claims to be
    misting until someone switches it on again. Found by running the integration in
    real Home Assistant and calling switch.turn_off, not by any unit test.
    """
    frozen = FakeCoordinator(data={"2": False, "103": "kai"})
    assert ArozenMistingBinarySensor(frozen).is_on is False


def test_misting_still_reads_the_dp_while_running():
    # The gate must not swallow the real signal: powered on, the DP is live.
    running = FakeCoordinator(data={"2": True, "103": "kai"})
    assert ArozenMistingBinarySensor(running).is_on is True
    paused = FakeCoordinator(data={"2": True, "103": "guan"})
    assert ArozenMistingBinarySensor(paused).is_on is False


def test_misting_unknown_when_power_unknown():
    # No power DP reported: we cannot say the device is idle, so do not claim it.
    assert ArozenMistingBinarySensor(FakeCoordinator(data={"103": "kai"})).is_on is True


def test_misting_exposes_the_duty_cycle():
    sensor = ArozenMistingBinarySensor(
        FakeCoordinator(data={"103": "kai", "105": 30, "106": 300})
    )
    assert sensor.extra_state_attributes == {"work_seconds": 30, "pause_seconds": 300}


# -- Charging binary sensor ---------------------------------------------------------------
#
# Three device states into a two-state device class. Every one of these tests exists to pin
# a place where that collapse could lose or invent information.


def test_charging_is_none_before_first_read():
    assert ArozenChargingBinarySensor(FakeCoordinator(data=None)).is_on is None


def test_charging_reads_the_three_observed_states():
    """Both real transitions in the remote-walk capture, plus the state seen on the cable."""
    assert ArozenChargingBinarySensor(FakeCoordinator(data={"102": "zzcd"})).is_on is True
    assert ArozenChargingBinarySensor(FakeCoordinator(data={"102": "wcd"})).is_on is False
    # Charge complete is not charging - true, and the assertion that costs us the third
    # state in the bool. It survives in the attributes; see the test below.
    assert ArozenChargingBinarySensor(FakeCoordinator(data={"102": "cdwc"})).is_on is False


def test_charging_unknown_value_reads_none_rather_than_off():
    """A fourth firmware state is a state we have never seen, not a synonym for "no".

    The deliberate divergence from the misting sensor, which reads an unknown value as off
    because misting really is binary at the device. Folding an unrecognised charging value
    into "not charging" would report a plausible lie; None reports the truth and gets
    noticed.
    """
    assert ArozenChargingBinarySensor(FakeCoordinator(data={"102": "xyz"})).is_on is None


def test_charging_is_none_when_the_dp_is_absent():
    # A payload with no DP 102 at all must not read as "not charging".
    assert ArozenChargingBinarySensor(FakeCoordinator(data={"2": True})).is_on is None


def test_charging_is_not_gated_on_power():
    """Charging an idle diffuser is the ordinary case, and the one this is most wanted for.

    The misting sensor is gated because DP 103 demonstrably freezes while off. DP 102 has
    never been shown to freeze - both captured transitions happened with the device running
    - so gating it would trade a real capability for a hypothetical wrong reading.
    """
    off_and_charging = FakeCoordinator(data={"2": False, "102": "zzcd"})
    assert ArozenChargingBinarySensor(off_and_charging).is_on is True


def test_charging_keeps_the_third_state_in_the_attributes():
    sensor = ArozenChargingBinarySensor(FakeCoordinator(data={"102": "cdwc"}))
    assert sensor.is_on is False
    assert sensor.extra_state_attributes == {
        "raw_value": "cdwc",
        "charge_state": "complete",
    }


def test_charging_attributes_show_the_raw_value_of_an_unknown_state():
    """When we cannot name it, the raw string is the only place it is visible at all."""
    sensor = ArozenChargingBinarySensor(FakeCoordinator(data={"102": "xyz"}))
    assert sensor.extra_state_attributes == {"raw_value": "xyz", "charge_state": None}


def test_charging_attributes_are_empty_before_first_read():
    assert ArozenChargingBinarySensor(FakeCoordinator(data=None)).extra_state_attributes == {}


def test_charging_survives_a_non_scalar_dp_value():
    """A list or dict from the device must read as unknown, not raise out of a property.

    The lookup this entity does is `value in CHARGING_STATES`, and an unhashable value makes
    that raise TypeError — from inside a property, which Home Assistant surfaces as a broken
    entity rather than an unknown one. The misting sensor cannot hit this because it compares
    instead of looking up. Tuya DPs are scalars in practice, so this is a guard rather than an
    observed failure, but it is the difference between "unknown" and "the entity is dead".
    """
    for hostile in ([], {}, [1, 2], {"a": 1}):
        sensor = ArozenChargingBinarySensor(FakeCoordinator(data={"102": hostile}))
        assert sensor.is_on is None
        assert sensor.extra_state_attributes == {"raw_value": hostile, "charge_state": None}


def test_charging_reads_none_for_scalar_values_that_are_not_states():
    # Hashable but wrong: a bool or a number is not a charging state either.
    for wrong in (True, 0, 1.5, b"zzcd"):
        assert ArozenChargingBinarySensor(FakeCoordinator(data={"102": wrong})).is_on is None


# -- The binary_sensor platform's setup ----------------------------------------------------
#
# The only tests in this suite that call an async_setup_entry. They exist because adding the
# charging entity turned a single-entity early-return into a two-entity list, and that is
# exactly the kind of edit that silently drops the *other* entity. Nothing else in the test
# suite would notice: every other entity test constructs its class directly. The live check
# that would have caught it, tools/verify_ha.py, needs the real diffuser and a power cycle.


class FakeEntry:
    """Just the one attribute async_setup_entry reads."""

    def __init__(self, coordinator):
        self.runtime_data = coordinator


async def _setup_binary_sensors(monkeypatch, **unmapped):
    """Run the platform's setup, optionally unmapping DPs, and return what it added."""
    for name, value in unmapped.items():
        monkeypatch.setattr(binary_sensor.dp, name, value)
    added = []
    await binary_sensor.async_setup_entry(
        None, FakeEntry(FakeCoordinator(data={})), added.extend
    )
    return [type(entity).__name__ for entity in added]


async def test_setup_adds_both_binary_sensors(monkeypatch):
    assert await _setup_binary_sensors(monkeypatch) == [
        "ArozenMistingBinarySensor",
        "ArozenChargingBinarySensor",
    ]


async def test_setup_without_misting_still_adds_charging(monkeypatch):
    """An unmapped DP must cost its own entity and no other.

    The regression this guards: the pre-#16 setup returned early when misting was unmapped,
    which was correct when misting was the only entity here and would have taken charging
    down with it the moment it was not.

    One unmapping per test, deliberately: monkeypatch unwinds at teardown, not between
    calls, so two in one test would silently be testing both-unmapped the second time. It
    passed anyway on the first draft of this file, in the direction that happened not to
    notice.
    """
    assert await _setup_binary_sensors(monkeypatch, DP_MISTING=None) == [
        "ArozenChargingBinarySensor"
    ]


async def test_setup_without_charging_still_adds_misting(monkeypatch):
    # The other direction: charging must not be able to take misting down with it either.
    assert await _setup_binary_sensors(monkeypatch, DP_CHARGING=None) == [
        "ArozenMistingBinarySensor"
    ]


async def test_setup_adds_nothing_when_both_are_unmapped(monkeypatch):
    # No entities, and no exception: an empty map is a warning, not a failed setup.
    assert await _setup_binary_sensors(monkeypatch, DP_MISTING=None, DP_CHARGING=None) == []


# -- Availability -------------------------------------------------------------------------


def test_available_when_fresh():
    switch = ArozenPowerSwitch(FakeCoordinator(data={"1": True}))
    assert switch.available


def test_available_after_one_missed_poll_holds_reading():
    coordinator = FakeCoordinator(data={"1": True}, last_update_success=False)
    coordinator.health.failed("boom")
    switch = ArozenPowerSwitch(coordinator)
    assert switch.available


def test_unavailable_after_two_missed_polls():
    coordinator = FakeCoordinator(data={"1": True}, last_update_success=False)
    coordinator.health.failed("boom")
    coordinator.health.failed("boom")
    switch = ArozenPowerSwitch(coordinator)
    assert not switch.available


def test_unavailable_with_no_reading_even_within_tolerance():
    # Tolerating a failure *means* holding the previous reading; with none, there is
    # nothing to hold. This is also the startup path.
    coordinator = FakeCoordinator(data=None, last_update_success=False)
    coordinator.health.failed("boom")
    switch = ArozenPowerSwitch(coordinator)
    assert not switch.available
