"""Tests for the reconfigure step — the in-place fix for credentials that moved.

The properties worth pinning, because getting any of them wrong is silent damage to a
working installation rather than a visible failure:

* **the device ID survives, and so does the entry** — it is the entry's `unique_id`, and a
  reconfigure that changed it would be adding a different device under the old entry's
  history and entity ids. The step does not offer it as a field at all, so the test asserts
  both halves: it is absent from the form, and it is still in `entry.data` afterwards;
* **bad credentials change nothing** — validation opens a real connection, so a wrong new
  key must fail in the dialog. If it did not, the entry would be overwritten with a key that
  cannot talk to the device and the only route back would be the delete-and-re-add this step
  exists to avoid;
* **the entry is reloaded exactly once** — `__init__.py` registers an update listener that
  reloads on any change, which is why the step calls `async_update_and_abort` rather than
  `async_update_reload_and_abort`. The fake below fires listeners the way Home Assistant
  does, so the test sees the reload happen without a second one being scheduled.

There is no `pytest_homeassistant_custom_component` in this project's pins, so the flow is
driven directly: a real `ArozenConfigFlow`, a context shaped like the one the config-entries
manager builds for `SOURCE_RECONFIGURE`, and a fake `hass.config_entries` implementing the
three methods the step reaches. The fake mirrors `homeassistant.config_entries` 2026.8.1 —
`UNDEFINED` means "leave this field alone", and listeners fire only when something actually
changed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant", reason="config flow tests need Home Assistant installed")

import voluptuous as vol
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.typing import UNDEFINED

from custom_components.arozen_eon import config_flow as config_flow_module
from custom_components.arozen_eon.config_flow import ArozenConfigFlow
from custom_components.arozen_eon.const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DOMAIN,
)
from custom_components.arozen_eon.device import ArozenUnreachable

#: The entry as it stands before a re-pair: a working device ID, a local key that has just
#: been invalidated, and the 3.5 observed on the LAN.
STORED = {
    CONF_HOST: "192.0.2.10",
    CONF_DEVICE_ID: "test-device-id",
    CONF_LOCAL_KEY: "oldkeyoldkey0000",
    CONF_PROTOCOL_VERSION: "3.5",
}

NEW_INPUT = {
    CONF_HOST: "192.0.2.20",
    CONF_LOCAL_KEY: "newkeynewkey1111",
    CONF_PROTOCOL_VERSION: "3.4",
}


class FakeEntry:
    """The attributes the reconfigure path reads or writes on a ConfigEntry."""

    def __init__(self, data: dict[str, str]) -> None:
        self.entry_id = "entry-under-test"
        self.domain = DOMAIN
        self.title = config_flow_module.DEFAULT_TITLE
        self.data = dict(data)
        self.unique_id = data[CONF_DEVICE_ID]
        self.update_listeners: list[object] = []


class FakeConfigEntries:
    """The three `hass.config_entries` methods the step can reach.

    `async_update_entry` follows the real one's contract closely enough for the assertions
    to mean something: it only writes fields that are not UNDEFINED, it returns whether
    anything changed, and it notifies the entry's update listeners only when it did.
    """

    def __init__(self, entry: FakeEntry) -> None:
        self._entry = entry
        self.reload_calls: list[str] = []
        self.listener_calls: list[str] = []

    def async_get_known_entry(self, entry_id: str) -> FakeEntry:
        assert entry_id == self._entry.entry_id
        return self._entry

    def async_update_entry(self, *, entry, unique_id, title, data, options) -> bool:
        changed = False
        if unique_id is not UNDEFINED and entry.unique_id != unique_id:
            entry.unique_id = unique_id
            changed = True
        if title is not UNDEFINED and entry.title != title:
            entry.title = title
            changed = True
        if data is not UNDEFINED and entry.data != data:
            entry.data = dict(data)
            changed = True
        if options is not UNDEFINED:
            changed = True
        if changed:
            # Home Assistant schedules these as tasks; recording the call is enough here.
            for _listener in entry.update_listeners:
                self.listener_calls.append(entry.entry_id)
        return changed

    def async_schedule_reload(self, entry_id: str) -> None:
        self.reload_calls.append(entry_id)


class FakeHass:
    def __init__(self, entry: FakeEntry) -> None:
        self.config_entries = FakeConfigEntries(entry)


def _flow(entry: FakeEntry) -> ArozenConfigFlow:
    """A flow wired up the way the manager wires one for a reconfigure."""
    flow = ArozenConfigFlow()
    flow.hass = FakeHass(entry)
    flow.handler = DOMAIN
    flow.flow_id = "flow-under-test"
    flow.context = {"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    return flow


def _entry_with_listener() -> FakeEntry:
    """An entry as __init__.py leaves it: one update listener, registered at setup."""
    entry = FakeEntry(STORED)
    entry.update_listeners.append(object())
    return entry


def _schema_keys(schema: vol.Schema) -> set[str]:
    return {str(marker.schema) for marker in schema.schema}


def _suggested(schema: vol.Schema) -> dict[str, object]:
    return {
        str(marker.schema): (marker.description or {}).get("suggested_value")
        for marker in schema.schema
    }


# -- The form -----------------------------------------------------------------------------


async def test_form_offers_the_three_drifting_values_and_not_the_device_id():
    entry = _entry_with_listener()
    flow = _flow(entry)

    result = await flow.async_step_reconfigure()

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert _schema_keys(result["data_schema"]) == {
        CONF_HOST,
        CONF_LOCAL_KEY,
        CONF_PROTOCOL_VERSION,
    }
    assert CONF_DEVICE_ID not in _schema_keys(result["data_schema"])


async def test_form_shows_the_device_id_it_will_not_let_you_change():
    entry = _entry_with_listener()
    flow = _flow(entry)

    result = await flow.async_step_reconfigure()

    assert result["description_placeholders"] == {CONF_DEVICE_ID: STORED[CONF_DEVICE_ID]}


async def test_form_prefills_from_the_stored_entry():
    entry = _entry_with_listener()
    flow = _flow(entry)

    result = await flow.async_step_reconfigure()

    assert _suggested(result["data_schema"]) == {
        CONF_HOST: STORED[CONF_HOST],
        CONF_LOCAL_KEY: STORED[CONF_LOCAL_KEY],
        CONF_PROTOCOL_VERSION: STORED[CONF_PROTOCOL_VERSION],
    }


# -- Success ------------------------------------------------------------------------------


async def test_new_credentials_are_validated_against_the_stored_device_id(monkeypatch):
    """The device ID is not a form field, so it has to come from the entry."""
    entry = _entry_with_listener()
    calls: list[tuple[str, str, str, str]] = []

    async def fake_validate(host, device_id, local_key, protocol_version):
        calls.append((host, device_id, local_key, protocol_version))
        return {2: True}

    monkeypatch.setattr(config_flow_module, "_async_validate", fake_validate)

    await _flow(entry).async_step_reconfigure(dict(NEW_INPUT))

    assert calls == [
        (
            NEW_INPUT[CONF_HOST],
            STORED[CONF_DEVICE_ID],
            NEW_INPUT[CONF_LOCAL_KEY],
            NEW_INPUT[CONF_PROTOCOL_VERSION],
        )
    ]


async def test_accepted_credentials_update_the_entry_in_place(monkeypatch):
    entry = _entry_with_listener()

    async def fake_validate(host, device_id, local_key, protocol_version):
        return {2: True}

    monkeypatch.setattr(config_flow_module, "_async_validate", fake_validate)

    flow = _flow(entry)
    result = await flow.async_step_reconfigure(dict(NEW_INPUT))

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {
        CONF_HOST: NEW_INPUT[CONF_HOST],
        CONF_DEVICE_ID: STORED[CONF_DEVICE_ID],
        CONF_LOCAL_KEY: NEW_INPUT[CONF_LOCAL_KEY],
        CONF_PROTOCOL_VERSION: NEW_INPUT[CONF_PROTOCOL_VERSION],
    }


async def test_the_entry_keeps_its_identity(monkeypatch):
    """A reconfigure that moved the unique_id would be a new device wearing the old entry."""
    entry = _entry_with_listener()

    async def fake_validate(host, device_id, local_key, protocol_version):
        return {2: True}

    monkeypatch.setattr(config_flow_module, "_async_validate", fake_validate)

    await _flow(entry).async_step_reconfigure(dict(NEW_INPUT))

    assert entry.unique_id == STORED[CONF_DEVICE_ID]
    assert entry.entry_id == "entry-under-test"
    assert entry.title == config_flow_module.DEFAULT_TITLE


async def test_values_are_stripped_before_they_are_stored(monkeypatch):
    """Paste from the recon output and you paste the trailing whitespace with it."""
    entry = _entry_with_listener()

    async def fake_validate(host, device_id, local_key, protocol_version):
        return {2: True}

    monkeypatch.setattr(config_flow_module, "_async_validate", fake_validate)

    await _flow(entry).async_step_reconfigure(
        {
            CONF_HOST: f"  {NEW_INPUT[CONF_HOST]}  ",
            CONF_LOCAL_KEY: f"\t{NEW_INPUT[CONF_LOCAL_KEY]}\n",
            CONF_PROTOCOL_VERSION: NEW_INPUT[CONF_PROTOCOL_VERSION],
        }
    )

    assert entry.data[CONF_HOST] == NEW_INPUT[CONF_HOST]
    assert entry.data[CONF_LOCAL_KEY] == NEW_INPUT[CONF_LOCAL_KEY]


async def test_the_update_listener_reloads_and_nothing_schedules_a_second_reload(
    monkeypatch,
):
    """Why the step calls async_update_and_abort and not the *_reload_* variant."""
    entry = _entry_with_listener()

    async def fake_validate(host, device_id, local_key, protocol_version):
        return {2: True}

    monkeypatch.setattr(config_flow_module, "_async_validate", fake_validate)

    flow = _flow(entry)
    await flow.async_step_reconfigure(dict(NEW_INPUT))

    assert flow.hass.config_entries.listener_calls == [entry.entry_id]
    assert flow.hass.config_entries.reload_calls == []


# -- Rejected credentials -----------------------------------------------------------------


async def test_rejected_credentials_show_cannot_connect_and_keep_the_entry(monkeypatch):
    entry = _entry_with_listener()
    before = dict(entry.data)

    async def fake_validate(host, device_id, local_key, protocol_version):
        raise ArozenUnreachable("no answer from 192.0.2.20")

    monkeypatch.setattr(config_flow_module, "_async_validate", fake_validate)

    flow = _flow(entry)
    result = await flow.async_step_reconfigure(dict(NEW_INPUT))

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data == before
    assert entry.unique_id == STORED[CONF_DEVICE_ID]
    assert flow.hass.config_entries.listener_calls == []
    assert flow.hass.config_entries.reload_calls == []


async def test_a_failed_attempt_redisplays_what_was_typed(monkeypatch):
    """Not the stored values: those are the ones that stopped working."""
    entry = _entry_with_listener()

    async def fake_validate(host, device_id, local_key, protocol_version):
        raise ArozenUnreachable("no answer")

    monkeypatch.setattr(config_flow_module, "_async_validate", fake_validate)

    result = await _flow(entry).async_step_reconfigure(dict(NEW_INPUT))

    assert _suggested(result["data_schema"]) == {
        CONF_HOST: NEW_INPUT[CONF_HOST],
        CONF_LOCAL_KEY: NEW_INPUT[CONF_LOCAL_KEY],
        CONF_PROTOCOL_VERSION: NEW_INPUT[CONF_PROTOCOL_VERSION],
    }


async def test_an_unexpected_error_is_reported_as_unknown_not_as_cannot_connect(
    monkeypatch,
):
    """cannot_connect tells the user to check their credentials. A TypeError does not."""
    entry = _entry_with_listener()
    before = dict(entry.data)

    async def fake_validate(host, device_id, local_key, protocol_version):
        raise TypeError("something in the transport is wrong, not the credentials")

    monkeypatch.setattr(config_flow_module, "_async_validate", fake_validate)

    result = await _flow(entry).async_step_reconfigure(dict(NEW_INPUT))

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}
    assert entry.data == before


# -- Wiring -------------------------------------------------------------------------------


def test_home_assistant_will_offer_the_reconfigure_entry():
    """`ConfigEntry.supports_reconfigure` is a hasattr check on the handler class."""
    assert hasattr(ArozenConfigFlow, "async_step_reconfigure")


def test_both_string_files_describe_the_step():
    """The form renders from strings.json; en.json is what a running instance actually reads."""
    import json
    from pathlib import Path

    root = Path(config_flow_module.__file__).parent
    strings = json.loads((root / "strings.json").read_text())
    english = json.loads((root / "translations" / "en.json").read_text())

    assert strings == english
    for translations in (strings, english):
        step = translations["config"]["step"]["reconfigure"]
        assert set(step["data"]) == {CONF_HOST, CONF_LOCAL_KEY, CONF_PROTOCOL_VERSION}
        # The device ID is only in the description, and only as a placeholder the step fills.
        assert "{device_id}" in step["description"]
        assert CONF_DEVICE_ID not in step["data"]
        assert "reconfigure_successful" in translations["config"]["abort"]
