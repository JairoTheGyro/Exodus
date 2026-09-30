"""Build the public-domain TempleOS 8x8 standard font as a browser TTF.
Requires fonttools; input provenance is in static/fonts/temple/README.md.
"""
from pathlib import Path
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

root = Path(__file__).resolve().parents[1] / 'static/fonts/temple'
values = [int(line, 16) for line in (root / 'FontStd.hex').read_text().splitlines()]
fb = FontBuilder(1024, isTTF=True)
names = ['.notdef'] + [f'cp{i:03}' for i in range(256)]
fb.setupGlyphOrder(names)
glyphs = {}
for name, value in zip(names, [0x7E4242424242427E] + values):
    pen = TTGlyphPen(None)
    for row in range(8):
        bits = (value >> (8 * row)) & 255
        for col in range(8):
            if bits & (1 << col):
                x, y = col * 128, (7 - row) * 128
                pen.moveTo((x, y)); pen.lineTo((x, y + 128))
                pen.lineTo((x + 128, y + 128)); pen.lineTo((x + 128, y)); pen.closePath()
    glyphs[name] = pen.glyph()
fb.setupGlyf(glyphs)
fb.setupHorizontalMetrics({name: (1024, 0) for name in names})
fb.setupHorizontalHeader(ascent=1024, descent=0)
cmap = {ord(bytes([i]).decode('cp437')): f'cp{i:03}' for i in range(32, 256)}
cmap[160] = 'cp032'
fb.setupCharacterMap(cmap)
fb.setupNameTable({'familyName': 'Exodus Temple', 'styleName': 'Regular', 'uniqueFontIdentifier': 'ExodusTemple8x8-v1', 'fullName': 'Exodus Temple 8x8', 'psName': 'ExodusTemple8x8', 'version': 'Version 1.0', 'copyright': 'Public-domain TempleOS standard font, credited to FreeDOS by Terry A. Davis. Browser outline conversion for Exodus.'})
fb.setupOS2(sTypoAscender=1024, sTypoDescender=0, usWinAscent=1024, usWinDescent=0)
fb.setupPost(isFixedPitch=1)
fb.setupMaxp()
fb.save(root / 'Temple8x8.ttf')
print('Built Temple8x8.ttf')
