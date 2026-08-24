"""The one entity that ships switched off, and the reasons it is that one (#51).

`Datapoints (recon)` is scaffolding: its state is a count of datapoints and its attributes are
the raw Tuya payload. It was the recon phase's instrument inside Home Assistant and it is still
the only *live* view of the raw dps — but it is also one of eleven entities on the device page
of somebody who bought a diffuser, with a parenthetical in its name explaining that it is not
for them. So it is registered and disabled, and the installer never meets it.

Three things this module holds, because each of them is a way the decision could be undone
without anyone noticing:

* **the flag is on the recon sensor and on nothing else.** `entity_registry_enabled_default`
  is inherited, so setting it one class up — on `ArozenDiagnosticSensor`, or on `ArozenEntity`
  — would silently switch off `Failed polls`, `Intensity restores` and, one level higher,
  every entity the integration has. The vacuity guard here is the test that would fail;
* **the sensor still reads what it always read.** Disabling an entity is a change to where it
  appears, not to what it says, and until this module existed nothing at all covered this
  class's state or attributes;
* **the real-Home-Assistant harness agrees.** `tools/verify_ha.py` asserts the entity set
  exactly and fails on a stray, so the recon sensor had to move from `EXPECTED_ENTITIES` to
  `EXPECTED_DISABLED_ENTITIES` in the same change. That harness runs against a live diffuser
  a few times a year; this runs on every push, which is the whole reason to pin the pair here.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

pytest.importorskip("homeassistant", reason="entity tests need Home Assistant installed")

from custom_components.arozen_eon.binary_sensor import (
    ArozenChargingBinarySensor,
    ArozenMistingBinarySensor,
)
from custom_components.arozen_eon.select import ArozenIntensitySelect, ArozenTimerSelect
from custom_components.arozen_eon.sensor import (
    ArozenBatterySensor,
    ArozenCountdownRemainingSensor,
    ArozenDatapointsSensor,
    ArozenFailedPollsSensor,
    ArozenIntensityRestoresSensor,
)
from custom_components.arozen_eon.switch import ArozenLedSwitch, ArozenPowerSwitch

REPO = Path(__file__).resolve().parent.parent

#: The entity id the README promises and the harness names. Written out rather than derived,
#: because a test that computes the id it checks would follow a rename instead of catching it.
RECON_ENTITY_ID = "sensor.arozen_eon_pro_2_datapoints_recon"


class FakeDevice:
    host = "-test-device"
    device_id = "test-device-id"


class FakeCoordinator:
    """Enough coordinator to construct an entity. Same shell idiom as the other suites."""

    def __init__(self, data=None, last_update_success=True):
        self.data = data
        self.last_update_success = last_update_success
        self.device = FakeDevice()


# -- Where it appears ----------------------------------------------------------------------


def test_the_recon_sensor_is_not_enabled_on_a_fresh_install():
    sensor = ArozenDatapointsSensor(FakeCoordinator())
    assert sensor.entity_registry_enabled_default is False


def test_it_is_disabled_rather_than_hidden():
    """Hidden would keep it recording and reachable from automations, costing the installer
    everything about it except the sight of it. Disabled is the honest version of "not for
    you", and this pins which of the two knobs the decision actually turned."""
    sensor = ArozenDatapointsSensor(FakeCoordinator())
    assert sensor.entity_registry_visible_default is True


@pytest.mark.parametrize(
    "factory",
    [
        ArozenPowerSwitch,
        ArozenLedSwitch,
        ArozenMistingBinarySensor,
        ArozenChargingBinarySensor,
        ArozenIntensitySelect,
        ArozenTimerSelect,
        ArozenBatterySensor,
        ArozenCountdownRemainingSensor,
        ArozenFailedPollsSensor,
        ArozenIntensityRestoresSensor,
    ],
    ids=lambda cls: cls.__name__,
)
def test_every_other_entity_is_still_enabled_by_default(factory):
    """The vacuity guard. `entity_registry_enabled_default` is a class attribute and every
    entity here shares a base, so the same one line put on `ArozenDiagnosticSensor` disables
    the two counters this integration exists to keep, and on `ArozenEntity` it disables the
    diffuser. The parametrisation is the list of entities an installer is supposed to get."""
    assert factory(FakeCoordinator()).entity_registry_enabled_default is True


# -- What it reads, which the change does not touch -----------------------------------------


def test_the_state_is_how_many_datapoints_the_device_reported():
    sensor = ArozenDatapointsSensor(FakeCoordinator(data={"2": True, "3": "L4", "104": "kk"}))
    assert sensor.native_value == 3


def test_no_state_and_no_attributes_before_the_first_poll():
    sensor = ArozenDatapointsSensor(FakeCoordinator(data=None))
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_the_datapoints_are_ordered_by_number_and_not_by_string():
    """`"104"` sorts before `"7"` as text and after it as a number, and this device has DPs on
    both sides of that boundary. The sort is there so the attribute reads like the DP table in
    docs/datapoints.md; lexical order would interleave the 1xx block into the single digits."""
    data = {"7": True, "104": "kk", "2": True, "101": 96, "3": "L4"}
    attributes = ArozenDatapointsSensor(FakeCoordinator(data=data)).extra_state_attributes
    assert list(attributes["dps"]) == ["2", "3", "7", "101", "104"]
    assert attributes["dps"] == data


def test_it_reports_while_the_device_is_silent():
    """Inherited from ArozenDiagnosticSensor and worth pinning at this entity: the dps set from
    the last successful poll is exactly what somebody wants to look at once the polls stop."""
    sensor = ArozenDatapointsSensor(FakeCoordinator(data={"2": True}, last_update_success=False))
    assert sensor.available is True


# -- The pair the real-device harness depends on --------------------------------------------


def _verify_ha():
    """`tools/verify_ha.py` as a module, or a skip.

    The skip is not defensive padding: `tools/` is excluded from the published file set
    (tools/published_set.txt — it is finished recon scaffolding, and three of its tools write
    to a live appliance), so in the public repository this file exists and that one does not.
    #41's answer to a test with nothing to say after publication was to exclude the module;
    this module has plenty to say, so it skips the one test instead of travelling as an
    exclusion."""
    path = REPO / "tools" / "verify_ha.py"
    if not path.exists():
        pytest.skip("tools/ does not travel to the published repository")
    spec = importlib.util.spec_from_file_location("_verify_ha_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_real_home_assistant_harness_expects_it_to_be_absent():
    """It asserts the entity set *exactly* — a stray entity fails it as surely as a missing
    one — so leaving the recon sensor in EXPECTED_ENTITIES would turn this change into a red
    run against a live diffuser, months later, for a reason nobody would guess from the
    output. The harness runs by hand; this runs on every push."""
    harness = _verify_ha()
    assert RECON_ENTITY_ID not in harness.EXPECTED_ENTITIES
    assert RECON_ENTITY_ID in harness.EXPECTED_DISABLED_ENTITIES
    assert len(harness.EXPECTED_ENTITIES) == 10


def test_the_readme_tells_the_reader_it_is_disabled():
    """The entity table is where somebody counts what they are about to get. A row promising
    an entity that a default install does not show is the same defect as a missing entity,
    just told earlier."""
    rows = [
        line
        for line in (REPO / "README.md").read_text().splitlines()
        if RECON_ENTITY_ID in line and line.lstrip().startswith("|")
    ]
    assert rows, f"README.md no longer has an entity-table row for {RECON_ENTITY_ID}"
    for row in rows:
        assert re.search(r"disabled by default", row, re.IGNORECASE), row
