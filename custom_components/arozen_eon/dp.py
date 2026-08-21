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
#: Powering **on** restores the firmware's defaults, in the same status record as the power
#: change, and it happens whoever turns the device on - us, the phone app, or the remote:
#:
#: * intensity is cleared to L1.
#: * the countdown is reset - DP 4 to "3h", DP 5 to 240 minutes. An "8h" setting became
#:   "3h" on the next power-on, so this overwrites a choice rather than filling a blank.
#:
#: Powering **off** never touches intensity or the countdown - unanimous across all six
#: captured off-edges. It is not DP 2 alone as a rule, though: two of the six also took DP 7
#: (the LED) down with it. The established claim is about intensity and the countdown, and
#: this comment deliberately does not stretch it into "no other datapoint moves".
#:
#: An earlier revision of this comment said the opposite: that the *off* reset the settings,
#: and that the phone app avoided it by sending something more than a DP 2 write. Both
#: halves were wrong. The remote walk of 2026-08-21 measured both edges with the app closed,
#: then measured the app itself - three power-ons, two sources, all identical, and nobody
#: re-applied anything. Restoring intensity is issue #14.
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
#:
#: ⚠️ **Frozen while the device is off.** Switching off mid-burst leaves this reporting
#: ``"kai"`` indefinitely - measured still ``"kai"`` minutes later with DP_POWER false.
#: It is a live reading only while the device is running, so binary_sensor.py gates it on
#: power. DP_PAUSE_S freezes the same way; assume any status DP on this device does.
DP_MISTING: Final[int | None] = 103
MISTING_ON: Final = "kai"
MISTING_OFF: Final = "guan"

#: Intensity level, L1-L6. Writing it is accepted and DP 106 mirrors the pause seconds ✅.
DP_INTENSITY: Final[int | None] = 3

#: Burst length in seconds. Fixed at 30 by design, not by coincidence: the manual specifies
#: a 30 s emission at every one of the six levels. Never moved during the walk, no app
#: control touches it, and the measured burst matched it to the second. Read-only.
DP_WORK_S: Final[int | None] = 105

#: Pause seconds - read-only mirror of DP_INTENSITY. Follows every intensity write ✅,
#: but only while the device is running: written while powered off, DP 3 changes and 106
#: keeps its previous value until the next power-on (observed 2026-08-21).
DP_PAUSE_S: Final[int | None] = 106

#: Countdown setting. Writing it is accepted and DP 5 follows ✅.
#: Note "3h" arms 240 minutes on this firmware - the label is what it is.
DP_COUNTDOWN: Final[int | None] = 4
#: The device has exactly **four** countdown settings, not six. Confirmed twice over: the
#: manual lists 1h / 4h / 8h / continuous, and the control walk cycled the app's whole timer
#: list while producing only these four DP values. An earlier revision also offered "2h" and
#: "4h" - invented to round out the enum, never acknowledged by the device, and removed.
#:
#: ⚠️ **"3h" is the manual's 4-hour setting.** It arms 240 minutes, observed repeatedly. The
#: firmware's own string is simply wrong; COUNTDOWN_MINUTES is the truth and the entity layer
#: labels it by duration so nobody has to know that.
COUNTDOWN_MINUTES: Final = {"untime": 0, "1h": 60, "3h": 240, "8h": 480}
COUNTDOWN_OPTIONS: Final = tuple(COUNTDOWN_MINUTES)
COUNTDOWN_LABELS: Final = {
    "untime": "Continuous",
    "1h": "1 hour",
    "3h": "4 hours",  # yes, really - see above
    "8h": "8 hours",
}

#: Countdown remaining, minutes. Ticks down; read-only ✅.
#: Not a pure mirror of DP_COUNTDOWN: a power-on sets this to 240 while DP 4 still reads
#: "untime", so treat DP 4 as the request and DP 5 as what the device actually armed.
DP_COUNTDOWN_REMAINING: Final[int | None] = 5

#: Battery percent. Rose to 100 while plugged in, then fell ~1%/minute while running -
#: including through pause phases, which is discharge rather than consumption ✅.
DP_BATTERY: Final[int | None] = 101

#: Intensity level -> pause seconds. **Confirmed against the printed manual** (the project owner,
#: 2026-08-21), which specifies a 30 s emission followed by a pause of 1/3/5/10/20/40
#: minutes for L1-L6. Five of the six were also observed on the device via DP 106; L5 was
#: never reached during the walk and had been interpolated at 1200 - the manual puts it at
#: exactly 20 minutes, so the inference was right and is now sourced.
#:
#: Note the direction: the level number counts *pause*, so **L1 is the strongest setting
#: and L6 the weakest**. The entity layer is responsible for not making a user guess that.
INTENSITY_PAUSE_S: Final = {"L1": 60, "L2": 180, "L3": 300, "L4": 600, "L5": 1200, "L6": 2400}
INTENSITY_LEVELS: Final = tuple(INTENSITY_PAUSE_S)

#: Human labels for the levels, derived from the pause table rather than written out, so a
#: label can never drift from the interval it claims. "L1 · every 1 min" keeps the app's own
#: level name - the two surfaces stay in sync - while making the direction self-evident,
#: which a bare "L1…L6" does not: the number counts pause, so it runs strongest to weakest.
INTENSITY_LABELS: Final = {
    level: f"{level} · every {pause // 60} min" for level, pause in INTENSITY_PAUSE_S.items()
}


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
