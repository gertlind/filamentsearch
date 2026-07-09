#!/usr/bin/env python3
import sys
import math
import yaml
from pathlib import Path
from PIL import Image

# DB_PATH = Path(__file__).parent / "data" / "materials"
DB_PATH = Path(__file__).parent / "openprinttag-database" / "data" / "materials"
IGNORE_WHITE_BACKGROUND = True
WHITE_LIMIT = 245


def rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def hex_to_rgb(hex_color):
    hex_color = hex_color.strip().lstrip("#")
    if len(hex_color) == 8:
        hex_color = hex_color[:6]
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def srgb_to_linear(c):
    c = c / 255
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb):
    r, g, b = [srgb_to_linear(c) for c in rgb]

    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505

    x /= 0.95047
    y /= 1.00000
    z /= 1.08883

    def f(t):
        if t > 0.008856:
            return t ** (1 / 3)
        return (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)

    return (
        (116 * fy) - 16,
        500 * (fx - fy),
        200 * (fy - fz),
    )


def ciede2000(lab1, lab2):
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2

    kL = kC = kH = 1

    C1 = math.sqrt(a1 * a1 + b1 * b1)
    C2 = math.sqrt(a2 * a2 + b2 * b2)
    C_avg = (C1 + C2) / 2

    G = 0.5 * (1 - math.sqrt((C_avg ** 7) / ((C_avg ** 7) + (25 ** 7))))

    a1p = (1 + G) * a1
    a2p = (1 + G) * a2

    C1p = math.sqrt(a1p * a1p + b1 * b1)
    C2p = math.sqrt(a2p * a2p + b2 * b2)

    def hp(a, b):
        if a == 0 and b == 0:
            return 0
        angle = math.degrees(math.atan2(b, a))
        return angle + 360 if angle < 0 else angle

    h1p = hp(a1p, b1)
    h2p = hp(a2p, b2)

    dLp = L2 - L1
    dCp = C2p - C1p

    if C1p * C2p == 0:
        dhp = 0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360

    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2))

    Lp_avg = (L1 + L2) / 2
    Cp_avg = (C1p + C2p) / 2

    if C1p * C2p == 0:
        hp_avg = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp_avg = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hp_avg = (h1p + h2p + 360) / 2
    else:
        hp_avg = (h1p + h2p - 360) / 2

    T = (
        1
        - 0.17 * math.cos(math.radians(hp_avg - 30))
        + 0.24 * math.cos(math.radians(2 * hp_avg))
        + 0.32 * math.cos(math.radians(3 * hp_avg + 6))
        - 0.20 * math.cos(math.radians(4 * hp_avg - 63))
    )

    d_ro = 30 * math.exp(-(((hp_avg - 275) / 25) ** 2))
    Rc = 2 * math.sqrt((Cp_avg ** 7) / ((Cp_avg ** 7) + (25 ** 7)))

    Sl = 1 + ((0.015 * ((Lp_avg - 50) ** 2)) / math.sqrt(20 + ((Lp_avg - 50) ** 2)))
    Sc = 1 + 0.045 * Cp_avg
    Sh = 1 + 0.015 * Cp_avg * T

    Rt = -math.sin(math.radians(2 * d_ro)) * Rc

    return math.sqrt(
        (dLp / (kL * Sl)) ** 2
        + (dCp / (kC * Sc)) ** 2
        + (dHp / (kH * Sh)) ** 2
        + Rt * (dCp / (kC * Sc)) * (dHp / (kH * Sh))
    )


def get_pixels(img):
    try:
        return list(img.get_flattened_data())
    except AttributeError:
        return list(img.getdata())


def average_image_color(image_path):
    img = Image.open(image_path).convert("RGBA")
    img = img.resize((100, 100))

    pixels = get_pixels(img)

    filtered = []

    for r, g, b, a in pixels:
        if a == 0:
            continue

        if IGNORE_WHITE_BACKGROUND and r >= WHITE_LIMIT and g >= WHITE_LIMIT and b >= WHITE_LIMIT:
            continue

        filtered.append((r, g, b))

    if not filtered:
        raise ValueError("Hittade inga pixlar att analysera efter filtrering.")

    avg_rgb = tuple(
        round(sum(channel) / len(filtered))
        for channel in zip(*filtered)
    )

    return avg_rgb, len(filtered)


def main():
    if len(sys.argv) < 2:
        print("Usage: python color_average_ciede2000.py <bild.png> [max_results]")
        sys.exit(1)

    image_path = sys.argv[1]
    max_results = int(sys.argv[2]) if len(sys.argv) >= 3 else 20

    avg_rgb, pixel_count = average_image_color(image_path)
    avg_lab = rgb_to_lab(avg_rgb)

    results = []

    for file in DB_PATH.glob("*/*.yaml"):
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            continue

        if not data:
            continue

        color_hex = data.get("primary_color", {}).get("color_rgba")
        if not color_hex:
            continue

        try:
            db_rgb = hex_to_rgb(color_hex)
            db_lab = rgb_to_lab(db_rgb)
        except Exception:
            continue

        distance = ciede2000(avg_lab, db_lab)

        results.append({
            "delta_e_2000": distance,
            "brand": data.get("brand", {}).get("slug", ""),
            "name": data.get("name", ""),
            "type": data.get("type", ""),
            "color": color_hex,
            "url": data.get("url", ""),
            "file": str(file)
        })

    results.sort(key=lambda x: x["delta_e_2000"])

    print("Image average RGB:", avg_rgb)
    print("Image average HEX:", rgb_to_hex(avg_rgb))
    print("Analyzed pixels:", pixel_count)
    print()
    print("brand,name,type,color,delta_e_2000,url")

    for r in results[:max_results]:
        print(
            f'{r["brand"]},'
            f'"{r["name"]}",'
            f'{r["type"]},'
            f'{r["color"]},'
            f'{round(r["delta_e_2000"], 2)},'
            f'{r["url"]}'
        )


if __name__ == "__main__":
    main()
