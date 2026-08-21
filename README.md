# arozen_ha_controller

Control an **Arozen EON Pro 2** cold-air scent diffuser from **Home Assistant**, locally
over WiFi, without the Tuya cloud.

> ⚠️ **This repository is private, and the thing that must never leave it is the Tuya
> `local_key`.**
>
> This is not the same privacy problem as a BLE MAC. The `local_key` is a **live credential**:
> it is what authenticates and encrypts local control of the device, and anyone with it plus
> LAN access can drive the diffuser. The device ID and the Tuya `uid` identify the unit and the
> account behind it.
>
> | Artefact | Where it comes from | Rule |
> |---|---|---|
> | `local_key` | QR login / Tuya IoT platform | **Never committed, in any file, ever** |
> | `device_id`, `uid` | same | Redact in captures; record once in the dossier if needed |
> | LAN IP, SSID | your network | Redact |
> | `devices.json`, `snapshot.json`, `tinytuya.json` | `tinytuya wizard` | **Gitignored — these contain local keys in plaintext** |
>
> `.gitignore` covers the tooling's default output filenames, but do not rely on that alone —
> the wizard will happily write a key into any path you point it at. Audit before publishing,
> because it is one command and the answer changes:
>
> ```sh
> git ls-files -z | xargs -0 grep -niE \
>   'local_key|localkey|"uid"|[0-9a-f]{16,22}|\b(10|192\.168|172\.(1[6-9]|2[0-9]|3[01]))(\.[0-9]{1,3}){2}\b'
> ```
>
> It reports **candidates for a human to look at**, not confirmed leaks. A false positive costs
> a glance; a false negative publishes a working credential to the device in your house.

## The problem

The diffuser pairs to the **generic Tuya Smart app** over WiFi and works fine there. Added to
Home Assistant through the official Tuya integration, it produces **no entities at all**.

That symptom is well understood and it is *not* "Tuya doesn't know what this is". Traced in
Home Assistant core (`dev` branch, read 2026-08-10):

| Where | What |
|---|---|
| `homeassistant/components/tuya/const.py:427` | `XXJ = "xxj"` — the diffuser category **is** defined, docstring `"""Diffuser` |
| `homeassistant/components/tuya/switch.py:869` | `DeviceCategory.XXJ` appears here, and **only** here |
| everywhere else | `fan.py`, `light.py`, `humidifier.py`, `select.py`, `number.py`, `sensor.py`, `binary_sensor.py` — **zero** references to `XXJ` |

So the entire official support for a Tuya diffuser is three switches:

```python
DeviceCategory.XXJ: (
    SwitchEntityDescription(key=DPCode.SWITCH,       translation_key="power"),
    SwitchEntityDescription(key=DPCode.SWITCH_SPRAY, translation_key="spray"),
    SwitchEntityDescription(key=DPCode.SWITCH_VOICE, translation_key="voice", ...),
)
```

No intensity. No timer. No schedule. And if the Arozen's firmware does not use those exact
three DP codes — plausible, because a cold-air nebuliser driven by work/pause intervals is not
the ultrasonic-humidifier shape the standard `xxj` set describes — then **none of the three
match and you get an empty device**. Which is what you get.

> ✅ **Confirmed and sharpened, 2026-08-21 — and the truth is stronger than the hypothesis.**
> The device is registered as `xxj` as assumed, but cloud queries show its registered
> instruction set is **empty**: `functions: []`, `status: []` (dossier §6.4). It is not that
> the firmware uses non-standard DP codes that miss the three switches; the OEM declared **no
> DPs at all**. Schema-driven integrations — the official one, but also `tuya-local`'s
> cloud-assisted setup and LocalTuya's auto-discovery — all read that same empty schema, which
> is why manual DP mapping is the only way in. The DPs exist on the device regardless; the app
> works because its panel carries the definitions client-side.

## The approach

```
Home Assistant  ──WiFi/LAN──▶  Arozen EON Pro 2
   3rd floor                    Tuya firmware, TCP 6668
```

That is the whole topology. **There is no ESP32 and no proxy** — see
[ADR-002](docs/decisions.md#adr-002--no-esp32-the-device-is-already-on-the-network), which
exists specifically so nobody copies the bridge out of `sibling_ha_controller` from habit. This
device is already on the network the Home Assistant box is on; the range problem that dominated
that project does not exist here.

Control goes **direct to the device on the LAN**, encrypted with the `local_key`, with no cloud
in the runtime path ([ADR-001](docs/decisions.md#adr-001--local-lan-control-the-tuya-cloud-is-the-fallback-not-the-plan)).
The cloud is touched exactly once, to fetch that key.

**The protocol is not the unknown here.** Tuya's local protocol is understood and implemented
in several mature libraries. What is unknown is the **datapoint map** — which numbered DP is
power, which is intensity, which is the work/pause pair. That is an afternoon of turning one
control at a time and diffing, not a reverse-engineering project.

## Current phase

**Working integration; one behavioural question left.**

| | |
|---|---|
| ✅ Settled | Mains-powered, so it does not sleep and local polling is viable ([ADR-001](docs/decisions.md#adr-001--local-lan-control-the-tuya-cloud-is-the-fallback-not-the-plan)) |
| ✅ Settled | Generic Tuya Smart app, so it is a standard Tuya registration and QR login will work — and did, 2026-08-21 |
| ✅ Settled | No ESP32 ([ADR-002](docs/decisions.md#adr-002--no-esp32-the-device-is-already-on-the-network)) |
| ✅ Found 2026-08-21 | Category `xxj`, product `uh3xooop1btksbtk`, `local_key` retrieved. **The "no entities" root cause: the product's registered cloud schema is empty** ([dossier §6.4](docs/research/dossier.md#64-the-products-registered-cloud-schema-is-empty----the-real-no-entities-cause)) |
| ✅ Decided 2026-08-21 | The deliverable is **our own integration** — `custom_components/arozen_eon/` ([ADR-003](docs/decisions.md#adr-003--defer-the-deliverable-until-the-datapoint-dump-exists), resolved by the project owner) |
| ✅ Resolved 2026-08-21 | **Local reachability.** The unit had silently dropped off; re-pairing put it on the main LAN at protocol 3.5, and it answers local reads and writes ([dossier §6.3](docs/research/dossier.md)) |
| ✅ Mapped 2026-08-21 | **The datapoints**, from a control walk plus write tests — power, intensity, timer, nozzle state, battery ([datapoints.md](docs/datapoints.md)). Corrected the same evening: DP 103 is the nozzle, not the switch ([dossier §6.7](docs/research/dossier.md)) |
| ❓ Open | **What the app's power-off sends.** A `DP 2 = false` write stops the device but resets intensity to L1; the app's own off preserves it. Until that is known, switching off from Home Assistant loses the intensity setting |
| ❓ Open | DP 102 (`zzcd`/`wcd`/`cdwc`) and DP 104 (`kk`) remain unidentified |
| ⏸️ Pending the owner | Whether the phone app has to keep working ([ADR-004](docs/decisions.md#adr-004--pending--must-the-phone-app-keep-working)) |

[`dp.py`](custom_components/arozen_eon/dp.py) is the only file that knows a DP number, and it
now separates **command** datapoints from **status** ones — a distinction the first pass did
not make, which cost it the power switch. Platforms backed by unmapped functions still create
no entities. The recon loop is `dp_dump` → `dp_watch` → `dp_set` → `dp_diff`, spelled out in
[tools/README.md](tools/README.md#the-recon-loop-in-four-commands).

## Scope

**In:** power on/off · scent intensity · work/pause interval timing · countdown timer ·
scheduling from Home Assistant.
**Out:** the Tuya cloud API as a runtime dependency · reflashing the WiFi module
(cloudcutter/OpenBeken) · the physical remote.

## Repository layout

```
custom_components/
  arozen_eon/           the integration (ADR-003, resolved 2026-08-21), built on
                        sibling_beacon's architecture. dp.py is the only file that knows a
                        DP number and the only place a map correction lands.
    switch.py           power — DP 2, the command DP
    binary_sensor.py    "Misting" — DP 103, the nozzle state the device drives itself
    select.py           intensity (DP 3) and countdown (DP 4)
    sensor.py           battery, timer remaining, poll diagnostics, raw-DP recon readout
docs/
  datapoints.md         the DP map — filled in 2026-08-21, with its open questions kept
                        explicit rather than rounded up to answers
  research/dossier.md   recon record: what is inferred, what is verified, the evidence for
                        the "no entities" diagnosis, and §6.7's correction
  hardware.md           the device, its power and radio, and what to measure
  decisions.md          ADR-001…005
  captures/             probe output and DP diffs (credentials redacted)
tools/
  dp_dump.py            read all DPs as a stable, diffable table
  dp_diff.py            diff two dumps, show only what moved
  dp_watch.py           poll on an interval, print one line per DP that moves
  dp_set.py             write a single DP (the explicit mutating exception)
  README.md             usage and the redaction discipline for probe output
tests/                  pytest suite — test_dp.py runs with no HA installed;
                        test_entities.py needs the .venv-test venv (Python 3.14, HA pinned
                        in requirements_test.txt)
```

## Prior art worth reading before starting

| | |
|---|---|
| [`make-all/tuya-local`](https://github.com/make-all/tuya-local) | Local control via YAML DP maps. Ships **12** aroma-diffuser configs — `asakuki_diffuser.yaml`, `calex_aromadiffuser.yaml`, `maxcio_aromadiffuser.yaml` and others. **None is an Arozen.** Config flow can pull device ID, local key and IP from the cloud for you. |
| [`vineetchoudhary/tuya-local-key`](https://github.com/vineetchoudhary/tuya-local-key) | QR login against Tuya's device-sharing SDK — local keys **without** a Tuya IoT developer account, cloud project, Access ID or Secret. This removes the historic worst part of this job. |
| [`jasonacox/tinytuya`](https://github.com/jasonacox/tinytuya) | The probe. `wizard` for keys, `scan` for discovery, and live DP status — this is what dumps the datapoints. |
| [`xZetsubou/hass-localtuya`](https://github.com/xZetsubou/hass-localtuya) | The maintained LocalTuya fork. Fallback if `tuya-local` cannot express something. |
| [Tuya `xxj` instruction set](https://developer.tuya.com/en/docs/iot/f?id=K9gf46lj5p3q4) | The standard diffuser DP codes — the hypothesis to test the dump against. |

## Project history

- **2026-08-21 — first contact.** `tinytuya scan` found the device on the LAN (protocol 3.5,
  product ID `jidyk1ybp0dqlteg`; the LAN's other Tuya device is a documented smart-plug
  product, which is why that one is presumed to be the diffuser — dossier §6.1). The "no
  entities" hypothesis is still untested against the category, which the broadcast does not
  carry. Same day: the project owner resolved ADR-003 to **our own integration**, so
  `custom_components/arozen_eon/` was scaffolded against the sibling project's architecture with the DP
  map isolated in `dp.py`, and the recon tools (`dp_dump.py`, `dp_diff.py`) were written.
  Next: QR login for the `local_key`, then the DP walk in [`datapoints.md`](docs/datapoints.md)
  §Method.
