"""Tests that Home Assistant and HACS can *load* this repository at all.

Not behaviour — packaging. The failures these catch surface at Home Assistant startup or
at HACS install time, in a house, rather than at review time here.

**Why these are tests rather than the HACS action.** `hacs/action` was in the CI workflow
first and could not do the job, for a structural reason worth writing down: its metadata
checks go through the authenticated GitHub API, but every *file content* check downloads
from `https://raw.githubusercontent.com/{repo}/{ref}/{path}` with no credentials at all
(`repositories/base.py::get_hacs_json_raw`, `repositories/integration.py::
get_integration_manifest`). **This repository is private, so those URLs 404**, the download
returns None, and the validator reports the file as invalid. Confirmed both ways: the run
failed exactly on `hacsjson` and `integration_manifest` while every tree- and metadata-based
check passed, and both raw URLs return 404 to an unauthenticated client.

So the schemas below are transcribed from HACS's own
`custom_components/hacs/utils/validate.py` and applied to the working tree, which is
strictly better here — the real rules, on the actual files, with no network and no
dependence on the repository being public. The cost is that a schema change upstream will
not reach us on its own; that is the trade, and it is written here so it is not forgotten.
"""

from __future__ import annotations

import json
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
