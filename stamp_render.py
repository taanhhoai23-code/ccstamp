import re, io, generator

from PIL import Image

SIZE = 32

_RECT_RE = re.compile(

    r"<rect x='(\d+)' y='(\d+)' width='1' height='1' fill='#([0-9a-fA-F]{6})'/>"

)

_GRAD_RE = re.compile(

    r"stop offset='0' stop-color='#([0-9a-fA-F]{6})'.*?stop offset='1' stop-color='#([0-9a-fA-F]{6})'",

    re.DOTALL,

)

def _hex_to_rgb(h):

    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

def _parse_svg(svg):

    g = _GRAD_RE.search(svg)

    c1 = _hex_to_rgb(g.group(1)) if g else (0, 0, 0)

    c2 = _hex_to_rgb(g.group(2)) if g else (0, 0, 0)

    pixels = {}

    for m in _RECT_RE.finditer(svg):

        x, y, col = int(m.group(1)), int(m.group(2)), m.group(3)

        pixels[(x, y)] = _hex_to_rgb(col)

    return pixels, c1, c2

def _base_image(seed):

    svg, _info = generator.gen(seed)

    pixels, c1, c2 = _parse_svg(svg)

    img = Image.new('RGB', (SIZE, SIZE))

    px = img.load()

    for y in range(SIZE):

        t = y / (SIZE - 1)

        bg = (

            round(c1[0] + (c2[0] - c1[0]) * t),

            round(c1[1] + (c2[1] - c1[1]) * t),

            round(c1[2] + (c2[2] - c1[2]) * t),

        )

        for x in range(SIZE):

            px[x, y] = pixels.get((x, y), bg)

    return img

def render_png(seed, size=1024):

    if size < SIZE:

        size = SIZE

    if size > 4096:

        size = 4096

    img = _base_image(seed)

    big = img.resize((size, size), Image.NEAREST)

    buf = io.BytesIO()

    big.save(buf, 'PNG', optimize=True)

    return buf.getvalue()

def render_svg(seed):

    svg, _info = generator.gen(seed)

    return svg

if __name__ == '__main__':

    import sys

    s = sys.argv[1] if len(sys.argv) > 1 else 'CC-STAMP-00001-0'

    data = render_png(s, 1024)

    open(f'/tmp/{s}.png', 'wb').write(data)

    open(f'/tmp/{s}.svg', 'w').write(render_svg(s))

    print(f'PNG {len(data)} bytes -> /tmp/{s}.png')

    print(f'SVG -> /tmp/{s}.svg')
