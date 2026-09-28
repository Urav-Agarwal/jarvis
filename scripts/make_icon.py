"""
Generate the JARVIS glowing-orb application icon (assets/jarvis.ico).

Layered radial gradients: deep space background, outer glow halo,
bright cyan-blue core with a white hot center, orbit arc accents.
Multiple sizes embedded (16..256) for crisp taskbar/desktop scaling.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]

OUT_DIR = ROOT / "assets"
OUT_DIR.mkdir(exist_ok=True)

MASTER_SIZE = 512


def lerp(a, b, t):
    return int(a + (b - a) * t)


def build_orb(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    draw = ImageDraw.Draw(img)

    cx = cy = size / 2

    def radius_of(fraction):
        return fraction * size / 2

    # ------------------------------------------------
    # 1. Deep space disc (near-black blue)
    # ------------------------------------------------
    bg = radius_of(0.98)

    draw.ellipse(
        [cx - bg, cy - bg, cx + bg, cy + bg],
        fill=(6, 10, 22, 255),
    )

    # ------------------------------------------------
    # 2. Outer glow halo (cyan, blurred)
    # ------------------------------------------------
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)

    glow_radius = radius_of(0.92)

    glow_draw.ellipse(
        [cx - glow_radius, cy - glow_radius, cx + glow_radius, cy + glow_radius],
        fill=(34, 211, 238, 110),
    )

    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.055))

    img = Image.alpha_composite(img, glow)

    # ------------------------------------------------
    # 3. Core sphere: layered radial gradients
    # ------------------------------------------------
    core_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    core_radius = radius_of(0.56)

    # Build the gradient by concentric ellipses (fast, no numpy).
    steps = 90

    for step in range(steps, 0, -1):
        t = step / steps

        r = core_radius * t

        if t > 0.55:
            # Inner region: white-hot center blending to cyan.
            k = (t - 0.55) / 0.45

            red = lerp(120, 255, 1 - k)
            green = lerp(235, 255, 1 - k)
            blue = lerp(255, 255, 1 - k)
            alpha = 255

        elif t > 0.2:
            # Mid region: vivid cyan-blue.
            k = (t - 0.2) / 0.35

            red = lerp(30, 120, 1 - k)
            green = lerp(120, 235, 1 - k)
            blue = lerp(230, 255, 1 - k)
            alpha = 255

        else:
            # Outer edge: deep blue fading out.
            k = t / 0.2

            red = lerp(20, 30, k)
            green = lerp(60, 120, k)
            blue = lerp(160, 230, k)
            alpha = int(255 * (0.35 + 0.65 * k))

        draw_core = ImageDraw.Draw(core_layer)

        draw_core.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(red, green, blue, alpha),
        )

    # Soft edge for the whole sphere.
    core_layer = core_layer.filter(ImageFilter.GaussianBlur(size * 0.012))

    img = Image.alpha_composite(img, core_layer)

    # ------------------------------------------------
    # 4. Orbit arcs (two thin sweeping ellipses)
    # ------------------------------------------------
    arcs = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    arcs_draw = ImageDraw.Draw(arcs)

    arc_box = radius_of(0.88)

    arcs_draw.arc(
        [cx - arc_box, cy - arc_box, cx + arc_box, cy + arc_box],
        start=200,
        end=330,
        fill=(103, 232, 249, 230),
        width=max(2, size // 85),
    )

    arc_box_2 = radius_of(0.74)

    arcs_draw.arc(
        [cx - arc_box_2, cy - arc_box_2, cx + arc_box_2, cy + arc_box_2],
        start=30,
        end=140,
        fill=(59, 130, 246, 200),
        width=max(2, size // 110),
    )

    arcs = arcs.filter(ImageFilter.GaussianBlur(size * 0.004))

    img = Image.alpha_composite(img, arcs)

    # ------------------------------------------------
    # 5. Specular highlight (top-left glossy dot)
    # ------------------------------------------------
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    highlight_draw = ImageDraw.Draw(highlight)

    hx = cx - radius_of(0.18)
    hy = cy - radius_of(0.22)
    hr = radius_of(0.13)

    highlight_draw.ellipse(
        [hx - hr, hy - hr, hx + hr, hy + hr],
        fill=(255, 255, 255, 190),
    )

    highlight = highlight.filter(ImageFilter.GaussianBlur(size * 0.03))

    img = Image.alpha_composite(img, highlight)

    return img


def main():
    master = build_orb(MASTER_SIZE)

    sizes = [16, 24, 32, 48, 64, 128, 256]

    ico_path = OUT_DIR / "jarvis.ico"

    master.save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )

    # Also drop a PNG preview for the window/tray to load losslessly.
    png_path = OUT_DIR / "jarvis.png"

    master.resize((256, 256), Image.LANCZOS).save(png_path)

    print("Icon written:", ico_path)
    print("Preview written:", png_path)


if __name__ == "__main__":
    main()
