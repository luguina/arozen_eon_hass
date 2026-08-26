"""Tests for the Tuya transport - the layer that turns tinytuya's answers into a decision.

`device.py` is small and was, until this file, the only module in the integration with no
test at all. That is the wrong module to leave uncovered, because it is where three claims
about a third-party library are written down and nowhere else:

* **a failed exchange usually does not raise.** tinytuya returns an error payload like
  ``{"Error": "Unexpected Payload", "Err": "907"}`` instead, so "did it work" is "is there a
  dps dict", not "did no exception fire";
* **`status()` answers with a dict carrying a `dps` key**, which is the only part of the
  reply the integration reads;
* **a write is confirmed by reading back**, so `set_value` is checked for the same shape;
* **the local port is 6668**, which the integration now states itself rather than inheriting
  (#52) - and which is therefore checked against the installed library, since a port pinned
  at our layer is one a tinytuya release could move without us noticing.

All four are assertions about a library this repository does not control. They lived in a
docstring, which a tinytuya release cannot fail. Here they fail.

The fake below stands in for `tinytuya.Device` because the real one opens a socket in its
constructor path and this suite has no diffuser. It mirrors the 1.20.0 signatures the
integration actually calls - `set_version`, `set_socketTimeout`, `set_socketPersistent`,
`status`, `set_value` - and nothing else, so a tinytuya release that renames one of them
breaks these tests rather than passing them against a fake that has drifted. The one
deliberate deviation is the constructor's `port` default, and the reason is written at it.
"""

from __future__ import annotations

import asyncio
import inspect
import threading

import pytest
import tinytuya

from custom_components.arozen_eon import device as device_module
from custom_components.arozen_eon.const import TUYA_PORT
from custom_components.arozen_eon.device import ArozenDevice, ArozenUnreachable

#: A status reply in the shape the integration reads: DP ids as strings, mixed value types.
GOOD_PAYLOAD = {"dps": {"1": True, "3": "L4", "101": 87}}

#: tinytuya's real failure shape, transcribed from what it returns rather than invented.
#: This is the payload the whole module exists to recognise: no exception, no `dps` key.
ERROR_PAYLOAD = {"Error": "Unexpected Payload", "Err": "907", "Payload": None}


class FakeTuyaDevice:
    """The subset of `tinytuya.Device` that `ArozenDevice` touches.

    Records the calls the constructor makes and the thread each blocking call ran on, which
    is what lets the to_thread tests below assert something real rather than inspecting a
    mock.
    """

    #: `port` defaults to `None` here and to **6668** in the real `tinytuya.Device`, and the
    #: difference is the only thing that makes the port test below mean anything. With
    #: tinytuya's real default, "passed explicitly" and "left to the library" leave the same
    #: attribute behind, and an assertion that the constant arrived would pass just as
    #: happily against a `device.py` that had dropped the keyword altogether.
    def __init__(self, dev_id, address, local_key, port=None):
        self.dev_id = dev_id
        self.address = address
        self.local_key = local_key
        self.port = port
        self.version = None
        self.timeout = None
        self.persistent = None
        self.status_calls = 0
        self.writes: list[tuple[int, object]] = []
        self.threads: list[int] = []
        #: What the next status()/set_value() returns. A list is fine as a "not a dict" case.
        self.reply: object = GOOD_PAYLOAD

    # -- the four setters ArozenDevice calls in __init__ ---------------------------------
    def set_version(self, version):
        self.version = version

    def set_socketTimeout(self, s):
        self.timeout = s

    def set_socketPersistent(self, persist):
        self.persistent = persist

    # -- the two blocking calls ----------------------------------------------------------
    def status(self, nowait=False):
        self.status_calls += 1
        self.threads.append(threading.get_ident())
        return self.reply

    def set_value(self, index, value, nowait=False):
        self.writes.append((index, value))
        self.threads.append(threading.get_ident())
        return self.reply


@pytest.fixture
def fake_tuya(monkeypatch):
    """Replace `tinytuya.Device` as `device.py` looks it up, and hand back the instance."""
    made: list[FakeTuyaDevice] = []

    def _factory(dev_id, address, local_key, port=None):
        made.append(FakeTuyaDevice(dev_id, address, local_key, port))
        return made[-1]

    monkeypatch.setattr(device_module.tinytuya, "Device", _factory)
    return made


def _device(fake_tuya, **kwargs) -> tuple[ArozenDevice, FakeTuyaDevice]:
    arozen = ArozenDevice("192.0.2.10", "test-device-id", "0123456789abcdef", "3.5", **kwargs)
    return arozen, fake_tuya[0]


# -- The constructor ------------------------------------------------------------------------


def test_the_protocol_version_reaches_tinytuya_as_a_float(fake_tuya):
    """`"3.5"` arriving as a string is a silently wrong protocol, not an error.

    The config flow carries the version as a string, because `vol.In(PROTOCOL_VERSIONS)`
    holds strings and the frontend renders a dropdown of them. tinytuya compares
    `self.version` numerically to pick its cipher, so handing it `"3.5"` does not raise -
    it selects a different protocol, the device answers with something that will not
    decrypt, and the result is the `cannot_connect` this project spent a day attributing to
    a wrong local key.
    """
    _, tuya = _device(fake_tuya)
    assert tuya.version == 3.5
    assert isinstance(tuya.version, float), "a str version picks the wrong cipher silently"


def test_the_connection_parameters_reach_tinytuya_in_the_right_slots(fake_tuya):
    """Three same-typed positional strings, which is exactly how an argument swap hides.

    `tinytuya.Device(dev_id, address, local_key)` takes the id first and the host second.
    Swapping them yields a device object that constructs cleanly and never answers.
    """
    _, tuya = _device(fake_tuya)
    assert (tuya.dev_id, tuya.address, tuya.local_key) == (
        "test-device-id",
        "192.0.2.10",
        "0123456789abcdef",
    )


def test_the_port_is_stated_here_rather_than_left_to_the_library(fake_tuya):
    """#52. This changes no behaviour today - tinytuya defaults `port` to 6668 itself - so
    what it changes is which layer is responsible for the number.

    Until this argument existed, `TUYA_PORT` in const.py was a documented constant that
    documented nothing: the socket took its port from tinytuya, and the comment describing
    it could have said any number at all without a test or a device disagreeing.
    """
    _, tuya = _device(fake_tuya)
    assert tuya.port == TUYA_PORT, "the port reaches tinytuya from const.py, or not at all"


def test_tinytuya_still_defaults_to_the_port_this_integration_states():
    """The cost of stating it at our layer, paid back here.

    A tinytuya release that moved its local port used to reach this integration as a broken
    connection; now it would reach it as nothing at all, because the explicit argument keeps
    the socket on 6668 whatever the library thinks. So the agreement is asserted directly,
    against the installed tinytuya rather than the fake - a pin is only as good as the
    moment somebody bumps `tinytuya==` in the manifest, and this is the assertion that
    fires in that commit.

    Read out of the real signature, which also covers a rename. The fake above mirrors the
    methods `ArozenDevice` calls, but nothing makes it mirror the constructor's keywords: a
    tinytuya that renamed `port=` would be a `TypeError` on a user's device and a green
    suite here.
    """
    params = inspect.signature(tinytuya.Device.__init__).parameters
    assert "port" in params, (
        f"tinytuya {tinytuya.__version__} no longer takes a `port` keyword - device.py "
        "passes one, so this is a TypeError in production, not a style question"
    )
    assert params["port"].default == TUYA_PORT, (
        f"tinytuya {tinytuya.__version__} defaults its local port to "
        f"{params['port'].default!r}, not {TUYA_PORT}. device.py overrides that, so nothing "
        "here breaks - settle whether the protocol moved before shipping this version"
    )


def test_the_socket_is_not_persistent(fake_tuya):
    """ADR-004: the device accepts one local connection at a time, shared with the app.

    Holding the socket open would win that race permanently and take the phone app off the
    device. The poll pays a reconnect each time instead, deliberately.
    """
    _, tuya = _device(fake_tuya)
    assert tuya.persistent is False


def test_the_timeout_is_passed_through_and_defaults(fake_tuya):
    arozen, tuya = _device(fake_tuya)
    assert tuya.timeout == 10.0
    fake_tuya.clear()
    _device(fake_tuya, timeout=5.0)
    assert fake_tuya[0].timeout == 5.0, "the config flow's shorter timeout must reach the socket"


# -- _dps_or_raise: the error-payload contract ----------------------------------------------


def test_a_good_payload_yields_just_the_dps(fake_tuya):
    arozen, _ = _device(fake_tuya)
    assert arozen._dps_or_raise(GOOD_PAYLOAD, "status") == {"1": True, "3": "L4", "101": 87}


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        (ERROR_PAYLOAD, "tinytuya's error dict - the failure mode with no exception"),
        (None, "no reply at all"),
        ("Error", "a bare string where a dict was expected"),
        ([], "a non-dict container"),
        ({}, "an empty dict carries no dps"),
        ({"Error": "907", "dps": None}, "a dps key present but null"),
    ],
)
def test_anything_without_a_dps_dict_raises(fake_tuya, payload, why):
    """The central claim: absence of an exception is not success.

    `{"dps": None}` is the subtle one. It has the key, so a `"dps" in payload` check passes
    and the caller receives None where it expects a mapping - which fails later, somewhere
    else, as a TypeError in an entity property.
    """
    arozen, _ = _device(fake_tuya)
    with pytest.raises(ArozenUnreachable):
        arozen._dps_or_raise(payload, "status")


def test_the_error_names_the_host_and_the_operation(fake_tuya):
    """The message is the only diagnostic a user can paste, so it must say which and what."""
    arozen, _ = _device(fake_tuya)
    with pytest.raises(ArozenUnreachable) as caught:
        arozen._dps_or_raise(ERROR_PAYLOAD, "set DP 3 = 'L4'")
    message = str(caught.value)
    assert "192.0.2.10" in message
    assert "set DP 3 = 'L4'" in message
    assert "907" in message, "the device's own error code is the part worth searching for"


def test_the_local_key_is_not_in_the_error_message(fake_tuya):
    """A transport error is logged and pasted into bug reports. It must not carry the key."""
    arozen, _ = _device(fake_tuya)
    with pytest.raises(ArozenUnreachable) as caught:
        arozen._dps_or_raise(ERROR_PAYLOAD, "status")
    assert "0123456789abcdef" not in str(caught.value)


# -- async_status / async_set_dp -------------------------------------------------------------


async def test_status_returns_the_dps(fake_tuya):
    arozen, tuya = _device(fake_tuya)
    assert await arozen.async_status() == GOOD_PAYLOAD["dps"]
    assert tuya.status_calls == 1


async def test_status_raises_on_an_error_payload(fake_tuya):
    arozen, tuya = _device(fake_tuya)
    tuya.reply = ERROR_PAYLOAD
    with pytest.raises(ArozenUnreachable):
        await arozen.async_status()


async def test_set_dp_writes_the_datapoint(fake_tuya):
    arozen, tuya = _device(fake_tuya)
    await arozen.async_set_dp(3, "L4")
    assert tuya.writes == [(3, "L4")]


async def test_set_dp_raises_on_an_error_payload(fake_tuya):
    """A write that is not confirmed must fail loudly - the entities trust this return.

    `switch.py` and `select.py` both turn an `ArozenError` here into a `HomeAssistantError`
    the user sees. Swallowing it would report success for a command that did nothing.
    """
    arozen, tuya = _device(fake_tuya)
    tuya.reply = ERROR_PAYLOAD
    with pytest.raises(ArozenUnreachable):
        await arozen.async_set_dp(3, "L4")


# -- The event loop --------------------------------------------------------------------------


async def test_status_runs_off_the_event_loop_thread(fake_tuya):
    """tinytuya is synchronous and opens a socket. On the loop thread it stalls Home Assistant.

    Asserted by thread identity rather than by patching `asyncio.to_thread`, so the test
    fails for the reason that matters - the blocking call ran where the loop runs - and not
    merely because someone reached the same result another way. `asyncio.to_thread` is the
    current mechanism; running off the loop is the requirement.
    """
    arozen, tuya = _device(fake_tuya)
    await arozen.async_status()
    assert len(tuya.threads) == 1
    assert tuya.threads[0] != threading.get_ident(), (
        "status() ran on the event loop thread - Home Assistant blocks for the socket timeout"
    )


async def test_set_dp_runs_off_the_event_loop_thread(fake_tuya):
    arozen, tuya = _device(fake_tuya)
    await arozen.async_set_dp(2, True)
    assert tuya.threads[0] != threading.get_ident()


async def test_the_loop_keeps_running_while_a_slow_status_blocks(fake_tuya):
    """The point of the thread, stated as behaviour rather than as thread identity.

    A blocking `status()` must not stop other coroutines. Without `to_thread` the counter
    below cannot advance at all, because the loop is inside tinytuya's socket wait.
    """
    arozen, tuya = _device(fake_tuya)
    released = threading.Event()
    ticks = 0

    def _slow_status(nowait=False):
        released.wait(timeout=5)
        return GOOD_PAYLOAD

    tuya.status = _slow_status

    async def _tick():
        nonlocal ticks
        while not released.is_set():
            ticks += 1
            await asyncio.sleep(0)

    ticker = asyncio.create_task(_tick())
    await asyncio.sleep(0)
    status = asyncio.create_task(arozen.async_status())
    await asyncio.sleep(0.05)
    running_ticks = ticks
    released.set()
    assert await status == GOOD_PAYLOAD["dps"]
    await ticker

    assert running_ticks > 0, "the event loop was blocked while tinytuya waited on its socket"
