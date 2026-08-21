# Arozen EON Pro 2 — datapoint map

**Status: ❓ NOTHING HERE HAS BEEN OBSERVED ON THE DEVICE.** Every table below is either
Tuya's published standard or an empty form waiting to be filled. Do not build against it.

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

## Observed — to be filled in

### Device identity

| | |
|---|---|
| Tuya category | ✅ **`xxj`** — cloud device record, 2026-08-21 |
| Product ID (`product_id`) | ✅ `uh3xooop1btksbtk` — cloud device record, 2026-08-21. ⚠️ The value previously recorded here (`jidyk1ybp0dqlteg`, from the LAN broadcast) belongs to a **dehumidifier** on the same account — see dossier §6.1 for the misidentification |
| Product name as registered | ✅ "Arozen Eon pro 2-" — cloud device record |
| Registered cloud schema | ✅ **EMPTY** — `functions: []`, `status: []` (dossier §6.4). The DPs exist but are undeclared; only a live dump reveals them |
| Protocol version | ❓ (the 3.5 recorded earlier was the misidentified dehumidifier) |
| Firmware / module | ❓ |
| Local IP | ❓ device not reachable on the LAN (dossier §6.3) |
| Device ID | ✅ `bfdeadbeefdeadbeef0001` — cloud device record, 2026-08-21 |

### Datapoints

Evidence: [captures/dp-watch-2026-08-21.txt](captures/dp-watch-2026-08-21.txt) (control walk),
plus local write tests with `tools/dp_set.py` the same evening. Full DP set as first observed
(idle, after re-pair): `2=true, 3="L1", 4="3h", 5=239, 101=99, 102="zzcd", 103="kai",
104="kk", 105=30, 106=60`.

| DP | Type | Observed values | Function | How established |
|---|---|---|---|---|
| 2 | bool | `true`, `false` | ❓ unknown. Accepts writes, but they do not drive power or anything else observed. Flipped once during the walk without an obvious corresponding action | write test 2026-08-21 (no effect seen) |
| 3 | enum string | `L1`…`L6` | **Intensity level.** Writing it is accepted and DP 106 mirrors it: L1→60, L2→180, L3→300, L4→600, L6→2400 (L5 unobserved, presumably 1200) | walk + write test ✅ |
| 4 | enum string | `untime`, `1h`, `3h`, `8h` | **Countdown setting.** Writing it is accepted and DP 5 mirrors the remaining minutes: `1h`→60, `3h`→240, `8h`→480, `untime`→0. ⚠️ `3h`↔240 min is what the device does, mislabel or not; `2h` never observed | walk + write test ✅ |
| 5 | int | 0–480, ticks down | **Countdown remaining, minutes.** Watched decrement 240→239 during the walk | walk ✅ (read-only assumed) |
| 101 | int | 99, 100 | **Battery %, almost certainly.** Went 99→100 while plugged in; the vendor copy's "battery-operated" turns out to be true alongside mains | walk 🔵 (strong inference) |
| 102 | string | `zzcd`, `wcd`, `cdwc` | ❓ unknown. Moved only between walk phases, never in step with a single control. Looks like pinyin fragments; possibly a mode or program-state string | walk ❓ |
| 103 | string | `kai` (开/on), `guan` (关/off) | **Power state** — tracks every app power toggle. **Command semantics unresolved:** writing `guan` sticks (turns off); writing `kai` is acknowledged but reverted by the device, and once armed DP 4/5 as a side effect | walk ✅ state; write test ❓ on-command |
| 104 | string | `kk` | ❓ unknown. Never moved | walk ❓ |
| 105 | int | 30 | **Work (burst) seconds, apparently fixed at 30.** Never moved; no app control touched it | walk 🔵 |
| 106 | int | 60–2400 | **Pause seconds — read-only mirror of DP 3.** Follows every DP 3 write; direct writes untested | walk + write test ✅ |

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

- **The ON command.** `guan` written to DP 103 turns the device off; `kai` is acknowledged and
  reverted. Either "on" needs something more than the state DP (a companion write, a mode, a
  physical condition), or DP 103 is state-only in the on direction and the command lives
  elsewhere. Blocked on physical observation: did the unit mist during the write tests?
- DP 2's function; DP 102's values (`zzcd`/`wcd`/`cdwc`); DP 104 (`kk`).
- The intensity enum's full extent: L5 unobserved; whether L1…L6 is the whole range.
- The timer enum's full extent: `2h` never observed; why `3h` maps to 240 minutes.
- Whether the schedule the app created lives anywhere readable — it moved **no** DP during the
  walk, which points at a cloud-side or app-side schedule, not an on-device one. If so,
  scheduling in Home Assistant is automations + the countdown DP, full stop (the sibling project's ADR-009
  outcome, arrived at by a much shorter road).
- Whether writing a DP while the app is connected is accepted, rejected, or silently reverted
  — the contention seen during the write tests (null answers, one 914) is consistent with the
  app holding the single local connection. ADR-004's measurement, partially already made.
- Whether DP 101 is battery or oil level. Battery is the strong favourite (rose to 100 while
  plugged in); oil would be the find of the project.

## Change log

| Date | What |
|---|---|
| 2026-08-10 | Created. Standard `xxj` set recorded as the hypothesis; nothing observed yet. |
| 2026-08-21 | First contact: `tinytuya scan`, then QR login for the `local_key`; category `xxj` confirmed; **registered cloud schema found EMPTY** (the real "no entities" cause). Re-pair put the device on the LAN (v3.5). Control walk + write tests: DP table filled — intensity (3, mirrored by 106), timer (4, mirrored by 5), power state (103), battery (101), fixed work time (105). The hypothesis was wrong in detail — the standard `xxj` codes appear nowhere; every meaningful DP is vendor-specific — and right in spirit. ON command unresolved. |
