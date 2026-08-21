"""The datapoint map — which numbered Tuya DP is which function.

Deliberately free of Home Assistant imports, and deliberately the ONLY file that knows a
DP number: when docs/datapoints.md changes, this file is the one and only place the
integration changes.

**Status: observed, not hypothesised** (2026-08-21). The map below comes from the control
walk and local write tests recorded in docs/datapoints.md — the standard `xxj` codes
appear nowhere on this device; every meaningful DP is vendor-specific, most in the 100+
range exactly as the hypothesis predicted. The registered cloud schema is empty
(dossier §6.4), so nothing but this file describes the device's control surface.

One genuine unknown remains: the ON command. Writing DP 103 ``"guan"`` turns the device
off and sticks; writing ``"kai"`` is acknowledged but reverted. See docs/datapoints.md
"Still unknown". The switch entity writes 103 both ways — the off direction is verified,
the on direction is the best available candidate until the observation lands.
"""

from __future__ import annotations

from typing import Any, Final

#: Power state: "kai" (开, on) / "guan" (关, off). Tracks every app power toggle ✅.
#: Off-writes verified ✅; on-writes acknowledged but reverted ❓ (docs/datapoints.md).
DP_POWER: Final[int | None] = 103
POWER_ON: Final = "kai"
POWER_OFF: Final = "guan"

#: Intensity level, L1-L6. Writing it is accepted and DP 106 mirrors the pause seconds ✅.
DP_INTENSITY: Final[int | None] = 3

#: Burst length in seconds. Apparently fixed at 30 - never moved during the walk, and no
#: app control touches it. Mapped for completeness; the integration does not write it.
DP_WORK_S: Final[int | None] = 105

#: Pause seconds - read-only mirror of DP_INTENSITY. Follows every intensity write ✅.
DP_PAUSE_S: Final[int | None] = 106

#: Countdown setting. Writing it is accepted and DP 5 mirrors the remaining minutes ✅.
#: Note "3h" maps to 240 minutes on this firmware - the label is what it is.
DP_COUNTDOWN: Final[int | None] = 4
COUNTDOWN_OPTIONS: Final = ("untime", "1h", "2h", "3h", "4h", "8h")
COUNTDOWN_MINUTES: Final = {"untime": 0, "1h": 60, "3h": 240, "8h": 480}

#: Countdown remaining, minutes. Ticks down; read-only ✅.
DP_COUNTDOWN_REMAINING: Final[int | None] = 5

#: Battery percent. 99 -> 100 while plugged in ✅ (strong inference - docs/datapoints.md).
DP_BATTERY: Final[int | None] = 101

#: Intensity level -> pause seconds, as mirrored by the device (L5 unobserved, interpolated
#: from the geometric-ish progression 60/180/300/600/?/2400: the walk showed the app offers
#: six levels and the pause doubles-ish per step; L5=1200 is an inference, marked as such).
INTENSITY_PAUSE_S: Final = {"L1": 60, "L2": 180, "L3": 300, "L4": 600, "L5": 1200, "L6": 2400}
INTENSITY_LEVELS: Final = tuple(INTENSITY_PAUSE_S)


def unmapped_functions() -> list[str]:
    """Which functions have no DP number yet — for the setup-time warning."""
    return [
        name
        for name, dp in (
            ("power", DP_POWER),
            ("intensity", DP_INTENSITY),
            ("work_seconds", DP_WORK_S),
            ("pause_seconds", DP_PAUSE_S),
            ("countdown", DP_COUNTDOWN),
        )
        if dp is None
    ]


def get(dps: dict[str, Any], dp: int | None) -> Any:
    """Read a DP from a status payload, returning None for unmapped or absent DPs.

    Tuya reports DP ids as string keys ("1", "101"), so the lookup normalises. A missing
    key and an unmapped function are deliberately indistinguishable here — both mean "we
    do not know", and the entity layer already treats None as unknown.
    """
    if dp is None:
        return None
    return dps.get(str(dp))
