"""State and health for one Arozen EON Pro 2.

Simpler than a BLE coordinator in the ways this transport is simpler: no schedule arbitration
(the Tuya device holds one flat DP set, not four schedule records) and no presence tracking
(there is no advertisement to watch — "is it there" is "did the TCP poll answer").

Three things it does hold, and the first two are here because the device erases evidence on
its own:

* **health counting** — tolerated poll failures and a total-failure counter, exported as a
  diagnostic sensor so a tolerated miss still leaves a trace. See PollHealth.
* **an intensity memory** — the firmware clears intensity to L1 on every power-on and nothing
  on the device or in the vendor app puts it back. See IntensityMemory.
* **a repair issue** — a device that has stopped answering for an hour gets a card in
  Settings → System → Repairs, because the two states that produce that silence (unplugged,
  or re-paired so the local key no longer decrypts) are indistinguishable at this layer and
  only one of them has a fix the user can perform. See _raise_unreachable_issue, and ADR-008
  for why this is a repair issue rather than a reauth flow.

An earlier revision of this docstring claimed there was "no intensity memory (intensity is a
DP the device keeps, not a value off erases)". Wrong in both halves, and wrong the same way
the rest of this repo was: the device does not keep intensity across a power **on**, and the
off edge that sentence was busy exonerating was never the culprit in the first place. The
remote walk of 2026-08-21 measured both edges with the phone app closed
(docs/captures/remote-walk-2026-08-21.jsonl).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import dp
from .const import (
    DEFAULT_POLL_INTERVAL_S,
    DOMAIN,
    REPAIR_LEARN_MORE_URL,
    TOLERATED_POLL_FAILURES,
    UNREACHABLE_BEFORE_REPAIR_S,
)
from .device import ArozenDevice, ArozenError

_LOGGER = logging.getLogger(__name__)

type ArozenConfigEntry = ConfigEntry["ArozenCoordinator"]


class PollHealth:
    """How many polls have failed, in a row and in total.

    Poll health without off-air tracking, because there is no advertisement to watch here —
    a poll that ran and failed is the only failure shape:

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
        #: ``time.monotonic()`` when the current run of failures *started*, or None if the
        #: last exchange worked. Deliberately not ``last_failure``, which holds the most recent
        #: one: the two answer different questions — "when did we last try and fail" versus
        #: "how long has this been going on" — and only the second can tell a router reboot
        #: from a local key that is never going to work again (#49).
        #:
        #: Monotonic rather than ``dt_util.now()``, unlike every other timestamp in this class,
        #: because this one is only ever subtracted and the others are only ever displayed. A
        #: Home Assistant box with no real-time clock — a Raspberry Pi, which is most of them —
        #: boots at the epoch and jumps decades forward when NTP answers. A wall-clock
        #: subtraction across that jump reports fifty years of silence and raises a repair card
        #: on the second failed poll of the day.
        self.unreachable_since_monotonic: float | None = None

    def failed(self, error: str) -> None:
        self.consecutive += 1
        self.total += 1
        self.last_error = error
        self.last_failure = dt_util.now()
        if self.unreachable_since_monotonic is None:
            self.unreachable_since_monotonic = time.monotonic()

    def succeeded(self) -> None:
        """A fresh reading, from a poll or a write — both prove the link works."""
        self.consecutive = 0
        self.unreachable_since_monotonic = None

    def unreachable_for_at_least(self, seconds: int) -> bool:
        """Whether the current run of failures has lasted at least ``seconds`` of wall clock.

        False when the last exchange worked, and false on the *first* failure of a run — the
        run is zero seconds old at that moment, which is both the honest answer and the one
        that stops a single missed poll from meaning anything.

        Elapsed time rather than a count of failures, because the poll interval is a user
        setting spanning 10 s to 3600 s and a count means wildly different things across that
        range. See UNREACHABLE_BEFORE_REPAIR_S.
        """
        if self.unreachable_since_monotonic is None:
            return False
        return time.monotonic() - self.unreachable_since_monotonic >= seconds

    @property
    def may_hold_reading(self) -> bool:
        """Whether the previous reading is still worth showing rather than going unavailable."""
        return self.consecutive <= self.tolerated


class IntensityMemory:
    """The intensity level the user wants, carried across the firmware's power-on reset.

    The device clears DP 3 to ``dp.INTENSITY_POWER_ON_DEFAULT`` every time it is switched on,
    in the same status record as the power change, and it does so whoever turns it on — us,
    the phone app, or the physical remote. Three power-ons from two sources were captured on
    2026-08-21 and all three were identical, and the app does not restore it afterwards
    either. So this class is the only thing in the system that remembers what the level was.

    **The one thing it must never do is learn the reset.** A memory filled from "the last
    value we saw" would be handed L1 by the very update that carries the power-on, and would
    then restore L1 for ever. So the invariant is narrower and more exact than "power-on
    readings do not teach": *no power-on reading ever teaches this memory the firmware's own
    default.* A power-on that reports something else did not come from the firmware — somebody
    set a level in the interval before we looked — and that reading teaches like any other.

    Three ways in, then: ordinary readings teach (``observe``), a Home Assistant selection
    overrides (``remember``), and a power-on reading either restores from the memory or
    teaches it, never both (``restore_for``).

    No Home Assistant imports and no I/O, so it can be tested as the state machine it is; the
    coordinator below owns the writes. Same shape as PollHealth for the same reason.
    """

    def __init__(self, power_on_default: str = dp.INTENSITY_POWER_ON_DEFAULT) -> None:
        self.power_on_default = power_on_default
        #: The level to put back after a power-on. None until something has taught us one,
        #: which is the honest state on a fresh load and the reason a restore can decline.
        self.wanted: str | None = None
        #: A restore was written and the device has not reported it back yet. Learning is
        #: suspended while this is set — see ``observe``.
        self.unconfirmed = False
        #: Restores the device accepted since the config entry loaded, and the ones that
        #: failed. Exported as a diagnostic sensor: a restore that works erases the evidence
        #: that the firmware reset anything, which is the same reason PollHealth.total exists.
        self.restored = 0
        self.failures = 0
        self.last_error: str | None = None

    def observe(self, level: str | None) -> None:
        """Learn from a reading that is *not* the one carrying a power-on.

        Whatever the device reports outside that moment is a real setting — ours, the app's,
        or one somebody pressed on the remote. All three are the user's preference and all
        three are worth keeping.

        The exception is the reading that follows a restore we could not confirm. The device
        is then sitting at the default *because our write did not land*, so reading it back
        proves nothing and must not be allowed to overwrite the value it failed to restore.
        Any other level does mean a fresh choice, so it teaches and clears the flag.
        """
        if level is None:
            return
        if self.unconfirmed:
            if level == self.power_on_default:
                return
            self.unconfirmed = False
        self.wanted = level

    def remember(self, level: str) -> None:
        """Record a level the user selected through Home Assistant.

        Outranks anything observed, including an unconfirmed restore: the user has just said
        what they want, which settles the question that flag exists to keep open.
        """
        self.unconfirmed = False
        self.wanted = level

    def restore_for(self, reported: str | None) -> str | None:
        """The level to write after a witnessed power-on, or None to leave the device alone.

        Three ways this declines, and the first is the one that keeps the integration from
        fighting its user:

        * **the device reports something other than the default.** The power-on did happen,
          but somebody has set a level since and we have only just got round to looking — an
          external power-on is not noticed until the next poll, which is up to a minute. Their
          choice is newer than our memory, so it wins, and we learn it instead of clobbering
          it. An unreadable level (None) lands here too: not knowing is not a reason to write.
        * **nothing is remembered.** Nothing to restore, and inventing a level is worse than
          leaving the firmware's.
        * **the device already has the level we want.** Writing a value the device is already
          holding is noise on the wire and nothing else.
        """
        if reported != self.power_on_default:
            self.observe(reported)
            return None
        if self.wanted is None or self.wanted == reported:
            return None
        self.unconfirmed = True
        return self.wanted

    def restore_written(self) -> None:
        """The device accepted a restore write.

        Counted here rather than on the read-back, because this counter answers "how often did
        the firmware throw the level away and we put it back" — and the read-back is allowed
        to fail without that having happened any less. Confirmation is a separate axis, and it
        is ``unconfirmed`` that tracks it.
        """
        self.restored += 1

    def restore_failed(self, error: str) -> None:
        """A restore write did not land. ``unconfirmed`` stays set, deliberately.

        The device is now running at the default with the user's level lost, and the next
        reading will say so. Learning from that reading would quietly adopt the failure as the
        new preference, which is exactly how a memory degrades to L1 for ever.
        """
        self.failures += 1
        self.last_error = error


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
        self.intensity = IntensityMemory()
        #: One conversation with the device at a time. Both paths below are read → maybe
        #: correct → publish, and interleaving them is not a theoretical worry: a scheduled
        #: poll landing inside async_set_dp would publish a reading taken before the
        #: correction, and — worse — feed that pre-correction level into the intensity memory
        #: as though it were a choice. Many Tuya devices accept only one local connection at a
        #: time anyway (ADR-004), so serialising costs nothing we were getting.
        self._exchange = asyncio.Lock()
        #: Whether this run has a repair card on screen. Kept here rather than asked of the
        #: issue registry every poll, so the card is created once per outage instead of
        #: re-created every 60 s — and so "was it raised twice" is a question with an answer.
        #: A restart resets it to False and cannot strand a stale card: Home Assistant
        #: restores non-persistent issues with ``active=False``, so a card nobody re-creates
        #: is already invisible (helpers/issue_registry.py, ``_async_load``).
        self._unreachable_issue_raised = False

    async def _async_update_data(self) -> dict[str, Any]:
        async with self._exchange:
            try:
                dps = await self.device.async_status()
            except ArozenError as err:
                self.health.failed(str(err))
                self._raise_unreachable_issue()
                raise UpdateFailed(str(err)) from err
            except Exception as err:  # re-raised immediately
                # Not an ArozenError means a bug, not a flaky link — but it still has to break
                # the streak, or every entity would sit available on a frozen reading forever.
                #
                # No repair card from here, deliberately. The card tells the user to check the
                # power and the network or to reconfigure the key, and none of that is the
                # remedy for a TypeError in our own code. The failure still counts, because
                # `Failed polls` counts failures; only the advice is withheld.
                self.health.failed(f"{type(err).__name__}: {err}")
                raise
            self.health.succeeded()
            self._clear_unreachable_issue()
            return await self._async_apply_intensity_memory(dps)

    async def async_set_dp(self, dp_id: int, value: Any) -> None:
        """Write a DP, then fold the resulting state straight back into the coordinator."""
        async with self._exchange:
            await self.device.async_set_dp(dp_id, value)
            self.health.succeeded()
            self._clear_unreachable_issue()
            if dp_id == dp.DP_INTENSITY and isinstance(value, str):
                # The user has just said what they want. Recorded here rather than in
                # select.py so the entity layer stays ignorant of the memory, and recorded on
                # the write rather than on the read-back, which is allowed to fail below.
                self.intensity.remember(value)
            # The write was accepted; refresh now rather than leaving the UI on the pre-write
            # state for up to a poll interval. A failed refresh here does not un-write the DP,
            # so it is logged, not raised — the user watched their command land.
            try:
                dps = await self.device.async_status()
            except ArozenError as err:
                _LOGGER.debug(
                    "%s: write confirmed, follow-up read failed: %s", self.device.host, err
                )
                return
            dps = await self._async_apply_intensity_memory(dps)
        self.async_set_updated_data(dps)

    async def _async_apply_intensity_memory(self, dps: dict[str, Any]) -> dict[str, Any]:
        """Learn the intensity from this reading, or undo the firmware's power-on reset (#14).

        Called from both paths above with ``self.data`` still holding the *previous* reading,
        which is what makes the comparison possible at all — and what makes the correction
        identical whether our own switch caused the power-on or the physical remote did.
        Returns the DP set to publish: the corrected one when a restore landed, so the
        entities never show L1 for an interval before stepping back up on their own.

        **Restoring after somebody else's power-on is a decision, not an oversight.** A stored
        preference is the better default here: the remote has no memory of its own, the phone
        app does not restore the level either, and a diffuser that silently drops to its
        weakest setting whenever it is switched on is the bug being fixed — not a behaviour
        worth preserving for people who reach for the remote. The cost is honest and worth
        stating: an external power-on is not seen until the next poll, so the device really
        does run at L1 for up to one poll interval (60 s by default) and then steps up.
        Immediate for our own switch, which corrects inside the same exchange, so
        ``switch.turn_on`` returns with the level already right.

        The countdown is armed on this same edge and is deliberately **not** restored — see
        ADR-006, and note that the two defaults differ in kind: losing the intensity you chose
        is a defect, while an auto-off falling back to four hours is a safety default that
        overriding is not obviously right.
        """
        if dp.DP_INTENSITY is None or dp.DP_POWER is None:
            return dps
        level = dp.get(dps, dp.DP_INTENSITY)

        if not self._is_power_on_edge(dps):
            self.intensity.observe(level)
            return dps

        wanted = self.intensity.restore_for(level)
        if wanted is None:
            return dps

        _LOGGER.debug(
            "%s: power-on reset intensity to %s, restoring %s", self.device.host, level, wanted
        )
        try:
            await self.device.async_set_dp(dp.DP_INTENSITY, wanted)
        except ArozenError as err:
            self.intensity.restore_failed(str(err))
            _LOGGER.warning(
                "%s: the diffuser was switched on and its firmware reset intensity to %s; "
                "restoring %s failed: %s. It is running at %s until something sets it — the "
                "'Intensity restores' diagnostic sensor counts these",
                self.device.host,
                level,
                wanted,
                err,
                level,
            )
            return dps
        self.intensity.restore_written()

        try:
            restored = await self.device.async_status()
        except ArozenError as err:
            # The write was accepted, so the level is almost certainly right; we simply cannot
            # prove it. Publish the reading we have and let the next poll confirm — the memory
            # stays `unconfirmed` until it does, so it cannot be taught the value it corrected.
            _LOGGER.debug(
                "%s: intensity restored, follow-up read failed: %s", self.device.host, err
            )
            return dps
        self.intensity.observe(dp.get(restored, dp.DP_INTENSITY))
        return restored

    def _is_power_on_edge(self, dps: dict[str, Any]) -> bool:
        """Whether this reading is the first one to show the device switched on.

        Strictly ``False`` → ``True`` on DP 2, and deliberately not "power is true and was not
        true before": an absent or unreadable previous power DP is not evidence of an edge,
        and treating it as one would fire a restore every time the device answered a poll
        incompletely. With no previous reading at all there is no edge to see — a power-on
        that happens while Home Assistant is down is not recoverable, and is not guessed at.
        """
        if self.data is None:
            return False
        return dp.get(self.data, dp.DP_POWER) is False and dp.get(dps, dp.DP_POWER) is True

    @property
    def _unreachable_issue_id(self) -> str:
        """One card per config entry, not one per integration.

        Two diffusers on one Home Assistant would otherwise share a card, and the first one to
        come back would clear the other's — which is the sort of bug that only ever appears in
        somebody else's install.
        """
        return f"device_unreachable_{self.config_entry.entry_id}"

    def _raise_unreachable_issue(self) -> None:
        """Put a card in Settings → System → Repairs once the silence has gone on long enough.

        **Why this is not `ConfigEntryAuthFailed` and a reauth flow**, which is the answer Home
        Assistant conventions point at and the wrong one here. On the Tuya local protocol a
        local key that no longer decrypts produces the same error payload as a device that is
        powered off, asleep, or holding its single local connection open for the phone app
        (ADR-004). `device.py` collapses all of them into ArozenUnreachable because **they are
        genuinely not distinguishable at that layer** — not because it has not tried. Raising
        ConfigEntryAuthFailed would put "credentials are invalid" in front of a user whose
        diffuser is merely unplugged, and send them to re-enter a key that was never wrong.

        A repair issue does not have that problem, because **it does not have to claim a
        cause.** It can say the true thing — the device has not answered for an hour, here are
        the two states that produce that, here is the fix for one of them and the check for the
        other — and let the person holding the diffuser settle which. ADR-008 records the wider
        rule: this integration never asserts a cause the transport cannot distinguish.

        Raised at most once per outage, and only after UNREACHABLE_BEFORE_REPAIR_S. The
        entities have been `unavailable` since the second failed poll; this is the slower,
        louder signal that the silence is not going to end on its own.
        """
        if self._unreachable_issue_raised:
            return
        if not self.health.unreachable_for_at_least(UNREACHABLE_BEFORE_REPAIR_S):
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._unreachable_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="device_unreachable",
            translation_placeholders={
                "host": self.device.host,
                "minutes": str(UNREACHABLE_BEFORE_REPAIR_S // 60),
                "failures": str(self.health.consecutive),
            },
            learn_more_url=REPAIR_LEARN_MORE_URL,
        )
        self._unreachable_issue_raised = True
        _LOGGER.warning(
            "%s has not answered for %d minutes (%d consecutive polls). Either it is off or "
            "off the network, or it was re-paired in the Smart Life app and the local key has "
            "changed — see Settings > System > Repairs. Last error: %s",
            self.device.host,
            UNREACHABLE_BEFORE_REPAIR_S // 60,
            self.health.consecutive,
            self.health.last_error,
        )

    def _clear_unreachable_issue(self) -> None:
        """One successful exchange retires the card, from either path.

        A poll and a write are equally good proof: both mean the key decrypted and the device
        answered, which is the entire claim the card was making. Guarded on the flag so the
        common case — a device that has been fine for months — never touches the registry.
        """
        if not self._unreachable_issue_raised:
            return
        ir.async_delete_issue(self.hass, DOMAIN, self._unreachable_issue_id)
        self._unreachable_issue_raised = False
        _LOGGER.info("%s is answering again; repair issue cleared", self.device.host)
