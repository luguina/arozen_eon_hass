"""The repair card raised when the diffuser stops answering (#49).

Re-pairing the device in the Smart Life app mints a new local key, the old one stops
decrypting immediately, and before this the whole user-facing consequence was that every
entity went ``unavailable`` and a diagnostic counter climbed. Nothing said the fix existed.

What is actually being tested here is a **restraint**, and it is easier to break than the
feature. The card must:

* not appear for a router reboot, so the trigger is an hour of wall clock and not a count of
  failed polls — the poll interval is a user setting spanning 10 s to 3600 s, and a count
  means ten minutes at one end and two and a half days at the other;
* **not claim a cause.** A wrong local key and an unplugged diffuser are the same error
  payload at this layer (ADR-004, ADR-008), so the text names both and settles neither. There
  is a test below that reads the shipped string and holds it to that, because this is a
  property of the *words*, and words drift;
* not appear for a bug in our own code, which the card's advice does not fix;
* go away on its own, from a poll or a write, and never be raised twice for one outage.

``ArozenCoordinator``'s real constructor needs a running Home Assistant, so these build the
object explicitly, the same way ``tests/test_intensity_memory.py`` does and for the same
reason: a method that grows a dependency fails here with AttributeError rather than passing
against a permissive mock. The issue registry is replaced with a recorder — the real one
needs a hass with storage, and what these tests are about is *which calls are made*.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant", reason="coordinator tests need Home Assistant installed")

from custom_components.arozen_eon import coordinator as coordinator_module
from custom_components.arozen_eon.const import (
    DOMAIN,
    REPAIR_LEARN_MORE_URL,
    UNREACHABLE_BEFORE_REPAIR_S,
)
from custom_components.arozen_eon.coordinator import (
    ArozenCoordinator,
    IntensityMemory,
    PollHealth,
)
from custom_components.arozen_eon.device import ArozenUnreachable
from homeassistant.helpers import issue_registry as ir

INTEGRATION = Path(coordinator_module.__file__).parent
TRANSLATION_KEY = "device_unreachable"


# -- The streak clock ---------------------------------------------------------------------


def test_a_healthy_link_has_no_streak():
    assert PollHealth().unreachable_since_monotonic is None
    assert PollHealth().unreachable_for_at_least(0) is False


def test_the_streak_starts_at_the_first_failure_and_does_not_move():
    """``unreachable_since`` is the start, ``last_failure`` is the most recent one.

    Conflating them is the bug that would make the threshold unreachable: a start that
    advanced with every failure would measure the gap between two polls, which is the poll
    interval, for ever.
    """
    health = PollHealth()
    health.failed("first")
    started = health.unreachable_since_monotonic
    health.failed("second")

    assert health.unreachable_since_monotonic == started
    # `last_failure` is the wall clock the diagnostics sensor shows, and it does move.
    assert health.last_failure is not None


def test_the_first_failure_of_a_run_is_zero_seconds_old():
    # Not "a failure just happened, so something has been wrong for a while".
    health = PollHealth()
    health.failed("boom")
    assert health.unreachable_for_at_least(1) is False


def test_a_run_long_enough_is_reported_as_such():
    health = PollHealth()
    health.failed("boom")
    health.unreachable_since_monotonic = time.monotonic() - UNREACHABLE_BEFORE_REPAIR_S
    assert health.unreachable_for_at_least(UNREACHABLE_BEFORE_REPAIR_S) is True


def test_the_clock_is_monotonic_so_an_ntp_correction_cannot_raise_a_card():
    """A box with no real-time clock boots at the epoch and jumps decades when NTP answers.

    Subtracting wall clock across that jump reports fifty years of silence, and the second
    failed poll of the day puts a repair card on the screen. This holds the streak clock to a
    source that does not jump.
    """
    health = PollHealth()
    health.failed("boom")

    assert isinstance(health.unreachable_since_monotonic, float)
    assert health.unreachable_for_at_least(1) is False


def test_one_success_forgets_the_whole_run():
    health = PollHealth()
    health.failed("boom")
    health.unreachable_since_monotonic = time.monotonic() - 86400

    health.succeeded()

    assert health.unreachable_since_monotonic is None
    assert health.unreachable_for_at_least(0) is False


# -- The card ------------------------------------------------------------------------------


class FakeIssueRegistry:
    """Records what would have reached ``homeassistant.helpers.issue_registry``.

    ``IssueSeverity`` is the real enum rather than a stand-in, so a severity that does not
    exist still fails here instead of being quietly accepted.
    """

    IssueSeverity = ir.IssueSeverity

    def __init__(self) -> None:
        self.created: list[tuple[str, str, dict]] = []
        self.deleted: list[tuple[str, str]] = []

    def async_create_issue(self, hass, domain, issue_id, **kwargs) -> None:
        self.created.append((domain, issue_id, kwargs))

    def async_delete_issue(self, hass, domain, issue_id) -> None:
        self.deleted.append((domain, issue_id))


class FakeDevice:
    """Answers, or does not. ``fails`` makes every exchange raise, as a dead link does."""

    host = "-test-device"
    device_id = "test-device-id"

    def __init__(self, *, fails: bool = False, raises: type[Exception] | None = None):
        self._fails = fails
        self._raises = raises
        self.writes: list[tuple[int, object]] = []

    async def async_status(self):
        if self._raises is not None:
            raise self._raises("not a transport failure")
        if self._fails:
            raise ArozenUnreachable(f"{self.host}: status failed")
        return {"2": True, "3": "L3"}

    async def async_set_dp(self, dp_id, value):
        if self._fails:
            raise ArozenUnreachable(f"{self.host}: set DP {dp_id} failed")
        self.writes.append((dp_id, value))


@pytest.fixture
def registry(monkeypatch) -> FakeIssueRegistry:
    fake = FakeIssueRegistry()
    monkeypatch.setattr(coordinator_module, "ir", fake)
    return fake


def make_coordinator(device: FakeDevice | None = None, entry_id: str = "entry-1"):
    coordinator = object.__new__(ArozenCoordinator)
    coordinator.device = device if device is not None else FakeDevice()
    coordinator.health = PollHealth()
    coordinator.intensity = IntensityMemory()
    coordinator.data = None
    #: Only ever passed straight through to the issue registry, which is faked.
    coordinator.hass = object()
    coordinator.config_entry = SimpleNamespace(entry_id=entry_id)
    coordinator._exchange = asyncio.Lock()
    coordinator._unreachable_issue_raised = False
    coordinator.published = []
    coordinator.async_set_updated_data = coordinator.published.append
    return coordinator


def go_silent_for(coordinator: ArozenCoordinator, seconds: int, polls: int = 60) -> None:
    """Age the failure streak, rather than waiting an hour for it."""
    for _ in range(polls):
        coordinator.health.failed("no answer")
    coordinator.health.unreachable_since_monotonic = time.monotonic() - seconds


def test_a_short_outage_raises_nothing(registry):
    coordinator = make_coordinator()
    go_silent_for(coordinator, UNREACHABLE_BEFORE_REPAIR_S - 1)

    coordinator._raise_unreachable_issue()

    assert registry.created == []


def test_the_card_appears_once_the_silence_passes_the_threshold(registry):
    coordinator = make_coordinator()
    go_silent_for(coordinator, UNREACHABLE_BEFORE_REPAIR_S)

    coordinator._raise_unreachable_issue()

    assert len(registry.created) == 1
    domain, issue_id, kwargs = registry.created[0]
    assert domain == DOMAIN
    assert kwargs["translation_key"] == TRANSLATION_KEY
    assert kwargs["severity"] is ir.IssueSeverity.WARNING
    assert kwargs["learn_more_url"] == REPAIR_LEARN_MORE_URL
    # Not fixable, deliberately: the fix is the reconfigure step that already exists, and an
    # inline flow would be a second copy of it.
    assert kwargs["is_fixable"] is False
    assert issue_id.endswith("entry-1")


def test_the_card_is_not_raised_twice_for_one_outage(registry):
    coordinator = make_coordinator()
    go_silent_for(coordinator, UNREACHABLE_BEFORE_REPAIR_S)

    for _ in range(5):
        coordinator._raise_unreachable_issue()

    assert len(registry.created) == 1


def test_each_config_entry_gets_its_own_card(registry):
    """Two diffusers must not share one card, or the first to recover clears the other's."""
    first = make_coordinator(entry_id="entry-a")
    second = make_coordinator(entry_id="entry-b")
    for coordinator in (first, second):
        go_silent_for(coordinator, UNREACHABLE_BEFORE_REPAIR_S)
        coordinator._raise_unreachable_issue()

    raised = {issue_id for _, issue_id, _ in registry.created}

    assert len(raised) == 2


def test_a_successful_poll_retires_the_card(registry):
    coordinator = make_coordinator()
    go_silent_for(coordinator, UNREACHABLE_BEFORE_REPAIR_S)
    coordinator._raise_unreachable_issue()

    coordinator.health.succeeded()
    coordinator._clear_unreachable_issue()

    assert registry.deleted == [(DOMAIN, coordinator._unreachable_issue_id)]
    assert coordinator._unreachable_issue_raised is False


def test_clearing_a_card_that_was_never_raised_touches_nothing(registry):
    """The common case — a device that has been fine for months — never reaches the registry."""
    coordinator = make_coordinator()

    coordinator._clear_unreachable_issue()

    assert registry.deleted == []


# -- Through the real poll and write paths --------------------------------------------------


async def test_the_poll_path_raises_the_card_after_a_long_outage(registry):
    coordinator = make_coordinator(FakeDevice(fails=True))
    go_silent_for(coordinator, UNREACHABLE_BEFORE_REPAIR_S)

    with pytest.raises(Exception):
        await coordinator._async_update_data()

    assert len(registry.created) == 1
    assert registry.created[0][2]["translation_placeholders"]["host"] == FakeDevice.host


async def test_the_poll_path_retires_the_card_when_the_device_comes_back(registry):
    coordinator = make_coordinator(FakeDevice(fails=True))
    go_silent_for(coordinator, UNREACHABLE_BEFORE_REPAIR_S)
    with pytest.raises(Exception):
        await coordinator._async_update_data()

    coordinator.device = FakeDevice()
    await coordinator._async_update_data()

    assert registry.deleted == [(DOMAIN, coordinator._unreachable_issue_id)]


async def test_a_write_landing_also_retires_the_card(registry):
    """A write proves the key decrypted just as well as a poll does."""
    coordinator = make_coordinator(FakeDevice(fails=True))
    go_silent_for(coordinator, UNREACHABLE_BEFORE_REPAIR_S)
    with pytest.raises(Exception):
        await coordinator._async_update_data()

    coordinator.device = FakeDevice()
    await coordinator.async_set_dp(2, True)

    assert registry.deleted == [(DOMAIN, coordinator._unreachable_issue_id)]


async def test_a_bug_in_our_own_code_does_not_advise_reconfiguring(registry):
    """The card's advice is "check the power, or reconfigure the key". A TypeError is neither.

    The failure still counts — `Failed polls` counts failures — but the user is not sent to
    re-enter a credential that was never wrong.
    """
    coordinator = make_coordinator(FakeDevice(raises=TypeError))
    go_silent_for(coordinator, UNREACHABLE_BEFORE_REPAIR_S)

    with pytest.raises(TypeError):
        await coordinator._async_update_data()

    assert registry.created == []
    assert coordinator.health.total > 0


# -- The words on the card -------------------------------------------------------------------


def _issue_strings() -> list[dict]:
    """The card's text as each of the two string files carries it.

    ``strings.json`` is what hassfest validates; ``translations/en.json`` is what a running
    instance renders. Whole-file equality is asserted in test_config_flow_reconfigure.py; this
    reads both anyway, because a test that reads only one of them cannot notice a card that
    ships different words to the person actually looking at it.
    """
    return [
        json.loads(path.read_text(encoding="utf-8"))["issues"][TRANSLATION_KEY]
        for path in (INTEGRATION / "strings.json", INTEGRATION / "translations" / "en.json")
    ]


def test_both_string_files_carry_the_card():
    first, second = _issue_strings()
    assert first == second
    assert first["title"] and first["description"]


def test_the_card_names_both_causes_and_asserts_neither():
    """The one assertion this whole feature exists to preserve.

    A card that said "your local key is wrong" would be the reauth flow's mistake wearing a
    different hat: on this transport a wrong key and an unplugged diffuser are the same error
    payload (ADR-008). So the text must carry both branches *and* say out loud that it cannot
    tell which.
    """
    for text in _issue_strings():
        description = text["description"].lower()
        assert "re-pair" in description  # the branch with a fix
        assert "network" in description  # the branch with a check
        assert "cannot tell them apart" in description


def test_the_card_points_at_the_reconfigure_step_rather_than_a_reinstall():
    for text in _issue_strings():
        assert "reconfigure" in text["description"].lower()
        # The entity ids surviving is the whole reason it is not delete-and-re-add.
        assert "entity ids" in text["description"].lower()


def test_every_placeholder_the_code_passes_is_used_by_the_text():
    """A placeholder the string does not use is dead weight; one it uses and the code does not
    pass renders as a literal ``{minutes}`` on somebody's Repairs page."""
    passed = {"host", "minutes", "failures"}
    for text in _issue_strings():
        blob = text["title"] + text["description"]
        used = set(re.findall(r"\{(\w+)\}", blob))
        assert used == passed


async def test_the_placeholders_are_the_ones_the_code_actually_sends(registry):
    coordinator = make_coordinator(FakeDevice(fails=True))
    go_silent_for(coordinator, UNREACHABLE_BEFORE_REPAIR_S, polls=42)
    with pytest.raises(Exception):
        await coordinator._async_update_data()

    placeholders = registry.created[0][2]["translation_placeholders"]

    assert placeholders["host"] == FakeDevice.host
    assert placeholders["minutes"] == str(UNREACHABLE_BEFORE_REPAIR_S // 60)
    # 42 aged failures plus the one this poll just recorded.
    assert placeholders["failures"] == "43"
    assert all(isinstance(value, str) for value in placeholders.values())


# -- Where "Learn more" goes -------------------------------------------------------------------


def test_learn_more_is_built_on_the_manifest_documentation_url():
    """One URL to change when the repository is renamed, not two.

    The manifest is the authoritative copy — it is what Home Assistant links from the
    integration page — so the repair card's button is held to the same host and path.
    """
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))

    assert REPAIR_LEARN_MORE_URL.startswith(manifest["documentation"] + "#")


def test_learn_more_lands_on_a_heading_that_exists():
    """A fragment that matches nothing scrolls to nowhere, which is worse than no button.

    GitHub's anchor for a heading is its text lowercased, with anything that is not a letter,
    digit, space or hyphen dropped and spaces turned into hyphens. Computing that here means a
    reworded README heading fails the suite instead of silently breaking the button.
    """
    readme = (INTEGRATION.parent.parent / "README.md").read_text(encoding="utf-8")
    anchors = set()
    for line in readme.splitlines():
        if match := re.match(r"^#{1,6}\s+(.*)$", line):
            slug = re.sub(r"[^\w\s-]", "", match.group(1).strip().lower())
            # One hyphen per space, not per run of them: a heading with an em dash loses the
            # dash and keeps both surrounding spaces, which is why ADR anchors carry `--`.
            anchors.add(re.sub(r"\s", "-", slug))

    fragment = REPAIR_LEARN_MORE_URL.split("#", 1)[1]

    assert fragment in anchors
