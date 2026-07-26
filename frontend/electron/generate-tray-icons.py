"""Generate transparent tray icons visible on dark and light Windows taskbars."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def draw_ring(size: int, fill: tuple[int, int, int, int], stroke: tuple[int, int, int, int]) -> Image.Image:
    """Draw a thick cracked-ring mark on a fully transparent canvas."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Keep a small transparent margin so Windows doesn't clip the outline.
    pad = max(1, size // 16)
    ring_top = pad + size // 8
    outer = [pad, ring_top, size - pad - 1, size - pad - 1]
    inset = max(3, size // 5)
    inner = [pad + inset, ring_top + inset, size - pad - inset - 1, size - pad - inset - 1]

    # Dark/light contrast outline first, then the main fill ring.
    d.ellipse(outer, outline=stroke, width=max(3, size // 8))
    d.ellipse(outer, outline=fill, width=max(2, size // 10))
    # Clear the hole explicitly (transparent)
    hole = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hole)
    hd.ellipse(inner, fill=(255, 255, 255, 255))
    # Punch hole by clearing alpha where hole is opaque
    base = img.copy()
    for y in range(size):
        for x in range(size):
            if hole.getpixel((x, y))[3] > 0:
                base.putpixel((x, y), (0, 0, 0, 0))
    img = base
    d = ImageDraw.Draw(img)

    # Re-draw inner rim for definition
    d.ellipse(inner, outline=stroke, width=max(1, size // 16))
    d.ellipse(inner, outline=fill, width=max(1, size // 20))

    # Top bar motif
    bw = max(6, size // 2)
    bh = max(3, size // 6)
    bx0 = (size - bw) // 2
    by0 = pad
    d.rounded_rectangle([bx0 - 1, by0 - 1, bx0 + bw + 1, by0 + bh + 1], radius=bh // 2 + 1, fill=stroke)
    d.rounded_rectangle([bx0, by0, bx0 + bw, by0 + bh], radius=bh // 2, fill=fill)

    # Crack ticks
    cx = size // 2
    cy = (ring_top + size - pad) // 2
    for dx, dy in [(-size // 5, -size // 8), (size // 6, size // 10)]:
        d.line([(cx + dx, cy + dy), (cx + dx + size // 10, cy + dy + size // 7)], fill=stroke, width=max(1, size // 16))

    return img


def main() -> None:
    for_dark_taskbar = draw_ring(64, fill=(245, 250, 252, 255), stroke=(12, 18, 24, 255))
    for_light_taskbar = draw_ring(64, fill=(24, 32, 42, 255), stroke=(255, 255, 255, 255))
    accent = draw_ring(64, fill=(77, 163, 209, 255), stroke=(12, 18, 24, 255))

    assets = {
        "tray-for-dark-taskbar.png": for_dark_taskbar,
        "tray-for-light-taskbar.png": for_light_taskbar,
        "tray-accent.png": accent,
    }
    for name, image in assets.items():
        image.save(OUT / name, optimize=True)
        image.resize((32, 32), Image.Resampling.LANCZOS).save(
            OUT / name.replace(".png", "-32.png"),
            optimize=True,
        )
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
