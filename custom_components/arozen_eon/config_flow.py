"""Config flow for the Arozen EON Pro 2.

Manual entry only, deliberately: the device ID, local key and host are exactly the three
things the recon phase produces (docs/datapoints.md §Method step 1), and a discovery step
written before the dump would be written against a guess. tinytuya's UDP scan cannot run
inside Home Assistant's event loop anyway.

Validation is a real status query: it proves the host answers, the local key decrypts, and
the protocol version is right, in one exchange.
"""

from __future__ import annotations

import logging
from typing import Any, Final

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST

from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_POLL_INTERVAL,
    CONF_PROTOCOL_VERSION,
    DEFAULT_POLL_INTERVAL_S,
    DEFAULT_PROTOCOL_VERSION,
    DOMAIN,
    MAX_POLL_INTERVAL_S,
    MIN_POLL_INTERVAL_S,
    PROTOCOL_VERSIONS,
)
from .device import ArozenDevice, ArozenError

_LOGGER = logging.getLogger(__name__)

DEFAULT_TITLE = "Arozen EON Pro 2"

#: Built once at import rather than per call, because the retry path has to re-show *this*
#: schema with the user's own answers suggested back into it. `add_suggested_values_to_schema`
#: copies every marker before setting `description["suggested_value"]`, so the constant is
#: never mutated and one flow's input cannot leak into the next flow's form.
STEP_USER_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_LOCAL_KEY): str,
        vol.Required(CONF_PROTOCOL_VERSION, default=DEFAULT_PROTOCOL_VERSION): vol.In(
            PROTOCOL_VERSIONS
        ),
    }
)


async def _async_validate(
    host: str, device_id: str, local_key: str, protocol_version: str
) -> dict[str, Any]:
    """Prove the device answers with these credentials. Returns the DP set it reported."""
    device = ArozenDevice(host, device_id, local_key, protocol_version, timeout=5.0)
    return await device.async_status()


class ArozenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a diffuser by host, device ID and local key."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID].strip()
            await self.async_set_unique_id(device_id, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            try:
                await _async_validate(
                    user_input[CONF_HOST].strip(),
                    device_id,
                    user_input[CONF_LOCAL_KEY].strip(),
                    user_input[CONF_PROTOCOL_VERSION],
                )
            except ArozenError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating %s", user_input[CONF_HOST])
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=DEFAULT_TITLE,
                    data={
                        CONF_HOST: user_input[CONF_HOST].strip(),
                        CONF_DEVICE_ID: device_id,
                        CONF_LOCAL_KEY: user_input[CONF_LOCAL_KEY].strip(),
                        CONF_PROTOCOL_VERSION: user_input[CONF_PROTOCOL_VERSION],
                    },
                )

        # Suggested back on a retry: all four, the local key included. A wrong protocol
        # version reports the same `cannot_connect` as a wrong key, so the documented remedy
        # is "try 3.4, then 3.3", and a form that clears itself charges two extra re-types of
        # a 22-character device ID and a 16-character key for taking that advice. Echoing a
        # live credential is the deliberate half of that: it is the user's own key, returned
        # only to the session that just typed it, into a field the frontend does not mask on
        # the way in either - it infers masking for a plain `str` from a name containing
        # "password", "secret" or "token", and `local_key` matches none of the three. Core
        # agrees: of its 109 `add_suggested_values_to_schema` call sites whose schema holds a
        # secret, 46 pass bare `user_input` and 2 strip the secret out, and the generic
        # handler every schema-driven flow inherits merges `user_input` in unfiltered
        # (`SchemaCommonFlowHandler._show_next_step`). On the first pass `user_input` is None,
        # which the helper reads as "no suggestions": blank fields, version defaulted to 3.5.
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-point an existing entry at credentials that moved, instead of recreating it.

        Three of the four connection values drift on a device that was working yesterday.
        Re-pairing in the Smart Life app mints a new local key while the device ID survives
        — that is the documented remedy if a key leaks, and it also happens to anyone who
        removes and re-adds the device for an unrelated reason. A lease expiry moves the
        host, which is why the README asks for a DHCP reservation. And a firmware update can
        move the protocol version, which is why PROTOCOL_VERSIONS still carries 3.3 and 3.4
        beside the 3.5 observed on the LAN.

        The device ID is the fourth value and is deliberately not a field here: it is the
        entry's unique_id, so a different device ID is a different device, not a
        reconfigured one. It goes into the step description instead — the value the user
        must not change is still the value they need to see to know they are editing the
        right entry.

        Validation is the same real status exchange async_step_user runs, so a wrong new key
        fails in this dialog. Nothing is written until it passes.
        """
        entry = self._get_reconfigure_entry()
        device_id = entry.data[CONF_DEVICE_ID]
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            local_key = user_input[CONF_LOCAL_KEY].strip()
            protocol_version = user_input[CONF_PROTOCOL_VERSION]
            try:
                await _async_validate(host, device_id, local_key, protocol_version)
            except ArozenError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating %s", host)
                errors["base"] = "unknown"
            else:
                # async_update_and_abort, not async_update_reload_and_abort: __init__.py
                # ends async_setup_entry with entry.add_update_listener(...), and Home
                # Assistant fires update listeners from async_update_entry whenever the
                # entry actually changed — so the reload already happens, and the *_reload_*
                # variant would schedule a second one on top of it. HA 2026.8.1 says so
                # itself — async_update_reload_and_abort calls report_usage("has an
                # update listener and should use it for scheduling a reload") with
                # breaks_in_ha_version="2026.12.0".
                #
                # data_updates is merged over the stored data (`entry.data | data_updates`),
                # so CONF_DEVICE_ID stays, and unique_id is left UNDEFINED, so the entry
                # keeps its identity, its history and its entity ids.
                return self.async_update_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: host,
                        CONF_LOCAL_KEY: local_key,
                        CONF_PROTOCOL_VERSION: protocol_version,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_HOST): str,
                        vol.Required(CONF_LOCAL_KEY): str,
                        vol.Required(CONF_PROTOCOL_VERSION): vol.In(PROTOCOL_VERSIONS),
                    }
                ),
                # Prefill from what was just typed when there is a correction in flight, and
                # from the entry only on the first pass. Falling back to entry.data after a
                # failure would put the credentials that just failed back in the boxes and
                # throw away the user's edit.
                user_input or entry.data,
            ),
            description_placeholders={CONF_DEVICE_ID: device_id},
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ArozenOptionsFlow()


class ArozenOptionsFlow(OptionsFlow):
    """One tunable: how often to poll. Trades freshness against competing with the app."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_S
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL_S, max=MAX_POLL_INTERVAL_S),
                    ),
                }
            ),
        )
