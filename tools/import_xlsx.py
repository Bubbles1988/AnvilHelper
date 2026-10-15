"""Convert the Anvil Helper spreadsheet into the JSON files the bot reads.

Usage (from the repository root):

    python tools/import_xlsx.py                      # uses data/source/Anvil_Helper.xlsx
    python tools/import_xlsx.py path/to/export.xlsx  # e.g. a fresh Google Sheets download

Keep editing the Google Sheet as before, download it as .xlsx (File > Download >
Microsoft Excel), run this script and restart the bot. Spelling fixes that should be
applied to every import live in data/manual/aliases.json.
"""

import json
import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from anvilhelper.text import clean_name  # noqa: E402

DEFAULT_SOURCE = ROOT / "data" / "source" / "Anvil_Helper.xlsx"
OUT_DIR = ROOT / "data" / "sheet"

DAMAGE_TYPE_NAMES = {
    "impale": "Impaling",
    "impaling": "Impaling",
    "crush": "Crushing",
    "crushing": "Crushing",
    "slash": "Slashing",
    "slashing": "Slashing",
    "piercing": "Piercing",
    "missile": "Missile",
    "missle": "Missile",
    "siege": "Siege",
    "burning": "Burning",
    "cleaving": "Cleaving",
    "animal": "Animal",
    "default": "Default",
}

# Armour classes missing from the class table that behave like another class.
ARMOUR_CLASS_SAME_AS = {"Crude": "Light"}

warnings: list[str] = []


def load_aliases():
    data = json.loads((ROOT / "data" / "manual" / "aliases.json").read_text(encoding="utf-8"))
    items = {clean_name(k).lower(): clean_name(v) for k, v in data["items"].items()}
    stations = {clean_name(k).lower(): clean_name(v) for k, v in data["stations"].items()}
    return items, stations


ITEM_ALIASES, STATION_ALIASES = load_aliases()


def item_name(value) -> str:
    name = clean_name(value)
    return ITEM_ALIASES.get(name.lower(), name)


def station_name(value) -> str:
    name = clean_name(value)
    return STATION_ALIASES.get(name.lower(), name)


def blank(value) -> bool:
    return value is None or clean_name(value) in ("", "-", "⚡-", "🛡️-")


def text_or_none(value):
    return None if blank(value) else clean_name(value)


def number(value):
    """Pull the first number out of a cell such as '🍴15', '⚡20', '223 Hits' or 0.36."""
    if blank(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    return float(match.group().replace(",", ".")) if match else None


def percent(value):
    """'🛡️32%' -> 0.32, '66.5%' -> 0.665, 0.25 -> 0.25"""
    if blank(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    num = number(value)
    if num is None:
        return None
    return num / 100 if "%" in str(value) else num


def seconds(value):
    """'30 sec' -> 30, '2 min' -> 120, '1m 40sec' -> 100, '20 Seconds' -> 20"""
    if blank(value):
        return None
    text = str(value).lower()
    total = 0.0
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(h|hour|hours|m|min|mins|minutes?|s|sec|secs|seconds?)\b", text):
        factor = 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
        total += float(amount) * factor
    return total or None


def stamina(value):
    """'⚡20' -> 20. Some heavy attacks were typed as 0.3 (formatted as 30%) but mean 30 stamina."""
    num = number(value)
    if num is not None and 0 < num < 1 and "⚡" not in str(value):
        num = round(num * 100)
    return num


def damage(value):
    """'Slashing 27 - 33' / 'Impale 45-55' / '150 Siege' / '20 Default' -> dict"""
    if blank(value):
        return None
    text = clean_name(value)
    words = re.findall(r"[A-Za-z]+", text)
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        return None
    dtype = None
    for word in words:
        if word.lower() in DAMAGE_TYPE_NAMES:
            dtype = DAMAGE_TYPE_NAMES[word.lower()]
            break
    if dtype is None:
        warnings.append(f"Unknown damage type in '{text}'")
    return {"type": dtype, "min": nums[0], "max": nums[1] if len(nums) > 1 else nums[0]}


def rows(ws, min_row=2):
    for row in ws.iter_rows(min_row=min_row, values_only=True):
        yield list(row)


# --------------------------------------------------------------------------- sheets


def import_foods(wb):
    foods = []
    for r in rows(wb["Foods"]):
        if not r[0] or not str(r[0]).startswith("F"):
            continue
        foods.append({
            "id": r[0],
            "name": item_name(r[1]),
            "regen": number(r[2]),
            "duration_text": text_or_none(r[3]),
            "duration_s": seconds(r[3]),
            "hunger": number(r[4]),
            "food_type": text_or_none(r[5]),
        })
    return foods


def import_armour(wb):
    ws = wb["Armour"]
    # Armour class table (K:O): which armour classes count as heavy, etc.
    classes = {}
    notes = []
    for r in rows(ws):
        label = clean_name(r[10]) if len(r) > 10 else ""
        if label and len(r) > 14 and r[11] in ("Yes", "No"):
            classes[label] = {
                "heavy_armour": r[11] == "Yes",
                "projectile_stagger_immunity": r[12] == "Yes",
                "projectile_deflection": r[13] == "Yes",
                "piercing_vulnerability": r[14] == "Yes",
            }
        elif label and label != "Armour Class":
            notes.append(label)

    pieces = []
    for r in rows(ws):
        if not r[0] or not str(r[0]).startswith("A"):
            continue
        name = item_name(r[1])
        slot = clean_name(r[5])
        prefix = name.split(" ")[0]
        kind = text_or_none(r[7])
        # The class table only describes real armour, not clothing such as "Light Garment".
        prefix = ARMOUR_CLASS_SAME_AS.get(prefix, prefix)
        class_flags = classes.get(f"{prefix} {slot}") or classes.get(prefix) if kind == "Armour" else None
        flags = class_flags or {
            "heavy_armour": False,
            "projectile_stagger_immunity": False,
            "projectile_deflection": False,
            "piercing_vulnerability": False,
        }
        pieces.append({
            "id": r[0],
            "name": name,
            "slot": slot,  # Head / Chest / Leg
            "kind": kind,  # Armour / Clothing
            "damage_mitigation": number(r[2]) or 0.0,
            "stability_mitigation": number(r[3]) or 0.0,
            "temperature_mitigation": number(r[6]) or 0.0,
            "requirements": text_or_none(r[4]),
            **flags,
        })
    return {"pieces": pieces, "notes": notes}


def import_shields(wb):
    shields, notes = [], []
    for r in rows(wb["Shields"]):
        if r[0] and str(r[0]).startswith("SH"):
            shields.append({
                "id": r[0],
                "name": item_name(r[1]),
                "durability_hits": number(r[2]),
                "stability_loss_per_hit": number(r[3]),
                "requirements": text_or_none(r[4]),
            })
        elif r[0]:
            notes.append(clean_name(r[0]))
    return {"shields": shields, "notes": notes}


def import_tools(wb):
    tools = []
    for r in rows(wb["Tool"]):
        if r[0] and str(r[0]).startswith("T"):
            tools.append({
                "id": r[0],
                "name": item_name(r[1]),
                "effectiveness": number(r[2]),
                "durability": number(r[3]),
            })
    return tools


def import_weapons(wb):
    ws = wb["Weapon"]
    weapons = []
    damage_table = {}
    targets = []
    effect_labels = []
    all_rows = list(rows(ws, min_row=1))
    for i, r in enumerate(all_rows):
        first = clean_name(r[0])
        if re.fullmatch(r"W\d+", first):
            attacks = []
            for n, start in enumerate((2, 7, 12), start=1):
                dmg = damage(r[start])
                if not dmg:
                    continue
                attacks.append({
                    "slot": n,
                    "damage": dmg,
                    "time_s": seconds(r[start + 1]),
                    "movement": text_or_none(r[start + 2]),
                    "ability": text_or_none(r[start + 3]),
                    "stamina": stamina(r[start + 4]),
                })
            weapons.append({
                "id": first,
                "name": item_name(r[1]),
                "attacks": attacks,
                "stability_loss": percent(r[17]),
                "durability": number(r[18]),
                "requirements": text_or_none(r[19]),
            })
        elif first == "Damage Type":
            targets = [clean_name(c) for c in r[1:] if c]
            for row in all_rows[i + 1:]:
                if not row[0]:
                    break
                dtype = DAMAGE_TYPE_NAMES.get(clean_name(row[0]).lower(), clean_name(row[0]))
                damage_table[dtype] = {t: float(row[j + 1]) for j, t in enumerate(targets)}
        elif first in ("Very Effective", "Effective", "Reduced", "Very Reduced", "No Damage"):
            effect_labels.append({"label": first, "range": clean_name(r[1])})
    return weapons, {"targets": targets, "multipliers": damage_table, "labels": effect_labels}


def import_vehicles(wb):
    vehicles = []
    for r in rows(wb["Vehicle"]):
        if not r[0] or not str(r[0]).startswith("V"):
            continue
        speed = text_or_none(r[4])
        vehicles.append({
            "id": r[0],
            "name": item_name(r[1]),
            "health": number(r[2]),
            "seats": number(r[3]),
            "speed": speed.replace("m&s", "m/s") if speed else None,
            "sprint_speed": text_or_none(r[5]),
            "sprint_duration": text_or_none(r[6]),
            "road_bonus": text_or_none(r[7]),
            "damage": damage(r[8]),
            "description": text_or_none(r[9]),
        })
    return vehicles


def import_npcs(wb):
    npcs = []
    for r in rows(wb["NPCs"]):
        if not r[0] or not str(r[0]).startswith("N"):
            continue
        extras = text_or_none(r[6]) or ""
        dmg_nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(r[4] or "0"))]
        if "missile" in extras.lower() and "reaver" in str(r[1]).lower():
            dtype = "Missile"
        elif "slash" in extras.lower():
            dtype = "Slashing"
        else:
            dtype = "Animal"
        npcs.append({
            "id": r[0],
            "name": item_name(r[1]),
            "health": number(r[2]),
            "behaviour": text_or_none(r[3]),
            "damage_min": dmg_nums[0] if dmg_nums else 0.0,
            "damage_max": dmg_nums[-1] if dmg_nums else 0.0,
            "damage_type": dtype,
            "harvest_hits": number(r[5]),
            "extras": extras or None,
            "health_regen": text_or_none(r[7]),
        })
    return npcs


def import_structure_names(wb):
    return [{"id": r[0], "name": item_name(r[1])} for r in rows(wb["Structure"]) if r[0] and r[1]]


RESOURCE_HEADER_KEYS = {
    "id": "id",
    "tool": "tool",
    "description": "description",
    "discription": "description",
    "size": "size",
    "spoilage duration": "spoilage",
}


def import_resources(wb):
    """ResourceOverview has several stacked tables, each starting with its own header row."""
    world, resources = [], []
    header, section = None, None
    for r in rows(wb["ResourceOverview"], min_row=1):
        if not any(r):
            header = None
            continue
        if r[1] == "ID":
            section = clean_name(r[0])
            header = [clean_name(c).lower() if c else "" for c in r]
            continue
        if header is None:
            continue
        if section == "World Resource":
            outputs = []
            for j in (4, 6, 8):
                if r[j]:
                    amount = r[j + 1]
                    outputs.append({
                        "item": item_name(r[j]),
                        "amount": clean_name(amount) if isinstance(amount, str) else number(amount),
                    })
            world.append({
                "id": r[1],
                "name": item_name(r[0]),
                "tools": [item_name(t) for t in str(r[2] or "").split(",") if t.strip()],
                "description": text_or_none(r[3]),
                "outputs": outputs,
            })
        else:
            entry = {"name": item_name(r[0]), "category": section}
            for j, col in enumerate(header[1:], start=1):
                field = RESOURCE_HEADER_KEYS.get(col)
                if field and r[j] is not None:
                    entry[field] = clean_name(r[j])
            resources.append(entry)
    return world, resources


def import_recipes(wb):
    """The Recipes sheet is several stacked tables; each one starts with a header row."""
    recipes, structures, vehicle_builds = [], [], []
    layout, section = None, None
    for r in rows(wb["Recipes"], min_row=1):
        if not any(r):
            continue
        b, c, d = (clean_name(x) if x is not None else "" for x in r[1:4])
        if b in ("Amount", "Tools", "Tool"):
            section = clean_name(r[0])
            layout = "structure" if d == "Health" else "vehicle" if b == "Tools" else "item"
            continue
        if layout is None or not r[0]:
            continue
        first_resource = 5 if layout == "structure" else 3
        ingredients = []
        for j in range(first_resource, len(r) - 1, 2):
            if r[j] and not blank(r[j]):
                amount = number(r[j + 1])
                if amount is None:
                    warnings.append(f"Recipes: '{r[0]}' has {r[j]} without an amount")
                    continue
                ingredients.append({"item": item_name(r[j]), "amount": amount})
        name = item_name(r[0])
        if layout == "item":
            recipes.append({
                "output": name,
                "amount": number(r[1]) or 1,
                "station": station_name(r[2]),
                "ingredients": ingredients,
                "section": section,
            })
        elif layout == "vehicle":
            vehicle_builds.append({
                "output": name,
                "amount": 1,
                "station": f"Build site ({clean_name(r[2])})",
                "tool": clean_name(r[1]),
                "location": clean_name(r[2]),
                "ingredients": ingredients,
                "section": section,
            })
        else:
            structures.append({
                "name": name,
                "tools": [item_name(t) for t in str(r[1] or "").split(",") if t.strip() and clean_name(t) != "None"],
                "location": text_or_none(r[2]),
                "health": number(r[3]),
                "description": text_or_none(r[4]),
                "ingredients": ingredients,
            })

    # Same recipe listed twice (e.g. Iron Knife under both Weapon and Tools): keep one.
    seen, unique = set(), []
    for rec in recipes:
        sig = (rec["output"].lower(), rec["station"].lower(),
               tuple(sorted((i["item"].lower(), i["amount"]) for i in rec["ingredients"])))
        if sig not in seen:
            seen.add(sig)
            unique.append(rec)

    # Vehicles are built at several places with identical costs: merge locations.
    merged = {}
    for v in vehicle_builds:
        entry = merged.setdefault(v["output"].lower(), {**v, "locations": []})
        entry["locations"].append(v["location"])
    vehicles = []
    for v in merged.values():
        v["station"] = "Build site (" + ", ".join(v["locations"]) + ")"
        v.pop("location")
        vehicles.append(v)
    return unique, structures, vehicles


def main():
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    wb = openpyxl.load_workbook(source, data_only=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    weapons, damage_types = import_weapons(wb)
    world, resources = import_resources(wb)
    recipes, structures, vehicle_builds = import_recipes(wb)
    out = {
        "foods": import_foods(wb),
        "armour": import_armour(wb),
        "shields": import_shields(wb),
        "tools": import_tools(wb),
        "weapons": weapons,
        "damage_types": damage_types,
        "vehicles": import_vehicles(wb),
        "npcs": import_npcs(wb),
        "structure_list": import_structure_names(wb),
        "structures": structures,
        "world_resources": world,
        "resources": resources,
        "recipes": recipes + vehicle_builds,
    }
    for name, payload in out.items():
        path = OUT_DIR / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        count = len(payload) if isinstance(payload, list) else ""
        print(f"wrote {path.relative_to(ROOT)} {count}")
    for w in warnings:
        print("WARNING:", w)


if __name__ == "__main__":
    # Windows consoles are not UTF-8 by default; don't crash on emoji / special letters.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
