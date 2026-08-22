"""Enforces the one-authoritative-location half of `docs/captures/README.md`'s redaction rule.

The rule is that each identifier gets **one** sanctioned home in this repo, so that scrubbing
before publication is a single edit rather than an archaeology exercise. It was stated in prose,
in a file about captures, and it was broken in `docs/datapoints.md` from the initial commit until
[#20](https://github.com/luguina/arozen_ha_controller/issues/20) — with the violation *known*, and
written down in a capture header, for a day before anyone fixed it. That is the argument for this
file: a rule enforced by whoever remembers to run the README's sweep is a rule that holds until
somebody is in a hurry.

Two things it deliberately does **not** do:

* it does not know the real device id, and never puts one in a test file. It reads the id out of
  the sanctioned location and counts where else that shape occurs, so the check works without the
  test suite becoming a second copy of the thing it is protecting;
* it says nothing about git history, which is the other half of #20 and cannot be fixed by a
  test — see [ADR-007](../docs/decisions.md). A tree this file calls clean can still have the
  value one `git log -p` away, and the README's history sweep is what answers that.

No failure message here prints an identifier. A test that leaks the value on the way to reporting
the leak would be its own bug, and CI logs are more widely readable than the repo.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: `bf` plus 20 lowercase alphanumerics — the shape all three ids in dossier §6 have, and the
#: same pattern `tools/mq_listen.py` redacts with. Kept as a duplicate rather than imported so
#: that breaking the tool's regex cannot silently disarm this file too.
DEVICE_ID = re.compile(r"\bbf[0-9a-z]{20}\b")

#: Private IPv4, the second identifier the rule names. `hardware.md` is its sanctioned home.
LAN_ADDRESS = re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))(?:\.[0-9]{1,3}){2}\b")

#: dossier §6.2, the QR-login table. The one place a real device id is allowed to be.
SANCTIONED = "docs/research/dossier.md"

#: Files that hold identifier-shaped strings on purpose: the redaction fixtures in
#: `test_mq_redaction.py`, and the vacuity guard below, which needs a device id and a LAN address
#: that look real enough to prove the patterns work. Allowed by name — which is a hole, because
#: "it is only a test fixture" is exactly how a real value ends up somewhere nobody sweeps.
#:
#: Half of that hole is closed: the device ids here are compared against the sanctioned value in
#: `test_the_synthetic_ids_in_the_test_suite_are_not_the_real_one`. The LAN half is **not**, and
#: cannot be by the same trick — no LAN address is recorded anywhere in this repo, so there is
#: nothing to compare against. Stated rather than papered over; the exposure is small because the
#: pattern's real job is prose like `192.168.0.x` in the dossier, not a paste into a fixture.
FIXTURES = frozenset({"tests/test_mq_redaction.py", "tests/test_redaction_rule.py"})

#: Where a LAN address would go if one ever earned a place. None does today.
SANCTIONED_ADDRESS = "docs/hardware.md"


def _tracked_text_files() -> list[str]:
    """Tracked files only — `git ls-files`, not a directory walk.

    The distinction matters both ways round. A walk would miss nothing, but it would also read
    `.cache/creds.json`, which holds the real id legitimately and is gitignored for that reason;
    failing on it would train the reader to ignore this test. And a walk of a stale checkout can
    pass on files nobody would publish.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-z"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as err:  # pragma: no cover - see below
        # Deliberately a failure rather than a skip. A guard that quietly disarms itself when a
        # dependency is missing reports green on the run where it was needed most, and the whole
        # reason this file exists is that the previous enforcement mechanism was "somebody
        # remembers".
        pytest.fail(f"cannot ask git what is tracked, so this guard cannot run: {err}")
    return [name for name in out.split("\0") if name]


def _read(rel: str) -> str:
    try:
        return (REPO / rel).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def test_the_pattern_would_catch_an_unredacted_id():
    """The guard that stops every assertion below being vacuously true.

    All of them are "this shape does not appear here". A broken pattern satisfies them all.
    """
    assert DEVICE_ID.search('{"devId": "bf1a2b3c4d5e6f7a8bwxyz"}')
    assert LAN_ADDRESS.search("listening on 192.168.0.42:6668")
    assert not DEVICE_ID.search("bfshort") and not LAN_ADDRESS.search("2026.08.22")


def test_the_sanctioned_location_records_the_device_id_exactly_once():
    """Once, not at-least-once: the rule is *one* authoritative location, and a second copy
    inside the sanctioned file is the same defect as a second copy outside it.

    This is also what proves the tests below are reading a real value rather than an empty
    string — the id they compare against comes from here.
    """
    found = DEVICE_ID.findall(_read(SANCTIONED))
    assert len(found) == 1, (
        f"{SANCTIONED} holds {len(found)} device ids, expected exactly 1 (dossier §6.2). "
        "Values not printed on purpose."
    )


def test_no_other_tracked_file_records_a_device_id():
    offenders = sorted(
        name
        for name in _tracked_text_files()
        if name != SANCTIONED and name not in FIXTURES and DEVICE_ID.search(_read(name))
    )
    assert not offenders, (
        "device ids outside their one sanctioned location — see docs/captures/README.md: "
        + ", ".join(offenders)
    )


def test_the_synthetic_ids_in_the_test_suite_are_not_the_real_one():
    """`FIXTURES` is allowlisted by filename, which is a hole big enough to paste a real id into.

    Closing it does not require knowing the id: the sanctioned location has it, so the check is a
    comparison rather than a literal, and this file stays free of the value it is protecting.
    """
    real = DEVICE_ID.findall(_read(SANCTIONED))[0]
    offenders = sorted(name for name in FIXTURES if real in _read(name))
    assert not offenders, (
        "the real device id is in a file allowlisted for synthetic fixtures, so nothing else "
        "will catch it — replace it with a made-up one: " + ", ".join(offenders)
    )


def test_no_lan_address_is_recorded_outside_its_sanctioned_file():
    """Lower stakes than the device id and enforced anyway, because the reason it is low-stakes
    is that there are currently none — an unenforced clean state is a coincidence, not a rule.
    """
    offenders = sorted(
        name
        for name in _tracked_text_files()
        if name != SANCTIONED_ADDRESS and name not in FIXTURES and LAN_ADDRESS.search(_read(name))
    )
    assert not offenders, (
        f"LAN addresses outside {SANCTIONED_ADDRESS} — see docs/captures/README.md: "
        + ", ".join(offenders)
    )
