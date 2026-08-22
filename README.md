# Arozen EON Pro 2 for Home Assistant

[![CI](https://github.com/luguina/arozen_ha_controller/actions/workflows/ci.yml/badge.svg)](https://github.com/luguina/arozen_ha_controller/actions/workflows/ci.yml)
[![Validate](https://github.com/luguina/arozen_ha_controller/actions/workflows/validate.yml/badge.svg)](https://github.com/luguina/arozen_ha_controller/actions/workflows/validate.yml)

A Home Assistant custom integration for the **Arozen EON Pro 2** cold-air scent diffuser.
Power, intensity, timer, battery and charging — **locally over your LAN, with no Tuya cloud
in the runtime path.**

It exists because the **official Tuya integration gives this device zero entities**: the OEM
registered an empty datapoint schema, so every schema-driven integration reads nothing and
creates nothing. The datapoints are there; they just had to be found by hand.
[The full explanation, with the core source trace.](docs/why-not-the-official-integration.md)

---

## What you get

Eleven entities, on one device:

| Entity | What it is |
|---|---|
| `switch.arozen_eon_pro_2` | **Power.** On means the duty cycle is running — not that it is misting this second |
| `switch.arozen_eon_pro_2_led` | **Frontal LED.** Writable — verified on the device, and it sticks. The diffuser also moves this one itself on some power cycles; the integration reports that rather than fighting it |
| `binary_sensor.arozen_eon_pro_2_misting` | **Misting.** Whether the nozzle is open *right now*. On for 30 s, then off for the interval |
| `binary_sensor.arozen_eon_pro_2_charging` | **Charging.** On while the battery is taking charge. The device reports three states and this class holds two, so `charge_state` in the attributes carries all three — including `complete` — see gotcha 5 |
| `select.arozen_eon_pro_2_intensity` | **Intensity**, `L1 · every 1 min` … `L6 · every 40 min` |
| `select.arozen_eon_pro_2_timer` | **Timer** — `Continuous`, `1 hour`, `4 hours`, `8 hours` |
| `sensor.arozen_eon_pro_2_battery` | **Battery %** |
| `sensor.arozen_eon_pro_2_timer_remaining` | **Minutes left** on the auto-off countdown |
| `sensor.arozen_eon_pro_2_failed_polls` | Diagnostic: polls that failed, with the last error |
| `sensor.arozen_eon_pro_2_intensity_restores` | Diagnostic: times the power-on intensity reset was undone, and any that failed — see gotcha 2 |
| `sensor.arozen_eon_pro_2_datapoints_recon` | Diagnostic: the raw datapoints. Scaffolding — see [Status](#status) |

The device diffuses in **bursts**: 30 seconds of mist, then a pause. The intensity level sets
the pause, which is why the entity is labelled the way it is.

## Install

**Home Assistant 2026.8.1** is what this is developed and tested against. It is not tested
against anything older.

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/luguina/arozen_ha_controller`, category **Integration**
3. Install **Arozen EON Pro 2 Diffuser**, then restart Home Assistant

### Manually

Copy `custom_components/arozen_eon/` into your Home Assistant `config/custom_components/`
directory and restart.

## Set it up

**Settings → Devices & Services → Add Integration → Arozen EON Pro 2 Diffuser.**

Four fields, and the form proves them before it accepts them — it opens a real connection and
reads status, so a wrong key or version fails here rather than silently later.

| Field | What it is |
|---|---|
| **IP address** | Where the diffuser sits on your LAN |
| **Device ID** | Its permanent identity in Tuya's world — 22 characters, starting `bf` |
| **Local key** | The secret the firmware accepts commands under. ⚠️ A **live credential** — see [below](#about-the-local_key) |
| **Protocol version** | Which dialect the firmware speaks. `3.3`, `3.4` or `3.5` — **`3.5` for this unit**, and the default the form offers |

### Where the device ID and local key come from

**This is the hard part, and it is hard on purpose.** The diffuser is sold as a cloud
appliance: you pair it to a Tuya account with the Smart Life app, and from then on the app
talks to Tuya's servers and Tuya's servers talk to the device. The `local_key` is what lets
you skip that round trip and address the device directly on your own network — and nothing in
the product wants you to have it. It is **not printed on the device**, **not shown anywhere in
the app**, and **not readable from the device itself**. It is minted when the device is paired,
and it only ever leaves Tuya through Tuya's own APIs.

So every route below is the same manoeuvre: authenticate as yourself, ask Tuya which devices
are on your account, and read the key out of the reply. **The diffuser has to be paired in the
Smart Life / Tuya app first** — if it is not in the app, there is nothing for either tool to
read.

**Route A — [`tuya-local-key`](https://github.com/vineetchoudhary/tuya-local-key). Start here.**
A QR login against Tuya's device-sharing SDK, and **no Tuya IoT developer account needed**,
which removes what used to be the worst part of this job. It runs as a CLI, a Docker container
or a Home Assistant add-on, and prints device ID, `local_key`, IP, online status and category
for every device on the account.

One trap, and it catches most people once: **the QR code expires in a minute or two.** Have the
phone unlocked with the Smart Life app already open on its scanner *before* you generate it.

**Route B — `tinytuya wizard`. The classic route, and heavier.**

```sh
pip install tinytuya
python -m tinytuya wizard
```

This one *does* want a **Tuya IoT Platform** project with an Access ID and Secret, and inside
that project you must also "Link Tuya App Account" so the project can see devices you paired in
the app. The trial expires and needs periodic renewal — that lapsing is the usual reason a setup
that worked once cannot be reproduced six months later. Note where it puts its output:
`devices.json`, `tinytuya.json` and `snapshot.json`, in the working directory, **each containing
live keys in plaintext**.

### Finding the IP, and confirming the protocol version

```sh
python -m tinytuya scan
```

It broadcasts on the LAN and reports every Tuya device that answers, with its address **and the
protocol version that device is speaking** — which is the only honest way to fill the fourth
field. `3.5` is what this unit reports; `3.3` and `3.4` stay selectable because a firmware
update can move it.

**A wrong protocol version does not present as a wrong protocol version.** The connection opens,
the reply comes back undecryptable, and the form reports it the way it reports a bad key. So if
setup rejects credentials you are confident in, change the version before you start doubting the
key.

### The order that works

1. Pair the diffuser in the Smart Life app, if it is not already
2. Route A or Route B → **device ID** and **local key**
3. `python -m tinytuya scan` → **IP address** and **protocol version**
4. **Close the Smart Life app.** During recon, local *writes* failed intermittently while it was
   open and landed reliably once it was closed. This form only *reads*, so it may well survive an
   open app — but closing it costs nothing, and a contended connection here would look like bad
   credentials rather than like contention, which is the expensive kind of wrong turn
5. Fill the form and submit — it validates against the real device, so success here means it
   genuinely works
6. Give the diffuser a **DHCP reservation** in your router. The config entry stores an address,
   not a name, and a lease change is a silent break
7. Put the `local_key` in your password manager, and nowhere else

### Re-pairing the diffuser invalidates the key

Removing the device from the app and adding it back **mints a new `local_key`**. The device ID
survives; the key does not. Home Assistant will then fail every poll, with the reason on
`sensor.…_failed_polls`. The fix is to reconfigure the entry with the new key — and that same
property is the remedy if you ever leak one, which is worth knowing before you need it.

Recon-level detail on all of the above: [datapoints.md §Method](docs/datapoints.md#1-get-the-credentials).

## Before you automate it

This device has five behaviours that will look like bugs if you meet them without warning.
None of them is the integration inventing something; all five are the firmware.

**1. L1 is the *strongest* setting and L6 the weakest.** The level number counts the *pause*,
not the output — L1 mists every minute, L6 every forty. The entity labels say so
(`L4 · every 10 min`) precisely so nobody has to remember it.

**2. Turning it *on* resets intensity to L1 and the timer to 4 hours — the integration puts
the intensity back.** The device does this itself on every power-**on**, whoever performs it —
Home Assistant, the phone app, or the physical remote — and the phone app does not undo it
either. The integration does ([#14](https://github.com/luguina/arozen_ha_controller/issues/14)): it remembers the level from ordinary polling
and writes it back the moment it sees the device switched on. Immediately when Home Assistant
is what turned it on, so `switch.turn_on` returns with the level already right; within one
poll interval when the remote or the app did, so expect a few seconds at L1 first.
`sensor.…_intensity_restores` counts them and carries the error if one ever fails.

**The timer is on you**, deliberately: an auto-off falling back to four hours is a safety
default, and overriding a safety default is a different act from repairing a defect
([ADR-006](docs/decisions.md#adr-006--correct-the-power-on-intensity-reset-and-only-that-one)). So an automation that power-cycles the diffuser still has to set the
timer again *after* turning it back on:

```yaml
automation:
  - alias: "Diffuser: gentle overnight"
    triggers:
      - trigger: time
        at: "22:00:00"
    actions:
      - action: switch.turn_on
        target: { entity_id: switch.arozen_eon_pro_2 }
      # Intensity comes back on its own. The timer does not — the power-on just armed 4 h.
      # After the switch, never before: turning on is what resets it.
      - action: select.select_option
        target: { entity_id: select.arozen_eon_pro_2_timer }
        data: { option: "8 hours" }
```

*(Set the intensity explicitly anyway if your automation wants a **specific** level. The
restore puts back whatever the device was last seen at, which is the right default and is not
the same thing as the level you had in mind.)*

**3. Turning it on arms a 240-minute countdown by itself.** `sensor.…_timer_remaining` will
read `240` after a switch-on even though the Timer select says `Continuous`. That is the
firmware's own default auto-off. Whether it actually powers down when the count reaches zero
has **not** been observed — do not build an automation that depends on either answer yet.

**4. The Misting sensor reads `off` whenever the power is off — deliberately.** The device
*freezes* that datapoint when it stops: switch it off mid-burst and it keeps reporting "nozzle
open" indefinitely. The integration refuses to read a frozen register as a live one. The raw
value is still visible on the diagnostic datapoints sensor if you want it.

**5. `Charging` flips on and off while the diffuser runs on mains, and `Charging: off` does
not mean unplugged.** Two separate surprises in one entity, both the firmware's:

* Sitting at "charge complete" with the battery at 100 %, the next mist burst pulled the gauge
  down to 96 and charging restarted in the same poll — then stayed on for the following eight
  minutes and two further bursts. Running on the cable, this entity cycles.
* "Charge complete" reads as `off` on this entity, because Home Assistant's battery-charging
  class has two states and the device has three. If you care about the difference between
  *full on the cable* and *running on the battery*, trigger on the `charge_state` attribute
  (`charging` / `not_charging` / `complete`), not on the on/off state.

And "complete" is not a synonym for 100 %: it was recorded at 99 % with the gauge still
climbing. Whatever the firmware means by it, it is not "the number reached its maximum".

## Tuning

One option, under the integration's **Configure** button: **poll interval**, default 60 s
(range 10–3600).

Lower is fresher, but every poll competes with the phone app — many Tuya devices accept only
one local connection at a time. If the app starts failing to connect while Home Assistant is
polling hard, that is why. A tolerated single poll failure holds the previous reading rather
than dropping every entity to `unavailable`; `sensor.…_failed_polls` still counts it, so a
degrading link is visible instead of merely smoothed over.

## About the `local_key`

> ⚠️ **This repository is private, and the thing that must never leave it is the Tuya
> `local_key`.**

It is not a device identifier — it is a **live credential**. It authenticates and encrypts
local control, and anyone holding it plus LAN access can drive the diffuser. Home Assistant
stores it in the config entry like any other integration secret, which is fine; a git
repository is not.

| Artefact | Rule |
|---|---|
| `local_key` | **Never committed, in any file, ever** — not truncated, not partially masked |
| `device_id`, Tuya `uid` | Redact in captures; recorded once in the dossier |
| LAN IP, SSID | Redact |
| `devices.json`, `snapshot.json`, `tinytuya.json` | **Gitignored** — the wizard writes local keys into these in plaintext |

`.gitignore` covers the tooling's default output filenames, but do not rely on that alone —
the wizard will happily write a key into any path you point it at. Audit before publishing,
because it is one command and the answer changes every time somebody adds a file:

```sh
git ls-files -z | xargs -0 grep -niE \
  'local_key|localkey|"uid"|[0-9a-f]{16,22}|\b(10|192\.168|172\.(1[6-9]|2[0-9]|3[01]))(\.[0-9]{1,3}){2}\b'
```

It reports **candidates for a human to look at**, not confirmed leaks. A false positive costs a
glance; a false negative publishes a working credential to the device in your house. Deliberately
noisy, then — but it is worth knowing *how* noisy before you skim it, because a rate you have not
measured is one you assume is low. On the tree as this was written it returns **70 lines, 6 of
which are identifiers**: the one sanctioned entry in dossier §6.2, and five synthetic ids in the two test
files that need identifier-shaped strings to test redaction with. The other 64 are the *word*
`local_key`, in code that reads a credential out of an untracked file rather than containing one.
So about one line in twelve is an identifier, and they do not look different from the rest — read
all 70 rather than scanning for something that jumps out.

**It scans the working tree only, and that is a different question from the one you are asking.**
A file cleaned up at the tip still carries its old contents in every commit before the cleanup, so
this sweep can report a clean repo while the value stays one `git log -p` away. That is not
hypothetical here — it is exactly what
[#20](https://github.com/luguina/arozen_ha_controller/issues/20) found. The companion, over every
blob on every ref:

```sh
git grep -nIE 'bf[0-9a-z]{20}|"(local_)?key"' $(git rev-list --all) \
  | sed 's/^[0-9a-f]\{40\}://' | sort -u
```

Narrower than the tree sweep on purpose. The broad regex over forty-odd commits returns several
hundred lines that are mostly the same file forty times, and a report that long gets skimmed rather
than read; dropping the commit SHA and deduping collapses one leak in thirty commits down to one
line, which is the difference between **a few dozen lines and several hundred** — small enough to
read, which is the whole trick.

No exact figure is quoted for it on purpose. Both counts move with **every commit**, including the
one that adds a line above a hit and thereby mints a fresh `path:line` entry under dedup — so a
number written down here is stale by the time the change that measured it merges. That is not a
reason to distrust the command; it is the reason it is a command. Run it.

It answers *"was this ever committed"*, not *"in which commits"*; `git log -S<value> --all` is the
follow-up once you know there is something to chase.

The two halves of that pattern do different jobs, and the second one has never fired in anger. A
`bf`-prefixed hit is a **Tuya device id**. A `"key"` hit has **never once matched a value** — every
one is the field name in a tool reading credentials from an untracked file. That is the point of
including it: a hit that *was* a value would look nothing like the others, and it would mean the
`local_key` had been committed.

The capture-specific rules are in [docs/captures/README.md](docs/captures/README.md#redaction-rule),
and `tests/test_redaction_rule.py` enforces the one-authoritative-location half of them on every
test run — so a *third* copy of the device id fails CI, rather than waiting for somebody to
remember to run any of this.

## Status

**Working, in daily use, with one unidentified datapoint left.**

| | |
|---|---|
| ✅ | Power, intensity, timer, battery, nozzle state, charging, LED — all mapped, write-verified against the device where writing is meaningful, and covered by tests |
| ✅ | Config flow, options flow and all nine entities *as they stood on 2026-08-21* verified end to end against a real Home Assistant instance and the real diffuser |
| ✅ | **What the phone app's power-off does that ours does not: nothing.** [#5](https://github.com/luguina/arozen_ha_controller/issues/5)'s remote walk settled it and overturned the premise — the reset belongs to the power-**on** edge, and the app loses intensity exactly like we do. Gotcha #2 above is the corrected version |
| ✅ | **Intensity survives a power cycle** ([#14](https://github.com/luguina/arozen_ha_controller/issues/14)) — remembered from ordinary polling, written back on the on edge from any source, and never taught the firmware's default *by* the reading that carries the reset — which is what would otherwise restore L1 for ever. A power-on that reports some *other* level means a human got there first, and that one does teach. The countdown is armed on the same edge and is deliberately left alone ([ADR-006](docs/decisions.md#adr-006--correct-the-power-on-intensity-reset-and-only-that-one)) |
| ✅ | **The restore is verified on the real diffuser** (2026-08-21), from both directions: Home Assistant's own switch, where L4 was back before the turn-on call returned, and the **physical remote**, where it came back on the following poll. The guard holds too — switch on with the remote and press intensity, and the level you chose survives untouched. Fifteen checks, two restores, no failures. The restore *counter* is what proves the firmware did reset it, because a restore only fires when the device reports L1 on the on edge |
| ✅ | The **entity wiring** is verified too, in a throwaway Home Assistant driven over its own REST API: the config flow validates and creates the entry, exactly the nine entities that existed then appear — the ten listed above, less `charging`, which postdates that run — and nothing else, and after `switch.turn_off` / `switch.turn_on` the intensity select still reads `L4 · every 10 min` with the restores sensor at 1 and `remembered_level: L4` |
| ✅ | **DP 102 is charging status** (`zzcd`/`wcd`/`cdwc` — 正在充电 / 未充电 / 充电完成) and is now the tenth entity ([#16](https://github.com/luguina/arozen_ha_controller/issues/16)). It was never reachable by pressing buttons — the stimulus is a cable, not a control — which is why an entire remote walk went past it. `cdwc` was confirmed on the device 2026-08-22, on the cable at 100 % |
| ✅ | **DP 7 is the frontal LED, and it is a command DP** ([#15](https://github.com/luguina/arozen_ha_controller/issues/15)) — write-verified 2026-08-22, both directions, each holding across five reads over 30 seconds. That duration is the test, not the acceptance: DP 103 accepts writes and then reverts them at the end of a burst, so 30 s spans the window in which a revert would have shown. Had it snapped back this would have shipped as a read-only sensor. The device also moves DP 7 by itself on some power cycles, and the integration reports that rather than fighting it — no memory, no restore, deliberately unlike intensity ([ADR-006](docs/decisions.md#adr-006--correct-the-power-on-intensity-reset-and-only-that-one)) |
| ⏸️ | **Neither the charging sensor nor the LED switch has been through `tools/verify_ha.py`.** Both have unit tests and both DPs are well attested, but that harness power-cycles the real diffuser, so the run is a deliberate act rather than something to do in passing. The expectation once it runs is 23/23 |
| ❓ | **DP 104** (`kk`) is the last unidentified datapoint. It has not moved through an app walk, a remote walk, an LED toggle or a charger event; a firmware constant is the leading explanation. The `datapoints_recon` diagnostic sensor watches it, and gets deleted once it is named |
| ⏸️ | Whether the phone app has to keep working alongside Home Assistant ([ADR-004](docs/decisions.md#adr-004--pending--must-the-phone-app-keep-working)) |
| ✅ | **The repo's own redaction rule holds in the tree, and is enforced there** ([#20](https://github.com/luguina/arozen_ha_controller/issues/20)). One device id, in dossier §6.2; two other appliances' ids out of the dossier entirely; `tests/test_redaction_rule.py` fails the build on a regression instead of waiting for somebody to run the audit sweep. The identifiers stay in **git history**, deliberately — a force-push would clean `main` and would *not* clean the `refs/pull/*/head` that GitHub keeps for every PR, so it is the expensive half of a fix that does not fix the thing it is for ([ADR-007](docs/decisions.md#adr-007--do-not-rewrite-git-history-scrub-at-publication-on-a-fresh-repository) has the measurement, and the publication route that does work). The `local_key` has never been committed, on any ref — audited, clean |

The honest version, with evidence and everything still unknown, is
[docs/datapoints.md](docs/datapoints.md).

## Repository layout

```
custom_components/arozen_eon/     the integration. dp.py is the only file that knows a DP
                                  number, and the only place a map correction lands — it
                                  separates command datapoints from status ones, a
                                  distinction the first pass did not make and which cost
                                  it the power switch
  switch.py                       power (DP 2) and the LED (DP 7) — the written DPs
  binary_sensor.py                "Misting" (DP 103), "Charging" (DP 102) — device-driven
  select.py                       intensity (DP 3) and countdown (DP 4)
  sensor.py                       battery, timer remaining, poll and restore
                                  diagnostics, raw DPs
  coordinator.py                  the poll loop, poll health, and the intensity memory
                                  that survives the firmware's power-on reset
docs/
  why-not-the-official-integration.md   why this exists: the core source trace, the empty
                                        cloud schema, the topology, and the prior art
  datapoints.md                   the DP map, its evidence, and its open questions
  research/dossier.md             the recon record, including §6.7's correction
  hardware.md · decisions.md      the device itself; ADR-001…006
  captures/                       probe output and DP diffs (credentials redacted)
tools/                            dp_dump · dp_diff · dp_watch · dp_set · mq_listen —
                                  the recon loop, spelled out in tools/README.md.
                                  verify_restore.py is the odd one out: it drives the
                                  integration itself against the real device
tests/                            pytest. test_dp.py runs with no Home Assistant
                                  installed; the entity tests need the pinned core
```

## Scope

**In:** power on/off · scent intensity · countdown timer · scheduling from Home Assistant
automations.
**Out:** the Tuya cloud API as a runtime dependency · reflashing the WiFi module
(cloudcutter/OpenBeken) · emulating the physical remote.

## Working on it

Two rules carry most of the weight here, both learned by breaking them:

1. **`dp.py` is the only file that may contain a DP number.** A map correction then lands in
   exactly one place. It also separates *command* datapoints from *status* ones — the
   distinction the first pass did not make, which cost it the power switch entirely
   ([dossier §6.7](docs/research/dossier.md)).
2. **A claim about the device belongs in [`docs/datapoints.md`](docs/datapoints.md) with the
   evidence that established it.** "Toggled power in the app, DP 2 flipped" is evidence.
   "Probably intensity" is not, and should say so — the ❓ column exists to be used.

Design decisions are recorded as ADRs in [`docs/decisions.md`](docs/decisions.md). The recon
tools and their rules are in [`tools/README.md`](tools/README.md); `tests/test_dp.py` runs
against `dp.py` alone with no Home Assistant installed, which makes it the cheapest place to
pin a fact about the device.
