"""Make build/icons/ios-homescreen.{ico,icns} from docs/assets/logo.png (needs Pillow)."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
out = ROOT / "build" / "icons"
out.mkdir(parents=True, exist_ok=True)
logo = Image.open(ROOT / "docs" / "assets" / "logo.png").convert("RGBA")
# A white rounded tile behind the line drawing, so the icon reads on dark docks too.
tile = Image.new("RGBA", logo.size, (0, 0, 0, 0))
mask = Image.new("L", logo.size, 0)
from PIL import ImageDraw  # noqa: E402

ImageDraw.Draw(mask).rounded_rectangle((16, 16, 496, 496), radius=110, fill=255)
tile.paste((255, 255, 255, 255), mask=mask)
icon = Image.alpha_composite(tile, logo)
icon.save(out / "ios-homescreen.png")
icon.save(out / "ios-homescreen.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
icon.save(out / "ios-homescreen.icns")
print(f"icons in {out}")
