"""Combat math: armour mitigation, effective health and hits-to-kill.

Formulas follow the notes in the spreadsheet / wiki:
* Damage mitigation stacks multiplicatively:
  total = 1 - (1 - a*q) * (1 - b*q) * (1 - c*q), q = quality multiplier.
* Quality levels add 10% / 20% / 30% on top of the base mitigation.
* Stability and temperature mitigation simply add up and ignore quality.
* Piercing vulnerability halves a piece's mitigation against Piercing damage.
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


@dataclass
class Loadout:
    head: dict | None = None
    chest: dict | None = None
    legs: dict | None = None
    shield: dict | None = None
    quality: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def pieces(self) -> list[dict]:
        return [p for p in (self.head, self.chest, self.legs) if p]

    def piece_mitigation(self, piece: dict, damage_type: str | None = None) -> float:
        value = piece["damage_mitigation"] * QUALITY_MULTIPLIER.get(self.quality, 1.0)
        if damage_type == "Piercing" and piece.get("piercing_vulnerability"):
            value /= 2
        return min(value, 0.99)

    def damage_mitigation(self, damage_type: str | None = None) -> float:
        remaining = 1.0
        for piece in self.pieces:
            remaining *= 1 - self.piece_mitigation(piece, damage_type)
        return 1 - remaining

    def stability_mitigation(self) -> float:
        return sum(p["stability_mitigation"] for p in self.pieces)

    def temperature_mitigation(self) -> float:
        return sum(p["temperature_mitigation"] for p in self.pieces)

    def effective_health(self, damage_type: str | None = None) -> float:
        return PLAYER_HEALTH / (1 - self.damage_mitigation(damage_type))

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
    factor = multiplier(table, dmg["type"], "Infantry") * (1 - loadout.damage_mitigation(dmg["type"]))
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
    factor = multiplier(table, dtype, "Infantry") * (1 - loadout.damage_mitigation(dtype))
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
    "Piercing": "Halves the mitigation of armour with Piercing Vulnerability (Crude, Light & Reinforced armour).",
    "Impaling": "Anti-cavalry: ×3 damage to mounted units and ×1.5 to NPCs.",
    "Missile": "Heavy Chest armour can deflect arrows and javelins; Heavy/Reinforced chests are not staggered by them.",
    "Siege": "Made for structures and vehicles (×5 vs vehicles), weak against people.",
    "Cleaving": "Hurts light structures and vehicles as well as people.",
    "Burning": "Sets light structures on fire; full damage to people and NPCs.",
    "Crushing": "Good for stability (stagger) damage.",
}
