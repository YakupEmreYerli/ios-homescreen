"""Synthetic home screens shaped like real ``getIconState`` answers.

Only Apple stock apps and ``com.example.*`` placeholders; no real device data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

MODIFIED = datetime(2026, 9, 1, 8, 30, 0)


def app(bundle: str, name: str) -> dict[str, Any]:
    return {
        "bundleIdentifier": bundle,
        "displayIdentifier": bundle,
        "displayName": name,
        "bundleVersion": "1.0",
        "iconModDate": MODIFIED,
    }


def offloaded(display_id: str, name: str) -> dict[str, Any]:
    """An offloaded app keeps only its display identifier."""
    return {"displayIdentifier": display_id, "displayName": name}


def webclip(display_id: str, name: str, url: str) -> dict[str, Any]:
    return {
        "displayIdentifier": display_id,
        "displayName": name,
        "webClipURL": url,
        "iconModDate": MODIFIED,
        "iconData": b"\x89PNG\r\n\x1a\nfake",
    }


def safari_webapp(display_id: str) -> dict[str, Any]:
    """iOS 26+ 'Add to Home Screen' web app: Safari's bundle id, its own display id."""
    return {
        "bundleIdentifier": "com.apple.mobilesafari",
        "displayIdentifier": display_id,
        "iconType": "app",
    }


def widget(
    display_id: str,
    size: str,
    *,
    container: str,
    extension: str,
    kind: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "elementType": "widget",
        "iconType": "custom",
        "bundleIdentifier": extension,
        "containerBundleIdentifier": container,
        "widgetIdentifier": kind,
        "displayIdentifier": display_id,
        "gridSize": size,
        **extra,
    }


def widget_stack(display_id: str, size: str, elements: list[dict[str, Any]], selected: str):
    return {
        "iconType": "custom",
        "displayIdentifier": display_id,
        "gridSize": size,
        "elements": elements,
        "userSelectedElementIdentifier": selected,
    }


def folder(name: str, *pages: list[Any]) -> dict[str, Any]:
    return {"listType": "folder", "displayName": name, "iconLists": [list(p) for p in pages]}


WEATHER_WIDGET = "0D0C4E8A-1111-4A6B-9C1D-000000000001"
STACK = "0D0C4E8A-1111-4A6B-9C1D-000000000002"
LIGHTS_A = "0D0C4E8A-1111-4A6B-9C1D-000000000003"
LIGHTS_B = "0D0C4E8A-1111-4A6B-9C1D-000000000004"
STATUS_CLIP = "5B1F2C3D4E5F40718293A4B5C6D7E8F9"
DOCS_CLIP = "6C2A3B4C5D6E4F708192A3B4C5D6E7F8"
WEBAPP_PAGE = "7D3B4C5D-6E7F-4081-92A3-B4C5D6E7F809"
WEBAPP_FOLDER = "8E4C5D6E-7F80-4192-A3B4-C5D6E7F8091A"
OFFLOADED = "com.example.journal"

ON_SCREEN_APPS = {
    "com.apple.mobilephone": "Phone",
    "com.apple.mobilesafari": "Safari",
    "com.apple.MobileSMS": "Messages",
    "com.apple.camera": "Camera",
    "com.apple.mobilecal": "Calendar",
    "com.apple.mobileslideshow": "Photos",
    "com.apple.mobilemail": "Mail",
    "com.apple.Maps": "Maps",
    "com.apple.mobiletimer": "Clock",
    "com.apple.mobilenotes": "Notes",
    "com.apple.reminders": "Reminders",
    "com.apple.Preferences": "Settings",
    "com.apple.AppStore": "App Store",
    "com.apple.calculator": "Calculator",
    "com.apple.VoiceMemos": "Voice Memos",
    "com.apple.findmy": "Find My",
    "com.apple.Music": "Music",
    "com.apple.podcasts": "Podcasts",
    "com.apple.tv": "TV",
    "com.apple.iBooks": "Books",
    "com.apple.Health": "Health",
    "com.apple.Passbook": "Wallet",
    "com.apple.DocumentsApp": "Files",
    "com.example.lights": "Lights",
}

LIBRARY_SYSTEM_APPS = [
    "com.apple.tips",
    "com.apple.stocks",
    "com.apple.news",
    "com.apple.Home",
    "com.apple.facetime",
    "com.apple.MobileAddressBook",
    "com.apple.Translate",
    "com.apple.shortcuts",
    "com.apple.Magnifier",
    "com.apple.compass",
    "com.apple.measure",
]
LIBRARY_USER_APPS = [f"com.example.app{n:02d}" for n in range(1, 21)]


def _a(bundle: str) -> dict[str, Any]:
    return app(bundle, ON_SCREEN_APPS[bundle])


def home_screen() -> list[list[Any]]:
    """A format-version-2 answer: ``[dock, page 1, page 2]``."""
    dock = [
        _a(b)
        for b in (
            "com.apple.mobilephone",
            "com.apple.mobilesafari",
            "com.apple.MobileSMS",
            "com.apple.camera",
        )
    ]
    page1 = [
        widget(
            WEATHER_WIDGET,
            "medium",
            container="com.apple.weather",
            extension="com.apple.weather.widget",
            kind="com.apple.weather.forecast",
        ),
        *[
            _a(b)
            for b in (
                "com.apple.mobilecal",
                "com.apple.mobileslideshow",
                "com.apple.mobilemail",
                "com.apple.Maps",
                "com.apple.mobiletimer",
                "com.apple.mobilenotes",
                "com.apple.reminders",
                "com.apple.Preferences",
            )
        ],
        folder(
            "Utilities",
            [
                _a("com.apple.calculator"),
                _a("com.apple.VoiceMemos"),
                _a("com.apple.findmy"),
                webclip(DOCS_CLIP, "Docs", "https://docs.example.com/"),
                safari_webapp(WEBAPP_FOLDER),
            ],
        ),
        _a("com.apple.AppStore"),
        webclip(STATUS_CLIP, "Status", "https://status.example.com/"),
        safari_webapp(WEBAPP_PAGE),
    ]
    page2 = [
        widget_stack(
            STACK,
            "small",
            [
                {
                    "uniqueIdentifier": "e1",
                    "bundleIdentifier": "com.apple.mobilecal.widget",
                    "containerBundleIdentifier": "com.apple.mobilecal",
                    "widgetIdentifier": "com.apple.mobilecal.upnext",
                },
                {
                    "uniqueIdentifier": "e2",
                    "bundleIdentifier": "com.apple.reminders.widget",
                    "containerBundleIdentifier": "com.apple.reminders",
                    "widgetIdentifier": "com.apple.reminders.list",
                },
            ],
            selected="e2",
        ),
        # Two widgets from the same extension: only the display id tells them apart.
        widget(
            LIGHTS_A,
            "small",
            container="com.example.lights",
            extension="com.example.lights.widget",
            kind="SceneWidget",
        ),
        widget(
            LIGHTS_B,
            "small",
            container="com.example.lights",
            extension="com.example.lights.widget",
            kind="SceneWidget",
            userSelectedElementIdentifier="scene-2",
        ),
        folder(
            "Media",
            [_a("com.apple.Music"), _a("com.apple.podcasts"), _a("com.apple.tv")],
            [_a("com.apple.iBooks")],
        ),
        offloaded(OFFLOADED, "Journal"),
        _a("com.apple.Health"),
        _a("com.apple.Passbook"),
        _a("com.apple.DocumentsApp"),
        _a("com.example.lights"),
    ]
    return [dock, page1, page2]


def installed_apps() -> dict[str, dict[str, str]]:
    """What Installation Proxy reports (User + System only), as stored in a read."""
    apps = {
        bundle: {"name": name, "type": "System" if bundle.startswith("com.apple.") else "User"}
        for bundle, name in ON_SCREEN_APPS.items()
    }
    apps[OFFLOADED] = {"name": "Journal", "type": "User"}
    apps.update({b: {"name": b.rsplit(".", 1)[-1], "type": "System"} for b in LIBRARY_SYSTEM_APPS})
    apps.update({b: {"name": f"App {b[-2:]}", "type": "User"} for b in LIBRARY_USER_APPS})
    return apps


def library_only() -> set[str]:
    return {*LIBRARY_SYSTEM_APPS, *LIBRARY_USER_APPS}


def read_snapshot() -> dict[str, Any]:
    return {"state": home_screen(), "apps": installed_apps()}
