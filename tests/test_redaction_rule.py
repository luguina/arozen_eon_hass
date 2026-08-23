"""Enforces the one-authoritative-location half of `docs/captures/README.md`'s redaction rule.

The rule is that each identifier gets **one** sanctioned home in this repo, so that scrubbing
before publication is a single edit rather than an archaeology exercise. It was stated in prose,
in a file about captures, and it was broken in `docs/datapoints.md` from the initial commit until
[#20](https://github.com/luguina/arozen_ha_controller/issues/20) — with the violation *known*, and
written down in a capture header, for a day before anyone fixed it. That is the argument for this
file: a rule enforced by whoever remembers to run the README's sweep is a rule that holds until
somebody is in a hurry.

What it reads is the working tree as a commit would take it — the index, plus every untracked file
`.gitignore` does not cover — so an offending line is caught while it is still a line in a file
rather than a blob on a ref. `_publishable_text_files` has the argument for that boundary and the
two occasions that forced it.

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


def _publishable_text_files(root: Path = REPO) -> list[str]:
    """Every file a commit would take: the index, plus untracked files git is not ignoring.

    Asked of git rather than walked off the disk, and each half of that answer is argued for.

    `--others` is here because `--cached` alone — which is all this asked for until
    [#36](https://github.com/luguina/arozen_ha_controller/issues/36) — cannot fail on a file
    nobody has staged yet, and that is *every* new file, for the whole time anyone is writing it.
    Two new test files went green that way during
    [#35](https://github.com/luguina/arozen_ha_controller/pull/35) and tripped this rule only on
    commit, which is to say after the value was already in a commit object. "Amend it away before
    pushing" is a discipline, and replacing a discipline is the entire reason this file exists.

    `--exclude-standard` is what makes `--others` safe, and it is the same distinction the old
    wording drew one step later. A directory walk is still wrong, because it would read
    `.cache/creds.json`, which holds the real id legitimately and is gitignored for exactly that
    reason; a guard that fails on a sanctioned file teaches its reader to ignore the guard.
    Honouring `.gitignore` keeps that file out while letting in the unignored new files that are
    on their way into a commit. Note the asymmetry, which is the right one: `--exclude-standard`
    filters only the untracked half, so a file already in the index stays scanned however
    `.gitignore` reads and the escape hatch cannot be used to hide something that already ships.

    The cost, written down rather than discovered: an unignored scratch file in somebody's working
    tree is scanned now. That is the intended behaviour — a scratch file with an id in it is one
    `git add -A` from permanent — and `.gitignore` is how you say a path is going nowhere.

    `root` is a parameter only so the meta-tests at the bottom can aim the enumeration at a
    throwaway checkout. Nothing in the guard itself passes anything but `REPO`.
    """
    cmd = ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as err:  # pragma: no cover - see below
        # Deliberately a failure rather than a skip. A guard that quietly disarms itself when a
        # dependency is missing reports green on the run where it was needed most, and the whole
        # reason this file exists is that the previous enforcement mechanism was "somebody
        # remembers".
        pytest.fail(f"cannot ask git what a commit would take, so this guard cannot run: {err}")
    return [name for name in out.split("\0") if name]


def _read(rel: str, root: Path = REPO) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _offenders(pattern: re.Pattern[str], sanctioned: str, root: Path = REPO) -> list[str]:
    """Files carrying `pattern` outside the one place it is allowed, sorted so messages are stable.

    Shared by the two rules below *and* by the meta-tests, on purpose: a meta-test that rebuilt
    this sweep against a throwaway checkout would prove only that the rebuild works.
    """
    return sorted(
        name
        for name in _publishable_text_files(root)
        if name != sanctioned and name not in FIXTURES and pattern.search(_read(name, root))
    )


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


def test_no_other_publishable_file_records_a_device_id():
    offenders = _offenders(DEVICE_ID, SANCTIONED)
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
    offenders = _offenders(LAN_ADDRESS, SANCTIONED_ADDRESS)
    assert not offenders, (
        f"LAN addresses outside {SANCTIONED_ADDRESS} — see docs/captures/README.md: "
        + ", ".join(offenders)
    )


# --- Meta-tests: what the enumeration above can and cannot see ---------------------------------
#
# These do not check this repo. They build a throwaway git repo, one file per case the
# enumeration has to tell apart, and ask the same `_offenders` the rules above call. A version of
# these that asserted against a hand-written file list would pass whatever `git ls-files` did,
# which is the one thing under test — and one that leaned on the developer's own working tree
# would fail whenever somebody had an unrelated scratch file open, which is worse than the bug.


@pytest.fixture
def throwaway_checkout(tmp_path: Path) -> Path:
    """A real git repo holding one file of each kind: staged, untracked, gitignored.

    Nothing is committed. `git add` fills the index, which is all `--cached` reads, and stopping
    there keeps the fixture from needing a `user.email` that CI does not necessarily have.

    `core.excludesFile` is pinned at a path that does not exist so that whatever the developer
    keeps in `~/.config/git/ignore` cannot decide the outcome. The `.gitignore` written below is
    then the only exclude in play, which is the one these tests are about.

    The device ids are synthetic and obviously so; the real one is never in this file, and
    `test_the_synthetic_ids_in_the_test_suite_are_not_the_real_one` is what keeps that true.
    """
    root = tmp_path / "checkout"
    (root / ".cache").mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, check=True, text=True
        )

    git("init")
    git("config", "core.excludesFile", str(tmp_path / "no-such-personal-excludes"))

    # Mirrors `.gitignore:42` in the real repo, which is the line that keeps `.cache/creds.json`
    # out of the scan.
    (root / ".gitignore").write_text(".cache/\n", encoding="utf-8")
    # The sanctioned-but-secret file. Its real counterpart holds the actual device id, put there
    # on purpose, and the guard failing on it would be the guard crying wolf.
    (root / ".cache" / "creds.json").write_text(
        '{"device_id": "bf000000000000000creds"}\n', encoding="utf-8"
    )
    (root / "staged.md").write_text("device id bf00000000000000staged\n", encoding="utf-8")
    # Written and then left alone: no `git add`, no commit. This is the state every new file is
    # in for as long as somebody is working on it, and the state the guard used to be blind to.
    (root / "unstaged.md").write_text("device id bf000000000000unstaged\n", encoding="utf-8")

    git("add", ".gitignore", "staged.md")
    return root


def test_a_file_is_scanned_before_anybody_stages_it(throwaway_checkout: Path):
    """The case #36 is about, and the reason the flags changed.

    Two agents hit this on #35: each wrote a new test file with identifier-shaped strings in it,
    each ran the suite green, and each learned about the rule from the commit that made the
    problem permanent. A guard whose answer arrives after the commit object exists is answering
    a question nobody can act on cheaply any more.
    """
    root = throwaway_checkout
    index_only = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True, text=True
    ).stdout.split("\0")
    # State the premise as an assertion. If the fixture ever staged this file, everything below
    # would pass for the wrong reason and this test would quietly stop guarding anything.
    assert "unstaged.md" not in index_only, "fixture no longer exercises the untracked case"

    assert "unstaged.md" in _offenders(DEVICE_ID, SANCTIONED, root)


def test_the_index_is_still_scanned_as_well():
    """`--others` was added alongside `--cached`, not in place of it — and the sweep over this
    repo would keep passing either way, since a clean checkout has nothing untracked to notice.
    Asserted here so that regression cannot hide behind a green suite.
    """
    # This one is about the real repo on purpose: it is tracked files that carry every identifier
    # the rule is actually protecting today.
    assert "docs/captures/README.md" in _publishable_text_files()


def test_a_gitignored_file_is_still_invisible_to_the_guard(throwaway_checkout: Path):
    """`.cache/creds.json`, proved rather than assumed.

    This is the assertion that makes `--others` acceptable at all. Without `--exclude-standard`
    the guard would fail on the one file that is *supposed* to hold the real id, and a rule that
    fires on a sanctioned file is a rule people learn to skip past.
    """
    root = throwaway_checkout
    creds = root / ".cache" / "creds.json"
    # Vacuity guard, the same move as `test_the_pattern_would_catch_an_unredacted_id`: if the
    # fixture stopped writing an id-shaped string here, the assertions below would hold for free.
    assert DEVICE_ID.search(creds.read_text(encoding="utf-8"))

    assert ".cache/creds.json" not in _publishable_text_files(root)
    assert not [
        name for name in _offenders(DEVICE_ID, SANCTIONED, root) if name.startswith(".cache/")
    ]
