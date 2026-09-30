# Exodus Temple font

`FontStd.hex` contains the 256 original 8×8 glyph bitmaps from TempleOS
`Kernel/FontStd.HC`. `Temple8x8.ttf` converts those pixels to square outlines for
local browser use. No font service is contacted.

Source: https://templeos.info/Wb/Kernel/FontStd.HC.HTML

TempleOS's credits identify this standard font as taken from FreeDOS and in the
public domain: https://templeos.info/Wb/Doc/Credits.DD.HTML

The converter is `scripts/build_temple_font.py` (requires Python fonttools).
Each source bit becomes a square in a 1024-unit em, with an 8-pixel advance at
8px CSS size. ASCII and CP437 mappings are included; other characters use the
browser's monospace fallback. Font smoothing and fractional scaling can vary by
browser. This is a UI theme honoring Terry A. Davis's design, not TempleOS itself.
