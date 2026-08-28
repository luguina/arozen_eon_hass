"""Constants for the Arozen EON Pro 2 integration.

The datapoint map lives in dp.py, which is deliberately free of Home Assistant imports.
This file is for the Home-Assistant-facing bits: the domain, the connection settings, and
the tunables exposed in the options flow.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "arozen_eon"
MANUFACTURER: Final = "Arozen"
MODEL: Final = "EON Pro 2"

# --- Connection -------------------------------------------------------------------------
CONF_DEVICE_ID: Final = "device_id"
CONF_LOCAL_KEY: Final = "local_key"
CONF_PROTOCOL_VERSION: Final = "protocol_version"

#: Tuya's local protocol port, passed explicitly to `tinytuya.Device` in device.py rather
#: than left to the library's default. Measured on this unit rather than assumed of Tuya
#: devices in general - the previous claim here, that every Tuya WiFi device listens on it,
#: was inherited from tinytuya's documentation and never checked. What was checked is this
#: diffuser, found listening on TCP 6668 during the 2026-08-21 LAN sweep
#: (docs/research/dossier.md §6.3), which is the reading the whole local transport rests on.
#:
#: tinytuya defaults to the same number (`tinytuya/core/const.py`) and describes the keyword
#: in its own constructor as "default - do not expect caller to pass in". Passing it anyway
#: costs one argument and makes the number this file states the one the socket connects to;
#: until then the constant documented nothing, because no behaviour depended on it.
#: `tests/test_device.py` asserts both halves - that it reaches the device object, and that
#: tinytuya's own default still agrees with it - so a version bump that moved the port is a
#: red build here rather than a silent divergence between this file and the socket.
#:
#: Not configurable: there is no form field for it, and the protocol does not offer one.
TUYA_PORT: Final = 6668

#: Observed on the LAN 2026-08-21 (docs/research/dossier.md §6). Offered as the config-flow
#: default; 3.3 and 3.4 remain selectable because a firmware update can move this.
DEFAULT_PROTOCOL_VERSION: Final = "3.5"
PROTOCOL_VERSIONS: Final = ("3.3", "3.4", "3.5")

# --- Options ----------------------------------------------------------------------------
CONF_POLL_INTERVAL: Final = "poll_interval"

#: Cheap, because this is one TCP exchange on the LAN rather than a radio connection at range.
#: Still not aggressive, because many Tuya devices accept only one local connection at a time
#: (ADR-004) and every poll competes with the phone app.
DEFAULT_POLL_INTERVAL_S: Final = 60
MIN_POLL_INTERVAL_S: Final = 10
MAX_POLL_INTERVAL_S: Final = 3600

#: Consecutive failed polls the entities survive before reporting `unavailable`, holding the
#: last reading in between. One missed poll should not cost a full interval of unavailability.
TOLERATED_POLL_FAILURES: Final = 1

#: How long the device must go on not answering before a repair issue appears in
#: **Settings → System → Repairs** (#49). Wall clock, not a poll count, and the difference is
#: not pedantry: the poll interval is configurable across a 360x range, so the same count is
#: ten minutes for one installation and two and a half days for another. What this trades is
#: patience against noise, and both are measured in time — a router reboot, a DHCP renewal or
#: a firmware update takes minutes, so anything much shorter puts a card on the screen for
#: every one of them and teaches the user to ignore the card.
#:
#: An hour is the deliberately unhurried end of that trade. The entities have already gone
#: `unavailable` after TOLERATED_POLL_FAILURES, which is the fast signal; this is the slow one
#: that says the silence is not going to end on its own.
UNREACHABLE_BEFORE_REPAIR_S: Final = 3600

#: Where the repair card's "Learn more" button goes: the README section that explains what
#: re-pairing does to the key and how to reconfigure. Built on the manifest's `documentation`
#: URL rather than repeating it, because a repository rename must move both together, and
#: tests/test_repair_issue.py holds it to that — it checks the prefix against the manifest and
#: the fragment against a heading that actually exists in README.md. A "Learn more" button
#: landing on a 404, or scrolling to nowhere, is worse than no button.
REPAIR_LEARN_MORE_URL: Final = (
    "https://github.com/luguina/arozen_eon_hass"
    "#re-pairing-the-diffuser-invalidates-the-key"
)
