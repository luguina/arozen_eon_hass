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
# BINARY_SENSOR carries exactly one entity, "Misting" (DP 103). It is a platform rather
# than an attribute on the switch because it is a genuinely separate state: the switch says
# whether the duty cycle is running, this says whether the nozzle is open right now.
PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SENSOR,
]


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
