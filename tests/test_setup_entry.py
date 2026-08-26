"""Tests for the integration's own setup and teardown.

`__init__.py` is the module Home Assistant calls first and this suite never called at all.
It was *imported* — pulling in any submodule executes the package body — which is why it
never looked missing; none of its three functions had ever run.

What it holds is not glue. It holds one decision that is deliberately unconventional and
looks, to anyone reading it cold, like a mistake to be tidied up:

    await coordinator.async_refresh()          # not async_config_entry_first_refresh()

The conventional call raises `ConfigEntryNotReady` when the device does not answer, which
parks the entry in `setup_retry` with **nothing on the dashboard at all**. This device is a
battery-capable diffuser on a home LAN; being asleep when Home Assistant restarts is normal,
not exceptional. So the integration sets its entities up anyway and lets them read
`unavailable`, which is the honest state and one a user can see. Nothing asserted that, so a
refactor to the conventional call would have passed the whole suite green.

The coordinator is faked here rather than built. It needs a real hass, it has its own tests,
and what is under test on this page is the wiring: what gets constructed, from which values,
in which order, and what still happens when the device says nothing.

It also holds the schema-version tripwire (#53). `async_migrate_entry` cannot run today — the
version on disk matches the version the flow declares, so Home Assistant never reaches for it —
which means the ordinary tests below could not tell a working migration handler from a broken
one. The last test in this file is the one that fires: it fails the build the day `VERSION` or
`MINOR_VERSION` moves, because that is the only moment the handler starts mattering and the
only moment somebody can still add the branch before a user's entry stops loading.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("homeassistant", reason="setup tests need Home Assistant installed")

from homeassistant.const import CONF_HOST, Platform

#: The package itself, so the collaborators can be swapped where setup looks them up.
#: `from ... import __init__` binds the module's `__init__` method-wrapper rather than the
#: module, which fails as a missing attribute at the first monkeypatch.
import custom_components.arozen_eon as init_module
from custom_components.arozen_eon import (
    PLATFORMS,
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.arozen_eon.config_flow import ArozenConfigFlow
from custom_components.arozen_eon.const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_POLL_INTERVAL,
    CONF_PROTOCOL_VERSION,
    DEFAULT_POLL_INTERVAL_S,
)

ENTRY_DATA = {
    CONF_HOST: "192.0.2.10",
    CONF_DEVICE_ID: "test-device-id",
    CONF_LOCAL_KEY: "0123456789abcdef",
    CONF_PROTOCOL_VERSION: "3.5",
}


class FakeDevice:
    """Records the four connection values, in the order ArozenDevice takes them."""

    def __init__(self, host, device_id, local_key, protocol_version):
        self.args = (host, device_id, local_key, protocol_version)


class FakeCoordinator:
    """Enough of ArozenCoordinator to see what setup does with one."""

    def __init__(self, hass, entry, device, poll_interval=DEFAULT_POLL_INTERVAL_S):
        self.hass = hass
        self.entry = entry
        self.device = device
        self.poll_interval = poll_interval
        self.refreshes = 0
        #: Set False to play a device that did not answer during setup.
        self.last_update_success = True

    async def async_refresh(self):
        self.refreshes += 1


class FakeConfigEntries:
    def __init__(self):
        self.forwarded: list[tuple[object, list[Platform]]] = []
        self.unloaded: list[tuple[object, list[Platform]]] = []
        self.reloaded: list[str] = []
        self.updated: list[tuple[object, dict]] = []
        self.unload_result = True

    def async_update_entry(self, entry, **changes):
        """Records the call *and* applies it, because the real one does both.

        `ConfigEntries._async_update_entry` writes each changed field onto the entry with
        `object.__setattr__` before scheduling the save (config_entries.py:2599). A fake that
        only recorded would let a migration test assert `entry.minor_version` and get the
        stale value back — passing or failing for a reason that has nothing to do with the
        code under test.
        """
        self.updated.append((entry, changes))
        for field, value in changes.items():
            setattr(entry, field, value)

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry, list(platforms)))

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry, list(platforms)))
        return self.unload_result

    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)


class FakeHass:
    def __init__(self):
        self.config_entries = FakeConfigEntries()


class FakeEntry:
    def __init__(self, data=None, options=None, version=1, minor_version=1):
        self.entry_id = "test-entry-id"
        #: The schema stamp Home Assistant writes into every entry and compares on load.
        #: Real entries carry it; the migration handler reads nothing else.
        self.version = version
        self.minor_version = minor_version
        self.data = dict(data if data is not None else ENTRY_DATA)
        self.options = dict(options or {})
        self.runtime_data = None
        self.update_listeners: list[object] = []
        self.on_unload: list[object] = []

    def add_update_listener(self, listener):
        self.update_listeners.append(listener)
        return lambda: None

    def async_on_unload(self, unsubscribe):
        self.on_unload.append(unsubscribe)


@pytest.fixture
def wired(monkeypatch):
    """Setup's two collaborators replaced, so what remains under test is the wiring."""
    monkeypatch.setattr(init_module, "ArozenDevice", FakeDevice)
    monkeypatch.setattr(init_module, "ArozenCoordinator", FakeCoordinator)


async def _setup(entry=None, hass=None):
    hass = hass or FakeHass()
    entry = entry or FakeEntry()
    result = await async_setup_entry(hass, entry)
    return result, hass, entry


# -- What setup builds ----------------------------------------------------------------------


async def test_setup_reports_success(wired):
    result, _, _ = await _setup()
    assert result is True


async def test_the_coordinator_is_published_on_the_entry(wired):
    """`entry.runtime_data` is how every platform finds the coordinator.

    Each `async_setup_entry` in switch.py, sensor.py, select.py and binary_sensor.py reads
    it directly. Leaving it unset does not fail here — it fails four times over, in four
    other modules, as an AttributeError on None.
    """
    _, _, entry = await _setup()
    assert isinstance(entry.runtime_data, FakeCoordinator)


async def test_the_device_is_built_from_the_entry_in_the_right_slots(wired):
    """Four values of the same type, so a swap constructs cleanly and never connects."""
    _, _, entry = await _setup()
    assert entry.runtime_data.device.args == (
        "192.0.2.10",
        "test-device-id",
        "0123456789abcdef",
        "3.5",
    )


async def test_the_poll_interval_defaults_when_the_option_is_unset(wired):
    _, _, entry = await _setup()
    assert entry.runtime_data.poll_interval == DEFAULT_POLL_INTERVAL_S


async def test_the_poll_interval_comes_from_options_when_set(wired):
    """Options, not data — the options flow writes there, and reading the wrong mapping
    silently pins every install to the default."""
    _, _, entry = await _setup(FakeEntry(options={CONF_POLL_INTERVAL: 300}))
    assert entry.runtime_data.poll_interval == 300


async def test_setup_refreshes_once_before_forwarding(wired):
    """The order is the point: entities that appear already carrying a reading."""
    _, hass, entry = await _setup()
    assert entry.runtime_data.refreshes == 1
    assert hass.config_entries.forwarded, "platforms were never set up"


# -- The deliberate async_refresh choice ------------------------------------------------------


async def test_every_platform_is_forwarded(wired):
    _, hass, entry = await _setup()
    assert hass.config_entries.forwarded == [(entry, list(PLATFORMS))]


async def test_platforms_are_forwarded_even_when_the_device_never_answered(wired, monkeypatch):
    """The regression that would otherwise be invisible, and the reason this file exists.

    A device asleep at Home Assistant start must still produce entities — unavailable ones,
    which a user can see and which recover on the next successful poll. Swapping this for
    `async_config_entry_first_refresh()` would raise `ConfigEntryNotReady` here and leave
    the dashboard empty, and every other test in this suite would still pass.
    """
    class SilentCoordinator(FakeCoordinator):
        async def async_refresh(self):
            await super().async_refresh()
            self.last_update_success = False

    monkeypatch.setattr(init_module, "ArozenCoordinator", SilentCoordinator)
    result, hass, entry = await _setup()

    assert result is True, "a silent device must not fail setup"
    assert hass.config_entries.forwarded == [(entry, list(PLATFORMS))]


async def test_a_silent_device_is_logged_rather_than_raised(wired, monkeypatch, caplog):
    class SilentCoordinator(FakeCoordinator):
        async def async_refresh(self):
            await super().async_refresh()
            self.last_update_success = False

    monkeypatch.setattr(init_module, "ArozenCoordinator", SilentCoordinator)
    with caplog.at_level(logging.INFO, logger="custom_components.arozen_eon"):
        await _setup()
    assert "192.0.2.10" in caplog.text
    assert "unavailable" in caplog.text


async def test_the_local_key_is_never_logged_during_setup(wired, monkeypatch, caplog):
    """Setup logs the host on a silent device. It must not reach for the neighbouring value."""
    class SilentCoordinator(FakeCoordinator):
        async def async_refresh(self):
            await super().async_refresh()
            self.last_update_success = False

    monkeypatch.setattr(init_module, "ArozenCoordinator", SilentCoordinator)
    with caplog.at_level(logging.DEBUG, logger="custom_components.arozen_eon"):
        await _setup()
    assert "0123456789abcdef" not in caplog.text


# -- The unmapped-DP warning -------------------------------------------------------------------


async def test_an_unmapped_datapoint_warns_by_name(wired, monkeypatch, caplog):
    """Scaffolding from the recon phase: an unmapped DP means missing entities, silently."""
    monkeypatch.setattr(init_module.dp, "DP_POWER", None)
    with caplog.at_level(logging.WARNING, logger="custom_components.arozen_eon"):
        await _setup()
    assert "power" in caplog.text


async def test_a_fully_mapped_device_warns_about_nothing(wired, caplog):
    """The guard against a warning that has become background noise."""
    with caplog.at_level(logging.WARNING, logger="custom_components.arozen_eon"):
        await _setup()
    assert caplog.text == ""


# -- The update listener --------------------------------------------------------------------


async def test_an_options_change_is_wired_to_a_reload(wired):
    """Registered *and* unregistered: a listener that outlives its entry reloads a dead one."""
    _, _, entry = await _setup()
    assert len(entry.update_listeners) == 1
    assert len(entry.on_unload) == 1


async def test_the_listener_reloads_the_entry(wired):
    """The poll interval is a constructor argument, so applying it means rebuilding."""
    _, hass, entry = await _setup()
    listener = entry.update_listeners[0]
    await listener(hass, entry)
    assert hass.config_entries.reloaded == ["test-entry-id"]


# -- Unload -------------------------------------------------------------------------------------


async def test_unload_tears_down_every_platform(wired):
    _, hass, entry = await _setup()
    assert await async_unload_entry(hass, entry) is True
    assert hass.config_entries.unloaded == [(entry, list(PLATFORMS))]


async def test_unload_reports_a_refused_teardown(wired):
    """Home Assistant reads this return. Answering True over a failed unload strands entities."""
    _, hass, entry = await _setup()
    hass.config_entries.unload_result = False
    assert await async_unload_entry(hass, entry) is False


# -- PLATFORMS itself -----------------------------------------------------------------------


def test_platforms_has_no_duplicates():
    """A duplicate is forwarded twice and sets every entity up twice, under suffixed ids."""
    assert len(PLATFORMS) == len(set(PLATFORMS))


# -- The schema-version branch point (#53) -----------------------------------------------------


async def test_a_current_entry_migrates_to_itself():
    """Version 1 is the only shape `entry.data` has ever had, so there is nothing to do."""
    assert await async_migrate_entry(FakeHass(), FakeEntry()) is True


async def test_migrating_a_current_entry_rewrites_nothing():
    """A no-op that quietly rewrote the entry would be a no-op only in its return value.

    The real handler's write is `hass.config_entries.async_update_entry`, so the check is that
    it was never called, not just that `entry.data` came out equal — the first migration to be
    written here will reach for exactly that method.
    """
    hass, entry = FakeHass(), FakeEntry()
    await async_migrate_entry(hass, entry)

    assert entry.data == ENTRY_DATA
    assert entry.options == {}
    assert hass.config_entries.updated == []
    assert (entry.version, entry.minor_version) == (1, 1)


async def test_the_handler_answers_with_a_bool():
    """Home Assistant type-checks the return before believing it.

    `ConfigEntry.async_migrate` logs `did not return boolean` and treats the entry as failed
    when the handler answers with anything else (config_entries.py:1183) — which is what a
    branch that falls off the end returning `None` would do, and it would do it silently in
    every test that only asserted truthiness.
    """
    assert type(await async_migrate_entry(FakeHass(), FakeEntry())) is bool


async def test_a_stale_minor_version_is_stamped_forward():
    """The half of a no-op migration that is not nothing.

    Home Assistant compares the numbers it read off disk and re-runs the handler whenever they
    differ, so a branch that answers True without moving the stamp migrates the same entry on
    every restart, forever. This was visible in the real-Home-Assistant run: an entry seeded at
    1.0 loaded cleanly and came out still stamped 1.0.
    """
    hass, entry = FakeHass(), FakeEntry(minor_version=0)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.minor_version == ArozenConfigFlow.MINOR_VERSION
    assert hass.config_entries.updated == [(entry, {"minor_version": 1})]
    assert entry.data == ENTRY_DATA, "a minor bump is additive - nothing here changes shape"


async def test_a_newer_minor_version_is_left_where_it_is():
    """Forward only. An entry stamped ahead of this build has been through a newer release and
    come back down — exactly what `MINOR_VERSION` exists to tolerate, since its data is a
    superset of what this build reads. Dragging the number backwards would discard the only
    record that the migration has already run."""
    hass, entry = FakeHass(), FakeEntry(minor_version=9)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.minor_version == 9
    assert hass.config_entries.updated == []


async def test_a_version_with_no_branch_is_refused():
    """The half of this that is not a no-op.

    Answering True here is the failure the issue was filed about: Home Assistant would carry
    on to `async_setup_entry`, which reads four keys straight out of `entry.data`, and the user
    would get a `KeyError` traceback instead of a migration error naming the integration.
    """
    assert await async_migrate_entry(FakeHass(), FakeEntry(version=2)) is False


async def test_a_refused_version_says_which_one_it_was(caplog):
    """Announced *and* refused. A handler that logged and then returned True would leave the
    log looking exactly like a working refusal while the entry loaded anyway, which is the
    failure this whole branch exists to prevent."""
    with caplog.at_level(logging.ERROR, logger="custom_components.arozen_eon"):
        refused = await async_migrate_entry(FakeHass(), FakeEntry(version=3, minor_version=2))
    assert refused is False
    assert "3.2" in caplog.text, "the refused version has to be in the message to act on"


def test_the_schema_version_has_not_moved_without_a_migration_branch():
    """The tripwire. If you are reading this because it failed, you bumped the version.

    `async_migrate_entry` in `__init__.py` treats version 1 as current and refuses everything
    else. That is correct only while 1 *is* current. The moment `VERSION` or `MINOR_VERSION`
    moves, every entry already on disk is one step behind, and the handler has to grow the
    branch that carries it forward before the pair below is updated to match.

    The comment at those constants states the rule; this is the part that enforces it. Nothing
    else can: the handler is unreachable at runtime until the bump, so the bump is the first
    and last chance to catch a missing branch before it reaches an installed integration.
    """
    assert (ArozenConfigFlow.VERSION, ArozenConfigFlow.MINOR_VERSION) == (1, 1), (
        "The config entry schema version moved. Add the branch to `async_migrate_entry` in "
        "custom_components/arozen_eon/__init__.py that migrates an entry from the old version "
        "to this one, then update the pair in this assertion."
    )
