"""Diagnostics for the Arozen EON Pro 2 - the state a bug report needs, minus the credential.

Every way this integration fails looks the same from the dashboard: the entities go
`unavailable`. A wrong local key, a wrong protocol version and a diffuser that has gone to
sleep are three different problems with one symptom, and the state that separates them --
which protocol version is in use, how many polls have failed in a row, what tinytuya actually
answered with -- lives in the coordinator and has until now never left the machine. Both
diagnostic sensors already carry most of it, but only to whoever is looking at the dashboard;
`extra_state_attributes` is not something a reporter can hand you.

**Redaction is the load-bearing part, and it is done twice** because there are two different
ways a secret gets into this dump:

* **by key.** `entry.data` holds a live `local_key`. `async_redact_data` replaces it by name,
  along with the device id and the host -- the three identifiers docs/captures/README.md
  names, applied to the one file in the integration that deliberately serialises the entry.
* **by substring.** The error strings are the trap, and they are the reason a key-based
  redactor on its own would have shipped a leak here. `device.py` formats every failure as
  ``f"{self.host}: {what} failed: {payload!r}"``, so `health.last_error` -- one of the most
  useful fields in the whole dump -- carries the LAN address inside free text, where nothing
  matching on keys will ever find it. `_scrub` takes it back out.

Which is why the test for this file asserts on the **absence of the values** rather than on
the shape of the output: a dump is pasted into a GitHub issue by someone who has never read
this repository's rules about identifiers, so the redaction has to be right here, once,
instead of right in every reporter's habits.

Deliberately **not** here: `async_get_device_diagnostics`. There is one device per config
entry, so a device-level dump would be the same dump reached by a different menu.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import tinytuya
from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID, CONF_LOCAL_KEY
from .coordinator import ArozenConfigEntry

#: The `entry.data` keys that never leave the machine. A module constant rather than an inline
#: set for two reasons: the test asserts against this object instead of restating the list, and
#: the free-text scrub below derives its needles from it -- so adding a key here covers both
#: halves of the redaction at once, which is the failure mode a second hand-kept list invites.
#:
#: `protocol_version` and the poll interval are deliberately left in the clear. They are the
#: two settings a support conversation actually turns on, and a dump that redacts everything
#: passes an absence test perfectly while being useless.
TO_REDACT = {CONF_LOCAL_KEY, CONF_DEVICE_ID, CONF_HOST}


def _scrub(text: str | None, secrets: Iterable[str]) -> str | None:
    """Take the connection values back out of a free-text string.

    Empty secrets are skipped, and that guard does real work rather than being tidy:
    ``"anything".replace("", REDACTED)`` inserts the placeholder between every character and
    hands back a string with no information left in it. A config entry with a blank host --
    which the config flow refuses, and a hand-edited `.storage` file does not -- would
    otherwise turn the one field a reader needs into confetti.
    """
    if text is None:
        return None
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ArozenConfigEntry
) -> dict[str, Any]:
    """Return everything about this config entry that is safe to paste into an issue."""
    coordinator = entry.runtime_data
    health = coordinator.health
    intensity = coordinator.intensity

    #: The values behind the redacted keys, for the free-text pass. Derived from TO_REDACT so
    #: the two halves cannot drift apart.
    secrets = [str(entry.data[key]) for key in TO_REDACT if key in entry.data]

    return {
        # Neither `entry.title` nor `entry.unique_id`: the unique id *is* the device id, set
        # by the config flow from the value it has just validated, so dumping it would hand
        # back through the front door precisely what TO_REDACT takes out of the data.
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            # Redacted too, though today's only option is the poll interval. Uniform because
            # the next option to be added will not come with a reminder to reconsider this.
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            # The interval the coordinator is *running at*, which is not always the one in
            # the options: applying a changed interval means a reload
            # (`_async_reload_on_options_change`), so the two disagreeing is itself the
            # finding -- a setting that was saved and never took effect.
            "update_interval_s": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval is not None
                else None
            ),
            "health": {
                "total": health.total,
                "consecutive": health.consecutive,
                "tolerated": health.tolerated,
                "last_error": _scrub(health.last_error, secrets),
                "last_failure": (
                    health.last_failure.isoformat() if health.last_failure else None
                ),
            },
            "intensity": {
                "wanted": intensity.wanted,
                "unconfirmed": intensity.unconfirmed,
                "restored": intensity.restored,
                "failures": intensity.failures,
                "last_error": _scrub(intensity.last_error, secrets),
            },
        },
        # The raw DP set from the last successful poll, unredacted and deliberately so: it is
        # numbered datapoints and their values, it carries no identifier, and it is the single
        # most useful thing in here. dp.py is a map *of* this; DP 104 is still unnamed, so a
        # stranger's dps set is free recon on the one open question in docs/datapoints.md.
        # None when the device has never answered, which is a reading in its own right.
        "dps": dict(coordinator.data) if coordinator.data is not None else None,
        # The manifest pins tinytuya exactly (#48) and Home Assistant attaches that manifest
        # to every dump; this is the version that actually got imported. The two disagreeing
        # is a real install state -- another integration's looser requirement can win the
        # resolve -- and it is invisible from the manifest alone.
        "tinytuya_version": getattr(tinytuya, "__version__", None),
    }
