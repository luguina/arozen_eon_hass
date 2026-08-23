# Why this repository exists

The Arozen EON Pro 2 pairs to the **generic Tuya Smart app** over WiFi and works fine there.
Added to Home Assistant through the **official Tuya integration**, it produces **no entities
at all**.

That symptom is well understood, and it is *not* "Tuya doesn't know what this is".

## What the official integration does with a diffuser

Traced in Home Assistant core (`dev` branch, read 2026-08-10):

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

## The real cause is worse, and simpler

> ✅ **Confirmed and sharpened, 2026-08-21.** The device is registered as `xxj` as assumed,
> but cloud queries show its registered instruction set is **empty**: `functions: []`,
> `status: []` ([dossier §6.4](research/dossier.md#64-the-products-registered-cloud-schema-is-empty---the-real-no-entities-cause)).

It is not that the firmware uses non-standard DP codes that miss the three switches. **The OEM
declared no DPs at all.**

That closes off an entire class of solution — a narrower class than it first looks, and the
distinction is worth getting right. The official integration builds its entities *from* the
schema, so an empty one leaves it nothing to build and it fails outright. LocalTuya is not
stopped that early: LAN discovery finds the device, and its DP picker will list every datapoint
the device reports, current values and all. `tuya-local`'s cloud-assisted setup gets that far
too, and then needs a YAML that already names them — of which none is an Arozen. What none of
them can supply is **meaning**: which number is power and which is intensity is precisely what
the schema was supposed to say. Which is why **manual DP mapping is the only way in**. The
datapoints exist on the device regardless; the phone app works because its panel carries the
definitions client-side.

## The approach

```
Home Assistant  ──WiFi/LAN──▶  Arozen EON Pro 2
   3rd floor                    Tuya firmware, TCP 6668
```

That is the whole topology. **There is no ESP32 and no proxy** — see
[ADR-002](decisions.md#adr-002--no-esp32-the-device-is-already-on-the-network), which exists
specifically so nobody copies the bridge out of `sibling_ha_controller` from habit. This device
is already on the network the Home Assistant box is on; the range problem that dominated that
project does not exist here.

Control goes **direct to the device on the LAN**, encrypted with the `local_key`, with no cloud
in the runtime path
([ADR-001](decisions.md#adr-001--local-lan-control-the-tuya-cloud-is-the-fallback-not-the-plan)).
The cloud is touched exactly once, to fetch that key.

**The protocol was never the unknown.** Tuya's local protocol is understood and implemented in
several mature libraries. What was unknown is the **datapoint map** — which numbered DP is
power, which is intensity, which is the work/pause pair. That was an afternoon of turning one
control at a time and diffing ([datapoints.md](datapoints.md)), plus **two** further sittings to
undo what that afternoon got wrong: the nozzle DP read as the power switch, and — the more
instructive one — the power-on settings reset blamed on the power-*off* edge, which took a
session driven from the physical remote with the app closed to settle.

## Prior art worth reading before starting something similar

| | |
|---|---|
| [`make-all/tuya-local`](https://github.com/make-all/tuya-local) | Local control via YAML DP maps. Ships **12** aroma-diffuser configs — `asakuki_diffuser.yaml`, `calex_aromadiffuser.yaml`, `maxcio_aromadiffuser.yaml` and others. **None is an Arozen.** Its config flow can pull device ID, local key and IP from the cloud for you. **If your diffuser is not an Arozen, start here** — one of those twelve may fit outright |
| [`vineetchoudhary/tuya-local-key`](https://github.com/vineetchoudhary/tuya-local-key) | QR login against Tuya's device-sharing SDK — local keys **without** a Tuya IoT developer account, cloud project, Access ID or Secret. This removes the historic worst part of this job |
| [`jasonacox/tinytuya`](https://github.com/jasonacox/tinytuya) | The probe. `wizard` for keys, `scan` for discovery, live DP status — this is what dumps the datapoints, and what this integration talks to the device with |
| [`xZetsubou/hass-localtuya`](https://github.com/xZetsubou/hass-localtuya) | The maintained LocalTuya fork. Fallback if `tuya-local` cannot express something |
| [Tuya `xxj` instruction set](https://developer.tuya.com/en/docs/iot/f?id=K9gf46lj5p3q4) | The standard diffuser DP codes — the hypothesis this device was tested against, and failed |

## How it turned out

> ⚠️ **Corrected 2026-08-23.** This section read *"the standard `xxj` codes appear nowhere on
> this device; every meaningful DP is vendor-specific, most in the 100+ range"*. The first half
> is vacuous and the second is inverted. No measurement changed — the datapoint map has said the
> opposite since 2026-08-21 and nobody re-read it against this page.

The guess going in was **vendor-specific DPs in the 100+ range**: the usual Tuya convention for
functions outside a standard category, and the stated reason the standard `xxj` set was not
expected to fit
([datapoints.md](datapoints.md#the-hypothesis-tuyas-standard-xxj-instruction-set)).

The device does the reverse. **Every writable datapoint is low-numbered** — 2 power, 3 intensity,
4 countdown, 7 LED — and everything from 101 up is status, telemetry or a firmware constant: 101
battery, 102 charging, 103 nozzle, 104 still unidentified, 105 burst seconds, 106 pause seconds.
The controls sit exactly where a standard device's controls would sit, **and they are invisible
anyway, because nothing declares what they mean.** Conventional numbering buys nothing against an
empty schema, which is this whole page in one line.

And "the standard `xxj` codes appear nowhere" was never a finding. With `functions: []` the
device reports bare numeric ids and no codes at all, so there is nothing on it to compare against
the standard set — matching or otherwise. That sentence restates the empty schema; it says
nothing about the firmware.

The full map, its evidence, and its remaining unknowns are in [datapoints.md](datapoints.md); the
recon narrative, including both corrections it took, is in
[research/dossier.md](research/dossier.md).
