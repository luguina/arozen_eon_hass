# Arozen EON Pro 2 for Home Assistant

[![CI](https://github.com/luguina/arozen_eon_hass/actions/workflows/ci.yml/badge.svg)](https://github.com/luguina/arozen_eon_hass/actions/workflows/ci.yml)
[![Validate](https://github.com/luguina/arozen_eon_hass/actions/workflows/validate.yml/badge.svg)](https://github.com/luguina/arozen_eon_hass/actions/workflows/validate.yml)

A Home Assistant custom integration for the **Arozen EON Pro 2** cold-air scent diffuser.
Power, intensity, timer, battery and charging — **locally over your LAN, with no Tuya cloud
in the runtime path.**

It exists because the **official Tuya integration gives this device zero entities**: the OEM
registered an empty datapoint schema, so every schema-driven integration reads nothing and
creates nothing. The datapoints are there; they just had to be found by hand.
[The full explanation, with the core source trace.](docs/why-not-the-official-integration.md)

---

## What you get

Ten entities on one device, and an eleventh that ships switched off:

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
| `sensor.arozen_eon_pro_2_datapoints_recon` | Diagnostic: the raw datapoints. **Disabled by default** — recon scaffolding, see below |

The last row is the exception and is off on a fresh install: it reports a *count* of Tuya
datapoints with the raw payload in its attributes, which is the instrument that mapped this
device and is of no use once the map exists. It is still the only live view of the raw
datapoints, so it is disabled rather than removed — enable it under **Settings → Devices &
services → Arozen EON Pro 2 → the entity → ⚙ → Enabled** and Home Assistant reloads the
integration itself. (A [diagnostics download](#when-it-misbehaves) carries the same
datapoints as a one-off snapshot, without enabling anything.)

The device diffuses in **bursts**: 30 seconds of mist, then a pause. The intensity level sets
the pause, which is why the entity is labelled the way it is.

## Install

**Home Assistant 2026.8.1** is what this is developed and tested against. It is not tested
against anything older.

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/luguina/arozen_eon_hass`, category **Integration**
3. Install **Arozen EON Pro 2 Diffuser**, then restart Home Assistant

### Manually

1. Download **Source code (zip)** or **(tar.gz)** from the
   [latest release](https://github.com/luguina/arozen_eon_hass/releases/latest) — a release
   rather than the branch tip, for the same reason HACS resolves to the tag: the tip is whatever
   landed most recently and has not necessarily been through an install.
2. Unpack it and copy the **`custom_components/arozen_eon/` folder** out of the archive into your
   Home Assistant `config/custom_components/`, so that
   `config/custom_components/arozen_eon/manifest.json` exists. Sixteen files land, including a
   `translations/` directory; nothing else in the archive is needed at runtime.
3. **Settings → System → ⋮ → Restart Home Assistant.** Restarting Home Assistant, not the host.

Then set it up below — the integration does not appear in **Add Integration** until the restart
has finished.

## Set it up

You are collecting **four values**. Three come from one tool; the fourth you can guess correctly
on the first try. The form at **Settings → Devices & Services → Add Integration → Arozen EON Pro
2 Diffuser** proves all four before it accepts them — it opens a real connection and reads
status, so a wrong key or version fails there rather than silently later.

| Field | Looks like | Where it comes from |
|---|---|---|
| **IP address** | `192.168.x.x` — where the diffuser sits on your LAN | Steps 2–3 |
| **Device ID** | 22 characters starting `bf` — its permanent identity in Tuya's world | Steps 2–3 |
| **Local key** | 16 characters. ⚠️ A **live credential**, not an identifier — anyone holding it, with access to your LAN, can drive the diffuser. Password manager, nowhere else | Steps 2–3 |
| **Protocol version** | `3.3`, `3.4` or `3.5` — **`3.5` for this unit**, and the default the form offers | Step 4 |

**None of this needs Python** on Home Assistant OS or Supervised. The one command-line route is
kept at the end, as a fallback.

### Why the local key is the hard part

**It is hard on purpose.** The diffuser is sold as a cloud appliance: you pair it to a Tuya
account with the Smart Life app, and from then on the app talks to Tuya's servers and Tuya's
servers talk to the device. The `local_key` is what lets you skip that round trip and address the
device directly on your own network — and nothing in the product wants you to have it. It is
**not printed on the device**, **not shown anywhere in the app**, and **not readable from the
device itself**. It is minted when the device is paired, and it only ever leaves Tuya through
Tuya's own APIs.

So every route below is the same manoeuvre: authenticate as yourself, ask Tuya which devices are
on your account, and read the key out of the reply. **The diffuser has to be paired in the Smart
Life / Tuya app first** — if it is not in the app, there is nothing for any tool to read.

### Step 1 — Find your Smart Life user code

The login handle the tool needs, and nothing tells you it exists.

In the **Smart Life app**: **Me** tab → **⚙️** top right → **Account and Security** → **User
Code**, at the bottom of that screen.

### Step 2 — Run `tuya-local-key`

[`tuya-local-key`](https://github.com/vineetchoudhary/tuya-local-key) logs in by QR code against
Tuya's device-sharing SDK — the same mechanism Home Assistant's own Tuya integration uses — and
needs **no Tuya IoT developer account**, which removes what used to be the worst part of this
job.

**As a Home Assistant add-on**, on HA OS or Supervised. No terminal at all:

1. **Settings → Add-ons → Add-on Store** (newer Home Assistant labels these **Apps → App Store**)
2. Top-right **⋮ → Repositories**
3. Add `https://github.com/vineetchoudhary/tuya-local-key`, then **Close**
4. Install **Tuya Local Key** from the store, **Start** it, and **Open Web UI**

**As a container**, on HA Container or Core, or on any machine with Docker — then open
`http://localhost:8000` for the same page:

```sh
docker run -d --name tuya-local-key -p 8000:8000 \
  -v tuya-session:/data ghcr.io/vineetchoudhary/tuya-local-key:latest
```

### Step 3 — Scan the QR code, and read off three of the four values

Enter your user code. A QR code appears.

**Read this before you generate it: the QR expires in a minute or two.** Have the phone unlocked
and the Smart Life app already open, and know where you are going — in the app, **+** (top right)
→ **Scan** → point it at the code → **Confirm login**. If the phone will not focus on the screen,
the tool also writes the code out as a PNG you can open larger.

The page then lists every device on the account. Find the diffuser and copy its **device ID**,
**local key** and **IP address**.

> **Check what you copied.** The device ID is 22 characters beginning `bf`; the local key is 16.
> The tool prints a `uuid` next to the device ID that looks much like it — if a value comes out
> the wrong length, that is usually which column it came from.

### Step 4 — The protocol version: try it, don't measure it

Nothing to install for this one. The form offers `3.5`, which is what this unit speaks.

**A wrong protocol version does not present as a wrong protocol version.** The connection opens,
the reply comes back undecryptable, and the form reports it exactly the way it reports a bad key.
So if setup rejects credentials you are confident in, drop to `3.4`, then `3.3`, *before* you
start doubting the key. `3.3` and `3.4` stay selectable because a firmware update can move it.

> **A rejected attempt hands your answers back**, version included, so iterating costs one
> dropdown change rather than a full re-entry.

*If you would rather measure than guess:* `python -m tinytuya scan` broadcasts on the LAN and
reports every Tuya device that answers, with its address **and the protocol version that device
is speaking**. It is the only step here that wants Python, and it saves you two clicks.

### Step 5 — Close the Smart Life app, then fill the form

During recon, local *writes* failed intermittently while the app was open and landed reliably
once it was closed. This form only *reads*, so it may well survive an open app — but closing it
costs nothing, and a contended connection here would look like bad credentials rather than like
contention, which is the expensive kind of wrong turn.

Then **Settings → Devices & Services → Add Integration → Arozen EON Pro 2 Diffuser**, paste the
four values, and submit. It validates against the real device, so success here means it genuinely
works.

### Step 6 — Three minutes that save you a bad evening

1. **Give the diffuser a DHCP reservation** in your router. The config entry stores an address,
   not a name, and a lease change is a silent break
2. **Put the `local_key` in your password manager**, and nowhere else
3. **Clean up the tool.** It caches your login, so anyone who reaches its Web UI can read every
   local key on the account. Log out, or uninstall the add-on — you needed it once. For the
   container: `docker rm -f tuya-local-key && docker volume rm tuya-session`

### If the QR route fails — `tinytuya wizard`

The classic route, and heavier:

```sh
pip install tinytuya
python -m tinytuya wizard
```

This one *does* want a **Tuya IoT Platform** project with an Access ID and Secret, and inside that
project you must also "Link Tuya App Account" so the project can see devices you paired in the
app. The trial expires and needs periodic renewal — that lapsing is the usual reason a setup that
worked once cannot be reproduced six months later. Note where it puts its output: `devices.json`,
`tinytuya.json` and `snapshot.json`, in the working directory, **each containing live keys in
plaintext**. Delete them when you are done.

### Re-pairing the diffuser invalidates the key

Removing the device from the app and adding it back **mints a new `local_key`**. The device ID
survives; the key does not. Home Assistant will then fail every poll, with the reason on
`sensor.…_failed_polls`.

**After an hour of silence a card appears in Settings → System → Repairs** (#49) and points you
back here. It deliberately does *not* claim the key is at fault: on this protocol a key that no
longer decrypts and a diffuser that is simply unplugged produce the identical error payload, so
the card names both causes and leaves you to settle which
([ADR-008](docs/decisions.md#adr-008--never-assert-a-cause-the-transport-cannot-distinguish)).
It clears itself the moment one poll succeeds. An hour is deliberately unhurried — a router
reboot should not put a card on your screen, and a card you learn to ignore is worse than none.

The fix is **Settings → Devices & Services → Arozen EON Pro 2 → ⋮ → Reconfigure**, which takes a
new IP address, local key and protocol version and tries them against the device before saving
anything. The entry keeps its identity, so your automations and entity ids survive — which is the
whole reason it is not "delete it and add it again". The device ID is shown but fixed: a different
device ID is a different device, not a reconfigured one.

That the key can be replaced at all is also the remedy if you ever leak one, which is worth
knowing before you need it.

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
either. The integration does (#14): it remembers the level from ordinary polling and writes it
back the moment it sees the device switched on. Immediately when Home Assistant is what turned
it on, so `switch.turn_on` returns with the level already right; within one poll interval when
the remote or the app did, so expect a few seconds at L1 first.
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
value is still visible on the diagnostic datapoints sensor if you want it — that one ships
disabled, see [What you get](#what-you-get).

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

## When it misbehaves

Every failure here looks the same from the dashboard: the entities go `unavailable`. A wrong
local key, a wrong protocol version and a diffuser that has fallen asleep are three different
problems with one symptom, so the state worth having is the state you cannot see — which
protocol version is actually in use, how many polls have failed in a row, and what tinytuya
answered with. A silence lasting more than an hour also raises a Repairs card naming the two
likeliest causes, which is the same restraint expressed as a notification rather than a
paragraph — see [Re-pairing the diffuser invalidates the
key](#re-pairing-the-diffuser-invalidates-the-key).

**Settings → Devices & Services → Arozen EON Pro 2 → ⋮ → Download diagnostics.** A JSON file
with the poll health, the intensity memory, the raw datapoints and the connection settings.
Attach it to an issue as it comes.

**The `local_key`, the device ID and the LAN address are taken out before the file exists** —
including out of the error strings, which is the half that is easy to miss: the transport
prefixes every failure with the address it was talking to, so the most useful field in the
dump is also the one carrying a LAN address in free text where nothing matching on key names
will find it. `tests/test_diagnostics.py` asserts on the **absence of those values** rather
than on the shape of the file, so a rewrite that moves every key around still fails if a
credential moves with them.

The protocol version and the poll interval are deliberately left in the clear. They are the
two settings a support conversation actually turns on, and a dump that redacts everything is a
file with nothing in it.

## Status

**Working, in daily use, with one unidentified datapoint left.**

| | |
|---|---|
| ✅ | Power, intensity, timer, battery, nozzle state, charging, LED — all mapped, write-verified against the device where writing is meaningful, and covered by tests |
| ✅ | Config flow, options flow and all nine entities *as they stood on 2026-08-21* verified end to end against a real Home Assistant instance and the real diffuser |
| ✅ | **What the phone app's power-off does that ours does not: nothing.** #5's remote walk settled it and overturned the premise — the reset belongs to the power-**on** edge, and the app loses intensity exactly like we do. Gotcha #2 above is the corrected version |
| ✅ | **Intensity survives a power cycle** (#14) — remembered from ordinary polling, written back on the on edge from any source, and never taught the firmware's default *by* the reading that carries the reset — which is what would otherwise restore L1 for ever. A power-on that reports some *other* level means a human got there first, and that one does teach. The countdown is armed on the same edge and is deliberately left alone ([ADR-006](docs/decisions.md#adr-006--correct-the-power-on-intensity-reset-and-only-that-one)) |
| ✅ | **The restore is verified on the real diffuser** (2026-08-21), from both directions: Home Assistant's own switch, where L4 was back before the turn-on call returned, and the **physical remote**, where it came back on the following poll. The guard holds too — switch on with the remote and press intensity, and the level you chose survives untouched. Fifteen checks, two restores, no failures. The restore *counter* is what proves the firmware did reset it, because a restore only fires when the device reports L1 on the on edge |
| ✅ | The **entity wiring** is verified too, in a throwaway Home Assistant driven over its own REST API: the config flow validates and creates the entry, exactly the entities that are enabled by default appear and nothing beyond them, and after `switch.turn_off` / `switch.turn_on` the intensity select still reads `L4 · every 10 min` with the restores sensor at 1 and `remembered_level: L4`. Run twice, and the expected count differs between them because the *default* moved rather than the entity set: **23/23 on 2026-08-22 with eleven** enabled, against the working tree, and **23/23 on 2026-08-28 with ten**, the recon sensor having become disabled-by-default in between (#51). The harness reads `/api/states`, so a disabled entity is absent rather than present-and-off, which is why the number is the assertion. The second run is also the first against the **delivered file set** (16 files) rather than the working tree — the mode #63 added, and the first time this harness tested what a user receives instead of what a developer has |
| ✅ | **DP 102 is charging status** (`zzcd`/`wcd`/`cdwc` — 正在充电 / 未充电 / 充电完成) and is now the tenth entity (#16). It was never reachable by pressing buttons — the stimulus is a cable, not a control — which is why an entire remote walk went past it. `cdwc` was confirmed on the device 2026-08-22, on the cable at 100 % |
| ✅ | **DP 7 is the frontal LED, and it is a command DP** (#15) — write-verified 2026-08-22, both directions, each holding across five reads over 30 seconds. That duration is the test, not the acceptance: DP 103 accepts writes and then reverts them at the end of a burst, so 30 s spans the window in which a revert would have shown. Had it snapped back this would have shipped as a read-only sensor. The device also moves DP 7 by itself on some power cycles, and the integration reports that rather than fighting it — no memory, no restore, deliberately unlike intensity ([ADR-006](docs/decisions.md#adr-006--correct-the-power-on-intensity-reset-and-only-that-one)) |
| ✅ | **The charging sensor and the LED switch have now been through `tools/verify_ha.py`** — 23/23 on 2026-08-22, the first run covering either. Until then both rested on unit tests and well-attested DPs alone; that gap is closed, and the harness confirms nothing beyond the entity set it names appears. It power-cycles the real diffuser, so a re-run stays a deliberate act rather than something to do in passing |
| ✅ | **A rotated local key no longer fails silently** (#49). Re-pairing in the app mints a new key, the old one stops decrypting immediately, and until now the entire user-facing consequence was `unavailable` entities and a climbing counter — the remedy existed and nothing pointed at it. An hour of silence now raises a repair card that names both plausible causes and asserts neither, because on this transport a dead key and a dead battery are the same error payload; the conventional `ConfigEntryAuthFailed` would have told users with an unplugged diffuser that their credentials were wrong ([ADR-008](docs/decisions.md#adr-008--never-assert-a-cause-the-transport-cannot-distinguish)). The threshold is wall clock rather than a count of polls, because the poll interval is a user setting spanning 10 s to 3600 s |
| ✅ | **The recon sensor stops arriving switched on** (#51). `Datapoints (recon)` reports a count of Tuya datapoints with the raw payload in its attributes — the instrument that mapped this device, and noise on the device page of somebody who bought a diffuser. It is now registered and *disabled*, not removed: it is still the only live view of the raw datapoints, and the recon workflow it exists for has nowhere else to run. Disabling beat an options-flow flag defaulting off for a reason that is easy to miss — `entity_registry_enabled_default` is read only when an entity is registered for the **first** time, so the change is inert on every install that already has the entity, while a default-off option would have reached back and switched it off on the one install where DP 104 is actually being watched. **Both halves are now observed** (2026-08-28). A fresh install shows ten entities and not the eleventh — `tools/verify_ha.py`, 23/23 against the delivered file set. And the inertness is measured rather than reasoned: the production install, whose registry predates this change, came through a HACS upgrade to v0.1.0 with `datapoints_recon` **still enabled** and every entity id unchanged. That is what `entity_registry_enabled_default` being read exactly once predicts, and it is the install a default-off option would have reached back and broken |
| ✅ | **Entity names, icons and error messages are out of Python** (#50). Ten names moved to `strings.json` behind `_attr_translation_key`, eight static icons to `icons.json`, and the four `HomeAssistantError` raises to an `exceptions:` block with placeholders — which also removed two English words that were being interpolated *into* user-facing text: the selects' `_label` ("intensity", "timer") and the switches' `'on' if value else 'off'`. Both are now the entity id, which needs no translating and says more. Nothing here changes an entity id: the display name is what Home Assistant slugifies on first registration, and `tests/test_translated_names.py` drives Home Assistant's own `Entity.name` against the real translation file and gets the same strings back. **Observed from both directions on 2026-08-28.** A registry built that day from `strings.json` produced the same ten entity ids as one built on 22 August from `_attr_name` (`tools/verify_ha.py`, delivered file set), and the production install upgraded from the older build to v0.1.0 with an empty diff across `entity_id` and `disabled_by`. Two registries, two name sources, identical ids |
| ✅ | **There is a branch point for the day `entry.data` changes shape** (#53). `async_migrate_entry` exists, treats version 1 as current, and **refuses** any version it has no branch for rather than waving it through — a blanket `return True` is the original failure wearing the fix's clothes, because Home Assistant would then carry on into `async_setup_entry`, which reads four keys straight out of `entry.data`. It cannot run today by construction: Home Assistant compares the stamped version against the flow's and returns success without ever loading the component when they match, so no test of the handler alone could tell a working one from a broken one. What makes the rule bite is a tripwire in `tests/test_setup_entry.py` that fails the build the moment `VERSION` or `MINOR_VERSION` moves — the one moment the branch can still be written before somebody's entry stops loading. `MINOR_VERSION` is declared alongside rather than inherited, because the choice between the two levers is the whole rule and it reads badly next to one of them. **Both branches were run against a real Home Assistant** (2026.8.1, delivered file set, no device): an entry stamped `1.0` went through the handler and on to register every entity **and came off disk stamped `1.1`**; one stamped `0.1` was refused, with no platform forwarded, no entity registered and its stamp left alone, because a migration that did not happen must not leave a record saying it did. The stamping is the half that is easy to miss — Home Assistant re-reads the numbers off disk on every start, so a branch answering yes without moving them migrates the same entry forever; it is forward-only, since an entry stamped *ahead* of the build has been through a newer release and come back down, which is the case `MINOR_VERSION` exists to tolerate. That run also settled what the handler's log line is for — Home Assistant writes nothing of its own when a migration is refused, so that one line is the entire diagnostic |
| ❓ | **DP 104** (`kk`) is the last unidentified datapoint. It has not moved through an app walk, a remote walk, an LED toggle or a charger event; a firmware constant is the leading explanation. The `datapoints_recon` diagnostic sensor watches it. It no longer gets deleted once the DP is named (#51): watching a *count* of datapoints is a job with no end date, and the entity now ships disabled instead |
| ⏸️ | Whether the phone app has to keep working alongside Home Assistant ([ADR-004](docs/decisions.md#adr-004--pending--must-the-phone-app-keep-working)) |
| ✅ | **The repo's own redaction rule holds in the tree, and is enforced there** (#20). One device id, in dossier §6.2; two other appliances' ids out of the dossier entirely; `tests/test_redaction_rule.py` fails the build on a regression instead of waiting for somebody to run the audit sweep. The identifiers stay in the **git history of the private archive**, deliberately — a force-push there would clean `main` and would *not* clean the `refs/pull/*/head` that GitHub keeps for every PR, so it is the expensive half of a fix that does not fix the thing it is for ([ADR-007](docs/decisions.md#adr-007--do-not-rewrite-git-history-scrub-at-publication-on-a-fresh-repository) has the measurement, and the publication route that does work). The `local_key` has never been committed, on any ref — audited, clean |
| ✅ | **The diagnostics dump is the one artefact designed to leave the machine, and it leaves without the credential** (#46). Redacted twice, because there are two ways in: by key name out of the config entry, and by substring out of the error strings, where `device.py`'s `f"{host}: … failed"` puts a LAN address that no key-based redactor can see. The tests assert the values are absent from the serialised dump, not that the output has a particular shape. ✅ **Confirmed against a real dump on 2026-08-28**: the file a user actually downloads carries three `**REDACTED**` placeholders and none of the device id, the local key or the LAN address, with `protocol_version` deliberately left in the clear because it is one of the two settings a support conversation turns on |
| ✅ | **It is published, and the primary install path has been walked** (#30, #63). `arozen_eon_hass` is a public repository *generated* from a scrubbed history rather than a mirror of the development archive, which stays private ([ADR-007](docs/decisions.md#adr-007--do-not-rewrite-git-history-scrub-at-publication-on-a-fresh-repository)). On 2026-08-28 the README's own route was followed end to end for the first time: HACS resolved the custom repository to the **v0.1.0 release tag** rather than the branch tip — the failure this run existed to catch — and delivered all sixteen files, including `diagnostics.py` and `icons.json`, which no real box had ever seen. The install it replaced was a hand copy six days and one refactor older, and it survived: no repair card, an entity registry that diffs empty, continuous recorder history, and the `tinytuya==1.20.0` pin intact through Home Assistant's own dependency resolve (#48). The **Manually** section has since been walked against the `v0.1.1` release itself (2026-08-29): the folder it names is exactly what the release archive contains and the copy lands the same sixteen files, but the section never said where to obtain them — it opened with "copy `custom_components/arozen_eon/`" and a reader who had not used HACS had nothing to copy from. It now names the release download, the resulting path to check, and which restart is meant. That is the executable half; whether it reads as executable to somebody who has not read this repository is still not evidence anyone here can produce |
| ✅ | **The public repository is de-identified in its history, not just at its tip** (#72). Removing a sibling project's name and the owner's from the published files left them in every earlier revision and in five commit messages, because the scrub truncates a history rather than editing one — 341 occurrences of the one and 135 of the other, still one `git log -p` away. `tools/history_phrases.txt` is a second manifest alongside `tools/published_set.txt`: phrase-to-replacement lines applied to blobs and commit messages, ordered longest-phrase-first so a specific rule always beats the catch-all that contains it, plus the terms that must not survive and the one path still allowed to hold one — `LICENSE`, whose copyright line a bare-name rule would have rewritten. Swept on both sides afterwards: nothing left in the artifact, and the archive still reads non-zero, which is what proves the sweep can still fail. It reduces incidental attribution and does not make the project anonymous — the account name is in the repository URL and in `manifest.json`'s required `documentation` and `issue_tracker` |

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
  diagnostics.py                  the ⋮ → Download diagnostics dump, with the local key,
                                  the device id and the LAN address taken out — including
                                  out of the error strings, where a key-based redactor
                                  cannot see them
docs/
  why-not-the-official-integration.md   why this exists: the core source trace, the empty
                                        cloud schema, the topology, and the prior art
  datapoints.md                   the DP map, its evidence, and its open questions
  research/dossier.md             the recon record, including §6.7's correction
  hardware.md · decisions.md      the device itself; ADR-001…008
  captures/                       probe output and DP diffs (credentials redacted)
tools/                            dp_dump · dp_diff · dp_watch · dp_set · mq_listen —
                                  the recon loop, spelled out in tools/README.md.
                                  verify_restore.py is the odd one out: it drives the
                                  integration itself against the real device
tests/                            pytest. test_dp.py runs with no Home Assistant
                                  installed; the entity tests need the pinned core
```

**`tools/`, `docs/captures/`, `docs/research/` and `docs/hardware.md` live only in the private
development archive.** They are recon evidence about one physical diffuser — its identifiers, its
LAN, its raw traffic — and the scaffolding that produced them, three tools of which write to a
live appliance. The reasoning and the arrangement are in `docs/decisions.md`, which does travel,
so the decision can be read even where its subject cannot.

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
   (dossier §6.7).
2. **A claim about the device belongs in [`docs/datapoints.md`](docs/datapoints.md) with the
   evidence that established it.** "Toggled power in the app, DP 2 flipped" is evidence.
   "Probably intensity" is not, and should say so — the ❓ column exists to be used.

Design decisions are recorded as ADRs in [`docs/decisions.md`](docs/decisions.md). The recon
tools and their rules are in `tools/README.md`; `tests/test_dp.py` runs
against `dp.py` alone with no Home Assistant installed, which makes it the cheapest place to
pin a fact about the device.

**A `#NN` in these files is an issue or pull request in this project's development archive** — the
private repository where the recon, the arguments and the review record happened, and where they
stay. They are written as plain text and never as links, because the archive is not readable from
the published repository and its numbers do not correspond to anything there: a link would 404,
and a number rewritten to match would point at something real and wrong, which is the worse of the
two failures because nothing about it invites checking. Add new ones the same way.
[ADR-007](docs/decisions.md#adr-007--do-not-rewrite-git-history-scrub-at-publication-on-a-fresh-repository)
has the reasoning, and the test to apply before making a reference a live link.
