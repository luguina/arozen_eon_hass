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
