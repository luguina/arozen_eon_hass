"""Tests for the select and sensor entities added after the DP dump.

The rules worth pinning:

* **a select reads back only values the device actually offers** — a DP value outside the
  option list reads as None (unknown), never as a fabricated option;
* **the intensity select carries the timing mirror as attributes**, because the pause
  seconds are the level's meaning on this device (DP 106 mirrors DP 3, burst fixed at 30 s);
* **battery and timer-remaining read their DPs straight**, and None before the first read.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant", reason="entity tests need Home Assistant installed")

from custom_components.arozen_eon.select import (
    ArozenIntensitySelect,
    ArozenTimerSelect,
)
from custom_components.arozen_eon.sensor import (
    ArozenBatterySensor,
    ArozenCountdownRemainingSensor,
)


class FakeDevice:
    host = "-test-device"
    device_id = "test-device-id"


class FakeCoordinator:
    def __init__(self, data=None, last_update_success=True):
        self.data = data
        self.last_update_success = last_update_success
        self.device = FakeDevice()
        self.writes: list[tuple[int, object]] = []

    async def async_set_dp(self, dp, value):
        self.writes.append((dp, value))

    def async_add_listener(self, *args, **kwargs):
        return lambda: None


DPS = {"3": "L3", "4": "1h", "5": 60, "101": 99, "105": 30, "106": 300}


def test_intensity_reads_level():
    assert ArozenIntensitySelect(FakeCoordinator(data=DPS)).current_option == "L3"


def test_intensity_none_before_first_read():
    assert ArozenIntensitySelect(FakeCoordinator(data=None)).current_option is None


def test_intensity_unknown_value_reads_none():
    # A firmware with an L7 we never mapped must not invent an option.
    assert ArozenIntensitySelect(FakeCoordinator(data={"3": "L7"})).current_option is None


async def test_intensity_write():
    coordinator = FakeCoordinator(data=DPS)
    await ArozenIntensitySelect(coordinator).async_select_option("L6")
    assert coordinator.writes == [(3, "L6")]


def test_intensity_attributes_carry_the_timing_mirror():
    attrs = ArozenIntensitySelect(FakeCoordinator(data=DPS)).extra_state_attributes
    assert attrs == {"pause_seconds": 300, "work_seconds": 30}


def test_timer_reads_option():
    assert ArozenTimerSelect(FakeCoordinator(data=DPS)).current_option == "1h"


async def test_timer_write():
    coordinator = FakeCoordinator(data=DPS)
    await ArozenTimerSelect(coordinator).async_select_option("untime")
    assert coordinator.writes == [(4, "untime")]


def test_timer_attributes_carry_remaining():
    attrs = ArozenTimerSelect(FakeCoordinator(data=DPS)).extra_state_attributes
    assert attrs == {"remaining_minutes": 60}


def test_battery_reads_dp101():
    assert ArozenBatterySensor(FakeCoordinator(data=DPS)).native_value == 99
    assert ArozenBatterySensor(FakeCoordinator(data=None)).native_value is None


def test_countdown_remaining_reads_dp5():
    assert ArozenCountdownRemainingSensor(FakeCoordinator(data=DPS)).native_value == 60
    assert ArozenCountdownRemainingSensor(FakeCoordinator(data=None)).native_value is None
