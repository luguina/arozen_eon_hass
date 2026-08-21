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
    # Power is the string DP 103: "kai" on, "guan" off. bool("guan") would be True,
    # which is exactly the bug this comparison exists to avoid.
    assert ArozenPowerSwitch(FakeCoordinator(data={"103": "kai"})).is_on is True
    assert ArozenPowerSwitch(FakeCoordinator(data={"103": "guan"})).is_on is False


def test_switch_is_none_when_power_dp_absent():
    # The device answered, but not with the DP we mapped - unknown, not a guess.
    assert ArozenPowerSwitch(FakeCoordinator(data={"2": True})).is_on is None


@pytest.mark.asyncio
async def test_switch_turn_on_writes_kai():
    coordinator = FakeCoordinator(data={"103": "guan"})
    switch = ArozenPowerSwitch(coordinator)
    await switch.async_turn_on()
    assert coordinator.writes == [(103, "kai")]


@pytest.mark.asyncio
async def test_switch_turn_off_writes_guan():
    coordinator = FakeCoordinator(data={"103": "kai"})
    switch = ArozenPowerSwitch(coordinator)
    await switch.async_turn_off()
    assert coordinator.writes == [(103, "guan")]


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
