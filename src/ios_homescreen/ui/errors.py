"""Turn exceptions into something a person can act on: a title, what to do, details.

The browser UI shows these instead of tracebacks. Codes come from the exceptions
(:class:`~ios_homescreen.transport.TransportError` and friends); pymobiledevice3's own
exceptions are recognised by class name so that this module never imports it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ..device import DeviceError
from ..planner import LayoutError
from ..state import StateError
from ..transport import TransportError
from ..workflow import WorkflowError

_TRUST_STEPS = [
    "Connect the iPhone with a cable and unlock it.",
    "Tap Trust This Computer and enter the passcode.",
    "Try again.",
]

_USB_STEPS = [
    "Plug the iPhone in with a cable that carries data.",
    "Unlock it. If it asks, tap Trust This Computer and enter the passcode.",
    "Try again.",
]

_WIFI_STEPS = [
    "Keep the iPhone awake and unlocked, on the same network as this computer.",
    "Guest networks and client isolation keep the phone and the computer apart, and "
    "firewalls must let mDNS (UDP 5353) through.",
    "Check with `ios-homescreen wifi status` over USB, or use the cable.",
]

_WIFI_SETUP = [
    "Connect the iPhone with a cable once and run `ios-homescreen wifi setup`.",
    "Then restart the editor with `--wifi`.",
]

# code -> (title, steps)
_KNOWN: dict[str, tuple[str, list[str]]] = {
    "no_usb_device": ("No iPhone found over USB", _USB_STEPS),
    "usbmuxd_unreachable": (
        "usbmuxd is not running",
        [
            "Install usbmuxd from your distribution and start it: `sudo systemctl start usbmuxd`.",
            "Plug the iPhone in again, then try again.",
        ],
    ),
    "not_trusted": ("This computer is not trusted yet", _TRUST_STEPS),
    "trust_pending": (
        "Waiting for Trust This Computer",
        [
            "Look at the iPhone: tap Trust and enter the passcode.",
            "Try again.",
        ],
    ),
    "trust_denied": (
        "The iPhone did not trust this computer",
        [
            "Unplug and plug the iPhone in again.",
            "Tap Trust this time and enter the passcode, then try again.",
        ],
    ),
    "locked": (
        "The iPhone is locked",
        ["Unlock the iPhone and keep it unlocked while you work.", "Try again."],
    ),
    "not_paired": ("The iPhone did not accept this computer", _TRUST_STEPS),
    "no_pair_record": ("This computer is not paired with the iPhone for Wi-Fi", _WIFI_SETUP),
    "stale_pair_record": ("The Wi-Fi pairing needs to be made again", _WIFI_SETUP),
    "not_advertising": ("The iPhone did not answer on the network", _WIFI_STEPS),
    "several_devices": (
        "More than one iPhone answered",
        ["Restart the editor with `--udid UDID` to pick one."],
    ),
    "several_pair_records": (
        "More than one paired iPhone",
        ["Restart the editor with `--udid UDID` to pick one."],
    ),
    "timeout": (
        "The iPhone did not answer in time",
        [
            "Unlock the iPhone and keep it awake.",
            "If it shows Trust This Computer, tap Trust.",
            "If every attempt times out, restart usbmuxd: "
            "`sudo systemctl restart usbmuxd`, then reconnect the phone.",
        ],
    ),
    "connection_failed": (
        "Could not connect to the iPhone",
        [
            "Unlock the iPhone and check the cable or the network.",
            "Try again. If it keeps failing, restart usbmuxd: `sudo systemctl restart usbmuxd`.",
        ],
    ),
    "layout_changed": (
        "The home screen changed on the iPhone",
        [
            "Someone moved things on the phone after the last read, so nothing was written.",
            "Read from phone again (your edits here are lost), or apply anyway to overwrite "
            "the phone's current layout.",
        ],
    ),
    "unsafe_payload": (
        "The layout was refused before sending",
        ["Nothing was written. Please report this as a bug, with the details below."],
    ),
}

# pymobiledevice3 exception class names -> our codes.
_BY_CLASS = {
    "PasswordRequiredError": "locked",
    "PairingDialogResponsePendingError": "trust_pending",
    "UserDeniedPairingError": "trust_denied",
    "NotPairedError": "not_trusted",
    "InvalidHostIDError": "not_trusted",
    "PairingError": "not_trusted",
    "SetProhibitedError": "not_trusted",
    "NoDeviceConnectedError": "no_usb_device",
    "DeviceNotFoundError": "no_usb_device",
    "ConnectionFailedToUsbmuxdError": "usbmuxd_unreachable",
}


_GENERIC_CODES = frozenset(
    {"connection_failed", "device_error", "transport_error", "workflow_error"}
)


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify(exc: BaseException) -> str:
    """A stable code for ``exc``, looking through chained exceptions."""
    for link in _chain(exc):
        for cls in type(link).__mro__:
            if cls.__name__ in _BY_CLASS:
                return _BY_CLASS[cls.__name__]
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code and code not in _GENERIC_CODES:
        return code
    text = str(exc)
    if "Mux error -8" in text or "pairing" in text.lower():
        return "not_trusted"
    if "passcode" in text.lower() or "locked" in text.lower():
        return "locked"
    if isinstance(code, str) and code:
        return code
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, OSError):
        return "os_error"
    return "unexpected"


def friendly(exc: BaseException) -> dict[str, Any]:
    """JSON-ready ``{code, title, steps, detail}`` for an exception."""
    code = classify(exc)
    title, steps = _KNOWN.get(code, (None, []))
    if title is None:
        if isinstance(exc, LayoutError):
            title = "The layout has problems"
        elif isinstance(exc, StateError):
            title = "The file or layout cannot be used"
        elif isinstance(exc, WorkflowError | DeviceError | TransportError):
            title = "The iPhone operation failed"
        else:
            title = "Something went wrong"
        steps = ["Check the details below and try again."]
    return {"code": code, "title": title, "steps": list(steps), "detail": str(exc)}
