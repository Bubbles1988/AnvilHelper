"""Combat math: armour mitigation, effective health and hits-to-kill.

Formulas follow the notes in the spreadsheet / wiki:
* Damage mitigation stacks multiplicatively:
  total = 1 - (1 - a*q) * (1 - b*q) * (1 - c*q), q = quality multiplier.
* Quality levels add 10% / 20% / 30% on top of the base mitigation.
* Stability and temperature mitigation simply add up and ignore quality.
* Clothing (garment / bottoms) is worn under armour and counts as extra pieces.
* Piercing damage is doubled against anyone wearing armour with Piercing Vulnerability (Heavy).
* Weapon damage is multiplied by the damage-type table (Infantry, NPC, ...).
"""

from dataclasses import dataclass, field

from .text import ceil_hits

PLAYER_HEALTH = 100.0
QUALITY_MULTIPLIER = {0: 1.0, 1: 1.1, 2: 1.2, 3: 1.3}
QUALITY_NAMES = {0: "Base", 1: "Quality 1 (+10%)", 2: "Quality 2 (+20%)", 3: "Quality 3 (+30%)"}

EFFECT_EMOJI = {
    "Very Effective": "🟢",
    "Effective": "🟩",
    "Reduced": "🟨",
    "Very Reduced": "🟧",
    "No Damage": "🟥",
}


def effectiveness(multiplier: float) -> str:
    if multiplier > 1:
        return "Very Effective"
    if multiplier == 1:
        return "Effective"
    if multiplier >= 0.5:
        return "Reduced"
    if multiplier > 0:
        return "Very Reduced"
    return "No Damage"


ARMOUR_SLOTS = ("head", "chest", "legs", "garment", "bottoms")
SLOT_LABELS = {"head": "Helmet", "chest": "Chest", "legs": "Legs", "garment": "Garment", "bottoms": "Bottoms"}
# Piercing damage against armour with Piercing Vulnerability (Heavy armour)
PIERCING_VULNERABILITY_MULTIPLIER = 2.0


@dataclass
class Loadout:
    """Armour pieces (head/chest/legs), clothing worn underneath (garment/bottoms) and a shield.

    `quality` is the default quality for every piece, `qualities` overrides it per slot,
    e.g. {"chest": 3} for a quality 3 chest with base helmet and legs.
    """

    head: dict | None = None
    chest: dict | None = None
    legs: dict | None = None
    garment: dict | None = None
    bottoms: dict | None = None
    shield: dict | None = None
    quality: int = 0
    qualities: dict[str, int] = field(default_factory=dict)

    def worn(self) -> list[tuple[str, dict]]:
        return [(slot, getattr(self, slot)) for slot in ARMOUR_SLOTS if getattr(self, slot)]

    @property
    def pieces(self) -> list[dict]:
        return [piece for _, piece in self.worn()]

    def quality_of(self, slot: str) -> int:
        return self.qualities.get(slot, self.quality)

    @staticmethod
    def piece_mitigation(piece: dict, quality: int = 0) -> float:
        return min(piece["damage_mitigation"] * QUALITY_MULTIPLIER.get(quality, 1.0), 0.99)

    def damage_mitigation(self) -> float:
        remaining = 1.0
        for slot, piece in self.worn():
            remaining *= 1 - self.piece_mitigation(piece, self.quality_of(slot))
        return 1 - remaining

    def damage_taken_multiplier(self, damage_type: str | None) -> float:
        """Extra damage the wearer takes: Piercing x2 when wearing Heavy armour."""
        if damage_type == "Piercing" and self.has("piercing_vulnerability"):
            return PIERCING_VULNERABILITY_MULTIPLIER
        return 1.0

    def stability_mitigation(self) -> float:
        return sum(p["stability_mitigation"] for p in self.pieces)

    def temperature_mitigation(self) -> float:
        return sum(p["temperature_mitigation"] for p in self.pieces)

    def effective_health(self, damage_type: str | None = None) -> float:
        return PLAYER_HEALTH / ((1 - self.damage_mitigation()) * self.damage_taken_multiplier(damage_type))

    def has(self, flag: str) -> bool:
        return any(p.get(flag) for p in self.pieces)

    @property
    def heavy(self) -> bool:
        return self.has("heavy_armour")

    def requirements(self) -> list[str]:
        reqs = [f"{p['name']}: {p['requirements']}" for p in self.pieces if p.get("requirements")]
        if self.shield and self.shield.get("requirements"):
            reqs.append(f"{self.shield['name']}: {self.shield['requirements']}")
        return reqs


def armour_set(data, prefix: str) -> Loadout:
    """Full set like 'Heavy' -> Heavy Helmet + Heavy Chest + Heavy Leg."""
    return Loadout(head=data.armour.get(f"{prefix} helmet"), chest=data.armour.get(f"{prefix} chest"),
                   legs=data.armour.get(f"{prefix} leg"))


def blocked_by_heavy_armour(weapon: dict) -> bool:
    """Bows, spears and javelins cannot be armed in Reinforced or Heavy armour."""
    req = (weapon.get("requirements") or "").lower()
    return "cannot be" in req and ("heavy armour" in req or "reinforced armour" in req)


def multiplier(table: dict, damage_type: str, target: str) -> float:
    return table["multipliers"].get(damage_type, {}).get(target, 1.0)


@dataclass
class HitResult:
    damage_min: float  # damage per hit after multipliers and armour
    damage_max: float
    hits_best: int | None  # with max damage rolls
    hits_worst: int | None  # with min damage rolls

    @property
    def text(self) -> str:
        if self.hits_best is None:
            return "can't hurt it"
        if self.hits_best == self.hits_worst:
            return f"{self.hits_best} hit{'s' if self.hits_best != 1 else ''}"
        return f"{self.hits_best}-{self.hits_worst} hits"


def hits(health: float, dmg_min: float, dmg_max: float) -> HitResult:
    return HitResult(dmg_min, dmg_max, ceil_hits(health, dmg_max), ceil_hits(health, dmg_min))


def attack_vs_player(attack: dict, loadout: Loadout, table: dict) -> HitResult:
    dmg = attack["damage"]
    factor = (multiplier(table, dmg["type"], "Infantry") * loadout.damage_taken_multiplier(dmg["type"])
              * (1 - loadout.damage_mitigation()))
    return hits(PLAYER_HEALTH, dmg["min"] * factor, dmg["max"] * factor)


def attack_vs_npc(attack: dict, npc: dict, table: dict) -> HitResult:
    dmg = attack["damage"]
    factor = multiplier(table, dmg["type"], "NPC")
    return hits(npc["health"], dmg["min"] * factor, dmg["max"] * factor)


def attack_vs_health(attack: dict, health: float, target: str, table: dict) -> HitResult:
    dmg = attack["damage"]
    factor = multiplier(table, dmg["type"], target)
    return hits(health, dmg["min"] * factor, dmg["max"] * factor)


def npc_vs_player(npc: dict, loadout: Loadout, table: dict) -> HitResult:
    """How many NPC hits a player survives. NPC damage uses the damage-type table vs Infantry
    (Reaver slashing x0.75; Animal and Missile x1) and is then reduced by armour."""
    dtype = npc.get("damage_type")
    factor = (multiplier(table, dtype, "Infantry") * loadout.damage_taken_multiplier(dtype)
              * (1 - loadout.damage_mitigation()))
    return hits(PLAYER_HEALTH, npc["damage_min"] * factor, npc["damage_max"] * factor)


def strengths(damage_type: str, table: dict) -> tuple[list[str], list[str], list[str]]:
    """Split the target list into (good against, ok against, bad against)."""
    good, ok, bad = [], [], []
    for target, mult in table["multipliers"].get(damage_type, {}).items():
        label = f"{target} ×{mult:g}"
        if mult > 1 or (mult == 1 and target != "Infantry"):
            good.append(label)
        elif mult >= 0.5 or target == "Infantry" and mult > 0:
            ok.append(label)
        else:
            bad.append(label)
    return good, ok, bad


DAMAGE_TYPE_TIPS = {
    "Piercing": "Deals ×2 damage to players wearing Heavy armour (piercing vulnerability).",
    "Impaling": "Anti-cavalry: ×3 damage to mounted units and ×1.5 to NPCs.",
    "Missile": "Heavy Chest armour can deflect arrows and javelins; Heavy/Reinforced chests are not staggered by them.",
    "Siege": "Made for structures and vehicles (×5 vs vehicles), weak against people.",
    "Cleaving": "Hurts light structures and vehicles as well as people.",
    "Burning": "Sets light structures on fire; full damage to people and NPCs.",
    "Crushing": "Good for stability (stagger) damage.",
}
