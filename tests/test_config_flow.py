"""Tests for the setup form, and specifically for what a *rejected* attempt renders.

The failure these pin is a usability one, not a crash. Validation is a real status query,
so a wrong protocol version and a wrong local key both surface as `cannot_connect` - the
socket opens either way and the reply simply fails to decrypt. The documented remedy is
therefore "try 3.4, then 3.3, before doubting the key", which means the retry form is a
control the first-time installer is expected to use two or three times in a row. Before
this, every one of those retries handed back a blank form with the version reset to 3.5:
the one field they meant to change was the one field that silently reverted, and the price
of changing it was re-typing a 22-character device ID and a 16-character key.

`add_suggested_values_to_schema` is the mechanism, and these tests assert its two halves
separately, because they fail in opposite directions: the text fields need a
`suggested_value` where they previously had nothing, and the version dropdown needs the
suggestion to *win over* a `default=` that is still, correctly, 3.5 for a first run.

There is no `pytest_homeassistant_custom_component` here and no hass fixture, so the flow
handler is driven directly - see `_flow()` for what that costs.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant", reason="config-flow tests need Home Assistant")

import voluptuous as vol
from homeassistant.const import CONF_HOST

from custom_components.arozen_eon import config_flow as config_flow_module
from custom_components.arozen_eon.config_flow import (
    DEFAULT_TITLE,
    STEP_USER_SCHEMA,
    ArozenConfigFlow,
)
from custom_components.arozen_eon.const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
)
from custom_components.arozen_eon.device import ArozenError

#: Shaped like the real thing - a 22-character Tuya device ID and a 16-character local key -
#: because the length is the whole argument for suggesting them back.
SUBMITTED = {
    CONF_HOST: "192.0.2.10",
    CONF_DEVICE_ID: "test-device-id",
    CONF_LOCAL_KEY: "0123456789abcdef",
    CONF_PROTOCOL_VERSION: "3.4",
}


def _flow() -> ArozenConfigFlow:
    """A flow handler with no Home Assistant behind it.

    `async_step_user` reaches into hass in exactly two places, both on the submit path:
    `async_set_unique_id` and `_abort_if_unique_id_configured`, which read
    `self.hass.config_entries` to spot a diffuser that is already set up. Neutering that
    pair on the instance is what makes the step runnable here; the duplicate-entry guard is
    not what these tests are about. Everything else the step touches is pure and works off
    `FlowHandler`'s class defaults - `async_show_form`, `add_suggested_values_to_schema`
    and `async_create_entry` only ever build a result dict, and `context` defaults to an
    empty mapping so `self.source` reads None, which is neither reauth nor reconfigure.
    """
    flow = ArozenConfigFlow()

    async def _async_set_unique_id(unique_id, *, raise_on_progress=True):
        return None

    flow.async_set_unique_id = _async_set_unique_id
    flow._abort_if_unique_id_configured = lambda *args, **kwargs: None
    return flow


def _rendered(result) -> dict[str, dict]:
    """What the frontend would put in each box, keyed by field name.

    `suggested` is the value the field is pre-filled with; `default` is the fallback used
    only when there is no suggestion. Reading both matters for the version dropdown, where
    the bug was the default winning over a suggestion that was never set.
    """
    fields = {}
    for marker in result["data_schema"].schema:
        description = marker.description or {}
        fields[marker.schema] = {
            "suggested": description.get("suggested_value"),
            "default": None if marker.default is vol.UNDEFINED else marker.default(),
        }
    return fields


@pytest.fixture
def rejecting(monkeypatch):
    """Make the device reject whatever it is handed, the way a wrong version presents."""

    async def _reject(host, device_id, local_key, protocol_version):
        raise ArozenError("no response")

    monkeypatch.setattr(config_flow_module, "_async_validate", _reject)


# -- First run ----------------------------------------------------------------------------


async def test_first_run_shows_empty_fields():
    """No suggestions at all when the form has never been submitted.

    `add_suggested_values_to_schema` is called with `user_input=None` on this path, and
    treats it as "nothing to suggest" - it copies the schema and touches no marker. That is
    what keeps hoisting the schema to a module constant free of side effects on first run.
    """
    result = await _flow().async_step_user()

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    fields = _rendered(result)
    assert set(fields) == {
        CONF_HOST,
        CONF_DEVICE_ID,
        CONF_LOCAL_KEY,
        CONF_PROTOCOL_VERSION,
    }
    for name in (CONF_HOST, CONF_DEVICE_ID, CONF_LOCAL_KEY):
        assert fields[name]["suggested"] is None, name


async def test_first_run_preselects_3_5():
    # 3.5 is what the device answered on the LAN 2026-08-21; it stays the opening guess.
    version = _rendered(await _flow().async_step_user())[CONF_PROTOCOL_VERSION]

    assert version["default"] == "3.5"
    assert version["suggested"] is None


async def test_first_run_reports_no_errors():
    # The error banner is driven by this dict; an empty one is what keeps it off the form.
    assert (await _flow().async_step_user())["errors"] == {}


# -- Rejected attempt ---------------------------------------------------------------------


async def test_rejected_attempt_reports_cannot_connect(rejecting):
    result = await _flow().async_step_user(dict(SUBMITTED))

    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_rejected_attempt_carries_host_and_device_id_back(rejecting):
    """The two values that are pure transcription and cost the most to re-type."""
    fields = _rendered(await _flow().async_step_user(dict(SUBMITTED)))

    assert fields[CONF_HOST]["suggested"] == "192.0.2.10"
    assert fields[CONF_DEVICE_ID]["suggested"] == "test-device-id"


async def test_rejected_attempt_carries_the_chosen_version_not_the_default(rejecting):
    """The regression that motivated the issue.

    The marker still carries `default="3.5"`, and must - that is first-run behaviour. What
    changed is that a suggestion now sits alongside it and takes precedence in the rendered
    form, so iterating 3.5 -> 3.4 -> 3.3 no longer springs back to 3.5 between attempts.
    """
    fields = _rendered(await _flow().async_step_user(dict(SUBMITTED)))

    assert fields[CONF_PROTOCOL_VERSION]["suggested"] == "3.4"
    assert fields[CONF_PROTOCOL_VERSION]["default"] == "3.5"


async def test_rejected_attempt_carries_the_local_key_back(rejecting):
    """Deliberate, and the one call here that could reasonably have gone the other way.

    Echoing a live credential is a different decision from echoing an IP address, and was
    made as one: 16 characters the owner cannot proof-read by eye, going back only to the
    session that just typed them, into a field that is not masked on the way in either -
    the frontend infers masking for a plain `str` from a name containing "password",
    "secret" or "token", and `local_key` matches none. Blanking it would tax the correct
    answer to punish nothing. Core lands the same way: 46 of its 109
    `add_suggested_values_to_schema` sites over a secret-bearing schema pass bare
    `user_input`; 2 strip the secret. A future reader who flips this should delete this
    test on purpose rather than watch it fail.
    """
    fields = _rendered(await _flow().async_step_user(dict(SUBMITTED)))

    assert fields[CONF_LOCAL_KEY]["suggested"] == "0123456789abcdef"


async def test_unexpected_error_carries_the_input_back_too(monkeypatch):
    """The `unknown` branch re-shows the same form, so it must not lose the input either."""

    async def _explode(host, device_id, local_key, protocol_version):
        raise RuntimeError("something else entirely")

    monkeypatch.setattr(config_flow_module, "_async_validate", _explode)

    result = await _flow().async_step_user(dict(SUBMITTED))

    assert result["errors"] == {"base": "unknown"}
    assert _rendered(result)[CONF_DEVICE_ID]["suggested"] == "test-device-id"


async def test_a_retry_does_not_pollute_the_next_flow(rejecting):
    """The hoisted schema is shared module state, so prove nothing sticks to it.

    `add_suggested_values_to_schema` copies each marker before setting its description,
    which is what makes the constant safe to share. Were it to mutate in place, one user's
    local key would pre-fill the next flow's form.
    """
    await _flow().async_step_user(dict(SUBMITTED))

    assert all(marker.description is None for marker in STEP_USER_SCHEMA.schema)
    assert _rendered(await _flow().async_step_user())[CONF_LOCAL_KEY]["suggested"] is None


# -- Accepted attempt ---------------------------------------------------------------------


async def test_successful_submit_creates_the_entry(monkeypatch):
    """The happy path is unchanged by all of the above - the schema move touches only the
    form, and validation still gets the four values in the order `_async_validate` takes."""
    validated = []

    async def _accept(host, device_id, local_key, protocol_version):
        validated.append((host, device_id, local_key, protocol_version))
        return {"1": True}

    monkeypatch.setattr(config_flow_module, "_async_validate", _accept)

    result = await _flow().async_step_user(dict(SUBMITTED))

    assert result["type"] == "create_entry"
    assert result["title"] == DEFAULT_TITLE
    assert result["data"] == SUBMITTED
    assert validated == [
        ("192.0.2.10", "test-device-id", "0123456789abcdef", "3.4")
    ]


async def test_successful_submit_strips_pasted_whitespace(monkeypatch):
    """These four values arrive by copy-paste from a key dump, trailing spaces and all."""

    async def _accept(host, device_id, local_key, protocol_version):
        return {"1": True}

    monkeypatch.setattr(config_flow_module, "_async_validate", _accept)

    padded = {key: f"  {value}  " for key, value in SUBMITTED.items()}
    padded[CONF_PROTOCOL_VERSION] = SUBMITTED[CONF_PROTOCOL_VERSION]

    result = await _flow().async_step_user(padded)

    assert result["data"] == SUBMITTED


# -- The copy above the fields ------------------------------------------------------------


def _user_step_descriptions() -> list[str]:
    """The description as each of the two string files carries it.

    `strings.json` is what hassfest validates; `translations/en.json` is what a running
    instance actually renders. They are conventionally identical, so an edit to one and
    not the other ships a dialog nobody reviewed.
    """
    import json
    from pathlib import Path

    root = Path(config_flow_module.__file__).parent
    return [
        json.loads(path.read_text(encoding="utf-8"))["config"]["step"]["user"]["description"]
        for path in (root / "strings.json", root / "translations" / "en.json")
    ]


def test_the_two_string_files_agree_on_the_setup_description():
    first, second = _user_step_descriptions()

    assert first == second


def test_the_setup_description_speaks_to_a_stranger():
    """No project vocabulary, and the QR-login tool named as the route to take.

    This string is the one screen every installer sees, before they have read anything of
    this repository. "The recon step" is our own history showing through: it means a
    document they have not opened and are not going to open while staring at four empty
    fields.
    """
    for description in _user_step_descriptions():
        assert "recon" not in description.lower()
        assert "tuya-local-key" in description


def test_the_setup_description_carries_no_url():
    """A URL here outlives the repository name it is written against.

    The pointer is the README, named rather than linked, so a rename cannot leave a dead
    link in the setup dialog.
    """
    for description in _user_step_descriptions():
        assert "http" not in description.lower()


def test_the_setup_description_still_warns_about_the_local_key():
    """Someone is pasting a live secret into a form; the warning is the point of the text."""
    for description in _user_step_descriptions():
        assert (
            "The local key is a live credential — it is stored in Home Assistant's "
            "config entry like any other integration secret." in description
        )
