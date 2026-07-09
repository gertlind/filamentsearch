from flask import Flask, render_template, request
from pathlib import Path
import sqlite3
import json
import math

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
SQLITE_DB = BASE_DIR / "optd.db"


def normalize_hex(value):
    if not value:
        return ""

    value = str(value).strip().lower()

    if not value.startswith("#"):
        value = "#" + value

    if len(value) == 7:
        value += "ff"

    return value


def hex_to_rgb(value):
    value = normalize_hex(value)

    if not value or len(value) < 7:
        return None

    value = value.lstrip("#")

    try:
        return (
            int(value[0:2], 16),
            int(value[2:4], 16),
            int(value[4:6], 16),
        )
    except ValueError:
        return None


def srgb_to_linear(value):
    value = value / 255.0

    if value <= 0.04045:
        return value / 12.92

    return ((value + 0.055) / 1.055) ** 2.4


def rgb_to_xyz(rgb):
    r, g, b = rgb

    r = srgb_to_linear(r)
    g = srgb_to_linear(g)
    b = srgb_to_linear(b)

    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

    return x, y, z


def xyz_to_lab(xyz):
    x, y, z = xyz

    # D65 reference white
    x = x / 0.95047
    y = y / 1.00000
    z = z / 1.08883

    def f(t):
        if t > 0.008856:
            return t ** (1 / 3)
        return (7.787 * t) + (16 / 116)

    fx = f(x)
    fy = f(y)
    fz = f(z)

    l = (116 * fy) - 16
    a = 500 * (fx - fy)
    b = 200 * (fy - fz)

    return l, a, b


def hex_to_lab(value):
    rgb = hex_to_rgb(value)

    if rgb is None:
        return None

    return xyz_to_lab(rgb_to_xyz(rgb))


def ciede2000(lab1, lab2):
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2

    k_l = 1
    k_c = 1
    k_h = 1

    c1 = math.sqrt(a1 ** 2 + b1 ** 2)
    c2 = math.sqrt(a2 ** 2 + b2 ** 2)
    c_bar = (c1 + c2) / 2

    g = 0.5 * (1 - math.sqrt((c_bar ** 7) / ((c_bar ** 7) + (25 ** 7))))

    a1_prime = (1 + g) * a1
    a2_prime = (1 + g) * a2

    c1_prime = math.sqrt(a1_prime ** 2 + b1 ** 2)
    c2_prime = math.sqrt(a2_prime ** 2 + b2 ** 2)

    h1_prime = math.degrees(math.atan2(b1, a1_prime)) % 360
    h2_prime = math.degrees(math.atan2(b2, a2_prime)) % 360

    delta_l_prime = l2 - l1
    delta_c_prime = c2_prime - c1_prime

    if c1_prime * c2_prime == 0:
        delta_h_prime_angle = 0
    else:
        h_diff = h2_prime - h1_prime

        if abs(h_diff) <= 180:
            delta_h_prime_angle = h_diff
        elif h_diff > 180:
            delta_h_prime_angle = h_diff - 360
        else:
            delta_h_prime_angle = h_diff + 360

    delta_h_prime = 2 * math.sqrt(c1_prime * c2_prime) * math.sin(
        math.radians(delta_h_prime_angle / 2)
    )

    l_bar_prime = (l1 + l2) / 2
    c_bar_prime = (c1_prime + c2_prime) / 2

    if c1_prime * c2_prime == 0:
        h_bar_prime = h1_prime + h2_prime
    else:
        h_sum = h1_prime + h2_prime

        if abs(h1_prime - h2_prime) <= 180:
            h_bar_prime = h_sum / 2
        elif h_sum < 360:
            h_bar_prime = (h_sum + 360) / 2
        else:
            h_bar_prime = (h_sum - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(h_bar_prime - 30))
        + 0.24 * math.cos(math.radians(2 * h_bar_prime))
        + 0.32 * math.cos(math.radians(3 * h_bar_prime + 6))
        - 0.20 * math.cos(math.radians(4 * h_bar_prime - 63))
    )

    delta_theta = 30 * math.exp(-(((h_bar_prime - 275) / 25) ** 2))

    r_c = 2 * math.sqrt(
        (c_bar_prime ** 7) / ((c_bar_prime ** 7) + (25 ** 7))
    )

    s_l = 1 + (
        (0.015 * ((l_bar_prime - 50) ** 2))
        / math.sqrt(20 + ((l_bar_prime - 50) ** 2))
    )

    s_c = 1 + 0.045 * c_bar_prime
    s_h = 1 + 0.015 * c_bar_prime * t

    r_t = -math.sin(math.radians(2 * delta_theta)) * r_c

    delta_e = math.sqrt(
        (delta_l_prime / (k_l * s_l)) ** 2
        + (delta_c_prime / (k_c * s_c)) ** 2
        + (delta_h_prime / (k_h * s_h)) ** 2
        + r_t
        * (delta_c_prime / (k_c * s_c))
        * (delta_h_prime / (k_h * s_h))
    )

    return delta_e


def color_distance(hex1, hex2):
    lab1 = hex_to_lab(hex1)
    lab2 = hex_to_lab(hex2)

    if lab1 is None or lab2 is None:
        return None

    return ciede2000(lab1, lab2)


def db_connect():
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_database_stats():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM filaments")
    filaments = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT brand) FROM filaments WHERE brand != ''")
    brands = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT material) FROM filaments WHERE material != ''")
    materials = cur.fetchone()[0]

    conn.close()

    return {
        "brands": brands,
        "materials": materials,
        "filaments": filaments,
    }


def search_filaments(
    manufacturer="",
    country="",
    material="",
    name="",
    color=""
):
    query = """
        SELECT *
        FROM filaments
        WHERE 1=1
    """

    params = []

    if manufacturer:
        query += " AND brand LIKE ?"
        params.append(f"%{manufacturer}%")

    if country:
        query += " AND country LIKE ?"
        params.append(f"%{country.upper()}%")

    if material:
        query += " AND material LIKE ?"
        params.append(f"%{material}%")

    if name:
        query += " AND name LIKE ?"
        params.append(f"%{name}%")

    if color:
        query += " AND color = ?"
        params.append(normalize_hex(color))

    query += " ORDER BY brand, name"

    conn = db_connect()
    cur = conn.cursor()
    cur.execute(query, params)

    rows = cur.fetchall()
    results = [dict(row) for row in rows]

    if results or not color:
        conn.close()
        return results

    # No exact color match was found.
    # Keep all other filters and return the closest colors by CIEDE2000 / Delta E.
    closest_query = """
        SELECT *
        FROM filaments
        WHERE color != ''
    """

    closest_params = []

    if manufacturer:
        closest_query += " AND brand LIKE ?"
        closest_params.append(f"%{manufacturer}%")

    if country:
        closest_query += " AND country LIKE ?"
        closest_params.append(f"%{country.upper()}%")

    if material:
        closest_query += " AND material LIKE ?"
        closest_params.append(f"%{material}%")

    if name:
        closest_query += " AND name LIKE ?"
        closest_params.append(f"%{name}%")

    cur.execute(closest_query, closest_params)
    rows = cur.fetchall()
    conn.close()

    closest = []

    for row in rows:
        item = dict(row)
        distance = color_distance(color, item.get("color", ""))

        if distance is not None:
            item["distance"] = round(distance, 1)
            closest.append(item)

    closest.sort(key=lambda x: x["distance"])

    return closest[:10]


@app.route("/", methods=["GET"])
def index():
    manufacturer = request.args.get("manufacturer", "").strip()
    country = request.args.get("country", "").strip()
    material = request.args.get("material", "").strip()
    name = request.args.get("name", "").strip()
    color = request.args.get("color", "").strip()

    results = []

    if manufacturer or country or material or name or color:
        results = search_filaments(
            manufacturer=manufacturer,
            country=country,
            material=material,
            name=name,
            color=color
        )

    stats = get_database_stats()

    return render_template(
        "index.html",
        results=results,
        manufacturer=manufacturer,
        country=country,
        material=material,
        name=name,
        color=color,
        search_color=normalize_hex(color),
        stats=stats
    )


@app.route("/properties/<int:filament_id>")
def properties_page(filament_id):
    return_query = request.args.get("return_query", "")

    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM filaments WHERE id = ?",
        (filament_id,)
    )

    row = cur.fetchone()
    conn.close()

    if not row:
        return "Filament hittades inte", 404

    item = dict(row)

    properties = json.loads(item.get("properties_json") or "{}")

    if not properties:
        return "Inga properties finns för detta filament", 404

    return render_template(
        "properties.html",
        brand=item.get("brand", ""),
        name=item.get("name", ""),
        color=item.get("color", ""),
        photo=item.get("photo", ""),
        properties=properties,
        return_query=return_query
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
