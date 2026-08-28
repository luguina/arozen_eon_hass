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
it keeps working when the internet does not. Note that it is a *weaker* commitment than
local-first usually implies: here the cloud path is a genuinely working fallback rather than
an inversion of the project's point. The official Tuya integration already talks to this
device; it just has nothing useful to say about it.

**What made this look viable, as filed — and the premise is false.** The device is
**mains-powered** (confirmed 2026-08-10). A battery-powered Tuya device sleeps, drops off
the LAN between wakeups, and cannot be polled locally — which would have forced the cloud path
regardless of preference. That question was the single largest risk to this whole approach and it
resolved in our favour before any work started.

**Correction, 2026-08-23 — right decision, wrong reason on file.** The device is not mains-only:
**it has a battery**, and it runs off it. DP 101 is a battery gauge, closed on 2026-08-21 against
the phone app's own readout, and DP 102 reports the charging state; both ship as entities
([datapoints.md](datapoints.md)). So the condition this entry called the single largest risk is a
condition the device is routinely in, and the paragraph above rules out an approach that has been
working the whole time.

**What actually makes local polling viable is that this device does not sleep, and unlike
"mains-powered" that is a measurement.** The remote walk of 2026-08-21
(capture `captures/remote-walk-2026-08-21.jsonl`) polled it every 2 s for 44 minutes, and
`dp_watch.py` emits a JSON line for every poll that throws or comes back without `dps` — the
capture contains **none**. The poller runs with `set_socketPersistent(False)`, so every one of
those polls was a fresh TCP connect and handshake rather than a socket held open across a doze.
The first half-hour ran **on battery**, DP 102 reading `wcd`, the gauge falling one point every
61 s through seven consecutive ticks. Inside that stretch sit **17 minutes with the diffuser
switched off** and not one datapoint moving — idle, on battery, unplugged, which is exactly the
state a sleeping Tuya device drops off the LAN in. It answered every poll.

**The bound on that, stated because it is the part still open.** Forty-four minutes is the
longest unbroken observation there is; nothing has watched an idle overnight on battery. The
no-sleep finding is solid at the scale measured and untested beyond it, which is why a future
"it went unavailable by morning" has a suspect ready
(dossier §1).

**What would change this.** The device refusing local connections, or shipping a protocol
version whose session keys we cannot derive. Then the fallback ladder is: LocalTuya →
official Tuya cloud integration + Tuya "tap-to-run" scenes as blunt on/off buttons →
reflashing the WiFi module. The last of those is out of scope
([ADR-005](#adr-005--scope-power-intensity-workpause-timer-scheduling-reflashing-excluded)).

---

## ADR-002 — No ESP32. The device is already on the network.

**Status:** accepted · **Date:** 2026-08-10

**Context.** The reflex architecture for an appliance Home Assistant cannot reach is a bridge:
an ESP32 running an ESPHome `bluetooth_proxy` next to the device. It earns its keep when the
appliance speaks BLE and sits out of radio range — three floors from the Home Assistant box,
say.

**Decision.** Nothing gets flashed. Home Assistant talks straight to the diffuser over the LAN.

**Why this ADR exists at all.** The verdict is obvious; the failure mode it guards against is
not. Two appliances of the same *kind*, same house, near-identical goals — and the strong
pull is to reach for the architecture that worked last time. It does not apply. A bridge is
needed when BLE cannot span the distance; **WiFi already spans it**, which is the entire
reason this device has an app that works "from anywhere". Copying the proxy across would add a
board, a firmware, a power supply and a failure mode, in exchange for nothing.

Stated plainly because a constraint that *feels* decisive often is not — the same trap from
the other direction, where "three floors away" feels like it chooses the implementation
language and does not.

**What would change this.** Nothing plausible. If WiFi does not reach the diffuser's position,
the fix is an access point or a mesh node, not a protocol bridge.

---

## ADR-003 — Defer the deliverable until the datapoint dump exists

**Status:** superseded · **Date:** 2026-08-10 · **Resolved 2026-08-21 → option C**

**Resolution.** Called before the dump: the deliverable is **our own integration**,
`custom_components/arozen_eon/`, on the standard Home Assistant shape (coordinator + entity
platforms + a diagnostic-sensor instrument). The gate's concern — that C might mean
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
| **C — our own integration** | A `custom_components/arozen_eon/` of the conventional shape. |

**Decision.** Do not choose yet. Dump the datapoints first
([`datapoints.md`](datapoints.md)), then decide against the criteria below.

**Be honest about how wide this gate actually is.** A gate like this is genuinely open when
the protocol could turn out to be anything, and one has demolished a front-runner before.
Here it is **much narrower**: the transport is a known, implemented,
encrypted protocol on TCP 6668, so option C is not "write a protocol" — it is "wrap `tinytuya`
and re-solve problems A and B already solved". C is on this list for completeness and starts
heavily disfavoured. The real question is A versus B.

**What decides it:**

1. **Can a `tuya-local` YAML express every control?** Its schema covers booleans, enums,
   integers with ranges, and mappings between DP values and HA values. If the Arozen packs
   work/pause into a single encoded string or a JSON DP that the schema cannot decompose,
   A weakens.
2. **Does an existing config already fit?** Twelve diffuser configs ship today. If one matches
   the DP set outright, this collapses to a configuration exercise. *(Do not lean on this. A
   hypothesis of exactly this shape — an existing config that surely fits — has been wrong
   before.)*
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

**Why this is not being decided by whoever writes the code.** A requirement of this kind is a
hard constraint that rejects otherwise-good solutions, and the honest resolution is often that
the owner *withdraws* it rather than the engineer working around it. Same principle: if the
answer is "the app must keep working", that changes which options are admissible, and it is a
preference, not a finding.

**Why the BLE intuition does not transfer, and it matters.** A BLE app holds an exclusive
link — one central, one connection. Tuya's app normally reaches the device **via the
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
category does expose a `countdown` DP, and the app clearly has schedules. But this question
has been settled before — on-device schedule records lose to Home Assistant automations,
because on-device schedules fought with
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
(remote walk `captures/remote-walk-2026-08-21.jsonl`). So the question is not "can we avoid
causing this" — we never caused it — but **which of the device's own defaults, if any, the
integration should overrule on the user's behalf.**

**Decision.** Restore **intensity** (#14, private archive — see ADR-007 for what the issue
numbers in these documents refer to). Leave the **countdown** alone. Take no position on the
LED until it has a write test (#15).

**LED update, 2026-08-22 — the position, now that the write test exists.** DP 7 is a command
DP: both directions were accepted and held for 30 s. It gets a switch, and it gets **no
restore**, which lands it with the countdown rather than with intensity. The test above is why.
Intensity is *reset to a known default on a known edge*, wiping a choice the user made — a
defect, and the correction is stateable in one line. DP 7 moves on a condition **nobody has
established**: it followed power down and up on two power cycles out of three, and the third
left it alone, with both episodes on the charger. There is no rule to restore *to*. Writing a
value back at the device on a pattern that fits two thirds of the evidence would not be
repairing a defect, it would be inventing one — and the entity would fight the firmware every
time the guess was wrong, invisibly. **What would change this:** an established rule for the
self-movement. If DP 7 turns out to be reset on power-on the way intensity is, it becomes the
same case as intensity and the same reasoning applies in the other direction.

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

**What would change this.** For the countdown: evidence that restoring it is what the device's
owner actually wants — most plausibly running on "Continuous" and being cut off at four hours often
enough to say so. That is a preference and it is the owner's call, not a finding. In the other
direction: if the intensity restore is ever seen fighting something that also writes DP 3 (a
Tuya scene, a schedule pushed from the app), the "somebody got there first" guard stops being
sufficient and the scope narrows to Home-Assistant-initiated power-ons only.

---

## ADR-007 — Do not rewrite git history. Scrub at publication, on a fresh repository.

**Status:** accepted · **Date:** 2026-08-22 · **Updated 2026-08-24 — publication decided, the
public repository named `arozen_eon_hass`** ·
**Updated 2026-08-28 — published; the public history is a regenerated artifact**

**Context.** An audit that day found the repo breaking its own redaction rule
(captures/README.md), which grants each identifier **one**
authoritative location. Three device IDs were in the tracked tree: this diffuser's, restated a
second time in `datapoints.md`, and two belonging to *other* appliances on the same Tuya account,
which had no sanctioned location at all. All three are also in **every commit back to the initial
one**, so fixing the tree leaves the values one `git log -p` away — which is why the history is a
decision rather than a chore.

The good news bounds the problem. The `local_key` — the thing that actually grants control — has
**never** been committed, on any ref; `git log -S` returns nothing. This entry is about identifiers
only, and a Tuya device ID is an *address, not a credential*. Holding one grants nothing: local
control needs the key, and re-pairing regenerates the key while the ID survives.

**Decision.** Fix the tree, enforce it with a test, and **leave git history alone.** No
`git filter-repo`, no force-push. When this repository is published, the scrub happens then, by
pushing a scrubbed history to a **new** repository and keeping this one private as the archive.
That *when* was an *if* on the day this was written; publication has since been decided and the
target named, in the dated update at the end of this entry.

**This reverses a decision taken earlier the same day, and the reversal is the point of the entry.**
The first version of ADR-007 said *rewrite now*, on the reasoning that the repo should follow the
rule it states and that forty-odd commits with no forks would never be cheaper to rewrite. That
reasoning rested on an assumption nobody had checked: that a force-push to `main` removes the value
from GitHub. **It does not.**

**The measurement.** GitHub keeps a `refs/pull/N/head` ref for every pull request, permanently, and
a force-push to `main` does not touch them. Fetching `+refs/pull/*/head` from this repo returns a
ref per pull request ever opened — **fourteen at the time of writing, and the device ID is in
`docs/datapoints.md` and `docs/research/dossier.md` under every single one.** There is no API to
delete a pull ref.

And the count is not static, which is what turns a footnote into an argument: it grows by one every
time a pull request is opened, **including the one that carried this entry into the repo**. So the
remainder a rewrite leaves behind does not sit still waiting to be cleaned up later. It accretes,
and it accretes fastest while the PR workflow is being used properly.

So the rewrite would buy a clean `main` — what a fresh clone and a `git log -p` see — at the cost of
invalidating every SHA across 25 pull requests, diverging every other clone, and installing a tool,
while leaving the values fetchable by anyone with repo access who knows the incantation. That is the
expensive half of a fix that does not fix the thing it is for.

**The strongest case for rewriting anyway, and why it does not carry.** A clone contains `main`'s
history but **not** the pull refs, which are not fetched by default. So against a *leaked clone* — a
laptop, a backup, a shared machine — a rewritten repo really would be clean, and that is the most
likely leak vector for a private repo. It does not carry because the machine that leaks a clone is
the machine holding `.cache/creds.json`, which has the live `local_key`. The rewrite protects
against the mild half of a failure whose severe half it cannot touch, and the severe half is
governed by `.gitignore` and by not putting the key in the tree — which is where the effort belongs.

**What is done instead, and why it is the durable part.** The tree holds exactly one device ID, in
dossier §6.2, and `tests/test_redaction_rule.py` fails the build if a second appears — reading the
value out of the sanctioned location rather than holding a copy, so the suite does not become the
third occurrence. That converts the rule from prose somebody remembers into a check that runs. It is
also the only part of this that was ever *broken* rather than merely historical.

**The publication path, spelled out, because this is where it actually matters.** While the repo is
private, pull refs are visible to whoever can already read every file anyway. Making it public makes
them public too, so publishing *this* repository can never be clean, rewrite or no rewrite. The
clean route is to publish a **new** repository built from a scrubbed history and keep this one
private as the archive: the public history has no pull refs carrying anything, and the entire issue,
PR and review record survives here. The scrub then happens once, at the moment it matters, on a
history being rewritten anyway — where doing it now means doing it twice.

**What travels is a list, and the list is in the tree.** `tools/published_set.txt`
names the published file set and carries the reasoning for everything held back;
`tools/publish_check.py` builds exactly that set into a scratch
repository and runs its suite there, which is the check step above made repeatable. Both exist
because #41 found the list living in a shell snippet in an issue body: it had drifted, and the
first time anyone ran it the published set came back with two collection errors and three
failures. The redaction guard split along the
same seam — `tests/test_redaction_rule.py` travels and asserts that no identifier shape appears in
any published file, `tests/test_one_authoritative_location.py` stays and enforces the one-home
rule this tree needs while it still has a real identifier to give a home to. A scrubbed repository
has no sanctioned location, so that is not a weakened guard but a different one.

**Update — 2026-08-24. Publication is decided, and the public repository has a name.**
The conditional in **Decision** above has resolved. The public repository is **`arozen_eon_hass`**
(<https://github.com/luguina/arozen_eon_hass>). The archive is this project's original repository,
kept private, and it is where the issue and pull-request numbers in these documents live. The name
is recorded *here* rather than only in the publication epic (#30) because every self-referential URL
in the tree needs a target before it can be rewritten, and a name that lives only in an issue is one
the rewrite has to go looking for.

Three kinds of self-reference had to be told apart, because they break differently at the moment of
publication and only one of them is anybody's emergency:

- **`manifest.json`'s `documentation` and `issue_tracker`** are the load-bearing pair. hassfest
  requires both, and Home Assistant renders them on the integration's device page as "Documentation"
  and "Report an issue" — the only route an installed integration offers back to its source. They
  point at the public repository. A 404 there is a user in a house with a misbehaving diffuser and
  nowhere to go.
- **Badges, workflow links and the HACS custom-repository URL** point at the public repository for
  the same reason in a milder form: they are read by somebody deciding whether to install, and a
  broken badge is an answer to that question.
- **Issue and pull-request references point at discussion that does not travel.** #5's remote walk,
  #14's restore design, #20's audit — that is the working record, and the working record stays in
  the archive. Rewriting the numbers to the public repository would make them *confidently wrong*,
  which is worse than a number a reader can see refers to somewhere else, because nothing about a
  plausible wrong number invites checking.

**So: an issue or pull-request number in these documents is written as plain `#NN`, never as a
link.** It refers to the archive, and it will not correspond to anything in the public repository,
whose numbering starts again at one. Most of the tree already wrote them this way; the linked
minority was the half that would have 404'd for every public reader, and it is gone. Where a
document leans on a reference hard enough that a reader might go looking, the first
one in that document says so outright — `#20 (private archive)` — and the rest are bare, because a
parenthetical repeated thirty times stops being read.

A live link survives only where the target is something a public reader can actually open: upstream
repositories, Home Assistant core, HACS. That is what the remaining links in these documents are,
and it is the test to apply to a new one.

**Update — 2026-08-28. Published. The public history is a regenerated artifact, not a mirror.**
The push happened, and what it produced is worth naming precisely, because the obvious mental
model of it is wrong. `arozen_eon_hass` is not this repository with some files withheld, and it is
not a branch of it: `tools/scrub_for_publication.py` rebuilds the whole history from scratch,
commit by commit, out of the archive filtered through `tools/published_set.txt`. The two share
nothing — not a SHA, not a parent chain, not a root commit. `v0.1.0` is 83 commits over 43 files;
this archive is 106 over 67.

**Re-running the scrub is deterministic, and that property belongs to the manifest rather than to
the tool.** With `tools/published_set.txt` unchanged a second run reproduces every SHA byte for
byte — verified twice — so an ordinary update to the public repository is a fast-forward and
behaves like any other push. **Change the manifest and it is not.** A file present in the root
commit alters that commit's tree, which alters its SHA, which alters every commit after it; the
histories then diverge at commit one, and the update is a force-push plus a tag move. That is the
design working rather than a failure, but it is easy to promise a fast-forward on Monday and owe a
force-push on Tuesday, so the question to ask before promising anything is whether the manifest
moved. It moved on 2026-08-28, when `docs/decisions.md` and `docs/datapoints.md` were added to fix
ADR references that 404'd for every public reader, and 77 commits over 40 files became 83 over 43.

**A quieter consequence: `--replace-text` became load-bearing that day.** Until then it was
insurance. No file that travelled had ever held a real device ID, so the path filter removed all
three by construction and only `--replace-message` did observable work — which made the content
substitution a guard nobody had watched fire. `docs/datapoints.md` carries this diffuser's ID in
two commits of its own history and now travels, so the substitution is doing the job it was
written for. The published objects were swept afterwards and hold none of the three IDs, in no
blob, tree or commit message.

**Sweep the archive too, every time, and require it to come back non-zero.** A check that says the
artifact is clean is worth only as much as the run proving that check can still fail. The first
sweep on 2026-08-28 reported zero occurrences in *both* repositories, which is impossible — this
one holds the ID in dossier §6.2 on purpose — and the cause was the sweep erroring out on a binary
object stream while its caller quietly turned the error into a zero. A redaction check that fails
open is indistinguishable from a pass, and nothing downstream catches it. So the sweep runs twice
over the same list: against the artifact, where it must find nothing, and against the archive,
where it must find something.

**What would change this.** Deciding to publish *this* repository, PR history and all, rather than a
fresh one — at which point the calculation changes completely and the pull refs, not `main`, become
the problem to solve. Or a `local_key` turning up in history, which is a different severity
altogether and would justify the rewrite plus a support request on its own. The counter-argument
that a repo stating a rule should visibly follow it is real and is not dismissed here; it is
outweighed by the rewrite not delivering that, and it is answered instead by the tree fix and the
test.

---

## ADR-008 — Never assert a cause the transport cannot distinguish

**Status:** accepted · **Date:** 2026-08-24

**Context.** Home Assistant has a well-worn answer for "the credentials stopped working": raise
`ConfigEntryAuthFailed` from the coordinator and let the framework open a reauth flow. It is the
right shape for a cloud API, where a 401 and a 503 are different answers to the same request.

The Tuya local protocol does not offer that distinction. A `local_key` that no longer decrypts —
which is exactly what re-pairing in the Smart Life app produces — comes back as an error payload
shaped like `{"Error": …, "Err": "914"}`. So does a diffuser that is powered off. So does one
asleep, one that a DHCP lease has moved to another address, and one holding its single local
connection open for the phone app (ADR-004). `device.py` collapses all of them into
`ArozenUnreachable` **because they are not distinguishable at that layer**, not because it has
not tried.

**Decision.** The integration **never puts a cause in front of the user that the transport cannot
establish.** For the rotated key (#49) that means a repair issue in Settings → System → Repairs,
raised after an hour of silence and retired by the first successful exchange — and specifically
*not* `ConfigEntryAuthFailed`, and not a reauth flow.

**Why that follows rather than being a matter of taste.** A reauth flow is an accusation with a
UI attached. It tells the user their credentials are wrong and puts a form in front of them, and
the most common reason this device stops answering is that somebody unplugged it. Getting that
wrong is not a cosmetic failure: it sends a person to re-enter a key that was never the problem,
teaches them the integration guesses, and leaves the actual cause — no power — unmentioned on the
one screen they were looking at.

**What makes the repair issue admissible where the reauth flow is not** is that it does not have
to name a cause at all. It can state the observation, which is true — this device has not
answered for an hour — then name both states that produce it and give the remedy for one and the
check for the other. Both branches, one card, no false accusation. The words are held to that by
a test that reads the shipped string (`tests/test_repair_issue.py`), because this is a property
of the *text* and text drifts in a way code does not.

**Scope, deliberately wider than one card.** The same rule decides anything else that would put a
cause on screen: an entity that reports "credentials invalid", an error string in the config flow
that blames the key rather than the exchange, a future `ConfigEntryAuthFailed` added for a
different symptom. If the transport cannot tell two causes apart, neither may the user interface.
The README's *When it misbehaves* section already worked this way — "a wrong local key, a wrong
protocol version and a diffuser that has fallen asleep are three different problems with one
symptom" — and this ADR is that observation promoted to a rule.

**What would change the answer.** A firmware or tinytuya release that gives a decryption failure
a shape distinguishable from a timeout. The premise here is a measured property of the transport,
not a preference, so the day it stops being true, `ConfigEntryAuthFailed` becomes the better
answer and this entry should be superseded rather than argued with.

---

## Pending

| # | Decision | Blocked on |
|---|---|---|
| [ADR-004](#adr-004--pending--must-the-phone-app-keep-working) | Must the phone app keep working? | The project owner, informed by a coexistence measurement — now half-made: with the app open, local writes failed intermittently (null/914); with it closed, they landed (dossier §6.3) |
| ~~On-device schedules vs Home Assistant automations~~ | **Resolved 2026-08-21 by evidence:** the app's schedule moved no DP during the control walk — scheduling is cloud/app-side, so HA automations + the countdown DP (dossier §6.6) |
| — | ~~Whether to make this repo public~~ | **Resolved 2026-08-24: yes, as a fresh repository — [`arozen_eon_hass`](https://github.com/luguina/arozen_eon_hass), with the original repository kept private as the archive** ([ADR-007](#adr-007--do-not-rewrite-git-history-scrub-at-publication-on-a-fresh-repository)). Two conditions, not one, and both hold. (a) Confirming no `local_key` has ever been committed — ✅ clean, tree and history, audited 2026-08-22. (b) The one-authoritative-location rule in captures/README.md actually holding. ✅ in the tree, and enforced by `tests/test_redaction_rule.py`; **not** in history, and deliberately so — publishing *this* repo can never be clean, because its `refs/pull/*/head` carry the identifiers and no force-push or API call removes them. That is what makes a fresh repository the answer rather than a flip of this one. The gate named only (a) until #20, which meant the repo could satisfy its own precondition with the `device_id` rule broken |
