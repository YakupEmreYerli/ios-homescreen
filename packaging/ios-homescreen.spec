# PyInstaller spec for the desktop app: `pyinstaller packaging/ios-homescreen.spec`.
# Builds ios-homescreen.app on macOS and a one-folder app on Windows and Linux; the
# workflow in .github/workflows/release-apps.yml wraps them into a .dmg, an installer
# .exe and an AppImage.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
# packaging/make_icons.py makes these first.
ICONS = ROOT / "build" / "icons"
ICON = str(
    ICONS / {"darwin": "ios-homescreen.icns", "win32": "ios-homescreen.ico"}.get(
        sys.platform, "ios-homescreen.png"
    )
)
sys.path.insert(0, str(ROOT / "src"))
from ios_homescreen import __version__  # noqa: E402

hidden = [
    # pymobiledevice3 and uvicorn import these by name at run time.
    *collect_submodules("pymobiledevice3"),
    *collect_submodules("uvicorn"),
    *collect_submodules("ios_homescreen"),
]
if sys.platform == "linux":
    hidden += ["webview.platforms.qt"]
elif sys.platform == "darwin":
    hidden += ["webview.platforms.cocoa"]
else:
    hidden += ["webview.platforms.edgechromium", "webview.platforms.winforms"]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        *collect_data_files("ios_homescreen"),
        *collect_data_files("pymobiledevice3"),
        *collect_data_files("webview"),
    ],
    hiddenimports=hidden,
    # av (video) comes with pymobiledevice3's screen recording; GTK is pywebview's other
    # Linux backend. Neither is used.
    excludes=["tkinter", "pytest", "IPython", "av", "gi", "webview.platforms.gtk"],
    noarchive=False,
)

# Qt WebEngine needs Core, Gui, Widgets, Network, Qml, Quick and a few more; the rest
# of PyQt6 (3D, multimedia, controls, translations) only makes the download bigger.
UNUSED_QT = (
    "Quick3D", "QuickControls2", "QuickDialogs2", "QuickTemplates2", "QuickParticles",
    "QuickTimeline", "QuickShapes", "QuickEffects", "QuickLayouts", "QuickVectorImage",
    "Multimedia", "ShaderTools", "Sensors", "TextToSpeech", "RemoteObjects", "Test",
    "Charts", "DataVisualization", "Graphs", "Bluetooth", "Nfc", "SerialPort",
    "SpatialAudio", "Pdf", "Designer", "Help", "Sql", "3D", "Location", "Scxml",
    "StateMachine", "LabsAnimation", "LabsFolderListModel", "LabsQmlModels",
    "LabsSettings", "LabsSharedImage", "LabsWavefrontMesh", "VirtualKeyboard",
)


def _unused(dest):
    path = dest.replace("\\", "/")
    if "/Qt6/qml/" in path or "/Qt6/translations/qt" in path:
        return True
    if "/qtwebengine_locales/" in path:
        return not path.endswith(("/en-US.pak", "/tr.pak"))
    name = path.rsplit("/", 1)[-1]
    return any(f"Qt6{part}" in name or f"Qt{part}." in name for part in UNUSED_QT)


a.binaries = [entry for entry in a.binaries if not _unused(entry[0])]
a.datas = [entry for entry in a.datas if not _unused(entry[0])]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ios-homescreen",
    console=False,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ios-homescreen")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ios-homescreen.app",
        icon=ICON,
        bundle_identifier="io.github.yakupemreyerli.ios-homescreen",
        version=__version__,
        info_plist={
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "13.0",
            # Wi-Fi mode finds the phone with Bonjour on the local network.
            "NSLocalNetworkUsageDescription": "ios-homescreen finds your iPhone on the local network to read and write its Home Screen over Wi-Fi.",
            "NSBonjourServices": ["_remotepairing._tcp", "_apple-mobdev2._tcp"],
        },
    )
