# Arozen EON Pro 2 — datapoint map

**Status: ✅ observed and write-verified on the device (2026-08-21), with one datapoint still
unidentified** — DP 104. The count read "three" until the remote walk of 2026-08-21 (night)
named DP 7 and DP 102, and was not updated with them. The map below comes from a control
walk, local write tests, a duty-cycle
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
| Local IP | ✅ reachable on the main LAN since the re-pair, 2026-08-21 (dossier §6.3). Address redacted — see captures/README.md |
| Device ID | ✅ known — recorded once, in dossier §6.2, and deliberately not restated here. One authoritative location per identifier: see captures/README.md |

### Datapoints

Evidence: captures/dp-watch-2026-08-21.txt (control walk
via the app), captures/remote-walk-2026-08-21.jsonl
(**physical remote, app closed**, plus the charger and LED tests that followed), local write
tests with `tools/dp_set.py`, a duty-cycle measurement taken with nothing writing to the
device, and **the printed manual**. Full DP set as first observed
(idle, after re-pair): `2=true, 3="L1", 4="3h", 5=239, 101=99, 102="zzcd", 103="kai",
104="kk", 105=30, 106=60`.

| DP | Type | Observed values | Function | How established |
|---|---|---|---|---|
| 2 | bool | `true`, `false` | **Power — and the *only* on/off this device has.** The phone app's separate "diffuser" button writes this same DP: pressing it moved DP 2 down and back up, carrying only the countdown re-arm that every power-on brings (`5: [237, 240]`) and nothing unique to itself. The app has **two** such controls — a "switch" and a "diffuser" — and both write DP 2. So there is no analogue of the standard `xxj` set's `switch_spray`; power and spray are one control. Writing `true` starts the device — it begins a mist burst within ~2 s; writing `false` stops it. ⚠️ **Both side effects belong to the *on* edge.** Powering on resets intensity to L1 **and** resets the countdown (DP 4 → `3h`, DP 5 → 240), in a single status record — one firmware default state, reapplied every time. Powering off never touches intensity or the countdown — unanimous across all **six** captured off-edges. It is not DP 2 alone as a rule, though: two of the six also took DP 7 (the LED) down with it, so "nothing else moves" would be an overclaim and this row does not make it. ⚠️ **Corrected 2026-08-21 (night).** This row previously blamed the off edge and claimed the phone app preserved intensity. Both were wrong: three power-ons — remote, remote, app — behaved identically, and the app does **not** restore intensity afterwards (30 s of silence, DP 3 flat at L1). The app's screen redraws from its own state, which is what "preserving" was. ✅ **The integration now undoes the intensity half of this** on the on edge (#14, `coordinator.IntensityMemory`); the countdown half is deliberately left alone, and [ADR-006](decisions.md#adr-006--correct-the-power-on-intensity-reset-and-only-that-one) has the reason the two are not the same case | write test ✅ both directions; **three power-ons, two sources, app closed for two of them** ✅ |
| 3 | enum string | `L1`…`L6` | **Intensity level.** Writing it is accepted and DP 106 mirrors it as pause seconds. L1=60, L2=180, L3=300, L4=600, L5=1200, L6=2400. ✅ **All six measured on the wire** — the remote walk stepped L1→L6 in order and DP 106 matched the manual's table at every level, including L5, which no app walk had ever produced. The manual is now corroboration, not the only source. ⚠️ The number counts *pause*, so L1 is the **strongest** setting and L6 the weakest. ⚠️ Changing intensity restarts the duty cycle — DP 103 goes to `kai` in the same record. ⚠️ **Cleared to L1 by every power-on**, by any source; see DP 2. ✅ **The integration writes it back** (#14) — inside the same exchange when Home Assistant causes the power-on, so `switch.turn_on` returns with the level already right, and on the next poll when the remote or the app causes it. It declines when the device reports any level *other* than L1 at that moment, because that means somebody set one in the interval before we looked | walk + write test + manual + **remote walk, all six levels** ✅ |
| 4 | enum string | `untime`, `1h`, `3h`, `8h` | **Countdown setting**, and there are exactly **four** of them. DP 5 follows: `1h`→60, `3h`→240, `8h`→480, `untime`→0. ⚠️ **`3h` is the 4-hour setting — the firmware string is simply wrong**, and the entity labels it by duration. ✅ **Proven on the remote rather than inferred:** the button physically labelled **4h** produced `4: "3h"` with `5: 240`. A printed button, a firmware string and a remaining count that disagree three ways — with the button and the count agreeing against the string. ⚠️ **Reset to `3h` by every power-on**, overwriting a deliberate choice: an `8h` setting became `3h` on the next on. `2h` and `4h` were never offered by the device and have been removed from the integration | walk + write test + manual + **remote button** ✅ |
| 5 | int | 0–480, ticks down | **Countdown remaining, minutes.** Watched decrement 240→239 during the walk. Not a pure mirror of DP 4: a power-on sets it to 240 while DP 4 still reads `untime`, so DP 4 is the request and DP 5 is what the device actually armed | walk ✅ + power-on test ✅ |
| 7 | bool | `true`, `false` | **Frontal LED.** ✅ Identified 2026-08-21 (night): toggling the LED in the app moved it within one poll, both directions, twice. ⚠️ **It also moves on its own, and not predictably.** Two power cycles carried it down with DP 2 and back up again; others moved DP 2 alone and left DP 7 untouched. The app's two off controls even differed from each other — its "switch" off took the LED down, its "diffuser" off did not — but that is one observation each and is recorded as a curiosity, not a distinction. Both self-moving episodes happened while the device was **on the charger**, which had itself produced four transitions in 40 s on plug-in. So the device does move this DP underneath a controller, but the condition is *not* established: "follows power" fits two observations out of three and is recorded here as the unfinished thing it is. Absent from every dump during the app control walk, and `false` throughout the remote walk, which in hindsight simply means the LED was off. ✅ **Write-verified 2026-08-22, and it is a command DP**: `false`→`true` was accepted and still read `true` across five polls over 30 s, and `true`→`false` the same. The duration is the test rather than the acceptance — DP 103 accepts writes and is reverted by the duty-cycle controller at the end of a burst, and 30 s spans a full `DP_WORK_S`, so a revert of that kind had its window. The test also ran with the charger connected and DP 7 did **not** drift, which narrows the self-movement above: the four transitions on plug-in belong to the *plug-in event*, not to sitting on the cable. ✅ **Now an entity** (#15) as `switch.arozen_eon_pro_2_led` — non-optimistic, with no memory and no restore, because the self-movement rule is still unestablished and correcting a rule you cannot state is inventing one | app toggle test 2026-08-21; local write test 2026-08-22 ✅ both directions, held 30 s |
| 101 | int | 80–100 | **Battery %.** ✅ Closed 2026-08-21 (night) — the app's own battery readout agreed with the DP to within a point (app 83%, DP 83), which is the cross-check this row previously lacked. On battery it falls **exactly 1 per 61 s while running** (seven consecutive ticks) and **stops dead when DP 2 goes false**, flat for 12 minutes; on the charger it rises. Discharge tracks *runtime*, not misting — through the pause phases, when no mist is produced — which is what rules out oil level. ⚠️ Whether the gauge is measured or a linear runtime estimate is not established: no intensity level was held long enough for the duty cycle to separate them, so treat it as approximate | remote walk on battery + charger test + app cross-check ✅ |
| 102 | string | `zzcd`, `wcd`, `cdwc` | **Charging status.** ✅ Identified 2026-08-21 (night): plugging in the charger moved it `wcd`→`zzcd`, and the app's own charging indicator agrees. The values are pinyin initials, the same house style as DP 103's `kai`/`guan`: `zzcd` = 正在充电 *zhèngzài chōngdiàn*, **charging**; `wcd` = 未充电 *wèi chōngdiàn*, **not charging**; `cdwc` = 充电完成 *chōngdiàn wánchéng*, **charge complete**. This also explains the movement that made it look like noise — it changed `cdwc`→`wcd` *between* sessions with the device idle and nothing writing to it, because the battery finished charging and then came off the cable. **No button walk of any length could have found it**; it needs a cable, which is why an entire remote walk never touched it. Neither 102 movement in that capture carries an attributing note, so what actually corroborates the decode is **DP 101 reversing direction across both**: falling 91→80 before the first, rising 80→88 after it, falling again after the second. ✅ **The integration now exposes it** (#16) as `binary_sensor.arozen_eon_pro_2_charging`, device class `battery_charging`: `zzcd` → on, the other two → off, with all three values kept in the `charge_state` attribute because the device class holds only two. ⚠️ **`cdwc` does not mean 100 %** — the control walk recorded it at DP 101 = 99 with the gauge still climbing to 100 twenty seconds later. ⚠️ **Nor is it a resting state while the device runs on mains**: watched 2026-08-22 (capture `captures/charging-cdwc-2026-08-22.txt`) it sat at `cdwc`/100, and the next mist burst took the gauge to 96 and this DP to `zzcd` in the same poll, then held `zzcd`/99 for eight minutes and two further bursts. A read five minutes after that capture stopped had it back at `cdwc`/100, so the round trip completes — but the `zzcd`→`cdwc` **edge itself has never been caught in a capture**, only inferred from readings either side of it. Unlike DP 103, the entity is deliberately *not* gated on power — see §Still unknown | charger test 2026-08-21; `cdwc` and the burst-driven flip watched 2026-08-22 ✅ |
| 103 | string | `kai` (开/open), `guan` (关/closed) | **Nozzle state — status, not command.** The device cycles it itself: `kai` for DP 105 seconds, then `guan` for DP 106 seconds, indefinitely. ⚠️ **Frozen while powered off**: switch off mid-burst and it reports `kai` indefinitely (measured still `kai` minutes later with DP 2 false), so it is a live reading only while running. It tracks app power toggles because power *causes* misting, which is what made it look like the power DP. Do not write it: `guan` merely interrupts the current burst, `kai` is reverted by the duty-cycle controller | duty-cycle measurement 2026-08-21 ✅ |
| 104 | string | `kk` | ❓ unknown, and the **last** one. Never moved — through an entire app control walk, an entire remote walk (power both ways, all six intensity levels, all four timer settings, the AROMA button), an LED toggle, a charger plug and unplug, a schedule created and deleted, and the app's own "diffuser" button. Every control the phone app exposes is now mapped to a different DP, so there is no untried stimulus left. Leading explanation is a firmware constant like DP 105 rather than a control; recorded as unknown because that is an explanation, not a measurement | walk + remote walk + LED + charger ❓ |
| 105 | int | 30 | **Work (burst) seconds, fixed at 30 by design.** The manual specifies a 30 s emission at every one of the six levels, so this is a firmware constant rather than a sampling artefact. Never moved; no app control touches it | walk + manual ✅ |
| 106 | int | 60–2400 | **Pause seconds — read-only mirror of DP 3.** Follows every DP 3 change *while the device is running*; changed while powered off, DP 3 moves and 106 keeps its old value until the next power-on. ✅ Mirrored correctly at **all six levels** during the remote walk, matching `dp.py`'s table exactly. Direct writes untested | walk + write test + remote walk ✅ |

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
- ~~**What the app's power-off does that a DP 2 write does not.**~~ ✅ **Resolved 2026-08-21
  (night): nothing, because the question was built on a false premise.** The remote walk caught
  both edges with the app closed. Off moves DP 2 alone. **On** clears intensity to L1 and resets
  the countdown, in one record — `{"2":[false,true],"3":["L3","L1"],"4":["untime","3h"]}` — after
  the device had held `L3` through the entire off period. Then the app was tested directly: its
  own on reset `L4`→`L1` and **did not restore it**, thirty seconds of silence afterwards. So the
  app never preserved intensity; its screen redraws from local state, which is what everyone was
  reading. Three power-ons from two sources, all identical.

  Two lessons, both already paid for once in this project. **The action that precedes an
  observation is not necessarily its cause** — the off collected the blame because it is what you
  do just before you notice, exactly as DP 103 collected the blame for power because it moves
  when power moves. And **check the premise before explaining it**: two hypotheses were framed,
  and the measurement that settled them was the one that asked whether there was anything to
  explain. Restoring intensity across a power cycle was #14, now built: a capability the phone
  app does not have rather than parity with it.
- **Why power-on arms a 240-minute countdown.** DP 5 → 240 within 2 s of `2=true`, with DP 4
  still reading `untime`. Presumably a firmware default auto-off. Harmless, but it means the
  countdown sensor reads non-zero after every switch-on.
- **Which status DPs freeze when the device is off, and which do not.** Confirmed frozen:
  DP 103 (nozzle) and DP 106 (pause mirror, which will not follow a DP 3 write while off).
  Assume any status DP on this device is stale until proven live — the integration gates
  the misting sensor on power for exactly this reason.
  **DP 102 (charging) is the open case, but it is not evidence-free, and an earlier revision
  of this bullet wrongly said it was.** The control walk's last record took DP 2 to false with
  102 reading `cdwc`; the remote walk opened 4 h 24 m later with DP 2 still false and 102
  reading `wcd`. The value moved between two observations that both have the device off, and
  the stimulus it tracks — a charger coming out — needs no device at all. That is not proof
  (nothing rules out the diffuser being run in between), but it leans *against* a freeze,
  which is the opposite of DP 103. The charging entity is deliberately not gated: charging an
  idle diffuser is the ordinary case, and a gate would blank the reading exactly when it is
  most wanted. **What settles it:** leave `dp_watch.py` running with the diffuser switched
  *off*, then pull the charger. If 102 moves it is live while off; if it sticks, the gate
  belongs on it and this note becomes the reason.
- ~~DP 102's values (`zzcd`/`wcd`/`cdwc`); DP 7~~ ✅ **Both identified 2026-08-21 (night).**
  DP 7 is the **frontal LED** (app toggle, both directions, within one poll). DP 102 is
  **charging status**, in pinyin initials — 正在充电 / 未充电 / 充电完成 — confirmed by plugging
  the charger in. Neither was findable by pressing buttons: the LED had simply been off all
  night, and 102 needs a *cable*, not a control, which is why an entire remote walk never
  moved it. Worth remembering the next time a DP "never moves" — it may mean the stimulus is
  not a button. **DP 7's direction was settled on 2026-08-22**: a local write test held both
  ways for 30 s, so it is a command DP and now has a switch.
- **Why DP 7 moves on its own.** Settled: no. Two power cycles out of three carried it down
  with DP 2 and back up; the third left it alone. Both self-moving episodes were on the
  charger, and plugging the charger in produced four transitions in ~40 s by itself. The
  2026-08-22 write test narrows it usefully — it ran *with the charger connected* and DP 7
  held whatever was written to it for 30 s, so the plug-in transitions belong to the event,
  not to the state of being on the cable. What is left unexplained is the power-cycle
  correlation, and "follows power" still fits only two observations out of three. The LED
  switch is deliberately built not to care: it reports the DP and never writes unasked.
- **DP 104 (`kk`)** — the last one, and now the only DP with no function. It survived an app
  control walk, a remote walk, an LED toggle and a charger event without moving, and every
  control the app exposes is mapped to a different DP. A firmware constant like DP 105 is the
  leading explanation, but that is an explanation, not a measurement, so it stays here.
- ~~The intensity enum's full extent.~~ ✅ Closed by the manual (the project owner, 2026-08-21), then **measured in full** on the remote walk that night: L1–L6, pauses 1/3/5/10/20/40 min against a fixed 30 s emission, with DP 106 matching at every level. L5 — the one level no app walk ever produced — is now observed rather than sourced.
- ~~The timer enum's full extent; why `3h` maps to 240 minutes.~~ ✅ Closed by the manual (the project owner, 2026-08-21): the device offers 1h / 4h / 8h / continuous — four settings, exactly the four DP values the walk produced. `"3h"` **is** the 4-hour setting, mislabelled in firmware. `2h` and `4h` never existed.
- Whether the schedule the app created lives anywhere readable. It moved **no** DP during the
  original control walk, and — tested again on 2026-08-21 (night) — creating *and then deleting*
  a schedule moved no DP either. Two independent attempts, nothing on the wire. That is about as
  close to settled as a negative gets: the schedule is cloud-side or app-side, not on-device, so
  scheduling in Home Assistant is automations + the countdown DP, full stop (the sibling project's ADR-009
  outcome, arrived at by a much shorter road). Left open rather than ticked because proving a DP
  *absent* needs a channel we have not checked, not just a walk that did not see it.
- Whether writing a DP while the app is connected is accepted, rejected, or silently reverted
  — the contention seen during the write tests (null answers, one 914) is consistent with the
  app holding the single local connection. ADR-004's measurement, partially already made.
- ~~Whether DP 101 is battery or oil level.~~ ✅ **Battery**, 2026-08-21 (night). The caveat
  this line used to carry — "nothing has confirmed it against the unit's own battery indicator"
  — is now discharged: the phone app read **83%** while the DP read **83**. On battery it falls
  exactly 1 per 61 s of runtime and stops dead when the device powers off; on the charger it
  rises. What remains open is narrower and worth keeping: whether the gauge is measured or a
  linear runtime estimate. No intensity level was held long enough for the duty cycle to
  separate them, so the sensor is documented as approximate rather than trusted.

## Change log

*The `#NN` here are issues and pull requests in this project's private development archive; they
are plain text because they resolve to nothing in the published repository — see
[ADR-007](decisions.md#adr-007--do-not-rewrite-git-history-scrub-at-publication-on-a-fresh-repository).*

| Date | What |
|---|---|
| 2026-08-23 | **The "100+ range" claim corrected wherever it had been copied** (#40). No measurement changed and the table above is untouched: it has said the opposite since 2026-08-21, and three other files went on repeating the hypothesis instead. The guess going in was vendor-specific DPs in the 100+ range, the usual Tuya convention outside a standard category. The device is the reverse — **every writable DP is low** (2 power, 3 intensity, 4 countdown, 7 LED) and everything from 101 up is status, telemetry or a firmware constant. The controls sit exactly where a standard device's would, and are invisible anyway because the registered schema declares nothing, which is a sharper statement of the problem than the one being corrected. Fixed in `dp.py`'s module docstring, [why-not-the-official-integration.md](why-not-the-official-integration.md) and dossier §6.6; the change-log row for 2026-08-21 below is left as written, because it records what was believed that day. **In the same pass, ADR-001's viability premise** was corrected from "the device is mains-powered" — it has a battery, DP 101, closed 2026-08-21 — to the measurement that actually carries the decision: the device does not sleep. 44 minutes of unbroken 2 s polling in the remote walk with no failed poll recorded, the first half-hour on battery and 17 minutes of that with the diffuser switched off ([ADR-001](decisions.md#adr-001--local-lan-control-the-tuya-cloud-is-the-fallback-not-the-plan)). |
| 2026-08-22 | **The device ID row stopped restating the value** (#20). It had carried a second copy of the id since the initial commit, in direct contradiction of the one-authoritative-location rule this repo states in captures/README.md — and the contradiction was *known*, written down in a capture header, before it was fixed. No measurement changed; the value is unchanged and lives in dossier §6.2. Two other appliances' ids were redacted out of dossier §6.1 in the same pass, which was the wider disclosure of the two, and `tests/test_redaction_rule.py` now fails the build on a third copy rather than waiting for the README's sweep to be run. The same identifiers remain in the **private archive's git history**, and stay there on purpose: [ADR-007](decisions.md#adr-007--do-not-rewrite-git-history-scrub-at-publication-on-a-fresh-repository) records why a force-push does not achieve what it looks like it achieves, and what does. |
| 2026-08-22 | **DP 7 write-tested, and the LED became a switch** (#15). The entity had been blocked on this one measurement since the DP was identified, because everything known about DP 7 was *observation* — the app moved it, the device moved it — and observing a DP move tells you nothing about whether you may move it. DP 103 is why: it accepts writes and the duty-cycle controller reverts them, which is how the valve was once mistaken for the power switch. So the test was not "is the write accepted" but "is it still there later": `false`→`true` held across five polls over 30 s, `true`→`false` the same, 30 s being a full `DP_WORK_S` and therefore the window a 103-style revert would need. Command DP, so a `switch` rather than a `binary_sensor`. It ships **non-optimistic and with no memory**: the device moves DP 7 by itself on a condition nobody has established, and an entity that put its own value back would be enforcing a rule the evidence does not support ([ADR-006](decisions.md#adr-006--correct-the-power-on-intensity-reset-and-only-that-one) is the reasoning for treating this differently from intensity). One incidental narrowing: the test ran with the charger connected and DP 7 did not drift, so the four transitions seen on plug-in belong to the plug-in event rather than to being on the cable. |
| 2026-08-22 | **Charging status exposed as an entity** (#16), plus one measurement that was meant to be a formality and was not (capture `captures/charging-cdwc-2026-08-22.txt`). Watching `cdwc` to confirm it — it had only ever been seen *before* it had a name — caught the next mist burst pulling DP 101 from 100 to 96 and flipping 102 to `zzcd` in the same poll, then holding there for eight minutes and two further bursts. So **`cdwc` is a state a burst breaks, not a resting place**, and the charging entity flaps while the device runs on mains. Recorded as gotcha 5 rather than smoothed over. Two claims were corrected in the same pass: `cdwc` does **not** mean 100 % (the control walk has it at 99 with the gauge still rising), and the question of whether 102 freezes while the device is off is **not** evidence-free — 102 moved `cdwc`→`wcd` between two observations that both have DP 2 false, which leans against a freeze and is why the entity is not power-gated. Three device states go into a two-state device class, so `charge_state` carries all three. An unrecognised value reads as **unknown**, not as off — a deliberate divergence from the misting sensor, where anything that is not `kai` genuinely is not misting. The reasoning, and the plain-three-state-sensor alternative that was turned down, are in the entity's docstring. |
| 2026-08-21 (night) | **Intensity restored across the power-on reset** (#14). No new measurement — this is the walk's finding turned into behaviour. The coordinator remembers the level from ordinary polls and writes it back when it witnesses `2: false → true`, from any source. The reading that carries a power-on is the one reading that never teaches the memory, which is what stops it restoring L1 for ever. The countdown is armed on the same edge and is deliberately not restored ([ADR-006](decisions.md#adr-006--correct-the-power-on-intensity-reset-and-only-that-one)). |
| 2026-08-21 (night) | **Remote walk** (capture `captures/remote-walk-2026-08-21.jsonl`), app closed, then charger and LED tests. **Correction: the intensity reset belongs to the power-*on* edge, not the off — and the phone app does not preserve intensity either.** The premise behind two competing hypotheses turned out to be false; the integration's `DP 2 = false` write was never responsible for anything. Identified **DP 7 = frontal LED** and **DP 102 = charging status** (pinyin initials), and closed **DP 101 = battery** against the app's own readout. Intensity L1–L6 measured in full, L5 seen on the wire for the first time; the `3h`/4-hour firmware mislabel proven by pressing the button. **DP 104 did not move once** — recorded as a result, not a gap. |
| 2026-08-21 (late) | Header corrected. This file had opened with "NOTHING HERE HAS BEEN OBSERVED ON THE DEVICE" through the entire recon that observed all of it — a first line that contradicted its own contents. The *Device identity* table's protocol-version and local-IP rows were stale from the same period. |
| 2026-08-10 | Created. Standard `xxj` set recorded as the hypothesis; nothing observed yet. |
| 2026-08-21 (late) | Manual consulted. Intensity table confirmed including the never-observed L5 (20 min); the countdown's four settings confirmed and `"3h"` identified as the mislabelled 4-hour option. Two phantom timer options (`2h`, `4h`) removed from the integration. |
| 2026-08-21 (evening) | **Correction.** DP 103 reclassified from power *command* to nozzle *status*: measured untouched, it cycles itself (30 s open / pause-interval closed). Power is DP 2, write-verified both directions. The integration's switch was rewritten onto DP 2 and 103 became a read-only `binary_sensor`. |
| 2026-08-21 | First contact: `tinytuya scan`, then QR login for the `local_key`; category `xxj` confirmed; **registered cloud schema found EMPTY** (the real "no entities" cause). Re-pair put the device on the LAN (v3.5). Control walk + write tests: DP table filled — intensity (3, mirrored by 106), timer (4, mirrored by 5), power state (103), battery (101), fixed work time (105). The hypothesis was wrong in detail — the standard `xxj` codes appear nowhere; every meaningful DP is vendor-specific — and right in spirit. ON command unresolved. |
