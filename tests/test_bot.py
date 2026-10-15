import pytest

from anvilhelper import combat, crafting, embeds
from anvilhelper.data import GameData


@pytest.fixture(scope="module")
def data():
    return GameData()


# ------------------------------------------------------------------ lookup

def test_find_exact_alias_and_typo(data):
    assert data.find("Iron Longsword").name == "Iron Longsword"
    assert data.find("long bow").name == "Longbow"  # alias from the recipe sheet
    assert data.find("iron longswrod", {"weapon"}).name == "Iron Longsword"  # typo
    assert data.find("Mánadýr").name == "Manadyr"
    assert data.find("definitely not an item xyz") is None


def test_recipe_names_link_to_items(data):
    # Every recipe ingredient should be something the bot knows (except known gaps).
    known_gaps = {"fish"}
    for recs in data.recipes.values():
        for rec in recs:
            for ing in rec["ingredients"]:
                k = ing["item"].lower()
                assert k in data.index or k in known_gaps, f"{rec['output']} uses unknown {ing['item']}"


# ------------------------------------------------------------------ combat

def test_mitigation_formula_matches_spreadsheet(data):
    lo = combat.armour_set(data, "reinforced")
    expected = 1 - (1 - 0.13) * (1 - 0.58) * (1 - 0.08)
    assert lo.damage_mitigation() == pytest.approx(expected)
    assert lo.effective_health() == pytest.approx(100 / (1 - expected))
    # Reinforced armour has no piercing vulnerability
    assert lo.effective_health("Piercing") == pytest.approx(lo.effective_health())
    assert lo.stability_mitigation() == pytest.approx(0.09 + 0.32 + 0.07)
    assert lo.heavy


def test_quality_adds_mitigation(data):
    chest = data.armour["heavy chest"]
    assert combat.Loadout(chest=chest, quality=3).damage_mitigation() == pytest.approx(0.64 * 1.3)


def test_quality_per_piece(data):
    lo = combat.armour_set(data, "heavy")
    lo.qualities = {"chest": 3}
    expected = 1 - (1 - 0.16) * (1 - 0.64 * 1.3) * (1 - 0.10)
    assert lo.damage_mitigation() == pytest.approx(expected)


def test_clothing_worn_under_armour(data):
    lo = combat.armour_set(data, "heavy")
    without = lo.damage_mitigation()
    lo.garment, lo.bottoms = data.armour["light garment"], data.armour["light bottoms"]
    assert lo.damage_mitigation() == pytest.approx(1 - (1 - without) * (1 - 0.04) * (1 - 0.02))
    assert lo.temperature_mitigation() == pytest.approx(0.75)
    assert data.armour_for_slot("garment") == ["Common Garment", "Light Garment"]
    assert "Light Garment" not in data.armour_for_slot("chest")


def test_piercing_double_damage_vs_heavy(data):
    heavy = combat.armour_set(data, "heavy")
    reinforced = combat.armour_set(data, "reinforced")
    sword = data.weapons["iron longsword"]["attacks"][0]  # 40-49 Piercing, x0.75 vs Infantry
    res = combat.attack_vs_player(sword, heavy, data.damage_types)
    assert res.damage_max == pytest.approx(49 * 0.75 * 2.0 * (1 - heavy.damage_mitigation()))
    res = combat.attack_vs_player(sword, reinforced, data.damage_types)
    assert res.damage_max == pytest.approx(49 * 0.75 * (1 - reinforced.damage_mitigation()))
    # Slashing is not doubled
    slash = data.weapons["iron short sword"]["attacks"][0]
    res = combat.attack_vs_player(slash, heavy, data.damage_types)
    assert res.damage_max == pytest.approx(38 * 0.75 * (1 - heavy.damage_mitigation()))


def test_hits_to_kill_npc(data):
    wolf = data.npcs["wolf"]  # 225 HP
    longsword = data.weapons["iron longsword"]["attacks"][0]  # 40-49 Piercing, NPC x1
    res = combat.attack_vs_npc(longsword, wolf, data.damage_types)
    assert (res.hits_best, res.hits_worst) == (5, 6)
    spear = data.weapons["iron spear"]["attacks"][0]  # Impaling x1.5 vs NPCs
    res = combat.attack_vs_npc(spear, wolf, data.damage_types)
    assert res.damage_min == pytest.approx(29 * 1.5)


def test_heavy_armour_blocks_bows(data):
    assert combat.blocked_by_heavy_armour(data.weapons["longbow"])
    assert combat.blocked_by_heavy_armour(data.weapons["flint spear"])
    assert not combat.blocked_by_heavy_armour(data.weapons["iron longsword"])


# ------------------------------------------------------------------ crafting

def test_craft_includes_intermediate_steps(data):
    plan = crafting.plan(data, "Catapult Boulder", 5)
    outputs = [s.output for s in plan.steps]
    assert outputs.index("Stone Bricks") < outputs.index("Catapult Boulder")
    assert outputs.index("Mortar") < outputs.index("Catapult Boulder")
    # Stone Bricks come in batches of 3: 5 needed -> 2 crafts -> 6 made, 1 left over
    bricks = next(s for s in plan.steps if s.output == "Stone Bricks")
    assert bricks.crafts == 2 and plan.surplus["Stone Bricks"] == 1
    assert plan.raw["Stone Off-Cuts"] == 6
    assert plan.raw["Wood Ash"] == 50


def test_craft_prefers_no_silver_and_respects_station(data):
    plan = crafting.plan(data, "Iron Short Sword", 1)
    assert "Silver" not in plan.raw
    town = crafting.plan(data, "Iron Short Sword", 1, prefer_station="Town Workshop")
    assert town.raw.get("Silver", 0) > 0


def test_craft_keep_items(data):
    plan = crafting.plan(data, "Iron Short Sword", 1, keep_as_raw={"Iron Sword Blade", "Wood Blank"})
    assert plan.raw == {"Iron Sword Blade": 1, "Wood Blank": 1}


def test_food_chain(data):
    plan = crafting.plan(data, "Lost Bread", 3)
    assert [s.output for s in plan.steps] == ["Flour", "Trencher Bread", "Lost Bread"]
    assert plan.raw["Wheat Sheaf"] == 6


# ------------------------------------------------------------------ embeds

def test_every_entry_renders_within_discord_limits(data):
    for entries in data.index.values():
        embed = embeds.entry_embed(data, entries[0], entries)
        assert len(embed) <= 6000 and len(embed.fields) <= 25, entries[0].name
        for field in embed.fields:
            assert 0 < len(field.value) <= 1024, (entries[0].name, field.name)


def test_every_craft_renders_within_discord_limits(data):
    for recs in data.recipes.values():
        embed = embeds.craft_embed(data, crafting.plan(data, recs[0]["output"], 25))
        assert len(embed) <= 6000 and len(embed.fields) <= 25, recs[0]["output"]


def test_command_tree_builds(data):
    from anvilhelper.bot import AnvilHelper

    client = AnvilHelper(data, fetch_images=False)
    names = {c.name for c in client.tree.get_commands()}
    assert {"wiki", "weapon", "loadout", "npc", "craft", "food"} <= names
    for command in client.tree.get_commands():
        command.to_dict(client.tree)  # raises if Discord would reject the definition


# ------------------------------------------------------------------ answers from the sheet owner

def test_heavy_attack_stamina_is_30(data):
    heavy = data.weapons["iron longsword"]["attacks"][2]
    assert heavy["stamina"] == 30
    assert data.weapons["iron longsword"]["attacks"][0]["stamina"] == 20


def test_armour_class_table(data):
    for name in ("crude helmet", "crude chest", "crude leg", "light chest", "reinforced chest"):
        assert not data.armour[name]["piercing_vulnerability"], name
    for name in ("heavy helmet", "heavy chest", "heavy leg"):
        assert data.armour[name]["piercing_vulnerability"], name
    assert data.armour["heavy chest"]["projectile_deflection"]
    assert data.armour["reinforced chest"]["projectile_stagger_immunity"]
    assert not data.armour["crude chest"]["heavy_armour"]


def test_reaver_slash_damage_uses_infantry_multiplier(data):
    bandit = data.npcs["reaver bandit"]  # 35 Slashing, x0.75 vs Infantry
    res = combat.npc_vs_player(bandit, combat.Loadout(), data.damage_types)
    assert res.damage_max == pytest.approx(35 * 0.75)
    wolf = data.npcs["wolf"]  # Animal damage x1
    assert combat.npc_vs_player(wolf, combat.Loadout(), data.damage_types).damage_max == 30


def test_smashing_plate_steps(data):
    plan = crafting.plan(data, "Steel Ingot", 1)
    assert "Coal" in plan.raw and "Pulverized Coal" not in plan.raw
    assert any(s.output == "Pulverized Coal" and s.station == "Smashing Plate" for s in plan.steps)
    # Gatherable fragments stay a raw material instead of being smashed by default
    assert "Iron Ore Fragment" in plan.raw
    gravel = crafting.plan(data, "Gravel", 1)
    assert gravel.raw == {"Stone Off-Cuts": 1}
    assert crafting.plan(data, "Stone Off-Cuts", 2).raw == {"Rock Slab": 2}


# ------------------------------------------------------------------ avatar skills

def test_skill_aliases(data):
    for alias, name in [("melee", "Melee Combat"), ("archery", "Ranged Combat"), ("smithing", "Blacksmithing"),
                        ("mining", "Logging & Mining"), ("logging", "Logging & Mining"), ("hunting", "Hunting"),
                        ("sprinting", "Fitness")]:
        assert data.find(alias, {"attribute"}).name == name


def test_skill_requirements_from_sheet(data):
    melee = dict((n, lv) for lv, n, _ in data.items_requiring("Melee"))
    assert melee["Superior Longsword"] == 7 and melee["Heavy Chest"] == 5 and melee["Javelin"] == 2
    ranged = dict((n, lv) for lv, n, _ in data.items_requiring("Ranged"))
    assert ranged["Longbow"] == 5 and ranged["Javelin"] == 4


def test_skill_embed_level_split(data):
    embed = embeds.attribute_embed(data, data.attributes["melee combat"], 4)
    unlocked = next(f.value for f in embed.fields if f.name.startswith("✅"))
    locked = next(f.value for f in embed.fields if f.name.startswith("🔒"))
    assert "Iron Longsword" in unlocked and "Superior Longsword" in locked
    assert len(embeds.attributes_overview_embed(data)) <= 6000
