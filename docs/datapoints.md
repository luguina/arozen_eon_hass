# Arozen EON Pro 2 — datapoint map

**Status: ✅ observed and write-verified on the device (2026-08-21), with three datapoints
still unidentified.** The map below comes from a control walk, local write tests, a duty-cycle
measurement taken with nothing writing to the device, and the printed manual. The integration
is built against it.

Two things to read carefully rather than skim. **The `xxj` hypothesis in the next section was
tested and failed** — it is kept because a rejected hypothesis is part of the record, not
because it describes this device. And [§Still unknown](#still-unknown) is the honest list;
where this file says ❓ it means ❓, and nothing downstream should round that up to an answer.

## Why this file is not called `protocol.md`

Because the protocol is not the unknown. On `sibling_ha_controller` that filename earned itself —
the frame format, checksum and command set all had to be recovered before anything could be
written. Here the transport is **Tuya's local protocol on TCP 6668**: published, understood, and
already implemented in `tinytuya`, `tuya-local` and LocalTuya. Nobody needs to decode a byte.

What is unknown is the **semantic layer**: the device exposes numbered datapoints ("DPs"), and
nothing tells you which number is power and which is intensity. That mapping is this document,
and it is the entire recon task.

---

## The hypothesis: Tuya's standard `xxj` instruction set

Published by Tuya for the **Diffuser (`xxj`)** category
([instruction set](https://developer.tuya.com/en/docs/iot/f?id=K9gf46lj5p3q4) ·
[category doc](https://developer.tuya.com/en/docs/iot/categoryxxj?id=Kaiuz1f9mo6bl)):

| Code | Name | Type | Values |
|---|---|---|---|
| `switch` | Master switch | Boolean | — |
| `switch_spray` | Spraying switch | Boolean | — |
| `mode` | Spraying mode | Enum | `large`, `middle`, `small`, `interval`, `continuous` |
| `level` | Spraying level | Enum | `level_1` … `level_10` |
| `countdown` | Countdown of spraying | Enum | `cancel`, `1`–`6` |
| `switch_led` | Light switch | Boolean | — |
| `work_mode` | Light mode | Enum | `white`, `colour`, `colourful1` |
| `colour_data_hsv` | Coloured light | JSON | h 0–360, s 0–255, v 0–255 |
| `bright_value` | Brightness | Integer | 0–255 |
| `bright_value_v2` | Brightness | Integer | 0–1000 |
| `switch_sound` | Voice switch | Boolean | — |
| `moodlighting` | Mood light | Enum | 1–5 *(legacy)* |
| `colour_data` | Coloured light value | Integer | 0–255 *(legacy)* |

### 🔵 Why the standard set probably does not describe this device

This is inference. Weigh it as such — but it is the reason the recon is worth doing carefully
rather than assuming a match:

1. **The standard set is shaped like an ultrasonic humidifier.** `mode` ∈ {large, middle, small}
   and `level_1…level_10` describe a mist output you turn up and down continuously. The EON Pro 2
   is a **waterless, heatless cold-air nebuliser** — vendor copy is explicit about this — and
   those diffuse in *bursts*: a work period, then a pause. The natural control surface is a
   work/pause pair, and there is **no DP for that in the standard set at all**.
2. **This is exactly the shape the sibling project turned out to have.** On that device intensity was not
   a level; it was the run and pause durations, and the sibling project's own documentation said so. Two
   different vendors, same physics, same likely control surface.
3. **`countdown` as an enum of 1–6** does not obviously match the vendor's stated timer options
   of 1, 2, 4, 8 hours or continuous. Close, but not the same shape.

If (1) and (2) hold, the device carries **vendor-specific DPs in the 100+ range**, which is the
normal Tuya convention for functions outside a standard category — and those are invisible to
the official Home Assistant integration by construction, since it only ever looks for the
codes listed in `const.py`.

**The counter-case, stated so it is not ignored:** plenty of OEMs ship a standard category with
standard codes and a custom shell, in which case this all collapses and one of the twelve
existing `tuya-local` diffuser configs may fit outright. That would be a good outcome. It is
just not one to plan around.

---

## Observed

### Device identity

| | |
|---|---|
| Tuya category | ✅ **`xxj`** — cloud device record, 2026-08-21 |
| Product ID (`product_id`) | ✅ `uh3xooop1btksbtk` — cloud device record, 2026-08-21. ⚠️ The value previously recorded here (`jidyk1ybp0dqlteg`, from the LAN broadcast) belongs to a **dehumidifier** on the same account — see dossier §6.1 for the misidentification |
| Product name as registered | ✅ "Arozen Eon pro 2-" — cloud device record |
| Registered cloud schema | ✅ **EMPTY** — `functions: []`, `status: []` (dossier §6.4). The DPs exist but are undeclared; only a live dump reveals them |
| Protocol version | ✅ **3.5** — reported by `tinytuya scan` after the re-pair and used by every successful local read and write since (dossier §6.3). The identical value recorded *before* that came from the misidentified dehumidifier and was a coincidence, not a source |
| Firmware / module | ❓ — the local status payload carries no version field, which is why the device registry reports none rather than inventing one |
| Local IP | ✅ reachable on the main LAN since the re-pair, 2026-08-21 (dossier §6.3). Address redacted — see [captures/README.md](captures/README.md#redaction-rule) |
| Device ID | ✅ `bfdeadbeefdeadbeef0001` — cloud device record, 2026-08-21 |

### Datapoints

Evidence: [captures/dp-watch-2026-08-21.txt](captures/dp-watch-2026-08-21.txt) (control walk),
local write tests with `tools/dp_set.py` the same evening, a duty-cycle measurement taken with
nothing writing to the device, and — for the intensity table — **the printed manual**, which is
the only source that covers L5. Full DP set as first observed
(idle, after re-pair): `2=true, 3="L1", 4="3h", 5=239, 101=99, 102="zzcd", 103="kai",
104="kk", 105=30, 106=60`.

| DP | Type | Observed values | Function | How established |
|---|---|---|---|---|
| 2 | bool | `true`, `false` | **Power.** Writing `true` starts the device — it begins a mist burst within ~2 s; writing `false` stops it. ⚠️ Two side effects, both observed: powering **on** arms a countdown by itself (DP 5 → 240 while DP 4 still reads `untime`), and powering **off** resets intensity to L1 and the countdown to `3h`. The phone app's own off preserves both, so the app sends more than a DP 2 write | write test 2026-08-21 ✅ both directions |
| 3 | enum string | `L1`…`L6` | **Intensity level.** Writing it is accepted and DP 106 mirrors it as pause seconds. **Confirmed against the printed manual**: 30 s emission then a pause of 1/3/5/10/20/40 min → L1=60, L2=180, L3=300, L4=600, L5=1200, L6=2400. Five observed on the device; L5 comes from the manual and matches the interpolation exactly. ⚠️ The number counts *pause*, so L1 is the **strongest** setting and L6 the weakest | walk + write test + manual ✅ |
| 4 | enum string | `untime`, `1h`, `3h`, `8h` | **Countdown setting**, and there are exactly **four** of them. DP 5 follows: `1h`→60, `3h`→240, `8h`→480, `untime`→0. ⚠️ **`3h` is the manual's 4-hour setting** — the firmware string is simply wrong, and the entity labels it by duration. The walk cycled the app's entire timer list and produced only these four values, matching the manual (1h / 4h / 8h / continuous); `2h` and `4h` were never offered by the device and have been removed from the integration | walk + write test + manual ✅ |
| 5 | int | 0–480, ticks down | **Countdown remaining, minutes.** Watched decrement 240→239 during the walk. Not a pure mirror of DP 4: a power-on sets it to 240 while DP 4 still reads `untime`, so DP 4 is the request and DP 5 is what the device actually armed | walk ✅ + power-on test ✅ |
| 7 | bool | `false` | ❓ unknown, and **new**: absent from every dump taken during the control walk, present 2026-08-21 late while the device sat powered off. A DP that appears partway through recon is worth watching — it may only be reported in certain states | live read 2026-08-21 ❓ |
| 101 | int | 91–100 | **Battery %, almost certainly.** Went 99→100 while plugged in, then fell ~1%/minute while running — including straight through pause phases, which is discharge rather than mist consumption, and is the observation that rules out oil level | walk + duty-cycle measurement 🔵 (strong inference) |
| 102 | string | `zzcd`, `wcd`, `cdwc` | ❓ unknown. Moved only between walk phases, never in step with a single control. Looks like pinyin fragments; possibly a mode or program-state string | walk ❓ |
| 103 | string | `kai` (开/open), `guan` (关/closed) | **Nozzle state — status, not command.** The device cycles it itself: `kai` for DP 105 seconds, then `guan` for DP 106 seconds, indefinitely. ⚠️ **Frozen while powered off**: switch off mid-burst and it reports `kai` indefinitely (measured still `kai` minutes later with DP 2 false), so it is a live reading only while running. It tracks app power toggles because power *causes* misting, which is what made it look like the power DP. Do not write it: `guan` merely interrupts the current burst, `kai` is reverted by the duty-cycle controller | duty-cycle measurement 2026-08-21 ✅ |
| 104 | string | `kk` | ❓ unknown. Never moved | walk ❓ |
| 105 | int | 30 | **Work (burst) seconds, fixed at 30 by design.** The manual specifies a 30 s emission at every one of the six levels, so this is a firmware constant rather than a sampling artefact. Never moved; no app control touches it | walk + manual ✅ |
| 106 | int | 60–2400 | **Pause seconds — read-only mirror of DP 3.** Follows every DP 3 write *while the device is running*; written while powered off, DP 3 changes and 106 keeps its old value until the next power-on. Direct writes untested | walk + write test ✅ |

Fill `How established` honestly. `"toggled power in app, DP 1 flipped"` is evidence.
`"probably intensity"` is not, and should say so.

---

## Method

The technique is the same one that works for any undocumented control surface, and it is the
one written into the sibling project's capture worksheet: **change exactly one control at a time, capture,
diff.** Ten dumps that each vary one thing beat a hundred dumps of mixed activity.

### 1. Get the credentials

Two routes, neither of which needs a Tuya IoT developer account any more — which used to be the
worst part of this job:

- **[`tuya-local-key`](https://github.com/vineetchoudhary/tuya-local-key)** — QR login against
  Tuya's device-sharing SDK. Returns device ID, `local_key`, IP, online status and category.
  Runs as a CLI, Docker container or Home Assistant add-on. QR codes expire in 1–2 minutes, so
  have the phone open before starting.
- **`tinytuya wizard`** — the classic route. Wants an IoT platform project (Access ID/Secret);
  the trial expires and needs periodic renewal.

`tuya-local`'s own config flow can also pull all of this itself during setup. That is convenient
for *installing* but less useful for *recon*, because it does not show you the raw DPs.

> ⚠️ Whatever writes these to disk writes a **live credential**. See the README's audit command
> before any commit.

### 2. Confirm it is reachable locally

```sh
python -m tinytuya scan          # does the device answer on the LAN, and at which version?
```

This also reports the protocol version, which everything downstream needs to get right.

### 3. Dump the baseline

Read full status with the device idle and off. Every subsequent dump is diffed against this one.

### 4. Walk the controls

One at a time, dumping after each. Suggested order — coarsest first, so the obvious DPs are
identified before the ambiguous ones:

| # | Action in the Tuya app | Expect to identify |
|---|---|---|
| 1 | Power on | master switch |
| 2 | Power off | (confirms #1 is a toggle, not a pulse) |
| 3 | Each intensity step, lowest → highest | intensity — enum, integer, or a work/pause pair |
| 4 | Work time only, if separately settable | work duration, and its units |
| 5 | Pause time only | pause duration |
| 6 | Each timer option (1 / 2 / 4 / 8 h / continuous) | `countdown`, and its encoding |
| 7 | Create a schedule | schedule DP — expect an opaque string or JSON blob |
| 8 | Let it run a while, dump periodically | read-only status DPs: remaining time, faults, oil level |

Step 7 is the one most likely to produce something a YAML schema cannot decompose, so it is the
main input to [ADR-003](decisions.md#adr-003--defer-the-deliverable-until-the-datapoint-dump-exists).

### 5. Cross-check against the app's own view

The Tuya IoT platform's *Device Debugging* screen shows the registered DP schema with names and
types directly, when an account is available. That turns the inference from step 4 into
confirmation — and where the two disagree, **the live dump wins**: the registered schema
describes what the product was defined as, the dump describes what the firmware actually does.

---

## Still unknown

Kept as an explicit list because on the sibling project the equivalent section was what stopped
half-answers being treated as answers.

- ~~**The ON command.**~~ ✅ **Resolved 2026-08-21 (evening).** It was DP 2 all along — the
  bool sitting in this very list as "unknown". Writing `true` starts the device; `false` stops
  it. The reason it took a second sitting to find: DP 103 moves whenever power is toggled, so
  it read as the power DP, and every attempt to fix "on" went into writing *harder* to a
  datapoint the device owns. The lesson is the generalisable one — **a DP that correlates with
  a control is not necessarily the control.** Deciding whether a DP is a command or a status
  needs a measurement with *nothing writing to it*, which is what finally settled it: left
  untouched, 103 cycled on its own.
- **What the app's power-off does that a DP 2 write does not.** Writing `false` resets intensity
  to L1 and the countdown to `3h`; the app's own off preserves both. So the app sends a
  compound command, or a different DP entirely. Until this is known, the Home Assistant switch
  resets the user's intensity on every off — documented in `switch.py`, not hidden.
- **Why power-on arms a 240-minute countdown.** DP 5 → 240 within 2 s of `2=true`, with DP 4
  still reading `untime`. Presumably a firmware default auto-off. Harmless, but it means the
  countdown sensor reads non-zero after every switch-on.
- **Which status DPs freeze when the device is off, and which do not.** Confirmed frozen:
  DP 103 (nozzle) and DP 106 (pause mirror, which will not follow a DP 3 write while off).
  Assume any status DP on this device is stale until proven live — the integration gates
  the misting sensor on power for exactly this reason.
- DP 102's values (`zzcd`/`wcd`/`cdwc`); DP 104 (`kk`); DP 7, which the device only started
  reporting after the control walk and so was never exercised by it.
- ~~The intensity enum's full extent.~~ ✅ Closed by the manual (the project owner, 2026-08-21): L1–L6 is the whole range, pauses 1/3/5/10/20/40 min against a fixed 30 s emission. L5 remains the one level never seen on the wire, but it is now sourced rather than inferred.
- ~~The timer enum's full extent; why `3h` maps to 240 minutes.~~ ✅ Closed by the manual (the project owner, 2026-08-21): the device offers 1h / 4h / 8h / continuous — four settings, exactly the four DP values the walk produced. `"3h"` **is** the 4-hour setting, mislabelled in firmware. `2h` and `4h` never existed.
- Whether the schedule the app created lives anywhere readable — it moved **no** DP during the
  walk, which points at a cloud-side or app-side schedule, not an on-device one. If so,
  scheduling in Home Assistant is automations + the countdown DP, full stop (the sibling project's ADR-009
  outcome, arrived at by a much shorter road).
- Whether writing a DP while the app is connected is accepted, rejected, or silently reverted
  — the contention seen during the write tests (null answers, one 914) is consistent with the
  app holding the single local connection. ADR-004's measurement, partially already made.
- Whether DP 101 is battery or oil level. Battery, near-certainly: it rose to 100 while plugged
  in, and it falls at a steady ~1%/minute while running — *including through the pause phases,
  when no mist is being produced*. Oil level would only fall while misting. Not closed outright
  because nothing has confirmed it against the unit's own battery indicator.

## Change log

| Date | What |
|---|---|
| 2026-08-21 (late) | Header corrected. This file had opened with "NOTHING HERE HAS BEEN OBSERVED ON THE DEVICE" through the entire recon that observed all of it — a first line that contradicted its own contents. The *Device identity* table's protocol-version and local-IP rows were stale from the same period. |
| 2026-08-10 | Created. Standard `xxj` set recorded as the hypothesis; nothing observed yet. |
| 2026-08-21 (late) | Manual consulted. Intensity table confirmed including the never-observed L5 (20 min); the countdown's four settings confirmed and `"3h"` identified as the mislabelled 4-hour option. Two phantom timer options (`2h`, `4h`) removed from the integration. |
| 2026-08-21 (evening) | **Correction.** DP 103 reclassified from power *command* to nozzle *status*: measured untouched, it cycles itself (30 s open / pause-interval closed). Power is DP 2, write-verified both directions. The integration's switch was rewritten onto DP 2 and 103 became a read-only `binary_sensor`. |
| 2026-08-21 | First contact: `tinytuya scan`, then QR login for the `local_key`; category `xxj` confirmed; **registered cloud schema found EMPTY** (the real "no entities" cause). Re-pair put the device on the LAN (v3.5). Control walk + write tests: DP table filled — intensity (3, mirrored by 106), timer (4, mirrored by 5), power state (103), battery (101), fixed work time (105). The hypothesis was wrong in detail — the standard `xxj` codes appear nowhere; every meaningful DP is vendor-specific — and right in spirit. ON command unresolved. |
