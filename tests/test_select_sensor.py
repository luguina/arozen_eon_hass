"""Tests for the select and sensor entities added after the DP dump.

The rules worth pinning:

* **a select shows a human label, not the device's enum value** — the firmware's ``"3h"``
  arms four hours and ``L1``…``L6`` runs strongest to weakest, so both are translated;
* **a select reads back only values the device actually offers** — a DP value outside the
  option list reads as None (unknown), never as a fabricated option;
* **the intensity select carries the timing mirror as attributes**, because the pause
  seconds are the level's meaning on this device (DP 106 mirrors DP 3, burst fixed at 30 s);
* **battery and timer-remaining read their DPs straight**, and None before the first read.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant", reason="entity tests need Home Assistant installed")

from custom_components.arozen_eon import dp
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
    assert ArozenIntensitySelect(FakeCoordinator(data=DPS)).current_option == "L3 · every 5 min"


def test_intensity_none_before_first_read():
    assert ArozenIntensitySelect(FakeCoordinator(data=None)).current_option is None


def test_intensity_unknown_value_reads_none():
    # A firmware with an L7 we never mapped must not invent an option.
    assert ArozenIntensitySelect(FakeCoordinator(data={"3": "L7"})).current_option is None


async def test_intensity_write():
    # The user picks a label; the device must receive its own enum value.
    coordinator = FakeCoordinator(data=DPS)
    await ArozenIntensitySelect(coordinator).async_select_option("L6 · every 40 min")
    assert coordinator.writes == [(3, "L6")]


def test_intensity_labels_state_the_real_interval():
    # Labels are derived from the pause table, so they cannot drift from it. The manual
    # specifies 1/3/5/10/20/40 minutes; the label must say what the device will do.
    options = ArozenIntensitySelect(FakeCoordinator(data=DPS)).options
    assert options[0] == "L1 · every 1 min"
    assert options[-1] == "L6 · every 40 min"
    for level, pause in dp.INTENSITY_PAUSE_S.items():
        assert f"every {pause // 60} min" in dp.INTENSITY_LABELS[level]


def test_intensity_attributes_carry_the_timing_mirror():
    attrs = ArozenIntensitySelect(FakeCoordinator(data=DPS)).extra_state_attributes
    assert attrs == {"raw_value": "L3", "pause_seconds": 300, "work_seconds": 30}


def test_timer_reads_option():
    assert ArozenTimerSelect(FakeCoordinator(data=DPS)).current_option == "1 hour"


def test_timer_calls_the_240_minute_setting_four_hours():
    """The firmware's "3h" arms 240 minutes. The manual calls that setting 4h.

    Showing the device's own string would tell the user three hours and give them four,
    so the label follows the behaviour, not the enum.
    """
    assert ArozenTimerSelect(FakeCoordinator(data={"4": "3h"})).current_option == "4 hours"
    assert dp.COUNTDOWN_MINUTES["3h"] == 240


def test_timer_offers_only_settings_the_device_has_acknowledged():
    """2h and 4h were invented to round out the enum; the device never reported either.

    The control walk cycled the app's entire timer list and produced exactly four values.
    """
    options = ArozenTimerSelect(FakeCoordinator(data=DPS)).options
    assert options == ["Continuous", "1 hour", "4 hours", "8 hours"]
    assert set(dp.COUNTDOWN_OPTIONS) == {"untime", "1h", "3h", "8h"}


async def test_timer_write():
    coordinator = FakeCoordinator(data=DPS)
    await ArozenTimerSelect(coordinator).async_select_option("Continuous")
    assert coordinator.writes == [(4, "untime")]


async def test_timer_write_four_hours_sends_the_firmware_string():
    coordinator = FakeCoordinator(data=DPS)
    await ArozenTimerSelect(coordinator).async_select_option("4 hours")
    assert coordinator.writes == [(4, "3h")]


def test_timer_attributes_carry_remaining():
    attrs = ArozenTimerSelect(FakeCoordinator(data=DPS)).extra_state_attributes
    assert attrs == {"raw_value": "1h", "remaining_minutes": 60}


def test_battery_reads_dp101():
    assert ArozenBatterySensor(FakeCoordinator(data=DPS)).native_value == 99
    assert ArozenBatterySensor(FakeCoordinator(data=None)).native_value is None


def test_countdown_remaining_reads_dp5():
    assert ArozenCountdownRemainingSensor(FakeCoordinator(data=DPS)).native_value == 60
    assert ArozenCountdownRemainingSensor(FakeCoordinator(data=None)).native_value is None
