"""Local Tuya transport for the Arozen EON Pro 2.

A thin async wrapper over tinytuya, which is synchronous: every call runs in a thread via
``asyncio.to_thread``. Owns the connection parameters and nothing else; the DP semantics live
in dp.py, the state lives in the coordinator.

Two things worth knowing about the failure shape here, both consequences of how tinytuya
reports errors:

* **a failed exchange usually does not raise** — tinytuya returns an error payload like
  ``{"Error": "Unexpected Payload", "Err": "907", ...}`` instead, so "did it work" is
  "is there a dps dict", not "did no exception fire";
* **a write is confirmed by reading back** — ``set_value`` returns whatever the device
  answered, which on success includes the new DP state. We do not treat a returned error
  payload as success, but the *entities* refresh from the next coordinator update rather
  than trusting the write's own echo.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import tinytuya

_LOGGER = logging.getLogger(__name__)


class ArozenError(Exception):
    """Base class for anything this transport can fail with."""


class ArozenUnreachable(ArozenError):
    """The device did not answer, or answered with an error payload."""


class ArozenDevice:
    """Local control of one diffuser: status reads and DP writes, nothing more."""

    def __init__(
        self,
        host: str,
        device_id: str,
        local_key: str,
        protocol_version: str,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.device_id = device_id
        device = tinytuya.Device(device_id, host, local_key)
        device.set_version(float(protocol_version))
        device.set_socketTimeout(timeout)
        device.set_socketPersistent(False)
        self._device = device

    async def async_status(self) -> dict[str, Any]:
        """Read every DP the device reports. Raises ArozenUnreachable on any failure."""
        payload = await asyncio.to_thread(self._device.status)
        return self._dps_or_raise(payload, "status")

    async def async_set_dp(self, dp: int, value: Any) -> None:
        """Write one datapoint. Returns once the device has answered.

        A successful return means the device accepted the write, not that the resulting
        state matches what was asked for — the coordinator's next refresh is the readback.
        """
        payload = await asyncio.to_thread(self._device.set_value, dp, value)
        self._dps_or_raise(payload, f"set DP {dp} = {value!r}")

    def _dps_or_raise(self, payload: Any, what: str) -> dict[str, Any]:
        """Unpack a tinytuya response, translating its error shapes into one exception."""
        if isinstance(payload, dict) and "dps" in payload:
            _LOGGER.debug("%s: %s -> %s", self.host, what, payload["dps"])
            return payload["dps"]
        # tinytuya's favourite failure mode: an error dict instead of an exception.
        raise ArozenUnreachable(f"{self.host}: {what} failed: {payload!r}")
