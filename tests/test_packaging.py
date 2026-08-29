"""Tests that Home Assistant and HACS can *load* this repository at all.

Not behaviour — packaging. The failures these catch surface at Home Assistant startup or
at HACS install time, in a house, rather than at review time here.

**Why these are tests rather than the HACS action.** `hacs/action` was in the CI workflow
first and could not do the job, for a structural reason worth writing down: its metadata
checks go through the authenticated GitHub API, but every *file content* check downloads
from `https://raw.githubusercontent.com/{repo}/{ref}/{path}` with no credentials at all
(`repositories/base.py::get_hacs_json_raw`, `repositories/integration.py::
get_integration_manifest`). **Those URLs 404 for any repository the unauthenticated fetch
cannot read**, which this one was for the whole of the development that produced it. The
download returns None and the validator reports as invalid a file it never saw — a property
of the action, not of the repository it is aimed at. Confirmed both ways at the time: the run
failed exactly on `hacsjson` and `integration_manifest` while every tree- and metadata-based
check passed, and both raw URLs returned 404 to an unauthenticated client.

So the schemas below are transcribed from HACS's own
`custom_components/hacs/utils/validate.py` and applied to the working tree, which is
strictly better here — the real rules, on the actual files, with no network and no
dependence on who can read the repository. The cost is that a schema change upstream will
not reach us on its own; that is the trade, and it is written here so it is not forgotten.

**That reason had an expiry date, and publication was it — the job is back.** The raw URLs
resolve for an unauthenticated client against the public repository, so `hacs/action` runs
again in `.github/workflows/validate.yml`, where the comment beside it carries this history.
It is guarded by the repository name, because this file runs in the private archive too and
the 404s there are exactly what they always were.

**These tests are not replaced by it, and the difference is not politeness.** They need no
network and no repository, so they are the half that still runs on every pull request
*here* — including the ones that break the manifest, which is where a packaging error is
cheapest to catch. The action covers what a local test cannot reach: `license`, and the
schemas as HACS currently has them rather than as they were transcribed. Each is the
other's blind spot.

`brands` used to be on that list and has moved across, which is worth saying because the
boundary moved rather than the rule. A custom integration may now carry its own brand
images (Home Assistant 2026.3.0), and HACS accepts them in place of the domain being
registered in home-assistant/brands — so the files the check reads are in this tree, and a
local test can read them too. The action still asks the question the way HACS asks it; the
tests below assert the sizes, which is the half that goes wrong quietly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import voluptuous as vol
from awesomeversion import AwesomeVersion

REPO = Path(__file__).resolve().parent.parent

#: Transcribed from HACS's HACS_MANIFEST_JSON_SCHEMA. `PREVENT_EXTRA` is the part that
#: earns its place: a typo'd optional key ("conten_in_root") is otherwise silently ignored
#: by us and rejected by HACS, which is the worst of both.
HACS_MANIFEST_SCHEMA = vol.Schema(
    {
        vol.Optional("content_in_root"): bool,
        vol.Optional("country"): vol.Any(str, [str]),
        vol.Optional("filename"): str,
        vol.Optional("hacs"): str,
        vol.Optional("hide_default_branch"): bool,
        vol.Optional("homeassistant"): str,
        vol.Optional("persistent_directory"): str,
        vol.Optional("render_readme"): bool,
        vol.Optional("zip_release"): bool,
        vol.Required("name"): str,
    },
    extra=vol.PREVENT_EXTRA,
)

#: Transcribed from HACS's INTEGRATION_MANIFEST_JSON_SCHEMA. `ALLOW_EXTRA`, because Home
#: Assistant's own manifest carries far more than HACS looks at; these six are the ones
#: whose absence breaks a HACS install.
INTEGRATION_MANIFEST_SCHEMA = vol.Schema(
    {
        vol.Required("codeowners"): list,
        vol.Required("documentation"): vol.Match(r"^https?://"),
        vol.Required("domain"): str,
        vol.Required("issue_tracker"): vol.Match(r"^https?://"),
        vol.Required("name"): str,
        vol.Required("version"): vol.Coerce(AwesomeVersion),
    },
    extra=vol.ALLOW_EXTRA,
)


#: `**Home Assistant 2026.8.1** is what this is developed and tested against` — the sentence
#: the README's Install section opens with, which is the promise a user reads before installing.
README_TESTED_VERSION = re.compile(r"\*\*Home Assistant ([\d.]+)\*\* is what this is developed")

#: `homeassistant==2026.8.1` in requirements_test.txt — the core this suite actually runs against.
PINNED_CORE_VERSION = re.compile(r"^homeassistant==([\d.]+)\s*$", re.MULTILINE)

#: `tinytuya==1.20.0` in requirements_test.txt — the version CI actually exercises.
PINNED_TINYTUYA_VERSION = re.compile(r"^tinytuya==([\d.]+)\s*$", re.MULTILINE)

#: A manifest requirement that names one version and no other. Anchored on `==` because
#: that is the entire property being asserted: anything with a range in it is a promise
#: about versions nobody ran. `;` is excluded from the version so an environment marker
#: (`foo==1.0; python_version < "3.13"`) is parsed rather than swallowed.
EXACT_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)")


@pytest.fixture
def integration_dir() -> Path:
    """The one integration directory, asserted to be the only one.

    HACS installs a single integration per repository. Two directories under
    `custom_components/` is not a richer repository; it is one HACS will pick from
    arbitrarily.
    """
    candidates = sorted(p for p in (REPO / "custom_components").iterdir() if p.is_dir())
    assert len(candidates) == 1, f"expected exactly one integration, found {candidates}"
    return candidates[0]


def test_hacs_json_matches_the_schema_hacs_enforces():
    hacs_json = json.loads((REPO / "hacs.json").read_text())
    HACS_MANIFEST_SCHEMA(hacs_json)


def test_the_minimum_home_assistant_version_is_the_one_that_was_tested():
    """One fact, written down in three independent places, only one of which has teeth.

    `hacs.json`'s `homeassistant` is the floor HACS enforces — it refuses to download onto
    an older core rather than letting the install fail at runtime, in a house. The schema
    above only asks for a string, so nothing but this test stops that string from being a
    version nobody ran.

    It is also the copy nobody reads, so it is the one that drifts when the tested core is
    bumped in `requirements_test.txt` and the README. Declaring a floor *below* what was
    tested would be worse than declaring none at all: an untested guess that HACS then
    presents to the user as a guarantee.
    """
    hacs_json = json.loads((REPO / "hacs.json").read_text())
    assert "homeassistant" in hacs_json, (
        "hacs.json declares no minimum Home Assistant version, so HACS will offer this "
        "integration to a core that cannot run it"
    )
    declared = hacs_json["homeassistant"]

    pinned = PINNED_CORE_VERSION.search((REPO / "requirements_test.txt").read_text())
    assert pinned, "requirements_test.txt no longer pins `homeassistant==`"
    assert declared == pinned.group(1), (
        f"hacs.json requires Home Assistant {declared}, but the suite runs against "
        f"{pinned.group(1)} — bump both, or the floor is a version nobody tested"
    )

    promised = README_TESTED_VERSION.search((REPO / "README.md").read_text())
    assert promised, (
        "README.md no longer opens Install with `**Home Assistant X.Y.Z** is what this is "
        "developed and tested against` — point this test at the new wording rather than "
        "dropping the check"
    )
    assert declared == promised.group(1), (
        f"hacs.json requires Home Assistant {declared}, README.md promises "
        f"{promised.group(1)} — a user reading one and HACS enforcing the other"
    )


def test_integration_manifest_matches_the_schema_hacs_enforces(integration_dir: Path):
    manifest = json.loads((integration_dir / "manifest.json").read_text())
    INTEGRATION_MANIFEST_SCHEMA(manifest)


def test_every_manifest_requirement_names_exactly_one_version(integration_dir: Path):
    """A range in `requirements` ships a version nobody tested into somebody's house.

    Home Assistant installs these with pip when it loads the integration, so the resolved
    version is decided on the user's machine, on the day they install — not here, and not
    by anything this repository can see afterwards. `tinytuya>=1.16.0` meant a tinytuya 2.0
    with a changed `status()` return shape would arrive in every install with no commit in
    this repository, and the first anyone would know of it is entities going `unavailable`.

    Core does not leave this open: of the 1483 integrations in the 2026.8.1 wheel, 1218
    requirements use `==` and **zero** use a range. Not a convention with exceptions — a
    convention with no counterexamples.

    The exposure is sharper here than the line count suggests, because `device.py` leans on
    three tinytuya behaviours that are documented nowhere but its own docstring: that
    `status()` returns a dict carrying a `"dps"` key, that a failed exchange comes back as
    an error payload rather than raising, and that `set_value()` echoes the new state.
    """
    manifest = json.loads((integration_dir / "manifest.json").read_text())
    for requirement in manifest.get("requirements", []):
        assert EXACT_PIN.match(requirement), (
            f"{requirement!r} does not pin one version. Home Assistant resolves this on the "
            f"user's machine, so a range means the installed version is whatever pip picks "
            f"that day — write it as `name==version`"
        )


def test_the_shipped_tinytuya_is_the_one_the_suite_ran(integration_dir: Path):
    """The same fact in two files, one of which ships and the other of which is tested.

    `manifest.json` is what gets installed into a user's Home Assistant.
    `requirements_test.txt` is what CI proves the code works against. Neither file can see
    the other, and only one of them is exercised by anything — so the drift is silent in
    the direction that matters: a green suite, and a different library in the house.

    Asserting equality rather than compatibility is deliberate. "The manifest allows what
    the suite ran" is satisfied by a range, which is the thing being removed; the property
    worth having is that the version a user gets is the version a test result refers to.
    """
    manifest = json.loads((integration_dir / "manifest.json").read_text())
    shipped = [
        match.group(2)
        for match in map(EXACT_PIN.match, manifest.get("requirements", []))
        if match and match.group(1) == "tinytuya"
    ]
    assert shipped, (
        "manifest.json no longer pins `tinytuya==` — if the transport moved off tinytuya, "
        "retire this test with it rather than deleting the assertion"
    )

    pinned = PINNED_TINYTUYA_VERSION.search((REPO / "requirements_test.txt").read_text())
    assert pinned, "requirements_test.txt no longer pins `tinytuya==`"
    assert shipped == [pinned.group(1)], (
        f"manifest.json ships tinytuya {shipped} but the suite ran against "
        f"{pinned.group(1)} — the tests say nothing about the library users get"
    )


def test_the_directory_name_is_the_domain(integration_dir: Path):
    """Home Assistant resolves a component by directory name and trusts `domain` to match.

    They are two independent strings that must be equal, which is exactly the kind of pair
    that drifts during a rename — and the symptom is an integration that cannot be loaded
    at all, with a message about neither of them.
    """
    manifest = json.loads((integration_dir / "manifest.json").read_text())
    assert manifest["domain"] == integration_dir.name


def test_the_version_is_one_home_assistant_can_order(integration_dir: Path):
    """A custom integration's `version` is what HACS compares to offer an update.

    Home Assistant requires the key to exist; HACS requires it to *sort*. A value that
    parses but does not order (an empty string, a date with no separators) yields an
    integration that can be installed and never updated.
    """
    manifest = json.loads((integration_dir / "manifest.json").read_text())
    version = AwesomeVersion(manifest["version"])
    assert version.valid, f"{manifest['version']!r} is not an orderable version"


def test_every_platform_the_integration_forwards_has_a_module(integration_dir: Path):
    """`PLATFORMS` is a list of strings; a typo in it fails at runtime, not at import.

    Read as text rather than imported, so this test keeps `tests/test_packaging.py`
    runnable without Home Assistant installed.
    """
    source = (integration_dir / "__init__.py").read_text()
    block = source.split("PLATFORMS: list[Platform] = [", 1)[1].split("]", 1)[0]
    platforms = [line.strip().rstrip(",").removeprefix("Platform.").lower()
                 for line in block.splitlines() if "Platform." in line]
    assert platforms, "no platforms parsed — has the PLATFORMS declaration changed shape?"
    for platform in platforms:
        assert (integration_dir / f"{platform}.py").is_file(), (
            f"__init__.py forwards to {platform!r}, but {platform}.py does not exist"
        )


#: The brand images HACS's `brands` validator accepts in place of the domain being
#: registered in home-assistant/brands, and the exact size each one has to be. `icon.png`
#: is the only required entry; the rest are optional and are asserted only if present, so
#: dropping one is a decision rather than a test failure, and mis-sizing one is not.
#:
#: Sizes are from the brands repository's own README. A wrong size is the realistic
#: regression here — somebody re-exports an image and it comes out 250x250, or flattened
#: to RGB against a white background, and the failure surfaces as a rejected submission
#: months later rather than as a red run.
BRAND_IMAGES = {
    "icon.png": (256, 256),
    "icon@2x.png": (512, 512),
    "dark_icon.png": (256, 256),
    "dark_icon@2x.png": (512, 512),
}

#: PNG colour type 6 is truecolour with alpha. Asserted because transparency is what makes
#: an icon usable on both Home Assistant themes, and a flatten is invisible in a file
#: listing: the dimensions still pass, the bytes are still a PNG, and the icon quietly
#: acquires a white box around it on the dark theme.
PNG_RGBA = 6


def _ihdr(path: Path) -> tuple[int, int, int, int]:
    """(width, height, bit depth, colour type) from a PNG's header, without Pillow.

    Read from the bytes rather than through an image library on purpose. Pillow reaches
    this suite only as a transitive dependency of `homeassistant`, and the whole point of
    this module is that it runs with nothing installed — parsing 33 bytes is cheaper than
    either a new pin or a skip that hides the check on the day it would have fired.
    """
    raw = path.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    assert raw[12:16] == b"IHDR", f"{path.name} does not start with an IHDR chunk"
    width = int.from_bytes(raw[16:20], "big")
    height = int.from_bytes(raw[20:24], "big")
    return width, height, raw[24], raw[25]


def test_the_required_brand_icon_exists(integration_dir: Path):
    """HACS's `brands` check passes on this file, and only this file is required.

    Without it the check fails, and the workflow may not paper over that with `ignore:`
    — HACS's default store requires its action to pass with no ignores at all, so a
    suppressed check and a failing one cost exactly the same thing.
    """
    assert (integration_dir / "brand" / "icon.png").is_file(), (
        "custom_components/<domain>/brand/icon.png is what satisfies HACS's brands check "
        "for a custom integration that is not registered in home-assistant/brands"
    )


@pytest.mark.parametrize("name", sorted(BRAND_IMAGES))
def test_every_brand_image_present_is_the_size_the_spec_names(integration_dir: Path, name: str):
    path = integration_dir / "brand" / name
    if not path.is_file():
        pytest.skip(f"{name} is optional and not shipped")
    width, height, depth, colour = _ihdr(path)
    assert (width, height) == BRAND_IMAGES[name], (
        f"{name} is {width}x{height}, the brands spec says {BRAND_IMAGES[name]}"
    )
    assert depth == 8, f"{name} is {depth}-bit; the spec's sizes assume 8"
    assert colour == PNG_RGBA, (
        f"{name} has PNG colour type {colour}, not {PNG_RGBA} (truecolour with alpha) — "
        "it has been flattened, and will show a solid box on one of the two themes"
    )


def test_the_logo_is_landscape_with_its_short_side_in_range(integration_dir: Path):
    """`logo.png` is the one brand image the spec sizes by *ratio* rather than exactly.

    Landscape, shortest side 128-256 (256-512 for @2x). It is optional, so absence is a
    skip; being square is not, because a square logo is an icon filed under the wrong name
    and Home Assistant will letterbox it wherever it expects a wordmark.
    """
    for name, (low, high) in (("logo.png", (128, 256)), ("logo@2x.png", (256, 512))):
        path = integration_dir / "brand" / name
        if not path.is_file():
            continue
        width, height, _, colour = _ihdr(path)
        assert width > height, f"{name} is {width}x{height}, which is not landscape"
        assert low <= height <= high, (
            f"{name}'s short side is {height}; the spec says {low}-{high}"
        )
        assert colour == PNG_RGBA, f"{name} has PNG colour type {colour}, not {PNG_RGBA}"
