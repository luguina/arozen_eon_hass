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
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

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

#: A masked box with a reveal toggle, on every step that asks for the key. A bare `str`
#: renders in clear text: the frontend infers masking from the field *name*, and only when
#: it contains "password", "secret" or "token" - `local_key` contains none of the three, so
#: the credential strings.json warns about in the paragraph above the field was being drawn
#: below it in full, readable by a screen share or by anyone standing behind the installer.
#: A selector states the intent rather than hoping the name carries it, which is how core
#: handles the same situation: 67 integrations in the 2026.8.1 wheel use this selector type
#: in a config flow.
#:
#: Shared between the two steps instead of written out twice, so the user step and the
#: reconfigure step cannot drift into disagreeing about how the key is rendered - they were
#: two independent `str`s before this, which is why the same mistake had to be fixed twice.
#: Safe to share: the config is validated once at construction and `__call__` only runs
#: `vol.Schema(str)` over the submitted value, so the instance carries no per-flow state,
#: exactly like the `str` it replaces.
#:
#: Deliberately no `autocomplete`, unlike the core flows that ask for an account password:
#: this is a per-device key, and "current-password" would invite the browser's password
#: manager to offer the Home Assistant login for the origin serving the form.
LOCAL_KEY_SELECTOR: Final = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD)
)

#: Built once at import rather than per call, because the retry path has to re-show *this*
#: schema with the user's own answers suggested back into it. `add_suggested_values_to_schema`
#: copies every marker before setting `description["suggested_value"]`, so the constant is
#: never mutated and one flow's input cannot leak into the next flow's form.
STEP_USER_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_LOCAL_KEY): LOCAL_KEY_SELECTOR,
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

    #: The shape of `entry.data`, stamped into every entry this flow creates and compared
    #: against on every load. **Both numbers are part of the schema contract: change the shape
    #: of `entry.data`, bump the matching one here, and add the branch to `async_migrate_entry`
    #: in `__init__.py` in the same commit.** Nothing about editing `STEP_USER_SCHEMA` forces
    #: any of that, which is why the rule is written at the constant rather than in a document
    #: - this is where somebody reshaping the entry is standing. `tests/test_setup_entry.py`
    #: fails the build on any change to the pair below, so the rule has teeth as well as prose:
    #: the assertion is updated last, after the branch it is there to remind you to write.
    #:
    #: Which of the two to move is the whole distinction, and it is about **old code meeting
    #: new data**, not about how large the change feels:
    #:
    #: * `VERSION` - an entry in the old shape breaks the running code. A key was renamed or
    #:   removed, a value changed type, something moved from `data` to `options`. Home Assistant
    #:   refuses to load an entry stamped *higher* than this (config_entries.py:1156), which is
    #:   what makes a downgrade a clean error message instead of a `KeyError`.
    #: * `MINOR_VERSION` - a purely additive change the old code tolerates, because the key it
    #:   reads is still there and still means what it meant. This is the cheaper lever: an
    #:   install that downgrades keeps working, so no downgrade path has to exist. 137 of the
    #:   1483 integrations in the 2026.8.1 wheel declare it.
    #:
    #: Restating the framework default of 1 rather than inheriting it is deliberate: the two
    #: levers are a pair, and a rule about choosing between them reads badly next to only one
    #: of them.
    VERSION = 1
    MINOR_VERSION = 1

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
        # a 22-character device ID and a 16-character key for taking that advice.
        #
        # Echoing a live credential is the deliberate half of that, and it was argued once on
        # the grounds that the field was unmasked on the way in anyway, so handing it back
        # exposed nothing new. LOCAL_KEY_SELECTOR retired that leg. The conclusion stands on
        # the two that remain, and masking supplies a third rather than costing one. What
        # returns is dots, in the box the user just filled, in the same session, in answer to
        # that session's own submit: nobody sees the key who did not watch it typed, and the
        # reveal toggle keeps it checkable by the one who did. And blanking it now costs more
        # than it did before the mask - a re-typed key can no longer be proof-read on screen
        # at all, so clearing the field would make a typo in 16 characters harder to catch,
        # in exchange for hiding the value from the person who chose it. Core lands here in
        # this exact shape: 24 integrations in the 2026.8.1 wheel hand bare `user_input` back
        # into a schema that masks a secret with this selector, `aws_s3` from a hoisted
        # module-level constant like this one.
        #
        # On the first pass `user_input` is None, which the helper reads as "no suggestions":
        # blank fields, version defaulted to 3.5.
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
                        vol.Required(CONF_LOCAL_KEY): LOCAL_KEY_SELECTOR,
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
