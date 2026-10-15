"""Crafting calculator: walks the recipe tree and adds up everything you need.

Example: Catapult Boulder -> Stone Bricks + Mortar -> Stone Off-Cuts, Wood Ash, ...
Every intermediate item becomes a step, everything without a recipe is a raw material.
"""

import math
from dataclasses import dataclass, field

from .data import GameData
from .text import key


@dataclass
class Step:
    output: str
    station: str
    crafts: int  # how many times you press "craft"
    produced: float  # crafts * recipe yield
    needed: float  # how many the plan actually uses
    ingredients: list[tuple[str, float]]  # totals for all crafts
    note: str | None = None
    other_stations: list[str] = field(default_factory=list)


@dataclass
class Plan:
    target: str
    amount: float
    steps: list[Step]  # in the order you should do them (ingredients first)
    raw: dict[str, float]  # things you have to gather / buy
    surplus: dict[str, float]  # extra items left over because recipes make batches
    cycles: list[str] = field(default_factory=list)

    @property
    def silver(self) -> float:
        return self.raw.get("Silver", 0)


def _score(data: GameData, recipe: dict, prefer_station: str | None) -> tuple:
    station = recipe["station"].lower()
    uses_silver = any(key(i["item"]) == "silver" for i in recipe["ingredients"])
    preferred = bool(prefer_station) and prefer_station.lower() in station
    # Lower is better: preferred station first, then no silver, then not a town building,
    # then the recipe with the fewest crafting steps below it.
    return (not preferred, uses_silver, station.startswith("town"), _depth(data, recipe, ()))


def _depth(data: GameData, recipe: dict, stack: tuple) -> int:
    """How many crafting levels are below this recipe (raw materials = 0)."""
    deepest = 0
    for ing in recipe["ingredients"]:
        k = key(ing["item"])
        options = data.recipes.get(k)
        if options and k not in stack and len(stack) < 12:
            deepest = max(deepest, 1 + min(_depth(data, r, stack + (k,)) for r in options))
    return deepest


def choose_recipe(data: GameData, recipes: list[dict], prefer_station: str | None = None) -> dict:
    return min(recipes, key=lambda r: _score(data, r, prefer_station))  # min() keeps sheet order on ties


def plan(data: GameData, item: str, amount: float = 1, prefer_station: str | None = None,
         keep_as_raw: set[str] | None = None) -> Plan:
    """Build a full crafting plan for `amount` of `item`.

    prefer_station: use recipes at this station when there is a choice (e.g. "Town Workshop").
    keep_as_raw: item names you already have and do not want broken down further.
    """
    keep = {key(k) for k in (keep_as_raw or set())}
    chosen: dict[str, dict] = {}
    order: list[str] = []  # post-order: ingredients before the things that use them
    cycles: list[str] = []
    names: dict[str, str] = {}

    def visit(k: str, stack: tuple):
        if k in chosen or k in stack:
            if k in stack:
                cycles.append(names.get(k, k))
            return
        recipes = data.recipes.get(k)
        # Items you can pick up in the world (e.g. Iron Ore Fragment from a pile) count as raw
        # materials even if they can also be made (smashing Iron Ore) - unless asked for directly.
        if not recipes or (stack and (k in keep or k in data.sources)):
            return
        rec = choose_recipe(data, recipes, prefer_station)
        chosen[k] = rec
        names[k] = rec["output"]
        for ing in rec["ingredients"]:
            names.setdefault(key(ing["item"]), ing["item"])
            visit(key(ing["item"]), stack + (k,))
        order.append(k)

    target_key = key(item)
    visit(target_key, ())

    demand: dict[str, float] = {target_key: amount}
    steps: dict[str, Step] = {}
    raw: dict[str, float] = {}
    surplus: dict[str, float] = {}

    # Parents before children so every demand is final before we split it into ingredients.
    for k in reversed(order):
        rec = chosen[k]
        need = demand.get(k, 0)
        if need <= 0:
            continue
        crafts = math.ceil(round(need / rec["amount"], 6))
        produced = crafts * rec["amount"]
        if produced > need:
            surplus[rec["output"]] = produced - need
        totals = []
        for ing in rec["ingredients"]:
            ik = key(ing["item"])
            total = crafts * ing["amount"]
            demand[ik] = demand.get(ik, 0) + total
            totals.append((ing["item"], total))
        others = sorted({r["station"] for r in data.recipes[k] if r["station"] != rec["station"]})
        steps[k] = Step(rec["output"], rec["station"], crafts, produced, need, totals,
                        rec.get("note"), others)

    for k, qty in demand.items():
        if k not in chosen:
            raw[names.get(k, k)] = qty

    return Plan(
        target=names.get(target_key, item),
        amount=amount,
        steps=[steps[k] for k in order if k in steps],
        raw=dict(sorted(raw.items(), key=lambda kv: kv[0].lower())),
        surplus=surplus,
        cycles=cycles,
    )
