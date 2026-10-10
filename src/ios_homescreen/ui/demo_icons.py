"""Simple generated app icons for the demo: a flat single-colour tile with a white glyph.

Every app in demo mode is invented, and so are these icons. They are plain SVG built
from the shapes below, drawn in a 120 x 120 box; the UI rounds the corners like iOS.
The colours are flat and of one saturation, so the demo reads as neutral sample data.
"""

from __future__ import annotations

# name -> (tile, cut-out). The cut-out colour is a darker shade for holes in glyphs.
PALETTES: dict[str, tuple[str, str]] = {
    "green": ("#2F9460", "#1F6B44"),
    "blue": ("#3A72C4", "#28528F"),
    "sky": ("#3A8BBF", "#28658C"),
    "rose": ("#C9444B", "#932F35"),
    "orange": ("#D07335", "#984F21"),
    "amber": ("#B98A1E", "#86630F"),
    "purple": ("#7A5BB8", "#573F87"),
    "indigo": ("#5864B8", "#3D4687"),
    "teal": ("#2C8C8C", "#1D6464"),
    "mint": ("#2E9A7A", "#1F6F57"),
    "slate": ("#5D6876", "#424A55"),
    "graphite": ("#3E434B", "#2A2E34"),
    "coral": ("#C95D45", "#93402F"),
    "violet": ("#6E58B5", "#4E3E85"),
    "cyan": ("#2C8FA8", "#1F677A"),
    "lime": ("#6A9433", "#4C6B22"),
    "pink": ("#B84A7E", "#86345B"),
    "navy": ("#3D5590", "#2B3C67"),
    "sand": ("#A88247", "#7A5D31"),
    "white": ("#FFFFFF", "#D5DAE0"),
}

# Glyphs use {fg} for the main colour and {dark} for cut-outs (a darker shade of the tile).
GLYPHS: dict[str, str] = {
    "phone": '<path d="M43 29c3 0 5 2 6.6 5.4l5 11c1.2 2.8.5 5.6-1.8 7.6l-5.2 4.4c3.6 7.6 '
    "9.8 13.8 17.4 17.4l4.4-5.2c2-2.3 4.8-3 7.6-1.8l11 5c3.4 1.6 5.4 3.6 5.4 6.6v6.4c0 "
    '6-5 10.6-11 10.2C55 94 26 65 23.8 40c-.4-6 4.2-11 10.2-11z" fill="{fg}"/>',
    "chat": '<path d="M60 27c-20 0-36 13-36 29.5 0 9 4.8 17 12.6 22.4L33 92l15.4-7.8c3.6 '
    '1 7.6 1.6 11.6 1.6 20 0 36-13 36-29.4S80 27 60 27z" fill="{fg}"/>',
    "compass": '<circle cx="60" cy="60" r="32" fill="none" stroke="{fg}" stroke-width="6"/>'
    '<g transform="rotate(40 60 60)"><path d="M60 33l8 27H52z" fill="#FF5A5F"/>'
    '<path d="M60 87l8-27H52z" fill="{fg}"/></g>',
    "music": '<path d="M52 81V41l34-9v40" fill="none" stroke="{fg}" stroke-width="7" '
    'stroke-linejoin="round"/><circle cx="43" cy="81" r="10" fill="{fg}"/>'
    '<circle cx="77" cy="72" r="10" fill="{fg}"/>',
    "weather": '<circle cx="50" cy="47" r="16" fill="#FFD43B"/><path d="M45 89h39a15 15 0 '
    '0 0 0-30 20 20 0 0 0-38-4.5A14.5 14.5 0 0 0 45 89z" fill="{fg}"/>',
    "calendar": '<rect x="28" y="32" width="64" height="58" rx="10" fill="none" '
    'stroke="{fg}" stroke-width="6"/><path d="M28 50h64" stroke="{fg}" stroke-width="6"/>'
    '<path d="M45 25v13M75 25v13" stroke="{fg}" stroke-width="6" stroke-linecap="round"/>'
    '<g fill="{fg}"><circle cx="44" cy="64" r="4.5"/><circle cx="60" cy="64" r="4.5"/>'
    '<circle cx="76" cy="64" r="4.5"/><circle cx="44" cy="78" r="4.5"/>'
    '<circle cx="60" cy="78" r="4.5"/></g>',
    "photo": '<rect x="26" y="32" width="68" height="56" rx="10" fill="none" stroke="{fg}" '
    'stroke-width="6"/><path d="M33 82l17-19 12 12 9-9 17 16" fill="none" stroke="{fg}" '
    'stroke-width="6" stroke-linejoin="round"/><circle cx="74" cy="49" r="6.5" fill="{fg}"/>',
    "camera": '<path d="M29 47a8 8 0 0 1 8-8h9l5-8h18l5 8h9a8 8 0 0 1 8 8v31a8 8 0 0 1-8 '
    '8H37a8 8 0 0 1-8-8z" fill="{fg}"/><circle cx="60" cy="62" r="15" fill="{dark}"/>'
    '<circle cx="60" cy="62" r="7" fill="{fg}" opacity=".55"/>',
    "mail": '<rect x="25" y="36" width="70" height="48" rx="9" fill="{fg}"/>'
    '<path d="M29 41l31 23 31-23" fill="none" stroke="{dark}" stroke-width="5" '
    'stroke-linejoin="round"/>',
    "pin": '<path d="M60 93S37 70 37 51a23 23 0 0 1 46 0c0 19-23 42-23 42z" fill="{fg}"/>'
    '<circle cx="60" cy="51" r="8.5" fill="{dark}"/>',
    "clock": '<circle cx="60" cy="60" r="33" fill="{fg}"/><path d="M60 39v22l14 8" '
    'fill="none" stroke="{dark}" stroke-width="6" stroke-linecap="round" '
    'stroke-linejoin="round"/>',
    "notes": '<rect x="31" y="27" width="58" height="66" rx="9" fill="{fg}"/><path '
    'd="M42 46h36M42 59h36M42 72h22" stroke="{dark}" stroke-width="5" '
    'stroke-linecap="round"/>',
    "checklist": '<g fill="{fg}"><circle cx="37" cy="42" r="6.5"/><circle cx="37" cy="60" '
    'r="6.5"/><circle cx="37" cy="78" r="6.5"/></g><path d="M52 42h34M52 60h34M52 78h22" '
    'stroke="{fg}" stroke-width="6.5" stroke-linecap="round"/>',
    "pen": '<path d="M33 87l4.5-19 38-38a7 7 0 0 1 10 0l4.5 4.5a7 7 0 0 1 0 10l-38 38z" '
    'fill="{fg}"/><path d="M70 36l14 14" stroke="{dark}" stroke-width="4"/>',
    "palette": '<path d="M60 26C40 26 25 40 25 58c0 19 15 34 33 34 6 0 8.5-4 6-8.5-2.3-4.3 '
    '0-8.5 6-8.5h8c9 0 17-6 17-16 0-19-16-33-35-33z" fill="{fg}"/>'
    '<circle cx="43" cy="55" r="5.5" fill="#EF4444"/><circle cx="55" cy="40" r="5.5" '
    'fill="#F59E0B"/><circle cx="72" cy="41" r="5.5" fill="#10B981"/>'
    '<circle cx="81" cy="56" r="5.5" fill="#3B82F6"/>',
    "clapper": '<rect x="27" y="52" width="66" height="38" rx="6" fill="{fg}"/><path '
    'd="M27 45l60-15 3 12-60 15z" fill="{fg}"/><path d="M45 40l7 11M64 35l7 11" '
    'stroke="{dark}" stroke-width="4"/>',
    "wave": '<path d="M28 60h0M42 47v26M56 34v52M70 43v34M84 52v16" stroke="{fg}" '
    'stroke-width="8" stroke-linecap="round"/>',
    "heart": '<path d="M60 91S27 71 27 48.5A16.5 16.5 0 0 1 60 43a16.5 16.5 0 0 1 33 5.5C93 '
    '71 60 91 60 91z" fill="{fg}"/>',
    "card": '<rect x="24" y="37" width="72" height="48" rx="9" fill="{fg}"/><rect x="24" '
    'y="48" width="72" height="9" fill="{dark}"/><rect x="33" y="67" width="20" height="8" '
    'rx="3" fill="{dark}" opacity=".5"/>',
    "gear": '<g fill="{fg}">'
    + "".join(
        f'<rect x="53" y="24" width="14" height="18" rx="3.5" transform="rotate({a} 60 60)"/>'
        for a in range(0, 360, 45)
    )
    + '<circle cx="60" cy="60" r="25"/></g><circle cx="60" cy="60" r="10" fill="{dark}"/>',
    "calculator": '<rect x="32" y="25" width="56" height="70" rx="11" fill="{fg}"/><rect '
    'x="40" y="33" width="40" height="15" rx="4" fill="{dark}"/><g fill="{dark}">'
    '<circle cx="45" cy="61" r="4.5"/><circle cx="60" cy="61" r="4.5"/><circle cx="75" '
    'cy="61" r="4.5"/><circle cx="45" cy="78" r="4.5"/><circle cx="60" cy="78" r="4.5"/>'
    '<circle cx="75" cy="78" r="4.5"/></g>',
    "mic": '<rect x="48" y="25" width="24" height="43" rx="12" fill="{fg}"/><path d="M38 '
    '58a22 22 0 0 0 44 0M60 80v12M48 93h24" fill="none" stroke="{fg}" stroke-width="6" '
    'stroke-linecap="round"/>',
    "ruler": '<g transform="rotate(-35 60 60)"><rect x="20" y="47" width="80" height="26" '
    'rx="5" fill="{fg}"/><path d="M33 47v11M46 47v7M59 47v11M72 47v7M85 47v11" '
    'stroke="{dark}" stroke-width="4"/></g>',
    "loupe": '<circle cx="53" cy="53" r="21" fill="none" stroke="{fg}" stroke-width="8"/>'
    '<path d="M69 69l19 19" stroke="{fg}" stroke-width="11" stroke-linecap="round"/>',
    "book": '<path d="M60 40c-9-6-21-8-33-6v49c12-2 24 0 33 6 9-6 21-8 33-6V34c-12-2-24 '
    '0-33 6z" fill="{fg}"/><path d="M60 41v47" stroke="{dark}" stroke-width="4"/>',
    "headphones": '<path d="M31 75V62a29 29 0 0 1 58 0v13" fill="none" stroke="{fg}" '
    'stroke-width="7"/><rect x="26" y="65" width="17" height="27" rx="7" fill="{fg}"/>'
    '<rect x="77" y="65" width="17" height="27" rx="7" fill="{fg}"/>',
    "bag": '<path d="M33 45h54l-4 47H37z" fill="{fg}"/><path d="M47 51v-10a13 13 0 0 1 '
    '26 0v10" fill="none" stroke="{fg}" stroke-width="6" stroke-linecap="round"/>',
    "trend": '<path d="M27 82l21-21 14 12 28-31" fill="none" stroke="{fg}" stroke-width="8" '
    'stroke-linecap="round" stroke-linejoin="round"/><path d="M73 40h18v18" fill="none" '
    'stroke="{fg}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>',
    "dining": '<path d="M35 27v18a8.5 8.5 0 0 0 17 0V27M43.5 27v66" fill="none" '
    'stroke="{fg}" stroke-width="6" stroke-linecap="round"/><path d="M81 93V27c-9 5-12 '
    '17-12 30h12" fill="{fg}" stroke="{fg}" stroke-width="5" stroke-linejoin="round"/>',
    "leaf": '<path d="M88 29C51 29 31 48 31 75c0 6 1.5 11 4 15.5 4-14 14-28 31-36-14 '
    '10-22 22-24 38 34 2 46-27 46-63.5z" fill="{fg}"/>',
    "bicycle": '<circle cx="37" cy="73" r="14" fill="none" stroke="{fg}" stroke-width="6"/>'
    '<circle cx="83" cy="73" r="14" fill="none" stroke="{fg}" stroke-width="6"/>'
    '<path d="M37 73l12-25h22l12 25M49 48l13 25H37M64 40h10" fill="none" stroke="{fg}" '
    'stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>',
    "box": '<path d="M60 25l33 14v41L60 95 27 80V39z" fill="{fg}"/><path d="M27 39l33 15 '
    '33-15M60 54v41" fill="none" stroke="{dark}" stroke-width="4" stroke-linejoin="round"/>',
    "globe": '<circle cx="60" cy="60" r="31" fill="none" stroke="{fg}" stroke-width="6"/>'
    '<ellipse cx="60" cy="60" rx="13" ry="31" fill="none" stroke="{fg}" stroke-width="5"/>'
    '<path d="M29 60h62M35 44h50M35 76h50" stroke="{fg}" stroke-width="5"/>',
    "bars": '<path d="M33 88V66M51 88V50M69 88V58M87 88V34" stroke="{fg}" '
    'stroke-width="11" stroke-linecap="round"/>',
    "pie": '<circle cx="60" cy="60" r="31" fill="{fg}" opacity=".45"/><path d="M60 60V29a31 '
    '31 0 0 1 29.5 40.5z" fill="{fg}"/>',
    "plane": '<path d="M60 23c4 0 6.5 4 6.5 8v18L93 64v8l-26.5-6.5V82l8.5 6v6.5l-15-4.5-15 '
    '4.5V88l8.5-6V65.5L27 72v-8l26.5-15V31c0-4 2.5-8 6.5-8z" fill="{fg}"/>',
    "suitcase": '<path d="M48 42v-8a6 6 0 0 1 6-6h12a6 6 0 0 1 6 6v8" fill="none" '
    'stroke="{fg}" stroke-width="6"/><rect x="26" y="42" width="68" height="46" rx="9" '
    'fill="{fg}"/><path d="M26 61h68" stroke="{dark}" stroke-width="4"/>',
    "people": '<circle cx="46" cy="45" r="12" fill="{fg}"/><circle cx="77" cy="48" r="9.5" '
    'fill="{fg}" opacity=".8"/><path d="M22 90c0-15 10.5-25 24-25s24 10 24 25z" '
    'fill="{fg}"/><path d="M68 90c0-8-2-15-6.5-20.5 4-2.8 9-4 14.5-4 11.5 0 21 9 21 24.5z" '
    'fill="{fg}" opacity=".8"/>',
    "typing": '<path d="M60 28c-20 0-36 13-36 29.5 0 9 4.8 17 12.6 22.4L33 92l15.4-7.8c3.6 '
    '1 7.6 1.6 11.6 1.6 20 0 36-13 36-29.4S80 28 60 28z" fill="{fg}"/><g fill="{dark}">'
    '<circle cx="45" cy="57" r="5"/><circle cx="60" cy="57" r="5"/>'
    '<circle cx="75" cy="57" r="5"/></g>',
    "star": '<path d="M60 25l10.5 22 24 3.2-17.6 16.6 4.6 23.8L60 79 38.5 90.6l4.6-23.8L25.5 '
    '50.2l24-3.2z" fill="{fg}"/>',
    "arcs": '<path d="M26 82a34 34 0 0 1 68 0M38 82a22 22 0 0 1 44 0M50 82a10 10 0 0 1 20 0" '
    'fill="none" stroke="{fg}" stroke-width="7" stroke-linecap="round"/>',
    "waves": '<path d="M25 46c6-6 13-6 18 0s12 6 17 0 12-6 17 0 12 6 18 0M25 62c6-6 13-6 18 '
    "0s12 6 17 0 12-6 17 0 12 6 18 0M25 78c6-6 13-6 18 0s12 6 17 0 12-6 17 0 12 6 18 "
    '0" fill="none" stroke="{fg}" stroke-width="6" stroke-linecap="round"/>',
    "nodes": '<path d="M37 83l19-31 26-14M56 52l26 31" fill="none" stroke="{fg}" '
    'stroke-width="5"/><g fill="{fg}"><circle cx="37" cy="83" r="9"/><circle cx="56" '
    'cy="52" r="9"/><circle cx="82" cy="38" r="9"/><circle cx="82" cy="83" r="9"/></g>',
    "flame": '<path d="M60 93c-16 0-27-10-27-24.5 0-16 14-22.5 16.5-41.5 10 8 14.5 16.5 '
    '14.5 25 4-4 6-8.5 6-12.5 10 8 16 18.5 16 29 0 14.5-10 24.5-26 24.5z" '
    'fill="{fg}"/>',
    "hexagon": '<path d="M60 25l31 17.5v35L60 95 29 77.5v-35z" fill="none" stroke="{fg}" '
    'stroke-width="7" stroke-linejoin="round"/><circle cx="60" cy="60" r="10" '
    'fill="{fg}"/>',
    "anchor": '<circle cx="60" cy="33" r="7.5" fill="none" stroke="{fg}" stroke-width="6"/>'
    '<path d="M60 41v51M44 54h32M31 67c0 16 12.5 25 29 25s29-9 29-25" fill="none" '
    'stroke="{fg}" stroke-width="6" stroke-linecap="round"/>',
    "mountain": '<path d="M22 87l25-38 14.5 21 10.5-14.5L98 87z" fill="{fg}"/>'
    '<circle cx="80" cy="37" r="7.5" fill="{fg}"/>',
    "kite": '<path d="M60 23l23 31-23 31-23-31z" fill="{fg}"/><path d="M37 54h46M60 '
    '23v62" stroke="{dark}" stroke-width="3.5"/><path d="M60 85c-5 5 5 8 0 13" '
    'fill="none" stroke="{fg}" stroke-width="4" stroke-linecap="round"/>',
    "mosaic": '<g fill="{fg}"><rect x="29" y="29" width="27" height="27" rx="7"/><rect '
    'x="64" y="29" width="27" height="27" rx="7" opacity=".7"/><rect x="29" y="64" '
    'width="27" height="27" rx="7" opacity=".7"/><rect x="64" y="64" width="27" '
    'height="27" rx="7" opacity=".45"/></g>',
    "cloud": '<path d="M40 84h44a17 17 0 0 0 0-34 22.5 22.5 0 0 0-43-4.5A19 19 0 0 0 40 '
    '84z" fill="{fg}"/>',
    "planet": '<circle cx="60" cy="60" r="21" fill="{fg}"/><ellipse cx="60" cy="60" rx="40" '
    'ry="12" fill="none" stroke="{fg}" stroke-width="5" transform="rotate(-22 60 60)"/>',
    "prism": '<path d="M60 26l35 61H25z" fill="none" stroke="{fg}" stroke-width="7" '
    'stroke-linejoin="round"/><path d="M60 40v42" stroke="{fg}" stroke-width="5" '
    'opacity=".6"/>',
    "quill": '<path d="M91 27c-35 0-57 22-57 57 31 0 53-21 57-57z" fill="{fg}"/><path '
    'd="M28 93l42-42" stroke="{dark}" stroke-width="4" stroke-linecap="round"/>',
    "ripple": '<circle cx="60" cy="60" r="9" fill="{fg}"/><circle cx="60" cy="60" r="21" '
    'fill="none" stroke="{fg}" stroke-width="5"/><circle cx="60" cy="60" r="33" '
    'fill="none" stroke="{fg}" stroke-width="5" opacity=".55"/>',
    "sprout": '<path d="M60 93V58" stroke="{fg}" stroke-width="7" stroke-linecap="round"/>'
    '<path d="M60 63c0-17-10.5-27-29-27 0 17 10.5 27 29 27zM60 55c0-17 10.5-27 29-27 0 '
    '17-10.5 27-29 27z" fill="{fg}"/>',
    "drop": '<path d="M60 23S33 54 33 71a27 27 0 0 0 54 0c0-17-27-48-27-48z" fill="{fg}"/>',
    "broadcast": '<circle cx="60" cy="61" r="8.5" fill="{fg}"/><path d="M47 75a19 19 0 0 '
    '1 0-28M73 47a19 19 0 0 1 0 28M37 85a33 33 0 0 1 0-48M83 37a33 33 0 0 1 0 48" '
    'fill="none" stroke="{fg}" stroke-width="6" stroke-linecap="round"/>',
    "cube": '<path d="M60 25l31 16.5v37L60 95 29 78.5v-37z" fill="{fg}"/><path d="M29 '
    '41.5l31 16.5 31-16.5M60 58v37" fill="none" stroke="{dark}" stroke-width="4" '
    'stroke-linejoin="round"/>',
    "paperplane": '<path d="M25 58l68-29-19 63-16-22z" fill="{fg}"/><path d="M58 70l35-41" '
    'stroke="{dark}" stroke-width="4"/>',
    "moon": '<path d="M73 28a33 33 0 1 0 18 48A27 27 0 0 1 73 28z" fill="{fg}"/>',
    "key": '<circle cx="43" cy="60" r="16" fill="none" stroke="{fg}" stroke-width="7.5"/>'
    '<path d="M59 60h33M81 60v13M92 60v9" stroke="{fg}" stroke-width="7.5" '
    'stroke-linecap="round"/>',
    "house": '<path d="M27 60l33-29 33 29" fill="none" stroke="{fg}" stroke-width="7" '
    'stroke-linecap="round" stroke-linejoin="round"/><path d="M37 55v34h46V55L60 35z" '
    'fill="{fg}"/><rect x="53" y="68" width="14" height="21" rx="3" fill="{dark}"/>',
    "translate": '<path d="M28 30h38a6 6 0 0 1 6 6v24a6 6 0 0 1-6 6H48l-12 9v-9h-8a6 6 0 0 '
    '1-6-6V36a6 6 0 0 1 6-6z" fill="{fg}"/><path d="M80 50h12a6 6 0 0 1 6 6v22a6 6 0 0 '
    '1-6 6h-6v8l-11-8H58a6 6 0 0 1-6-6v-6" fill="{fg}" opacity=".7"/>',
    "kanban": '<g fill="{fg}"><rect x="25" y="29" width="20" height="58" rx="5"/><rect '
    'x="50" y="29" width="20" height="42" rx="5" opacity=".85"/><rect x="75" y="29" '
    'width="20" height="29" rx="5" opacity=".7"/></g>',
    "document": '<path d="M38 25h30l16 16v54H38z" fill="{fg}"/><path d="M68 25v16h16" '
    'fill="{dark}" opacity=".25"/><path d="M47 57h28M47 67h28M47 77h18" stroke="{dark}" '
    'stroke-width="4" stroke-linecap="round"/>',
    "scan": '<path d="M28 44V34a6 6 0 0 1 6-6h10M76 28h10a6 6 0 0 1 6 6v10M92 76v10a6 6 0 0 '
    '1-6 6H76M44 92H34a6 6 0 0 1-6-6V76" fill="none" stroke="{fg}" stroke-width="6.5" '
    'stroke-linecap="round"/><path d="M38 60h44" stroke="{fg}" stroke-width="6.5" '
    'stroke-linecap="round"/>',
    "train": '<rect x="34" y="25" width="52" height="58" rx="13" fill="{fg}"/><rect x="42" '
    'y="35" width="36" height="19" rx="4" fill="{dark}"/><circle cx="47" cy="68" r="4.5" '
    'fill="{dark}"/><circle cx="73" cy="68" r="4.5" fill="{dark}"/><path d="M43 95l8-12M77 '
    '95l-8-12" stroke="{fg}" stroke-width="5" stroke-linecap="round"/>',
    "gamepad": '<rect x="21" y="43" width="78" height="38" rx="19" fill="{fg}"/><path '
    'd="M40 55v14M33 62h14" stroke="{dark}" stroke-width="4.5" stroke-linecap="round"/>'
    '<circle cx="76" cy="57" r="4.5" fill="{dark}"/><circle cx="85" cy="66" r="4.5" '
    'fill="{dark}"/>',
}


def icon_svg(glyph: str, palette: str, *, fg: str = "#FFFFFF", dark: str | None = None) -> bytes:
    """A full-bleed square icon as SVG bytes (the UI applies the rounded mask)."""
    tile, shade = PALETTES[palette]
    shape = GLYPHS[glyph].replace("{fg}", fg).replace("{dark}", dark or shade)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" '
        f'height="120"><rect width="120" height="120" fill="{tile}"/>{shape}</svg>'
    ).encode()
