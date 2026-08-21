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

#: Tuya local protocol port. Not configurable - every Tuya WiFi device listens on it.
TUYA_PORT: Final = 6668

#: Observed on the LAN 2026-08-21 (docs/research/dossier.md §6). Offered as the config-flow
#: default; 3.3 and 3.4 remain selectable because a firmware update can move this.
DEFAULT_PROTOCOL_VERSION: Final = "3.5"
PROTOCOL_VERSIONS: Final = ("3.3", "3.4", "3.5")

# --- Options ----------------------------------------------------------------------------
CONF_POLL_INTERVAL: Final = "poll_interval"

#: Much cheaper than the sibling project's 900 s BLE poll: this is one TCP exchange on the LAN, not a
#: radio connection three floors away. Still not aggressive, because many Tuya devices accept
#: only one local connection at a time (ADR-004) and every poll competes with the phone app.
DEFAULT_POLL_INTERVAL_S: Final = 60
MIN_POLL_INTERVAL_S: Final = 10
MAX_POLL_INTERVAL_S: Final = 3600

#: Consecutive failed polls the entities survive before reporting `unavailable`, holding the
#: last reading in between. Same shape as sibling_beacon's TOLERATED_POLL_FAILURES and for the
#: same reason: one missed poll should not cost a full interval of unavailability.
TOLERATED_POLL_FAILURES: Final = 1
