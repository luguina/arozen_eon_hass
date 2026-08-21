# Arozen EON Pro 2 for Home Assistant

[![CI](https://github.com/luguina/arozen_ha_controller/actions/workflows/ci.yml/badge.svg)](https://github.com/luguina/arozen_ha_controller/actions/workflows/ci.yml)
[![Validate](https://github.com/luguina/arozen_ha_controller/actions/workflows/validate.yml/badge.svg)](https://github.com/luguina/arozen_ha_controller/actions/workflows/validate.yml)

A Home Assistant custom integration for the **Arozen EON Pro 2** cold-air scent diffuser.
Power, intensity, timer and battery — **locally over your LAN, with no Tuya cloud in the
runtime path.**

It exists because the **official Tuya integration gives this device zero entities**: the OEM
registered an empty datapoint schema, so every schema-driven integration reads nothing and
creates nothing. The datapoints are there; they just had to be found by hand.
[The full explanation, with the core source trace.](docs/why-not-the-official-integration.md)

---

## What you get

Eight entities, on one device:

| Entity | What it is |
|---|---|
| `switch.arozen_eon_pro_2` | **Power.** On means the duty cycle is running — not that it is misting this second |
| `binary_sensor.arozen_eon_pro_2_misting` | **Misting.** Whether the nozzle is open *right now*. On for 30 s, then off for the interval |
| `select.arozen_eon_pro_2_intensity` | **Intensity**, `L1 · every 1 min` … `L6 · every 40 min` |
| `select.arozen_eon_pro_2_timer` | **Timer** — `Continuous`, `1 hour`, `4 hours`, `8 hours` |
| `sensor.arozen_eon_pro_2_battery` | **Battery %** |
| `sensor.arozen_eon_pro_2_timer_remaining` | **Minutes left** on the auto-off countdown |
| `sensor.arozen_eon_pro_2_failed_polls` | Diagnostic: polls that failed, with the last error |
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

| Field | Where it comes from |
|---|---|
| **IP address** | Your router's client list, or `python -m tinytuya scan`. Give the diffuser a DHCP reservation — the config entry stores an address, not a name |
| **Device ID** | The QR login or `tinytuya wizard` |
| **Local key** | Same. ⚠️ This is a **live credential** — see [below](#about-the-local_key) |
| **Protocol version** | `3.5` for this unit. `tinytuya scan` reports it |

Two ways to get the device ID and local key:

- **[`tuya-local-key`](https://github.com/vineetchoudhary/tuya-local-key)** — QR login against
  Tuya's device-sharing SDK, and **no Tuya IoT developer account needed**, which removes what
  used to be the worst part of this job. Runs as a CLI, a Docker container or a Home Assistant
  add-on. QR codes expire in a minute or two, so have the phone open before you start.
- **`tinytuya wizard`** — the classic route, and the one that *does* want a Tuya IoT platform
  project with an Access ID and Secret. The trial expires and needs periodic renewal.

Detail and gotchas: [datapoints.md §Method](docs/datapoints.md#1-get-the-credentials).

## Before you automate it

This device has four behaviours that will look like bugs if you meet them without warning.
None of them is the integration inventing something; all four are the firmware.

**1. L1 is the *strongest* setting and L6 the weakest.** The level number counts the *pause*,
not the output — L1 mists every minute, L6 every forty. The entity labels say so
(`L4 · every 10 min`) precisely so nobody has to remember it.

**2. Turning it off resets intensity to L1 and the timer to 4 hours.** The device does this
itself on power-off; it is not something the integration can decline to do. If your automation
turns the diffuser off, it must set the intensity again *after* turning it back on:

```yaml
automation:
  - alias: "Diffuser: gentle overnight"
    triggers:
      - trigger: time
        at: "22:00:00"
    actions:
      - action: switch.turn_on
        target: { entity_id: switch.arozen_eon_pro_2 }
      # After the switch, never before: the previous power-off reset this to L1.
      - action: select.select_option
        target: { entity_id: select.arozen_eon_pro_2_intensity }
        data: { option: "L4 · every 10 min" }
      - action: select.select_option
        target: { entity_id: select.arozen_eon_pro_2_timer }
        data: { option: "8 hours" }
```

*(Why the phone app appears not to lose the setting, and what to do about it, is the open
question in [Status](#status).)*

**3. Turning it on arms a 240-minute countdown by itself.** `sensor.…_timer_remaining` will
read `240` after a switch-on even though the Timer select says `Continuous`. That is the
firmware's own default auto-off. Whether it actually powers down when the count reaches zero
has **not** been observed — do not build an automation that depends on either answer yet.

**4. The Misting sensor reads `off` whenever the power is off — deliberately.** The device
*freezes* that datapoint when it stops: switch it off mid-burst and it keeps reporting "nozzle
open" indefinitely. The integration refuses to read a frozen register as a live one. The raw
value is still visible on the diagnostic datapoints sensor if you want it.

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
glance; a false negative publishes a working credential to the device in your house. The
capture-specific rules are in [docs/captures/README.md](docs/captures/README.md#redaction-rule).

## Status

**Working, in daily use, with one open question and three unidentified datapoints.**

| | |
|---|---|
| ✅ | Power, intensity, timer, battery, nozzle state — all mapped, write-verified against the device, and covered by tests |
| ✅ | Config flow, options flow and all eight entities verified end to end against a real Home Assistant instance and the real diffuser |
| ❓ | **What the phone app's power-off does that ours does not.** Ours resets intensity to L1; the app's appears not to. Until this is settled, gotcha #2 above stands. [#5](https://github.com/luguina/arozen_ha_controller/issues/5) is the experiment that decides it |
| ❓ | **DP 102, DP 104 and DP 7** are unidentified. The `datapoints_recon` diagnostic sensor exists to watch them, and gets deleted once they are named |
| ⏸️ | Whether the phone app has to keep working alongside Home Assistant ([ADR-004](docs/decisions.md#adr-004--pending--must-the-phone-app-keep-working)) |

The honest version, with evidence and everything still unknown, is
[docs/datapoints.md](docs/datapoints.md).

## Repository layout

```
custom_components/arozen_eon/     the integration. dp.py is the only file that knows a DP
                                  number, and the only place a map correction lands — it
                                  separates command datapoints from status ones, a
                                  distinction the first pass did not make and which cost
                                  it the power switch
  switch.py                       power — DP 2, the command DP
  binary_sensor.py                "Misting" — DP 103, the nozzle state the device drives
  select.py                       intensity (DP 3) and countdown (DP 4)
  sensor.py                       battery, timer remaining, poll diagnostics, raw DPs
docs/
  why-not-the-official-integration.md   why this exists: the core source trace, the empty
                                        cloud schema, the topology, and the prior art
  datapoints.md                   the DP map, its evidence, and its open questions
  research/dossier.md             the recon record, including §6.7's correction
  hardware.md · decisions.md      the device itself; ADR-001…005
  captures/                       probe output and DP diffs (credentials redacted)
tools/                            dp_dump · dp_diff · dp_watch · dp_set · mq_listen —
                                  the recon loop, spelled out in tools/README.md
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
