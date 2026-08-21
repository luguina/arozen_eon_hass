"""Tests for the datapoint map's two rules.

dp.py is the only file that knows a DP number, and until the dump fills it in, most of it
is deliberately ``None``. The rules that matter *now*:

* **an unmapped function reads as unknown, never as a guessed value** — ``get()`` must
  return None for a ``None`` DP even when the device reports plenty of other DPs;
* **the unmapped list is honest** — it must name exactly the functions with no DP number,
  because the setup-time warning and the entity platforms both trust it.

These run with no Home Assistant installed: dp.py is HA-free on purpose (pyproject.toml
explains the import path).
"""

from __future__ import annotations

import dp


def test_get_returns_none_for_unmapped_function():
    dps = {"1": True, "101": 5}
    assert dp.get(dps, None) is None


def test_get_reads_present_dp_by_string_key():
    # Tuya reports DP ids as string keys, always.
    assert dp.get({"1": True}, 1) is True
    assert dp.get({"101": "level_3"}, 101) == "level_3"


def test_get_returns_none_for_absent_dp():
    # A mapped DP the device did not report reads the same as unmapped: unknown.
    assert dp.get({"2": False}, 1) is None


def test_get_preserves_falsy_values():
    # False and 0 are real device states, not absence. If this ever broke, a diffuser
    # that is off would read as "unknown" instead of "off".
    assert dp.get({"1": False}, 1) is False
    assert dp.get({"101": 0}, 101) == 0


def test_unmapped_functions_matches_the_map():
    mapped = {
        "power": dp.DP_POWER,
        "misting": dp.DP_MISTING,
        "intensity": dp.DP_INTENSITY,
        "work_seconds": dp.DP_WORK_S,
        "pause_seconds": dp.DP_PAUSE_S,
        "countdown": dp.DP_COUNTDOWN,
    }
    expected = sorted(name for name, value in mapped.items() if value is None)
    assert sorted(dp.unmapped_functions()) == expected


def test_current_observed_map():
    """Pins the DP map as observed on the device 2026-08-21 (docs/datapoints.md).

    Every value here came from the control walk or a write test, not from a guess. If the
    device ever disagrees with this test, the device wins — update dp.py, datapoints.md,
    and this test together.
    """
    # Power is the bool DP 2, write-verified both ways. The valve state is DP 103, which
    # the device drives itself - the two are separate DPs and separate entities, and
    # collapsing them is the exact bug this map was corrected for.
    assert dp.DP_POWER == 2
    assert dp.DP_MISTING == 103
    assert (dp.MISTING_ON, dp.MISTING_OFF) == ("kai", "guan")
    assert dp.DP_INTENSITY == 3
    assert dp.DP_WORK_S == 105
    assert dp.DP_PAUSE_S == 106
    assert dp.DP_COUNTDOWN == 4
    assert dp.DP_COUNTDOWN_REMAINING == 5
    assert dp.DP_BATTERY == 101
    # The intensity->pause mirror exactly as the device reported it (L5 interpolated).
    assert dp.INTENSITY_PAUSE_S == {
        "L1": 60, "L2": 180, "L3": 300, "L4": 600, "L5": 1200, "L6": 2400,
    }
    # What the firmware puts intensity back to on every power-on, observed on all three
    # power-ons of the remote walk. The restore keys on it (coordinator.IntensityMemory),
    # so a typo here would not fail loudly - it would just quietly stop restoring.
    assert dp.INTENSITY_POWER_ON_DEFAULT == "L1"
    assert dp.INTENSITY_POWER_ON_DEFAULT in dp.INTENSITY_LEVELS
    assert dp.unmapped_functions() == []
