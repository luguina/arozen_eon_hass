"""No identifier-shaped value reaches a published file, except the synthetic fixtures here.

This is the half of the old redaction guard that **travels** to the public repository, and it is
written to mean the same thing in both places. The other half — one authoritative location per
identifier, `docs/research/dossier.md` for the device id — stays in
`tests/test_one_authoritative_location.py`, because after the scrub there is no sanctioned
location: the real identifier is not published anywhere, which is the entire point of publishing
a scrubbed history to a fresh repository ([ADR-007](../docs/decisions.md), [#30]). A guard whose
reference value does not exist is not a weakened guard, it is a different rule, so it is a
different file.

**What it is for in the public repository**, where there is no real device id to protect: a
contributor pasting *their own* device id into an issue-reproduction test. That is not
hypothetical — it is the single most likely way an identifier enters a Home Assistant integration
repository, and it arrives in a pull request from somebody who has never read a redaction rule.
The rule this file states needs no sanctioned value to enforce: identifier-shaped strings live in
the fixtures below and nowhere else.

**Why it is parameterised by a file set.** The rule above is false in *this* repository, where
`docs/research/dossier.md` holds the real device id legitimately. It is true of the files that
travel — and that is not a weaker statement, it is the accurate one: what is published is what
the public repository will contain. So the sweep runs over the published set, which
`tools/published_set.txt` defines here and which is *everything* in the public repository, where
that file does not exist. One rule, one implementation, and it can be run here as a real
prediction of what it will say there. `published_files` carries the argument for that boundary.

Two things it deliberately does **not** do:

* it does not know the real device id, and never puts one in a test file. That comparison needs
  the sanctioned location, so it lives with the other half of the split — which also means the
  fixture allowlist below is unbacked in the public repository, and that is said out loud in
  `FIXTURES` rather than papered over;
* it says nothing about git history, which cannot be fixed by a test — see
  [ADR-007](../docs/decisions.md). A tree this file calls clean can still have the value one
  `git log -p` away, and publishing a scrubbed history to a fresh repository is what answers that.

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
#: that breaking the tool's regex cannot silently disarm this file too — and so that this file
#: keeps working in the public repository, where `tools/` does not exist.
DEVICE_ID = re.compile(r"\bbf[0-9a-z]{20}\b")

#: Private IPv4, the second identifier the rule names. Nothing published records one.
LAN_ADDRESS = re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))(?:\.[0-9]{1,3}){2}\b")

#: The published file set, defined once, in a file that does not itself travel. See
#: `published_files` for what its absence means and why that is the safe direction.
MANIFEST = "tools/published_set.txt"

#: Files that hold identifier-shaped strings on purpose. Only this one travels: the redaction
#: fixtures in `tests/test_mq_redaction.py` stay behind with `tools/`, which is what they test.
#: The vacuity guards below need a device id and a LAN address that look real enough to prove the
#: patterns work, and this is where they live.
#:
#: Allowed by name, which is a hole, because "it is only a test fixture" is exactly how a real
#: value ends up somewhere nobody sweeps. In *this* repository half of that hole is closed:
#: `tests/test_one_authoritative_location.py` compares every id in these files against the real
#: one. **In the public repository it is not closed and cannot be**, because there is no reference
#: value there to compare against — the same argument that has always applied to the LAN half,
#: now applying to both. Stated rather than hidden; the exposure is one file, listed here, that a
#: reviewer can read in full.
FIXTURES = frozenset({"tests/test_redaction_rule.py"})


def _publishable_text_files(root: Path = REPO) -> list[str]:
    """Every file a commit would take: the index, plus untracked files git is not ignoring.

    Asked of git rather than walked off the disk, and each half of that answer is argued for.

    `--others` is here because `--cached` alone — which is all this asked for until #36 —
    cannot fail on a file nobody has staged yet, and that is *every* new file, for the whole
    time anyone is writing it. Two new test files went green that way during #35 and tripped
    this rule only on commit, which is to say after the value was already in a commit object.
    "Amend it away before pushing" is a discipline, and replacing a discipline is the entire
    reason this file exists.

    `--exclude-standard` is what makes `--others` safe. A directory walk is still wrong, because
    it would read `.cache/creds.json`, which holds the real id legitimately and is gitignored for
    exactly that reason; a guard that fails on a sanctioned file teaches its reader to ignore the
    guard. Honouring `.gitignore` keeps that file out while letting in the unignored new files
    that are on their way into a commit. Note the asymmetry, which is the right one:
    `--exclude-standard` filters only the untracked half, so a file already in the index stays
    scanned however `.gitignore` reads and the escape hatch cannot be used to hide something that
    already ships.

    The cost, written down rather than discovered: an unignored scratch file in somebody's working
    tree is scanned now. That is the intended behaviour — a scratch file with an id in it is one
    `git add -A` from permanent — and `.gitignore` is how you say a path is going nowhere.

    `root` is a parameter only so the meta-tests at the bottom can aim the enumeration at a
    throwaway checkout, and so `tools/publish_check.py` can aim it at a built published tree.
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


def _manifest_rules(text: str) -> tuple[list[str], list[str]]:
    """Split `tools/published_set.txt` into what travels and what is carved back out of it.

    `.gitignore`-shaped on purpose — `path` is a file, `path/` is a subtree, `!path` is an
    exclusion, `#` is a comment — because that is the syntax every reader of this repository
    already knows, and a bespoke format would be one more thing to be wrong about.
    """
    include: list[str] = []
    exclude: list[str] = []
    for line in text.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        (exclude if entry.startswith("!") else include).append(entry.removeprefix("!"))
    return include, exclude


def _matches(name: str, entries: list[str]) -> bool:
    """A trailing slash means the whole subtree; anything else is one exact path."""
    return any(name == entry or (entry.endswith("/") and name.startswith(entry))
               for entry in entries)


def published_files(root: Path = REPO) -> list[str]:
    """The files that will exist in the public repository, as this tree can best predict them.

    Public rather than underscore-prefixed because `tools/publish_check.py` imports it: that tool
    materialises exactly this list into a scratch repository and runs the suite there, so the set
    the gate builds and the set this guard sweeps are the same list of strings by construction.
    A second implementation of this would drift in the direction nobody notices — a gate proving
    a file set that is not the one being published.

    **With no manifest, every enumerated file is published.** That is the public repository, where
    `tools/published_set.txt` does not travel, and it is also the safe direction to be wrong in:
    losing the manifest makes this guard scan strictly *more* than it should and fail loudly,
    where the alternative — treating a missing manifest as "nothing is published" — would report
    green over an unswept tree.
    """
    names = _publishable_text_files(root)
    manifest = root / MANIFEST
    if not manifest.is_file():
        return names
    include, exclude = _manifest_rules(manifest.read_text(encoding="utf-8"))
    return [n for n in names if _matches(n, include) and not _matches(n, exclude)]


def _read(rel: str, root: Path = REPO) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _offenders(pattern: re.Pattern[str], root: Path = REPO) -> list[str]:
    """Published files carrying `pattern` outside the fixtures, sorted so messages are stable.

    There is no sanctioned-location parameter, and its absence is the whole difference between
    this file and `tests/test_one_authoritative_location.py`. Shared by the rules below *and* by
    the meta-tests, on purpose: a meta-test that rebuilt this sweep against a throwaway checkout
    would prove only that the rebuild works.
    """
    return sorted(
        name
        for name in published_files(root)
        if name not in FIXTURES and pattern.search(_read(name, root))
    )


def test_the_pattern_would_catch_an_unredacted_id():
    """The guard that stops every assertion below being vacuously true.

    All of them are "this shape does not appear here". A broken pattern satisfies them all.
    """
    assert DEVICE_ID.search('{"devId": "bf1a2b3c4d5e6f7a8bwxyz"}')
    assert LAN_ADDRESS.search("listening on 192.168.0.42:6668")
    assert not DEVICE_ID.search("bfshort") and not LAN_ADDRESS.search("2026.08.22")


def test_no_published_file_records_a_device_id():
    offenders = _offenders(DEVICE_ID)
    assert not offenders, (
        "device ids in files that get published — replace with a made-up one, or move the "
        "value somewhere that does not travel: " + ", ".join(offenders)
    )


def test_no_published_file_records_a_lan_address():
    """Lower stakes than the device id and enforced anyway, because the reason it is low-stakes
    is that there are currently none — an unenforced clean state is a coincidence, not a rule.
    """
    offenders = _offenders(LAN_ADDRESS)
    assert not offenders, (
        "LAN addresses in files that get published — a home network's addressing is not this "
        "repository's to publish: " + ", ".join(offenders)
    )


def test_the_sweep_covers_the_files_it_has_to_and_is_not_empty():
    """The other vacuity guard: an empty file list satisfies both rules above perfectly.

    Every path asserted here is one the guard structurally depends on, so this fails on the
    manifest edit that would quietly narrow the sweep rather than on a cosmetic rename.
    """
    published = published_files()
    assert len(published) > 20, (
        f"the published set is {len(published)} files, which is too few to be the real one — "
        "the sweep above proves nothing over a set this size"
    )

    # This file. If it ever stops being published, the guard is not running where it is claimed
    # to run, and the fixture ids below it would be shipping with nothing sweeping around them.
    assert "tests/test_redaction_rule.py" in published

    # `.gitignore` is a dependency, not housekeeping: `_publishable_text_files` enumerates with
    # `--exclude-standard`, which *is* `.gitignore`, and `throwaway_checkout` mirrors its line 42
    # as the case it is modelling. Publishing this guard without it would leave the exclusion
    # rules to be whatever the cloner's `~/.config/git/ignore` says. It was missing from the
    # published list in [#41] and this is what keeps it there.
    assert ".gitignore" in published


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

    No `tools/published_set.txt` is written here, so this checkout is in the state the public
    repository is in: everything enumerated is published. The two manifest tests write one.

    The device ids are synthetic and obviously so; the real one is never in this file, and
    `tests/test_one_authoritative_location.py` is what keeps that true while this repository
    still has a real one to compare against.
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

    assert "unstaged.md" in _offenders(DEVICE_ID, root)


def test_the_index_is_still_scanned_as_well(throwaway_checkout: Path):
    """`--others` was added alongside `--cached`, not in place of it — and a sweep over a clean
    checkout would keep passing either way, since there is nothing untracked to notice. Asserted
    here so that regression cannot hide behind a green suite.

    This used to assert that `docs/captures/README.md` appeared in the enumeration, which was a
    fine check in a repository that has that file and no check at all in the one this module is
    being published into. Aimed at the fixture instead, it is both repository-independent and
    strictly stronger: `staged.md` is index-only, and reaching `_offenders` proves the guard
    *scans* tracked files rather than merely listing them.
    """
    assert "staged.md" in _offenders(DEVICE_ID, throwaway_checkout)


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

    assert ".cache/creds.json" not in published_files(root)
    assert not [name for name in _offenders(DEVICE_ID, root) if name.startswith(".cache/")]


def test_with_no_manifest_every_enumerated_file_is_published(throwaway_checkout: Path):
    """The public repository's branch of `published_files`, exercised where it can be.

    It cannot be exercised in this repository — there is a manifest here, and there always will
    be — so without this the branch that will run in every public CI job is the one branch this
    suite never takes.
    """
    published = published_files(throwaway_checkout)
    assert set(published) == set(_publishable_text_files(throwaway_checkout))
    assert {"staged.md", "unstaged.md", ".gitignore"} <= set(published)


def test_a_manifest_narrows_the_sweep_to_what_it_names(throwaway_checkout: Path):
    """The other branch: includes admit, exclusions carve back out, and the rest is unpublished.

    Without this, `tools/published_set.txt` could name anything at all and the sweep over this
    repository would keep passing — it is a filter, and a filter that silently matches nothing
    turns a guard into a formality.
    """
    root = throwaway_checkout
    (root / "docs").mkdir()
    # A fifth synthetic id, fabricated like the others and named after the file it lives in. It
    # has to be a *new* value rather than a reused one: this test's whole claim is that the sweep
    # stops seeing this file, and a value that also appears somewhere the sweep still reads would
    # make the final assertion pass for the wrong reason.
    (root / "docs" / "private.md").write_text(
        "device id bf0000000000000000docs\n", encoding="utf-8"
    )
    (root / "tools").mkdir()
    (root / "tools" / "published_set.txt").write_text(
        "# a manifest of its own\nstaged.md\ndocs/\n!docs/private.md\n", encoding="utf-8"
    )

    # `unstaged.md` is named by no include, `docs/private.md` by an include and then an
    # exclusion, and `tools/published_set.txt` is the manifest itself — none of the three travel.
    published = published_files(root)
    assert published == ["staged.md"], published

    # Both directions in one assertion. The carved-out file holds an id the sweep no longer sees,
    # which is exactly the arrangement this repository relies on for `docs/research/dossier.md`;
    # the published file's id is still caught, so narrowing the sweep did not disarm it.
    assert DEVICE_ID.search(_read("docs/private.md", root))
    assert _offenders(DEVICE_ID, root) == ["staged.md"]
