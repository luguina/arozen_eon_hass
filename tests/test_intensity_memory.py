"""Tests for the intensity memory and the power-on restore it feeds (#14).

The firmware clears intensity to L1 on every power-on, whoever performs it, in the same status
record as the power change. The coordinator writes the level back. The rules worth pinning,
and every one of them is a way this could go wrong rather than a way it goes right:

* **no power-on reading ever teaches the memory the firmware's default.** That is the exact
  invariant, and it is narrower than "power-on readings do not teach" — a memory that learned
  L1 from the reading carrying the reset would restore L1 for ever, which is the naive version
  of this feature;
* **but a level somebody set after the power-on wins, and does teach.** An external power-on
  is not noticed until the next poll, so a power-on reading showing anything *other* than L1
  did not come from the firmware — a human got there first, and their choice is newer;
* **a failed restore does not teach the memory the value it failed to correct.** Otherwise one
  unreachable moment silently adopts L1 as the new preference and the feature quietly dies;
* **nothing is ever written that the device already has**, and nothing is invented when there
  is no memory to restore from.

``ArozenCoordinator``'s real constructor needs a running Home Assistant and this repo does not
carry ``pytest-homeassistant-custom-component``, so the coordinator tests build the object
explicitly (``make_coordinator``) rather than mocking it. See that helper for why that is a
narrower thing than it sounds.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("homeassistant", reason="coordinator tests need Home Assistant installed")

from custom_components.arozen_eon import dp
from custom_components.arozen_eon.coordinator import (
    ArozenCoordinator,
    IntensityMemory,
    PollHealth,
)
from custom_components.arozen_eon.device import ArozenUnreachable
from custom_components.arozen_eon.sensor import ArozenIntensityRestoresSensor
from homeassistant.const import EntityCategory

DEFAULT = dp.INTENSITY_POWER_ON_DEFAULT  # "L1", measured; see dp.py


# -- The state machine --------------------------------------------------------------------


def test_memory_starts_with_nothing_to_restore():
    memory = IntensityMemory()
    assert memory.wanted is None
    assert memory.restore_for(DEFAULT) is None


def test_memory_learns_from_an_ordinary_reading():
    # Whatever the device reports outside a power-on is a real setting - ours, the app's, or
    # one somebody pressed on the remote. All three are the user's preference.
    memory = IntensityMemory()
    memory.observe("L3")
    assert memory.wanted == "L3"


def test_memory_ignores_an_unreadable_level():
    memory = IntensityMemory()
    memory.observe("L3")
    memory.observe(None)  # the device answered, but not with DP 3
    assert memory.wanted == "L3"


def test_restore_returns_the_level_the_power_on_threw_away():
    memory = IntensityMemory()
    memory.observe("L3")
    assert memory.restore_for(DEFAULT) == "L3"


def test_restore_declines_when_nothing_is_remembered():
    # A fresh load that has not seen a reading yet. Inventing a level is worse than leaving
    # the firmware's.
    assert IntensityMemory().restore_for(DEFAULT) is None


def test_restore_declines_when_the_device_already_has_the_wanted_level():
    memory = IntensityMemory()
    memory.observe(DEFAULT)
    assert memory.restore_for(DEFAULT) is None


def test_restore_declines_and_learns_when_somebody_got_there_first():
    """The guard that keeps this from fighting whoever is holding the remote.

    An external power-on is not seen until the next poll - up to a minute. If the device
    reports a level other than the default by then, a human chose it in between, and their
    choice is newer than the memory. It wins, and it teaches.
    """
    memory = IntensityMemory()
    memory.observe("L3")
    assert memory.restore_for("L5") is None
    assert memory.wanted == "L5"


def test_restore_declines_when_the_level_is_unreadable():
    # Not knowing what the device is running at is not a reason to write to it.
    memory = IntensityMemory()
    memory.observe("L3")
    assert memory.restore_for(None) is None
    assert memory.wanted == "L3"


def test_an_explicit_selection_outranks_an_observation():
    memory = IntensityMemory()
    memory.observe("L3")
    memory.remember("L6")
    assert memory.wanted == "L6"


# -- Failure, and the degradation it would otherwise cause --------------------------------


def test_a_failed_restore_is_counted_and_keeps_its_error():
    memory = IntensityMemory()
    memory.observe("L3")
    memory.restore_for(DEFAULT)
    memory.restore_failed("boom")
    assert (memory.failures, memory.restored, memory.last_error) == (1, 0, "boom")


def test_a_failed_restore_does_not_teach_the_memory_the_value_it_failed_to_fix():
    """The subtle way this feature would die: quietly, over one unreachable moment.

    After a failed restore the device is sitting at L1 *because our write did not land*.
    Reading that back proves nothing, and adopting it would replace the user's level with the
    failure - after which every future restore is a no-op and nobody ever finds out why.
    """
    memory = IntensityMemory()
    memory.observe("L3")
    memory.restore_for(DEFAULT)
    memory.restore_failed("boom")

    memory.observe(DEFAULT)
    assert memory.wanted == "L3"

    # ...but a level that is not the default *is* a fresh choice, so learning resumes.
    memory.observe("L4")
    assert memory.wanted == "L4"
    assert memory.unconfirmed is False


def test_an_explicit_selection_ends_an_unconfirmed_restore():
    # The user has just said what they want, which settles the question the flag keeps open.
    memory = IntensityMemory()
    memory.observe("L3")
    memory.restore_for(DEFAULT)
    memory.restore_failed("boom")
    memory.remember("L2")
    assert (memory.wanted, memory.unconfirmed) == ("L2", False)


def test_a_confirmed_restore_resumes_learning_and_is_counted():
    memory = IntensityMemory()
    memory.observe("L3")
    assert memory.restore_for(DEFAULT) == "L3"
    assert memory.unconfirmed is True

    memory.restore_written()
    memory.observe("L3")  # the device reported the restored level back
    assert (memory.restored, memory.failures, memory.unconfirmed) == (1, 0, False)


# -- The coordinator funnel ---------------------------------------------------------------


class FakeDevice:
    """Answers status reads from a script, so a test can say what the wire returns.

    The last scripted reading repeats, so a test only has to write down the readings it
    actually cares about.
    """

    host = "-test-device"
    device_id = "test-device-id"

    def __init__(
        self,
        *statuses,
        write_fails: set[int] | None = None,
        reads_ok: int | None = None,
    ):
        self._statuses = list(statuses) or [{}]
        self._write_fails = write_fails or set()
        #: How many status reads answer before the link starts failing. None means all of
        #: them; 0 means the very next one raises.
        self._reads_ok = reads_ok
        self.reads = 0
        self.writes: list[tuple[int, object]] = []

    async def async_status(self):
        self.reads += 1
        if self._reads_ok is not None and self.reads > self._reads_ok:
            raise ArozenUnreachable(f"{self.host}: status failed")
        return self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]

    async def async_set_dp(self, dp_id, value):
        if dp_id in self._write_fails:
            raise ArozenUnreachable(f"{self.host}: set DP {dp_id} = {value!r} failed")
        self.writes.append((dp_id, value))


def make_coordinator(
    device: FakeDevice, data=None, remembers: str | None = None
) -> ArozenCoordinator:
    """An ArozenCoordinator carrying only the parts these tests touch.

    The real constructor needs a running Home Assistant. The methods under test read five
    attributes - the device, the memory, the previous DP set, the exchange lock and the repair
    card's flag - so the shell is built explicitly rather than mocked: a method that grows a
    sixth dependency fails here with AttributeError instead of quietly passing against a
    permissive mock. That has already happened once, which is the argument for the idiom: #49
    added a `_clear_unreachable_issue()` call to the write path and these tests broke, rather
    than passing while exercising a coordinator no production code resembles.

    ``async_set_updated_data`` is the one piece of real coordinator machinery in the path, and
    it is replaced by a list so a test can assert on what would have reached the entities.

    ``data`` and ``remembers`` are **not** the same thing, and conflating them is a mistake
    worth naming here because it is easy to make: ``data`` is what the device last reported,
    ``remembers`` is what we intend to put back. In production the second is filled from the
    first by every ordinary poll - which is what ``observe`` is - and
    ``test_ordinary_polling_fills_the_memory_the_edge_then_uses`` drives that wiring rather
    than assuming it.
    """
    coordinator = object.__new__(ArozenCoordinator)
    coordinator.device = device
    coordinator.health = PollHealth()
    coordinator.intensity = IntensityMemory()
    if remembers is not None:
        coordinator.intensity.observe(remembers)
    coordinator.data = data
    coordinator._exchange = asyncio.Lock()
    #: The write path retires the repair card on a successful write (#49). Nothing here raises
    #: one, so False is both the honest starting state and the value that keeps these tests
    #: away from the issue registry entirely - the guard in `_clear_unreachable_issue` returns
    #: before touching it. `tests/test_repair_issue.py` is where the card itself is tested.
    coordinator._unreachable_issue_raised = False
    coordinator.published = []
    coordinator.async_set_updated_data = coordinator.published.append
    return coordinator


async def test_a_power_on_restores_the_level_the_firmware_cleared():
    """The acceptance case: off at L4, switched on, device says L1, we put L4 back."""
    device = FakeDevice({"2": True, "3": "L4"})  # the read-back confirming the restore
    coordinator = make_coordinator(device, data={"2": False, "3": "L4"}, remembers="L4")

    published = await coordinator._async_apply_intensity_memory({"2": True, "3": DEFAULT})

    assert device.writes == [(dp.DP_INTENSITY, "L4")]
    # The corrected reading is what reaches the entities, so the select never shows L1 for an
    # interval and then steps up on its own.
    assert published == {"2": True, "3": "L4"}
    assert coordinator.intensity.restored == 1


async def test_powering_off_restores_nothing():
    # The off edge touches neither intensity nor the countdown - unanimous across all six
    # captured off-edges - and nothing here should give it something to do.
    device = FakeDevice({"2": False, "3": "L4"})
    coordinator = make_coordinator(device, data={"2": True, "3": "L4"})

    await coordinator._async_apply_intensity_memory({"2": False, "3": "L4"})

    assert device.writes == []


async def test_a_level_change_while_running_teaches_and_writes_nothing():
    device = FakeDevice({"2": True, "3": "L6"})
    coordinator = make_coordinator(device, data={"2": True, "3": "L4"})

    await coordinator._async_apply_intensity_memory({"2": True, "3": "L6"})

    assert device.writes == []
    assert coordinator.intensity.wanted == "L6"


async def test_the_first_reading_is_never_an_edge():
    # A power-on that happened while Home Assistant was down leaves no edge to see, and is
    # not guessed at.
    device = FakeDevice({"2": True, "3": DEFAULT})
    coordinator = make_coordinator(device, data=None)

    await coordinator._async_apply_intensity_memory({"2": True, "3": DEFAULT})

    assert device.writes == []


async def test_a_power_on_with_nothing_remembered_writes_nothing():
    # The previous reading carried no DP 3, so there is no level to put back.
    device = FakeDevice({"2": True, "3": DEFAULT})
    coordinator = make_coordinator(device, data={"2": False})

    await coordinator._async_apply_intensity_memory({"2": True, "3": DEFAULT})

    assert device.writes == []
    assert coordinator.intensity.restored == 0


async def test_a_power_on_someone_has_already_corrected_is_left_alone():
    # Powered on from the remote, and an intensity button pressed before our poll landed.
    device = FakeDevice({"2": True, "3": "L5"})
    coordinator = make_coordinator(device, data={"2": False, "3": "L3"})

    published = await coordinator._async_apply_intensity_memory({"2": True, "3": "L5"})

    assert device.writes == []
    assert published == {"2": True, "3": "L5"}
    assert coordinator.intensity.wanted == "L5"


async def test_a_failed_restore_publishes_the_truth_and_counts_itself():
    """A failed restore must not leave the entities showing the level the user wanted.

    The device is running at L1. The published reading says L1, the intensity select will
    therefore say L1, and the diagnostic counter carries the reason.
    """
    device = FakeDevice({"2": True, "3": DEFAULT}, write_fails={dp.DP_INTENSITY})
    coordinator = make_coordinator(device, data={"2": False, "3": "L4"}, remembers="L4")

    published = await coordinator._async_apply_intensity_memory({"2": True, "3": DEFAULT})

    assert published == {"2": True, "3": DEFAULT}
    assert (coordinator.intensity.failures, coordinator.intensity.restored) == (1, 0)
    assert coordinator.intensity.last_error is not None
    assert coordinator.intensity.wanted == "L4"  # still wanted, and still to be restored


async def test_a_restore_whose_read_back_fails_still_counts_and_stays_unconfirmed():
    # The write was accepted, so the level is almost certainly right; we just cannot prove it.
    device = FakeDevice({"2": True, "3": DEFAULT}, reads_ok=0)
    coordinator = make_coordinator(device, data={"2": False, "3": "L4"}, remembers="L4")

    published = await coordinator._async_apply_intensity_memory({"2": True, "3": DEFAULT})

    assert device.writes == [(dp.DP_INTENSITY, "L4")]
    assert published == {"2": True, "3": DEFAULT}
    assert coordinator.intensity.restored == 1
    assert coordinator.intensity.unconfirmed is True


async def test_ordinary_polling_fills_the_memory_the_edge_then_uses():
    """The two halves in sequence, because neither is any use without the other.

    Nothing teaches the memory except ordinary readings, and the reading that carries the
    power-on deliberately is not one of them. So the restore depends entirely on a poll having
    been through here first - which is the wiring an isolated edge test quietly assumes.
    """
    device = FakeDevice({"2": True, "3": "L6"})  # the read-back confirming the restore
    coordinator = make_coordinator(device, data=None)

    # Running at L6. First poll of a fresh load: no previous reading, so no edge - it teaches.
    await coordinator._async_apply_intensity_memory({"2": True, "3": "L6"})
    coordinator.data = {"2": True, "3": "L6"}
    assert coordinator.intensity.wanted == "L6"

    # Switched off. The device holds L6 while off, and this still is not an edge.
    await coordinator._async_apply_intensity_memory({"2": False, "3": "L6"})
    coordinator.data = {"2": False, "3": "L6"}

    # Switched back on, and the firmware has cleared the level.
    published = await coordinator._async_apply_intensity_memory({"2": True, "3": DEFAULT})

    assert device.writes == [(dp.DP_INTENSITY, "L6")]
    assert published == {"2": True, "3": "L6"}


# -- The write path, end to end -----------------------------------------------------------


async def test_turning_on_through_the_coordinator_corrects_in_the_same_exchange():
    """What switch.turn_on does: power on, firmware resets, level back, all before returning.

    This is the difference between our own switch and the remote - no poll interval spent at
    L1, because the correction happens inside the same conversation with the device.
    """
    device = FakeDevice({"2": True, "3": DEFAULT}, {"2": True, "3": "L4"})
    coordinator = make_coordinator(device, data={"2": False, "3": "L4"}, remembers="L4")

    await coordinator.async_set_dp(dp.DP_POWER, True)

    assert device.writes == [(dp.DP_POWER, True), (dp.DP_INTENSITY, "L4")]
    assert coordinator.published == [{"2": True, "3": "L4"}]


async def test_an_intensity_selection_is_remembered_even_when_the_read_back_fails():
    # The user's choice is recorded on the write, which succeeded - not on the follow-up read,
    # which is allowed to fail.
    device = FakeDevice({"2": True, "3": "L2"}, reads_ok=0)
    coordinator = make_coordinator(device, data={"2": True, "3": "L4"})

    await coordinator.async_set_dp(dp.DP_INTENSITY, "L2")

    assert coordinator.intensity.wanted == "L2"
    assert coordinator.published == []  # nothing to publish; the read never answered


# -- The meter ----------------------------------------------------------------------------
#
# A restore that works erases the evidence that the firmware ever threw the level away, and a
# restore that fails leaves the intensity select honestly reporting L1 - true, and silent about
# why. This entity is where both go. Same reasoning as the Failed polls sensor, and the same
# reason it is a diagnostic that never goes unavailable: the reading you most want is the one
# taken while the device is unreachable.


class FakeCoordinatorForEntity:
    """Just enough of ArozenCoordinator for a diagnostic entity to sit on."""

    def __init__(self, intensity: IntensityMemory):
        self.data = None
        self.last_update_success = True
        self.device = FakeDevice()
        self.intensity = intensity

    def async_add_listener(self, *args, **kwargs):
        return lambda: None


def test_the_restore_counter_starts_at_zero_and_admits_it_remembers_nothing():
    sensor = ArozenIntensityRestoresSensor(FakeCoordinatorForEntity(IntensityMemory()))
    assert sensor.native_value == 0
    # Worth surfacing: a restore that declines because it remembers nothing looks identical
    # from outside to one that declines because the level is already right.
    assert sensor.extra_state_attributes["remembered_level"] is None
    # False here means "no restore is outstanding", which on a fresh load is the honest
    # reading. The attribute is deliberately named for that rather than for its inverse: a
    # `confirmed: True` sitting next to a count of zero invites reading it as "the last
    # restore succeeded" when no restore has ever been attempted.
    assert sensor.extra_state_attributes["restore_unconfirmed"] is False


def test_the_restore_counter_counts_a_restore_the_device_confirmed():
    memory = IntensityMemory()
    memory.observe("L4")
    memory.restore_for(DEFAULT)
    memory.restore_written()
    memory.observe("L4")  # the device reported it back

    sensor = ArozenIntensityRestoresSensor(FakeCoordinatorForEntity(memory))
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["restore_unconfirmed"] is False
    assert sensor.extra_state_attributes["failed"] == 0


def test_the_restore_counter_carries_the_failure_and_its_reason():
    memory = IntensityMemory()
    memory.observe("L4")
    memory.restore_for(DEFAULT)
    memory.restore_failed("-test-device: set DP 3 = 'L4' failed")

    sensor = ArozenIntensityRestoresSensor(FakeCoordinatorForEntity(memory))
    assert sensor.native_value == 0
    assert sensor.extra_state_attributes == {
        "failed": 1,
        "last_error": "-test-device: set DP 3 = 'L4' failed",
        "remembered_level": "L4",
        "restore_unconfirmed": True,
    }


def test_the_restore_counter_is_a_diagnostic_that_never_goes_unavailable():
    sensor = ArozenIntensityRestoresSensor(FakeCoordinatorForEntity(IntensityMemory()))
    assert sensor.available is True
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC
