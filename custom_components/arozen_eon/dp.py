"""The datapoint map — which numbered Tuya DP is which function.

Deliberately free of Home Assistant imports, and deliberately the ONLY file that knows a
DP number: when docs/datapoints.md changes, this file is the one and only place the
integration changes.

**Status: observed and write-verified** (2026-08-21). Every mapping below comes from the
control walk, the duty-cycle measurement, or a local write test recorded in
docs/datapoints.md — the standard `xxj` codes appear nowhere on this device; every
meaningful DP is vendor-specific, most in the 100+ range. The registered cloud schema is
empty (dossier §6.4), so nothing but this file describes the device's control surface.

**The distinction this file exists to hold on to: command DPs vs status DPs.** The first
pass at this map read the device's own valve state (DP 103) as the power switch, because
it moves whenever power is toggled. It does — as a *consequence*. The device drives 103
itself on a duty cycle, which is why writing it never produced a working "on": the
firmware simply reasserts the real valve state at the end of each burst. Power is DP 2, a
plain bool, and it was sitting in the "unidentified" list the whole time.
"""

from __future__ import annotations

from typing import Any, Final

#: Power, a bool. Write-verified both ways 2026-08-21: ``True`` starts the device (it
#: begins a mist burst within ~2 s), ``False`` stops it. This is the command DP.
#:
#: Two firmware behaviours ride along with a power write, both observed, neither optional:
#:
#: * powering **on** arms a countdown by itself — DP 5 jumped 0 → 240 within 2 s of the
#:   write, while DP 4 still read "untime". The device has a default auto-off.
#: * powering **off** resets intensity to L1 and the countdown to "3h". Settings do not
#:   survive a power cycle driven through this DP, though the phone app's own off does
#:   preserve them — so the app is doing something more than writing DP 2.
DP_POWER: Final[int | None] = 2

#: Whether the nozzle is misting *right now*: "kai" (开, open) / "guan" (关, closed).
#:
#: **Status, not command.** The device owns this DP and cycles it: ``kai`` for exactly
#: DP_WORK_S seconds, then ``guan`` for DP_PAUSE_S seconds, forever, with nothing writing
#: to it. Measured 2026-08-21 with the device untouched: a 30.5 s burst against a fixed
#: 30 s work time, then silence for the whole L3 pause.
#:
#: Writes to it are worse than useless: ``guan`` interrupts the current burst (which reads
#: as "it turned off" and is what made this look like the power DP), and ``kai`` is
#: acknowledged and then reverted by the duty-cycle controller. The integration reads it
#: and never writes it.
DP_MISTING: Final[int | None] = 103
MISTING_ON: Final = "kai"
MISTING_OFF: Final = "guan"

#: Intensity level, L1-L6. Writing it is accepted and DP 106 mirrors the pause seconds ✅.
DP_INTENSITY: Final[int | None] = 3

#: Burst length in seconds. Fixed at 30 - never moved during the walk, no app control
#: touches it, and the measured burst matched it to the second. Read-only in practice.
DP_WORK_S: Final[int | None] = 105

#: Pause seconds - read-only mirror of DP_INTENSITY. Follows every intensity write ✅,
#: but only while the device is running: written while powered off, DP 3 changes and 106
#: keeps its previous value until the next power-on (observed 2026-08-21).
DP_PAUSE_S: Final[int | None] = 106

#: Countdown setting. Writing it is accepted and DP 5 follows ✅.
#: Note "3h" arms 240 minutes on this firmware - the label is what it is.
DP_COUNTDOWN: Final[int | None] = 4
COUNTDOWN_OPTIONS: Final = ("untime", "1h", "2h", "3h", "4h", "8h")
COUNTDOWN_MINUTES: Final = {"untime": 0, "1h": 60, "3h": 240, "8h": 480}

#: Countdown remaining, minutes. Ticks down; read-only ✅.
#: Not a pure mirror of DP_COUNTDOWN: a power-on sets this to 240 while DP 4 still reads
#: "untime", so treat DP 4 as the request and DP 5 as what the device actually armed.
DP_COUNTDOWN_REMAINING: Final[int | None] = 5

#: Battery percent. Rose to 100 while plugged in, then fell ~1%/minute while running -
#: including through pause phases, which is discharge rather than consumption ✅.
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
            ("misting", DP_MISTING),
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
