"""The Arozen EON Pro 2 integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from . import dp
from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_POLL_INTERVAL,
    CONF_PROTOCOL_VERSION,
    DEFAULT_POLL_INTERVAL_S,
)
from .coordinator import ArozenConfigEntry, ArozenCoordinator
from .device import ArozenDevice

_LOGGER = logging.getLogger(__name__)

# No NUMBER platform: unlike the sibling project, intensity here is a single enum DP (DP 3), not a
# settable work/pause pair - the pause seconds (DP 106) are a read-only mirror, exposed as
# an attribute on the intensity select, and the burst length (DP 105) is fixed at 30 s.
#
# SWITCH carries the two written DPs: power (DP 2) and the frontal LED (DP 7). On this device
# "writable" is a measured property rather than an obvious one - DP 103 accepts writes and
# reverts them - so DP 7 got an entity only after a write test held for 30 s in both
# directions (#15).
#
# BINARY_SENSOR carries two entities, "Misting" (DP 103) and "Charging" (DP 102). Misting is
# a platform rather than an attribute on the switch because it is a genuinely separate state:
# the switch says whether the duty cycle is running, this says whether the nozzle is open
# right now. Charging is separate from the battery sensor for the same kind of reason - a
# percentage says how full, not which direction it is heading.
PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SENSOR,
]


async def async_migrate_entry(hass: HomeAssistant, entry: ArozenConfigEntry) -> bool:
    """Bring an entry written by an older build up to the shape this one reads (#53).

    **Nothing calls this today, and that is the point.** Home Assistant compares the entry's
    stamped version against the config flow's before it looks for this function at all, and
    returns success on a match without loading the component (config_entries.py:1153). Every
    entry on disk was written by `VERSION = 1`, so the branch below has never run. It exists so
    that the first real schema change is a diff that adds a case to a mechanism that is already
    wired up and already under test, rather than one that invents the mechanism at the moment a
    user's entry has stopped loading.

    The moment it starts being called is a bump to `VERSION` or `MINOR_VERSION` in
    `config_flow.py`; the rule for choosing between them is written at those constants. The
    wiring here is the name on this module and nothing else - Home Assistant looks for it with
    `hasattr(component, "async_migrate_entry")` (config_entries.py:1170), so there is no
    decorator, no registration and no manifest key to get wrong, and equally nothing that
    complains if the name drifts.

    Two shapes deliberately *not* copied from core:

    * No `if entry.version > VERSION: return False` guard. Home Assistant refuses a
      higher-than-current entry itself, before reaching here (config_entries.py:1156), so the
      guard is unreachable - 2 of the 157 integrations in the 2026.8.1 wheel that ship a
      migration write it anyway.
    * No bare `return True` at the end. A blanket yes is the failure this issue was filed
      about, wearing the fix's clothes: it would tell Home Assistant an entry is current when
      no branch has touched it, and `async_setup_entry` would then read a key that is not there
      and fail on somebody's dashboard with a `KeyError`. Refusing instead stops the entry at
      `MIGRATION_ERROR` before any platform is forwarded, which is a state the user can see.

    The `_LOGGER.error` below is not decoration. Home Assistant writes **nothing** of its own
    when a handler answers False - it sets that state and returns (config_entries.py:782) - so
    the line this function logs is the entire diagnostic, and the version it names is the only
    place the failing entry's stamp appears. Both paths were run against a real Home Assistant
    2026.8.1 with the delivered file set and an entry stamped by hand, since the flow cannot
    write a stale one: 1.0 went through this function and on to register every entity, and 0.1
    was refused here with no platform set up and no entity registered. The 1.0 run is also what
    the stamping below is for: on the first pass it loaded but came off disk still stamped 1.0,
    which would have re-migrated it on every restart for the life of the install. With the
    stamp it comes off disk as 1.1. The refused entry stays 0.1, which is right - a migration
    that did not happen must not leave a record saying it did.

    The forward-migration idiom, for whoever needs the first one: branches oldest-first, each
    bringing the entry up exactly one step with
    `hass.config_entries.async_update_entry(entry, data=..., version=2)`, and no `return` until
    the chain has run - so an entry two versions behind walks through both.
    """
    if entry.version == 1:
        # `entry.data` has only ever had one shape: host, device id, local key, protocol
        # version, exactly as `STEP_USER_SCHEMA` writes them. So there is nothing to rewrite -
        # but the entry still has to be *stamped*, or it arrives here again on every single
        # restart. Home Assistant compares the numbers it read off disk, and a handler that
        # answers True without moving them has changed nothing it can see
        # (config_entries.py:1153); the save it schedules afterwards writes the old stamp
        # straight back. Stamping is what makes a migration a one-off.
        #
        # Forward only. A stamp *ahead* of this build is an entry that has been through a newer
        # release and come back down, which is the case `MINOR_VERSION` exists to tolerate -
        # its data is a superset of what this build reads. Dragging the number backwards would
        # throw away the one record that it has already been migrated.
        #
        # The target comes from the flow rather than a literal repeated here, so the two cannot
        # drift. Imported inside the function because this is the only path that needs it and
        # the class is certain to be loaded already: `ConfigEntry.async_migrate` looks the flow
        # up in HANDLERS before it will call this at all (config_entries.py:1141).
        from .config_flow import ArozenConfigFlow

        if entry.minor_version < ArozenConfigFlow.MINOR_VERSION:
            hass.config_entries.async_update_entry(
                entry, minor_version=ArozenConfigFlow.MINOR_VERSION
            )
        return True

    _LOGGER.error(
        "Config entry schema version %s.%s has no migration branch in this build",
        entry.version,
        entry.minor_version,
    )
    return False


async def async_setup_entry(hass: HomeAssistant, entry: ArozenConfigEntry) -> bool:
    """Set up a diffuser from a config entry."""
    device = ArozenDevice(
        entry.data[CONF_HOST],
        entry.data[CONF_DEVICE_ID],
        entry.data[CONF_LOCAL_KEY],
        entry.data[CONF_PROTOCOL_VERSION],
    )
    coordinator = ArozenCoordinator(
        hass,
        entry,
        device,
        poll_interval=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_S),
    )
    entry.runtime_data = coordinator

    unmapped = dp.unmapped_functions()
    if unmapped:
        _LOGGER.warning(
            "dp.py has no DP number for: %s — those entities do not exist yet. "
            "This is expected until the DP dump fills in docs/datapoints.md",
            ", ".join(unmapped),
        )

    # Deliberately async_refresh(), not async_config_entry_first_refresh() — same call the
    # sibling project makes and for the same reason: a device that does not answer at startup should
    # get entities that exist and read `unavailable`, not a config entry stuck in
    # setup_retry with nothing on the dashboard at all.
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        _LOGGER.info(
            "%s did not answer during setup - entities will be unavailable until it does",
            entry.data[CONF_HOST],
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ArozenConfigEntry) -> bool:
    """Tear down the platforms. Nothing else to release — there is no persistent socket."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_options_change(
    hass: HomeAssistant, entry: ArozenConfigEntry
) -> None:
    # The poll interval is a constructor argument, so a reload is the simplest correct
    # way to apply it.
    await hass.config_entries.async_reload(entry.entry_id)
