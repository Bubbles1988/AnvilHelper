"""Loads the JSON game data and answers "find me the thing called X" questions."""

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

from .text import clean_name, key

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Category id -> label shown to players
CATEGORIES = {
    "weapon": "Weapon",
    "armour": "Armour",
    "shield": "Shield",
    "tool": "Tool",
    "food": "Food",
    "npc": "Animal / NPC",
    "vehicle": "Vehicle",
    "structure": "Structure",
    "resource": "Resource",
    "world_resource": "Gathering spot",
    "item": "Item",
}


@dataclass
class Entry:
    category: str
    name: str
    data: dict

    @property
    def label(self) -> str:
        return CATEGORIES.get(self.category, self.category.title())


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class GameData:
    def __init__(self, data_dir: Path = DATA_DIR):
        sheet = data_dir / "sheet"
        manual = data_dir / "manual"

        aliases = _load(manual / "aliases.json")
        self.aliases = {key(k): clean_name(v) for k, v in aliases["items"].items()}
        images = _load(manual / "images.json")
        self.image_overrides = {key(k): v for k, v in images.get("images", {}).items()}
        self.wiki_titles = {key(k): v for k, v in images.get("wiki_titles", {}).items()}
        trophies = _load(manual / "trophies.json")["trophies"]
        self.trophies = {key(k): v for k, v in trophies.items()}

        self.damage_types = _load(sheet / "damage_types.json")
        armour = _load(sheet / "armour.json")
        shields = _load(sheet / "shields.json")
        self.armour_notes = armour["notes"]
        self.shield_notes = shields["notes"]

        self.weapons = {key(w["name"]): w for w in _load(sheet / "weapons.json")}
        self.armour = {key(a["name"]): a for a in armour["pieces"]}
        self.shields = {key(s["name"]): s for s in shields["shields"]}
        self.tools = {key(t["name"]): t for t in _load(sheet / "tools.json")}
        self.foods = {key(f["name"]): f for f in _load(sheet / "foods.json")}
        self.npcs = {key(n["name"]): n for n in _load(sheet / "npcs.json")}
        self.vehicles = {key(v["name"]): v for v in _load(sheet / "vehicles.json")}
        self.structures = {key(s["name"]): s for s in _load(sheet / "structures.json")}
        for s in _load(sheet / "structure_list.json"):
            self.structures.setdefault(key(s["name"]), {"name": s["name"], "ingredients": []})
        self.world_resources = {key(w["name"]): w for w in _load(sheet / "world_resources.json")}
        self.resources = {key(r["name"]): r for r in _load(sheet / "resources.json")}

        # Recipes: output -> list of ways to make it
        self.recipes: dict[str, list[dict]] = {}
        extra = _load(manual / "extra_recipes.json")["recipes"]
        for rec in _load(sheet / "recipes.json") + extra:
            self.recipes.setdefault(key(rec["output"]), []).append(rec)
        # Structures are "crafted" by building them; let the calculator use that too.
        for s in self.structures.values():
            if s["ingredients"] and key(s["name"]) not in self.recipes:
                tools = " / ".join(s.get("tools") or []) or "Hands"
                where = s.get("location") or "anywhere"
                self.recipes[key(s["name"])] = [{
                    "output": s["name"],
                    "amount": 1,
                    "station": f"Build ({tools}) - {where}",
                    "ingredients": s["ingredients"],
                    "section": "Structure",
                }]

        # Reverse lookups
        self.used_in: dict[str, list[dict]] = {}
        for recs in self.recipes.values():
            for rec in recs:
                for ing in rec["ingredients"]:
                    users = self.used_in.setdefault(key(ing["item"]), [])
                    if all(u["output"] != rec["output"] for u in users):
                        users.append(rec)
        self.sources: dict[str, list[dict]] = {}
        for w in self.world_resources.values():
            for out in w["outputs"]:
                self.sources.setdefault(key(out["item"]), []).append(w)

        self._build_index()

    # ------------------------------------------------------------------ index

    def _build_index(self):
        self.index: dict[str, list[Entry]] = {}

        def add(category, table):
            for k, value in table.items():
                self.index.setdefault(k, []).append(Entry(category, value["name"], value))

        add("weapon", self.weapons)
        add("armour", self.armour)
        add("shield", self.shields)
        add("food", self.foods)
        add("npc", self.npcs)
        add("vehicle", self.vehicles)
        add("tool", self.tools)
        add("structure", self.structures)
        add("resource", self.resources)
        add("world_resource", self.world_resources)
        # Anything that can be crafted but has no own sheet row (e.g. blades)
        for k, recs in self.recipes.items():
            if k not in self.index:
                self.index[k] = [Entry("item", recs[0]["output"], {"name": recs[0]["output"]})]
        for k, recs in self.sources.items():
            if k not in self.index:
                name = next(o["item"] for o in recs[0]["outputs"] if key(o["item"]) == k)
                self.index[k] = [Entry("item", name, {"name": name})]

    def names(self, categories=None) -> list[str]:
        out = []
        for entries in self.index.values():
            for e in entries:
                if categories is None or e.category in categories:
                    out.append(e.name)
                    break
        return sorted(set(out), key=str.lower)

    def find(self, query: str, categories=None) -> Entry | None:
        """Exact name, alias, then fuzzy match. Returns None when nothing is close."""
        k = key(query)
        if not k:
            return None
        k = key(self.aliases.get(k, k))
        entries = self._filter(self.index.get(k, []), categories)
        if entries:
            return entries[0]
        candidates = self.search(query, categories, limit=1)
        if candidates:
            return self._filter(self.index[key(candidates[0])], categories)[0]
        return None

    def find_all(self, query: str) -> list[Entry]:
        entry = self.find(query)
        return self.index.get(key(entry.name), []) if entry else []

    def search(self, query: str, categories=None, limit: int = 25) -> list[str]:
        """Names for autocomplete: starts-with, then contains, then typo-tolerant matches."""
        names = self.names(categories)
        q = key(query)
        if not q:
            return names[:limit]
        if q in self.aliases:
            target = self.aliases[q]
            if target in names:
                return [target]
        starts = [n for n in names if n.lower().startswith(q)]
        words = [n for n in names if n not in starts and any(w.startswith(q) for w in n.lower().split())]
        contains = [n for n in names if q in n.lower() and n not in starts and n not in words]
        result = starts + words + contains
        if len(result) < limit:
            lowered = {n.lower(): n for n in names}
            close = difflib.get_close_matches(q, list(lowered), n=limit, cutoff=0.6)
            result += [lowered[c] for c in close if lowered[c] not in result]
        return result[:limit]

    @staticmethod
    def _filter(entries, categories):
        if categories is None:
            return list(entries)
        return [e for e in entries if e.category in categories]

    # ------------------------------------------------------------------ helpers

    def armour_for_slot(self, slot: str) -> list[str]:
        return [a["name"] for a in self.armour.values() if a["slot"].lower() == slot.lower()]

    def stations(self) -> list[str]:
        return sorted({r["station"] for recs in self.recipes.values() for r in recs
                       if not r.get("section") == "Structure"}, key=str.lower)

    def wiki_url(self, name: str) -> str:
        title = self.wiki_titles.get(key(name), name)
        return "https://anvilempires.wiki.gg/wiki/" + title.replace(" ", "_")
