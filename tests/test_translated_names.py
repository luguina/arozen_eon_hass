"""The entity names, icons and error messages, now that none of them are Python literals (#50).

Moving a name out of Python and into `strings.json` is a rename with a silent failure mode. The
display name is what Home Assistant slugifies into an entity id on first registration, so a name
that comes back one character different — or does not come back at all, because the key was
misspelled and the lookup missed — produces a *different entity id* for anybody installing
fresh, while every existing install keeps the old one and looks fine. Nothing in the integration
notices, and the first symptom is somebody's dashboard.

So these tests do not check the JSON against itself. They drive Home Assistant's own name
resolution — `Entity._name_internal`, reached through `Entity.name`, with the real
`translations/en.json` loaded the way `EntityPlatform` loads it — and assert the string that
comes out is the one that was in Python before. Written out as literals rather than read from
the file, because a test that computes its expectation from the thing it checks follows a
rename instead of catching it.

The other three ways this change could go wrong, one section each:

* the two string files drift, so hassfest validates one and the running instance renders the
  other (whole-file equality is pinned in test_config_flow_reconfigure.py; here it is the
  entity block specifically, which is the half that decides entity ids);
* an icon is left behind in Python, or `icons.json` names a key no entity has;
* an exception's placeholders and its message stop matching, which is invisible until the
  error fires — and these four fire on a device that has just failed, which is not the moment
  to discover the message cannot be rendered.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("homeassistant", reason="entity tests need Home Assistant installed")

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import PlatformData

from custom_components.arozen_eon.binary_sensor import (
    ArozenChargingBinarySensor,
    ArozenMistingBinarySensor,
)
from custom_components.arozen_eon.const import DOMAIN
from custom_components.arozen_eon.device import ArozenError
from custom_components.arozen_eon.select import ArozenIntensitySelect, ArozenTimerSelect
from custom_components.arozen_eon.sensor import (
    ArozenBatterySensor,
    ArozenCountdownRemainingSensor,
    ArozenDatapointsSensor,
    ArozenFailedPollsSensor,
    ArozenIntensityRestoresSensor,
)
from custom_components.arozen_eon.switch import ArozenLedSwitch, ArozenPowerSwitch

INTEGRATION = Path(__file__).resolve().parent.parent / "custom_components" / "arozen_eon"

#: Every entity, the platform it belongs to, and the name it displayed when the name was a
#: Python literal. The third column is the assertion: these strings are what the entity ids in
#: README.md and tools/verify_ha.py were slugified from, so they are frozen by anything already
#: installed, not merely by taste.
ENTITIES = [
    (ArozenPowerSwitch, "switch", None),
    (ArozenLedSwitch, "switch", "LED"),
    (ArozenMistingBinarySensor, "binary_sensor", "Misting"),
    (ArozenChargingBinarySensor, "binary_sensor", "Charging"),
    (ArozenIntensitySelect, "select", "Intensity"),
    (ArozenTimerSelect, "select", "Timer"),
    (ArozenBatterySensor, "sensor", "Battery"),
    (ArozenCountdownRemainingSensor, "sensor", "Timer remaining"),
    (ArozenFailedPollsSensor, "sensor", "Failed polls"),
    (ArozenIntensityRestoresSensor, "sensor", "Intensity restores"),
    (ArozenDatapointsSensor, "sensor", "Datapoints (recon)"),
]

#: The icons that were `_attr_icon` in Python and are now `icons.json`, by platform and key.
STATIC_ICONS = {
    ("binary_sensor", "misting"): "mdi:air-humidifier",
    ("select", "intensity"): "mdi:air-filter",
    ("select", "timer"): "mdi:timer-cog-outline",
    ("sensor", "failed_polls"): "mdi:radar",
    ("sensor", "intensity_restores"): "mdi:backup-restore",
    ("sensor", "timer_remaining"): "mdi:timer-outline",
    ("sensor", "datapoints"): "mdi:database-search-outline",
    ("switch", "power"): "mdi:scent",
}


class FakeDevice:
    host = "-test-device"
    device_id = "test-device-id"


class FakeCoordinator:
    """Enough coordinator to construct an entity. Same shell idiom as the other suites."""

    def __init__(self, data=None, last_update_success=True, error=None):
        self.data = data
        self.last_update_success = last_update_success
        self.device = FakeDevice()
        self.writes = []
        self._error = error

    async def async_set_dp(self, number, value):
        if self._error is not None:
            raise self._error
        self.writes.append((number, value))


def _strings(name: str = "strings.json") -> dict:
    return json.loads((INTEGRATION / name).read_text(encoding="utf-8"))


def _english() -> dict:
    return _strings("translations/en.json")


def _placed(entity, platform: str):
    """The entity as Home Assistant sees it once a platform has adopted it.

    `PlatformData` is Home Assistant's own class rather than a stand-in: the lookup key is built
    from its `platform_name` and `domain` inside `_name_translation_key`, and a fake that got
    either wrong would agree with a test that made the same mistake twice.
    """
    data = PlatformData(None, domain=platform, platform_name=DOMAIN)
    data.platform_translations = {
        f"component.{DOMAIN}.entity.{platform}.{key}.name": spec["name"]
        for key, spec in _english()["entity"].get(platform, {}).items()
    }
    entity.platform_data = data
    return entity


# -- The names, resolved the way Home Assistant resolves them --------------------------------


@pytest.mark.parametrize(
    ("factory", "platform", "expected"), ENTITIES, ids=lambda value: getattr(value, "__name__", value)
)
def test_the_displayed_name_is_the_one_that_used_to_be_in_python(factory, platform, expected):
    entity = _placed(factory(FakeCoordinator()), platform)

    assert entity.name == expected


def test_the_power_switch_still_takes_the_devices_own_name():
    """It carries a translation key — `icons.json` is addressed by key and has no other way to
    reach it — and that key must not become a name. `_name_internal` returns `_attr_name` the
    moment the attribute exists, before any translation lookup, so `None` wins; this pins that
    reading of Home Assistant's source, because the alternative is an entity called
    `Arozen EON Pro 2 Power` and a changed entity id for every fresh install."""
    entity = _placed(ArozenPowerSwitch(FakeCoordinator()), "switch")

    assert entity.translation_key == "power"
    assert entity.name is None


def test_every_translation_key_matches_the_key_its_unique_id_is_built_from():
    """One vocabulary, two lifetimes. The unique id is registry identity and can never change;
    the translation key is presentation and could. They are asserted equal rather than derived
    from a shared literal for exactly that reason — deriving would turn a harmless rename of a
    display key into a silent orphaning of everybody's entity."""
    for factory, _platform, _name in ENTITIES:
        entity = factory(FakeCoordinator())
        suffix = entity.unique_id.removeprefix(f"{FakeDevice.device_id}_")
        assert entity.translation_key == suffix, factory.__name__


def test_no_entity_name_is_a_python_literal_any_more():
    """The vacuity guard on the whole change. `_attr_name = None` on the power switch is the
    one that stays, and it is not a name."""
    offenders = []
    for module in ("binary_sensor.py", "select.py", "sensor.py", "switch.py"):
        for number, line in enumerate((INTEGRATION / module).read_text().splitlines(), 1):
            assignment = re.match(r"\s*_attr_name\s*=\s*(\S.*?)\s*$", line)
            if assignment and assignment.group(1) != "None":
                offenders.append(f"{module}:{number}: {line.strip()}")
    assert not offenders, offenders


# -- The two string files ---------------------------------------------------------------------


def test_both_string_files_carry_the_same_entity_names():
    """Whole-file equality is pinned in test_config_flow_reconfigure.py. This is the entity
    block on its own, because it is the half that decides entity ids, and because a failure
    here should say so rather than reporting that two large files differ somewhere."""
    assert _strings()["entity"] == _english()["entity"]
    assert _strings()["exceptions"] == _english()["exceptions"]


def test_the_entity_block_names_every_entity_and_nothing_else():
    """A leftover key is a name nobody renders and a translator still translates; a missing one
    falls back to the device class or to nothing at all, quietly."""
    declared = {
        (platform, key)
        for platform, entities in _strings()["entity"].items()
        for key in entities
    }
    wanted = {
        (platform, factory(FakeCoordinator()).translation_key)
        for factory, platform, name in ENTITIES
        if name is not None
    }
    assert declared == wanted


# -- The icons ---------------------------------------------------------------------------------


def test_icons_json_carries_every_static_icon():
    icons = json.loads((INTEGRATION / "icons.json").read_text(encoding="utf-8"))["entity"]
    declared = {
        (platform, key): spec["default"]
        for platform, entities in icons.items()
        for key, spec in entities.items()
    }

    assert declared == STATIC_ICONS


def test_the_only_icon_left_in_python_is_the_one_that_reads_a_state():
    """`icons.json` could express the LED's three-way icon with a `state` block — this is not a
    limitation of the file. It stays in `switch.py` because it has to agree with `is_on` about
    what `None` means, and the person who changes that will be reading `is_on`."""
    offenders = []
    for module in ("binary_sensor.py", "select.py", "sensor.py", "switch.py"):
        for number, line in enumerate((INTEGRATION / module).read_text().splitlines(), 1):
            if re.match(r"\s*_attr_icon\s*=", line):
                offenders.append(f"{module}:{number}: {line.strip()}")
    assert not offenders, offenders

    led = ArozenLedSwitch(FakeCoordinator(data={"7": True}))
    assert led.icon == "mdi:led-on"
    assert ArozenLedSwitch(FakeCoordinator(data={"7": False})).icon == "mdi:led-off"
    assert ArozenLedSwitch(FakeCoordinator(data=None)).icon == "mdi:led-outline"


# -- The four errors ----------------------------------------------------------------------------


async def _raised(entity, method, *args) -> HomeAssistantError:
    entity.entity_id = "switch.arozen_eon_pro_2"
    with pytest.raises(HomeAssistantError) as caught:
        await getattr(entity, method)(*args)
    return caught.value


def _message(key: str) -> str:
    return _strings()["exceptions"][key]["message"]


@pytest.mark.parametrize(
    ("factory", "method", "args", "key"),
    [
        (ArozenPowerSwitch, "async_turn_on", (), "turn_on_failed"),
        (ArozenPowerSwitch, "async_turn_off", (), "turn_off_failed"),
        (ArozenLedSwitch, "async_turn_on", (), "turn_on_failed"),
        (ArozenLedSwitch, "async_turn_off", (), "turn_off_failed"),
        (ArozenIntensitySelect, "async_select_option", ("L1 · every 1 min",),
         "set_option_failed"),
        (ArozenTimerSelect, "async_select_option", ("Continuous",), "set_option_failed"),
    ],
    ids=lambda value: str(value),
)
async def test_a_failed_write_raises_a_translated_error(factory, method, args, key):
    """The message is not asserted, and that is the point: it lives in `strings.json` now, and
    a test quoting it would only pin a copy. What is asserted is the wiring — domain, key, and
    a placeholder for every `{slot}` the message actually has."""
    coordinator = FakeCoordinator(data={"2": True, "7": True}, error=ArozenError("boom"))
    error = await _raised(factory(coordinator), method, *args)

    assert error.translation_domain == DOMAIN
    assert error.translation_key == key
    assert set(error.translation_placeholders) == set(re.findall(r"\{(\w+)\}", _message(key)))


async def test_an_option_the_map_does_not_know_raises_the_bug_report_error():
    """Unreachable through the UI — Home Assistant filters against `_attr_options` first — so
    this fires only when the datapoint map is wrong. Translated anyway, for one mechanism in
    one method; the diagnosis rides in the placeholders, which no translation touches."""
    entity = ArozenIntensitySelect(FakeCoordinator(data={"3": "L1"}))
    error = await _raised(entity, "async_select_option", "not a level")

    assert error.translation_key == "unknown_option"
    assert error.translation_placeholders["option"] == "not a level"
    assert set(error.translation_placeholders) == set(
        re.findall(r"\{(\w+)\}", _message("unknown_option"))
    )


def test_no_error_message_is_an_f_string_any_more():
    """The vacuity guard on the other half. A `HomeAssistantError` built from a literal is one
    nobody can translate, and it is the exact shape this change removed."""
    offenders = []
    for module in ("select.py", "switch.py"):
        text = (INTEGRATION / module).read_text()
        for match in re.finditer(r"raise HomeAssistantError\(\s*\n\s*(.)", text):
            if match.group(1) in {'f', '"', "'"}:
                offenders.append(f"{module}: {text[match.start():match.start() + 90]!r}")
    assert not offenders, offenders
