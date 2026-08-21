"""State and health for one Arozen EON Pro 2.

Much simpler than the sibling project's coordinator, because the transport is simpler: no schedule
arbitration (the Tuya device holds one flat DP set, not four schedule records), no presence
tracking (there is no advertisement to watch — "is it there" is "did the TCP poll answer"),
and no intensity memory (intensity is a DP the device keeps, not a value off erases).

What is kept is the health counting: tolerated poll failures and a total-failure counter,
exported as a diagnostic sensor so a tolerated miss still leaves a trace. See PollHealth.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DEFAULT_POLL_INTERVAL_S, DOMAIN, TOLERATED_POLL_FAILURES
from .device import ArozenDevice, ArozenError

_LOGGER = logging.getLogger(__name__)

type ArozenConfigEntry = ConfigEntry["ArozenCoordinator"]


class PollHealth:
    """How many polls have failed, in a row and in total.

    Same design as sibling_beacon's PollHealth, minus the off-air tracking (there is no
    advertisement to watch here — a poll that ran and failed is the only failure shape):

    1. **Decide whether the entities may hold a stale reading** (``may_hold_reading``), so
       one missed poll does not cost a full interval of ``unavailable``;
    2. **Be the measurement channel the first job destroys.** Tolerating a miss erases the
       visible evidence of it, so the total is exported as a diagnostic sensor (sensor.py)
       and the recorder keeps it.
    """

    def __init__(self, tolerated: int = TOLERATED_POLL_FAILURES) -> None:
        self.tolerated = tolerated
        self.consecutive = 0
        #: Failures since the config entry loaded. Never decreases except on a reload.
        self.total = 0
        self.last_error: str | None = None
        self.last_failure: datetime | None = None

    def failed(self, error: str) -> None:
        self.consecutive += 1
        self.total += 1
        self.last_error = error
        self.last_failure = dt_util.now()

    def succeeded(self) -> None:
        """A fresh reading, from a poll or a write — both prove the link works."""
        self.consecutive = 0

    @property
    def may_hold_reading(self) -> bool:
        """Whether the previous reading is still worth showing rather than going unavailable."""
        return self.consecutive <= self.tolerated


class ArozenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holds the last DP set the device reported, and whether polls are landing."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device: ArozenDevice,
        poll_interval: int = DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {device.host}",
            update_interval=timedelta(seconds=poll_interval),
            config_entry=entry,
        )
        self.device = device
        self.health = PollHealth()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            dps = await self.device.async_status()
        except ArozenError as err:
            self.health.failed(str(err))
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # re-raised immediately
            # Not an ArozenError means a bug, not a flaky link — but it still has to break
            # the streak, or every entity would sit available on a frozen reading forever.
            self.health.failed(f"{type(err).__name__}: {err}")
            raise
        self.health.succeeded()
        return dps

    async def async_set_dp(self, dp: int, value: Any) -> None:
        """Write a DP, then fold the resulting state straight back into the coordinator."""
        await self.device.async_set_dp(dp, value)
        self.health.succeeded()
        # The write was accepted; refresh now rather than leaving the UI on the pre-write
        # state for up to a poll interval. A failed refresh here does not un-write the DP,
        # so it is logged, not raised — the user watched their command land.
        try:
            dps = await self.device.async_status()
        except ArozenError as err:
            _LOGGER.debug("%s: write confirmed, follow-up read failed: %s", self.device.host, err)
            return
        self.async_set_updated_data(dps)
