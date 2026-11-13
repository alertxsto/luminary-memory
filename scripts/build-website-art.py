"""Build the website's three-tone lunar garden images from credited source art.

Uses Pillow and NumPy from the project environment. No network access:
    python scripts/build-website-art.py --fern-source path/to/Haeckel_Filicinae_92.webp

The photographic moon is already tracked in website/assets/full-moon.jpg.
Source credits and the derivative artwork license live in assets/art/NOTICE.txt.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "website" / "assets" / "art"
BAYER = np.array(
    [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
    dtype=np.float32,
) / 16 - 0.5
PALETTES = {
    "dark": [(11, 16, 24), (37, 61, 94), (137, 177, 232)],
    "light": [(246, 248, 252), (171, 194, 225), (45, 84, 142)],
}
# Logical sizes become two-pixel print grains in the exported raster images.
SCENES = {
    "hero": ((480, 320), (0.64, 0.41), 0.77, 0.43, (0.5, 0.65)),
    "docs": ((540, 150), (0.79, 0.38), 1.25, 0.12, (0.5, 0.65)),
    "footer": ((720, 300), (0.72, 0.39), 0.88, 0.18, (0.5, 0.72)),
    "core": ((320, 200), (0.65, 0.43), 0.9, 0.42, (0.2, 0.6)),
    "recall": ((320, 200), (0.57, 0.45), 1.3, 0.6, (0.7, 0.6)),
    "store": ((320, 200), (0.64, 0.43), 0.88, 0.25, (0.5, 0.85)),
    "closing": ((600, 180), (0.77, 0.4), 1.15, 0.18, (0.4, 0.7)),
}


def _load_moon() -> Image.Image:
    with Image.open(ROOT / "website" / "assets" / "full-moon.jpg") as source:
        moon = source.convert("L")
    bounds = moon.point(lambda value: 255 if value > 18 else 0).getbbox()
    if bounds is None:
        raise ValueError("Moon source contains no visible lunar surface")
    return ImageOps.autocontrast(moon.crop(bounds), cutoff=1)


def _compose(
    moon: Image.Image,
    forest: Image.Image,
    size: tuple[int, int],
    position: tuple[float, float],
    diameter_ratio: float,
    foreground_start: float,
    forest_center: tuple[float, float],
) -> np.ndarray:
    width, height = size
    foliage = ImageOps.fit(forest, size, Image.Resampling.LANCZOS, centering=forest_center)
    foliage = ImageOps.autocontrast(foliage, cutoff=2).filter(
        ImageFilter.UnsharpMask(radius=1, percent=100, threshold=3)
    )
    leaves = np.asarray(foliage, dtype=np.float32) / 255
    diameter = int(height * diameter_ratio)
    center_x, center_y = int(width * position[0]), int(height * position[1])
    left, top = center_x - diameter // 2, center_y - diameter // 2
    layer = Image.new("L", size)
    layer.paste(moon.resize((diameter, diameter), Image.Resampling.LANCZOS), (left, top))
    mask = Image.new("L", size)
    ImageDraw.Draw(mask).ellipse((left, top, left + diameter, top + diameter), fill=255)
    # Solid night sky: no procedural noise masquerading as photographic detail.
    night = np.where(np.asarray(mask) > 0, np.asarray(layer, dtype=np.float32) / 255, 0)
    vertical = np.arange(height, dtype=np.float32)[:, None] / height
    foreground = np.clip((vertical - foreground_start) / (1 - foreground_start), 0, 1)
    return np.clip(night * (1 - foreground) + leaves * foreground, 0, 1)


def _dither(luminance: np.ndarray, colors: list[tuple[int, int, int]]) -> Image.Image:
    height, width = luminance.shape
    threshold = np.tile(BAYER, (height // 4 + 1, width // 4 + 1))[:height, :width]
    levels = np.clip(np.floor(np.power(luminance, 1.12) * 2 + threshold + 0.5), 0, 2)
    image = Image.fromarray(levels.astype(np.uint8)).convert("P")
    palette = [channel for color in colors for channel in color]
    image.putpalette(palette + [0] * (768 - len(palette)))
    return image.resize((width * 2, height * 2), Image.Resampling.NEAREST)


def main() -> None:
    """Generate theme-specific assets without changing source photographs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fern-source", type=Path, required=True)
    args = parser.parse_args()
    if not args.fern_source.is_file():
        parser.error("--fern-source must name the credited Filicinae 92 source image")
    with Image.open(args.fern_source) as source:
        forest = source.convert("L")
    forest = forest.crop((0, int(forest.height * 0.26), forest.width, int(forest.height * 0.98)))
    moon = _load_moon()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, settings in SCENES.items():
        luminance = _compose(moon, forest, *settings)
        for theme, colors in PALETTES.items():
            path = OUTPUT / f"lunar-{name}-{theme}.png"
            image = _dither(luminance, colors)
            image.save(path, optimize=True, bits=2)
            print(f"{path.relative_to(ROOT)}: {image.width} x {image.height}")


if __name__ == "__main__":
    main()
