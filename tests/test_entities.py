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
from custom_components.arozen_eon.binary_sensor import ArozenMistingBinarySensor
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


def test_misting_exposes_the_duty_cycle():
    sensor = ArozenMistingBinarySensor(
        FakeCoordinator(data={"103": "kai", "105": 30, "106": 300})
    )
    assert sensor.extra_state_attributes == {"work_seconds": 30, "pause_seconds": 300}


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
