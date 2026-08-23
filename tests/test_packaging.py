"""Tests that Home Assistant and HACS can *load* this repository at all.

Not behaviour — packaging. The failures these catch surface at Home Assistant startup or
at HACS install time, in a house, rather than at review time here.

**Why these are tests rather than the HACS action.** `hacs/action` was in the CI workflow
first and could not do the job, for a structural reason worth writing down: its metadata
checks go through the authenticated GitHub API, but every *file content* check downloads
from `https://raw.githubusercontent.com/{repo}/{ref}/{path}` with no credentials at all
(`repositories/base.py::get_hacs_json_raw`, `repositories/integration.py::
get_integration_manifest`). **Those URLs 404 for any repository the unauthenticated fetch
cannot read**, the download returns None, and the validator reports as invalid a file it
never saw — a property of the action, not of the repository it is aimed at. Confirmed both
ways at the time: the run failed exactly on `hacsjson` and `integration_manifest` while every
tree- and metadata-based check passed, and both raw URLs returned 404 to an unauthenticated
client.

So the schemas below are transcribed from HACS's own
`custom_components/hacs/utils/validate.py` and applied to the working tree, which is
strictly better here — the real rules, on the actual files, with no network and no
dependence on who can read the repository. The cost is that a schema change upstream will
not reach us on its own; that is the trade, and it is written here so it is not forgotten.
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
