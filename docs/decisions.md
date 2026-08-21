# Decision log

ADR-style. One entry per decision that would otherwise get re-argued. Record the
**reasoning**, not just the verdict — including what would change the answer.

Status values: `accepted` · `superseded` · `pending`.

---

## ADR-001 — Local LAN control; the Tuya cloud is the fallback, not the plan

**Status:** accepted · **Date:** 2026-08-10

**Context.** A Tuya WiFi device can be driven three ways: the vendor cloud API (what the
official Home Assistant Tuya integration uses), the device's own encrypted local protocol on
TCP 6668, or not at all.

**Decision.** Drive the device **locally on the LAN**. The cloud is touched exactly once, to
fetch the `local_key`, and never again at runtime.

**Why.** No vendor account in the control path, no outage, no round trip to a datacentre, and
it keeps working when the internet does not. This is the same call as
the sibling project's ADR-004 and for the same
reasons — but note it is a *weaker* commitment here, because unlike the sibling project the cloud path is
a genuinely working fallback rather than an inversion of the project's point. The official Tuya
integration already talks to this device; it just has nothing useful to say about it.

**What makes it viable, and it was not a given.** The device is **mains-powered** (confirmed by
the project owner, 2026-08-10). A battery-powered Tuya device sleeps, drops off the LAN between wakeups, and
cannot be polled locally — which would have forced the cloud path regardless of preference. That
question was the single largest risk to this whole approach and it resolved in our favour before
any work started.

**What would change this.** The device refusing local connections, or shipping a protocol
version whose session keys we cannot derive. Then the fallback ladder is: LocalTuya →
official Tuya cloud integration + Tuya "tap-to-run" scenes as blunt on/off buttons →
reflashing the WiFi module. The last of those is out of scope
([ADR-005](#adr-005--scope-power-intensity-workpause-timer-scheduling-reflashing-excluded)).

---

## ADR-002 — No ESP32. The device is already on the network.

**Status:** accepted · **Date:** 2026-08-10

**Context.** The sibling project `sibling_ha_controller` puts an ESP32 running an ESPHome
`bluetooth_proxy` next to the diffuser, because that device speaks BLE and sits three floors
from the Home Assistant box — out of radio range.

**Decision.** Nothing gets flashed. Home Assistant talks straight to the diffuser over the LAN.

**Why this ADR exists at all.** The verdict is obvious; the failure mode it guards against is
not. Two projects, same room, same *kind* of appliance, near-identical goals — and the strong
pull is to reach for the architecture that worked last time. It does not apply. The sibling project needed
a bridge because BLE could not span the distance; **WiFi already spans it**, which is the entire
reason this device has an app that works "from anywhere". Copying the proxy across would add a
board, a firmware, a power supply and a failure mode, in exchange for nothing.

Stated plainly because a constraint that *feels* decisive often is not — the same trap
the sibling project's ADR-002 called out from the other
direction, where "3 floors away" felt like it chose the implementation language and did not.

**What would change this.** Nothing plausible. If WiFi does not reach the diffuser's position,
the fix is an access point or a mesh node, not a protocol bridge.

---

## ADR-003 — Defer the deliverable until the datapoint dump exists

**Status:** superseded · **Date:** 2026-08-10 · **Resolved 2026-08-21 → option C, by the project owner**

**Resolution.** The project owner called it before the dump: the deliverable is **our own integration**,
`custom_components/arozen_eon/`, mirroring `sibling_beacon`'s architecture (coordinator +
entity platforms + a diagnostic-sensor instrument). The gate's concern — that C might mean
re-solving a solved transport — does not apply to the way it was built: the integration is a
thin async wrapper over `tinytuya`, with the entire DP map isolated in `dp.py`, so the dump
still decides *what the entities are*, just not *where they live*. Options A and B remain
available as fallbacks and as upstreamable by-products; nothing about C blocks writing a
`tuya-local` YAML later from the same `datapoints.md`.

The scaffold deliberately encodes no DP guesses: `dp.py` maps only power (DP 1, the one
near-universal Tuya convention, still marked hypothesis), and platforms backed by unmapped
functions create **no entities** until the dump fills the file in.

**Original entry (2026-08-10), kept for the reasoning:**

**Context.** Three shapes the deliverable could take:

| Option | What it is |
|---|---|
| **A — `tuya-local` device config** | A YAML file mapping DPs to Home Assistant entities, added to [`make-all/tuya-local`](https://github.com/make-all/tuya-local). ~40 lines. |
| **B — LocalTuya config** | Manual per-entity DP mapping in the [`xZetsubou`](https://github.com/xZetsubou/hass-localtuya) fork's UI. No file to write, but nothing to upstream either. |
| **C — our own integration** | A `custom_components/arozen_eon/` of the kind built for the sibling project. |

**Decision.** Do not choose yet. Dump the datapoints first
([`datapoints.md`](datapoints.md)), then decide against the criteria below.

**Be honest about how wide this gate actually is.** On the sibling project the equivalent gate was
genuinely open, because the protocol could have turned out to be anything and did in fact
demolish the front-runner. Here it is **much narrower**: the transport is a known, implemented,
encrypted protocol on TCP 6668, so option C is not "write a protocol" — it is "wrap `tinytuya`
and re-solve problems A and B already solved". C is on this list for completeness and starts
heavily disfavoured. The real question is A versus B.

**What decides it:**

1. **Can a `tuya-local` YAML express every control?** Its schema covers booleans, enums,
   integers with ranges, and mappings between DP values and HA values. If the Arozen packs
   work/pause into a single encoded string or a JSON DP that the schema cannot decompose,
   A weakens.
2. **Does an existing config already fit?** Twelve diffuser configs ship today. If one matches
   the DP set outright, this collapses to a configuration exercise. *(Do not lean on this. The
   Aroma-Link hypothesis on the sibling project was exactly this shape of hope and it was wrong.)*
3. **Is there anything worth upstreaming?** A produces an artefact another Arozen owner can use;
   B produces a screenshot. That is a real tiebreaker at equal effort, not a nicety.

**What would change this.** The dump itself. This ADR is closed by writing the result into
[`datapoints.md`](datapoints.md) and superseding this entry.

---

## ADR-004 — Pending — must the phone app keep working?

**Status:** pending · **Date:** 2026-08-10 · **The project owner's call, not an engineering choice**

**Context.** Many Tuya devices accept **only one local connection at a time**. `tuya-local`'s
own documentation warns that running it alongside the official Tuya integration causes
connection problems, and advises closing the manufacturer's app. So there is a plausible world
in which local control and the Tuya Smart app cannot comfortably coexist.

**Why this is not being decided by whoever writes the code.** On the sibling project the equivalent
requirement (its ADR-006) was a hard constraint
that would have rejected otherwise-good solutions, and it was eventually *withdrawn* by the project owner
rather than engineered around. Same principle: if the answer is "the app must keep working",
that changes which options are admissible, and it is a preference, not a finding.

**What is genuinely different from the sibling project, and it matters.** The sibling project's app talked BLE, and
BLE is exclusive — one central, one link. Tuya's app normally reaches the device **via the
cloud**, not over the LAN, so app and local control are not obviously competing for the same
channel. Contention is a documented risk, not a certainty. **Do not assume this is a conflict
before measuring it.**

**What settles it.** Once local control works: drive the diffuser from Home Assistant, then
open the Tuya app and drive it from there, then alternate. Record whether either side stops
responding, and how long recovery takes. That measurement makes this a fact rather than a
preference — and it may well dissolve the question entirely.

---

## ADR-005 — Scope: power, intensity, work/pause, timer, scheduling. Reflashing excluded.

**Status:** accepted · **Date:** 2026-08-10

**Decision.** In scope: on/off · scent intensity · work/pause interval timing · countdown
timer · scheduling. Out: the Tuya cloud API as a runtime dependency · reflashing the WiFi
module (tuya-cloudcutter / OpenBeken / LibreTuya) · the physical remote control.

**Why reflashing is out.** It is the one option on the fallback ladder that is
**irreversible and destructive** — it voids the warranty, can brick the unit, requires a
supported chip we have not identified, and would be undertaken to fix a problem we have no
evidence exists. It stays out until local control has actually been tried and actually failed.

**Scheduling — expect this to land in Home Assistant, not on the device.** Tuya's `xxj`
category does expose a `countdown` DP, and the app clearly has schedules. But the sibling project's work
ended at its ADR-009 — on-device schedule records
were rejected in favour of Home Assistant automations, because on-device schedules fought with
a reliable *off*, were overwritten by the phone app, and ran against a device clock that could
not be verified. **At least the second of those three almost certainly applies here too**, since
the Tuya app owns the device's schedule state and re-pushes it. Not a decision yet — flagged so
it is not rediscovered from scratch.

---

## ADR-006 — Correct the power-on intensity reset, and only that one

**Status:** accepted · **Date:** 2026-08-21

**Context.** Switching the diffuser on puts the firmware back to a power-on default state, in
a single status record: intensity cleared to `L1`, the countdown re-armed (DP 4 → `3h`, DP 5 →
240 minutes), and on two of six captured off-edges the LED (DP 7) went down with power too.
This happens whoever turns the device on — Home Assistant, the phone app, or the physical
remote — and the app does not undo any of it either
([remote walk](captures/remote-walk-2026-08-21.jsonl)). So the question is not "can we avoid
causing this" — we never caused it — but **which of the device's own defaults, if any, the
integration should overrule on the user's behalf.**

**Decision.** Restore **intensity** ([#14](https://github.com/luguina/arozen_ha_controller/issues/14)). Leave the **countdown** alone. Take
no position on the LED until it has a write test ([#15](https://github.com/luguina/arozen_ha_controller/issues/15)).

**Why the two are not the same case — which is the entire reason this entry exists.** They
look identical: both are settings, both are silently overwritten on the same edge, by the same
firmware, in the same record. The symmetry is misleading.

* **Losing intensity is a defect.** The user chose a level, the device is running, and it is
  running at a level nobody asked for. There is no reading of `L1` as a safe fallback — it is
  simply the *strongest* setting, bursting ten times more often than L6. Nothing is protected
  by getting it wrong.
* **The countdown falling back to four hours is a safety default,** and overriding a safety
  default is a different act from repairing a defect. Someone who set "Continuous" and gets
  four hours has a diffuser that stops early and notices. Someone whose "Continuous" we
  faithfully restore has one that runs until the tank is dry — possibly after a power cut
  restarted it unattended. The two failure modes are not symmetric, and the quiet one is the
  worse one to choose on somebody's behalf.

**What the restore deliberately does not do.**

* It does not fire when the device reports any level *other* than `L1` at the power-on. An
  external power-on is not noticed until the next poll — up to a minute — and a non-default
  level by then means a human got there first. Their choice is newer than our memory.
* It does not persist across a Home Assistant restart. A power-on that happens while HA is
  down leaves no edge to witness, and a stored preference could not be told apart from a level
  the user set deliberately in the meantime.
* It does not fake success. A failed restore leaves the intensity select reporting `L1`,
  because `L1` is what the device is running at; the "Intensity restores" diagnostic sensor
  carries the count and the error. Same principle as `sensor.…_failed_polls`: a fix that hides
  a fault ships with the meter that still records it.

**What would change this.** For the countdown: evidence that restoring it is what the device's owner
actually wants — most plausibly running on "Continuous" and being cut off at four hours often
enough to say so. That is a preference and it is his call, not a finding. In the other
direction: if the intensity restore is ever seen fighting something that also writes DP 3 (a
Tuya scene, a schedule pushed from the app), the "somebody got there first" guard stops being
sufficient and the scope narrows to Home-Assistant-initiated power-ons only.

---

## Pending

| # | Decision | Blocked on |
|---|---|---|
| [ADR-004](#adr-004--pending--must-the-phone-app-keep-working) | Must the phone app keep working? | The project owner, informed by a coexistence measurement — now half-made: with the app open, local writes failed intermittently (null/914); with it closed, they landed (dossier §6.3) |
| ~~On-device schedules vs Home Assistant automations~~ | **Resolved 2026-08-21 by evidence:** the app's schedule moved no DP during the control walk — scheduling is cloud/app-side, so HA automations + the countdown DP (dossier §6.6) |
| — | Whether to make this repo public | Confirming no `local_key` has ever been committed |
