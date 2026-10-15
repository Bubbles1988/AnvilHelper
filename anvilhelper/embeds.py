"""Turns game data into Discord embeds. No Discord connection needed, so this is easy to test."""

import discord

from . import combat
from .crafting import Plan
from .data import Entry, GameData
from .text import fmt_num, fmt_pct, key

COLORS = {
    "weapon": 0xC0392B,
    "armour": 0x7F8C8D,
    "shield": 0x95A5A6,
    "tool": 0xD35400,
    "food": 0x27AE60,
    "npc": 0x8E44AD,
    "vehicle": 0x2980B9,
    "structure": 0x795548,
    "resource": 0xF1C40F,
    "world_resource": 0x16A085,
    "item": 0xF1C40F,
    "craft": 0xE67E22,
    "info": 0x34495E,
}

FIELD_LIMIT = 1024
DESC_LIMIT = 4096


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def add_lines(embed: discord.Embed, name: str, lines: list[str], inline: bool = False):
    """Add a field, splitting into several fields when the text is too long for one."""
    if not lines:
        return
    chunk, chunks = [], []
    for line in lines:
        line = _cut(line, FIELD_LIMIT)
        if sum(len(x) + 1 for x in chunk) + len(line) > FIELD_LIMIT:
            chunks.append(chunk)
            chunk = []
        chunk.append(line)
    chunks.append(chunk)
    for i, part in enumerate(chunks):
        if len(embed.fields) >= 24:
            embed.add_field(name="…", value="(cut off - too much to show)", inline=False)
            return
        embed.add_field(name=name if i == 0 else f"{name} (cont.)", value="\n".join(part), inline=inline)


def base_embed(data: GameData, title: str, category: str, description: str | None = None,
               wiki: bool = True) -> discord.Embed:
    embed = discord.Embed(title=title, color=COLORS.get(category, COLORS["info"]),
                          description=_cut(description, DESC_LIMIT) if description else None)
    if wiki:
        embed.url = data.wiki_url(title)
    return embed


def dmg_text(dmg: dict) -> str:
    if dmg["min"] == dmg["max"]:
        return f"{fmt_num(dmg['min'])} {dmg['type']}"
    return f"{fmt_num(dmg['min'])}-{fmt_num(dmg['max'])} {dmg['type']}"


def attack_name(weapon: dict, attack: dict) -> str:
    names = {1: "Primary", 2: "Secondary", 3: "Heavy / Special"}
    if attack["slot"] == 2 and attack["damage"]["type"] == "Missile" and weapon["attacks"][0]["damage"]["type"] != "Missile":
        return "Throw"
    return names.get(attack["slot"], f"Attack {attack['slot']}")


# --------------------------------------------------------------------------- recipes


def recipe_lines(data: GameData, name: str) -> list[str]:
    lines = []
    for rec in data.recipes.get(key(name), []):
        parts = ", ".join(f"{fmt_num(i['amount'])}× {i['item']}" for i in rec["ingredients"])
        makes = f" → makes {fmt_num(rec['amount'])}" if rec["amount"] != 1 else ""
        lines.append(f"**{rec['station']}**: {parts or 'nothing'}{makes}")
    return lines


def used_in_lines(data: GameData, name: str, limit: int = 15) -> list[str]:
    users = data.used_in.get(key(name), [])
    names = sorted({u["output"] for u in users}, key=str.lower)
    if not names:
        return []
    text = ", ".join(names[:limit])
    if len(names) > limit:
        text += f" … and {len(names) - limit} more (use `/usedin`)"
    return [text]


def source_lines(data: GameData, name: str) -> list[str]:
    lines = []
    for w in data.sources.get(key(name), []):
        out = next(o for o in w["outputs"] if key(o["item"]) == key(name))
        amount = out["amount"] if isinstance(out["amount"], str) else fmt_num(out["amount"])
        tools = ", ".join(w["tools"]) or "Hands"
        lines.append(f"**{w['name']}** ({amount} per harvest) - tool: {tools}")
    return lines


def add_crafting_fields(embed: discord.Embed, data: GameData, name: str):
    add_lines(embed, "🔨 Recipe", recipe_lines(data, name))
    add_lines(embed, "⛏️ Gathered from", source_lines(data, name))
    add_lines(embed, "📦 Used in", used_in_lines(data, name))


# --------------------------------------------------------------------------- weapons


def weapon_embed(data: GameData, w: dict) -> discord.Embed:
    table = data.damage_types
    embed = base_embed(data, w["name"], "weapon")
    for attack in w["attacks"]:
        lines = [f"💥 **{dmg_text(attack['damage'])}**"]
        if attack["time_s"]:
            lines.append(f"⏱️ {fmt_num(attack['time_s'])} s")
        if attack["stamina"]:
            lines.append(f"⚡ Stamina: {fmt_num(attack['stamina'])}")
        if attack["movement"]:
            lines.append(f"🏃 Movement: {attack['movement']}")
        if attack["ability"]:
            lines.append(f"✨ {attack['ability']}")
        embed.add_field(name=attack_name(w, attack), value="\n".join(lines), inline=True)

    stats = []
    if w["stability_loss"] is not None:
        stats.append(f"🛡️ Stability loss when blocking: {fmt_pct(w['stability_loss'])}")
    if w["durability"]:
        stats.append(f"🔧 Durability: {fmt_num(w['durability'])}")
    if w["requirements"]:
        stats.append(f"📋 Requirements: {w['requirements']}")
    add_lines(embed, "Stats", stats)

    # What is it good for?
    seen = []
    for attack in w["attacks"]:
        dtype = attack["damage"]["type"]
        if dtype in seen or dtype not in table["multipliers"]:
            continue
        seen.append(dtype)
        lines = []
        for target, mult in table["multipliers"][dtype].items():
            label = combat.effectiveness(mult)
            lines.append(f"{combat.EFFECT_EMOJI[label]} {target}: ×{mult:g} ({label})")
        if dtype in combat.DAMAGE_TYPE_TIPS:
            lines.append(f"💡 {combat.DAMAGE_TYPE_TIPS[dtype]}")
        add_lines(embed, f"🎯 {dtype} damage is good against…", lines)

    if combat.blocked_by_heavy_armour(w):
        embed.add_field(name="⚠️ Armour", value="Cannot be used while wearing Reinforced or Heavy armour.", inline=False)
    add_crafting_fields(embed, data, w["name"])
    return embed


def compare_embed(data: GameData, a: dict, b: dict) -> discord.Embed:
    embed = discord.Embed(title=f"{a['name']} vs {b['name']}", color=COLORS["weapon"])
    for w in (a, b):
        lines = []
        for attack in w["attacks"]:
            dmg = attack["damage"]
            avg = (dmg["min"] + dmg["max"]) / 2
            dps = f", ~{avg / attack['time_s']:.0f} dmg/s" if attack["time_s"] else ""
            lines.append(f"**{attack_name(w, attack)}**: {dmg_text(dmg)}{dps}")
        if w["stability_loss"] is not None:
            lines.append(f"Stability loss: {fmt_pct(w['stability_loss'])}")
        if w["durability"]:
            lines.append(f"Durability: {fmt_num(w['durability'])}")
        lines.append(f"Requirements: {w['requirements'] or '-'}")
        embed.add_field(name=w["name"], value=_cut("\n".join(lines), FIELD_LIMIT), inline=True)

    # Hits needed against a few common targets with the primary attack
    targets = [
        ("🧍 Naked player", combat.Loadout()),
        ("🛡️ Reinforced set", combat.Loadout(data.armour.get("reinforced helmet"), data.armour.get("reinforced chest"), data.armour.get("reinforced leg"))),
        ("🛡️ Heavy set", combat.Loadout(data.armour.get("heavy helmet"), data.armour.get("heavy chest"), data.armour.get("heavy leg"))),
    ]
    lines = []
    for label, loadout in targets:
        res = [combat.attack_vs_player(w["attacks"][0], loadout, data.damage_types).text if w["attacks"] else "-" for w in (a, b)]
        lines.append(f"{label}: **{res[0]}** vs **{res[1]}**")
    for npc_name in ("wolf", "bear"):
        npc = data.npcs.get(npc_name)
        if npc:
            res = [combat.attack_vs_npc(w["attacks"][0], npc, data.damage_types).text if w["attacks"] else "-" for w in (a, b)]
            lines.append(f"🐺 {npc['name']} ({fmt_num(npc['health'])} HP): **{res[0]}** vs **{res[1]}**")
    add_lines(embed, "Hits to kill (primary attack)", lines)
    return embed


# --------------------------------------------------------------------------- armour


def armour_embed(data: GameData, a: dict, quality: int = 0) -> discord.Embed:
    loadout = combat.Loadout(quality=quality)
    mit = loadout.piece_mitigation(a)
    embed = base_embed(data, a["name"], "armour", f"{a['kind'] or 'Armour'} · slot: **{a['slot']}**")
    lines = [
        f"🛡️ Damage mitigation: **{fmt_pct(mit)}**" + (f" ({combat.QUALITY_NAMES[quality]})" if quality else ""),
        f"⚖️ Stability mitigation: {fmt_pct(a['stability_mitigation'])}",
        f"🌡️ Temperature mitigation: {fmt_pct(a['temperature_mitigation'])}",
    ]
    if a.get("piercing_vulnerability"):
        lines.append(f"🗡️ vs Piercing: only **{fmt_pct(loadout.piece_mitigation(a, 'Piercing'))}** (piercing vulnerability)")
    if a.get("requirements"):
        lines.append(f"📋 Requirements: {a['requirements']}")
    add_lines(embed, "Protection", lines)
    traits = []
    if a.get("heavy_armour"):
        traits.append("🚫 Heavy armour: can't arm bows, spears or javelins")
    if a.get("projectile_stagger_immunity"):
        traits.append("🧱 Not staggered by projectiles")
    if a.get("projectile_deflection"):
        traits.append("↩️ Can deflect arrows and javelins")
    if a.get("piercing_vulnerability"):
        traits.append("⚠️ Weak against Piercing damage (longswords, scorpion)")
    add_lines(embed, "Traits", traits)
    add_crafting_fields(embed, data, a["name"])
    return embed


def shield_embed(data: GameData, s: dict) -> discord.Embed:
    embed = base_embed(data, s["name"], "shield")
    lines = [
        f"🔧 Durability: {fmt_num(s['durability_hits'])} hits",
        f"⚖️ Stability loss per blocked hit: {fmt_pct(s['stability_loss_per_hit'])}",
        f"📋 Requirements: {s['requirements'] or '-'}",
    ]
    add_lines(embed, "Stats", lines + [f"💡 {n}" for n in data.shield_notes])
    add_crafting_fields(embed, data, s["name"])
    return embed


def loadout_embed(data: GameData, loadout: combat.Loadout, weapon: dict | None = None,
                  enemy_weapon: dict | None = None) -> discord.Embed:
    embed = discord.Embed(title="🛡️ Loadout check", color=COLORS["armour"])
    gear = [
        f"**Head:** {loadout.head['name'] if loadout.head else '-'}",
        f"**Chest:** {loadout.chest['name'] if loadout.chest else '-'}",
        f"**Legs:** {loadout.legs['name'] if loadout.legs else '-'}",
        f"**Shield:** {loadout.shield['name'] if loadout.shield else '-'}",
        f"**Weapon:** {weapon['name'] if weapon else '-'}",
        f"**Quality:** {combat.QUALITY_NAMES[loadout.quality]}",
    ]
    embed.add_field(name="Gear", value="\n".join(gear), inline=True)

    stats = [
        f"🛡️ Damage mitigation: **{fmt_pct(loadout.damage_mitigation())}**",
        f"🗡️ vs Piercing: **{fmt_pct(loadout.damage_mitigation('Piercing'))}**",
        f"❤️ Effective health: **{loadout.effective_health():.0f}** (base 100)",
        f"⚖️ Stability mitigation: {fmt_pct(loadout.stability_mitigation())}",
        f"🌡️ Temperature mitigation: {fmt_pct(loadout.temperature_mitigation())}",
    ]
    if loadout.shield:
        stats.append(f"🛡️ Shield: {fmt_num(loadout.shield['durability_hits'])} hits, "
                     f"{fmt_pct(loadout.shield['stability_loss_per_hit'])} stability loss per block")
    embed.add_field(name="Protection", value="\n".join(stats), inline=True)

    traits = []
    if loadout.heavy:
        traits.append("🚫 Heavy armour: no bows, spears or javelins")
    if loadout.has("projectile_stagger_immunity"):
        traits.append("🧱 Not staggered by projectiles")
    if loadout.has("projectile_deflection"):
        traits.append("↩️ Can deflect arrows and javelins")
    vulnerable = [p["name"] for p in loadout.pieces if p.get("piercing_vulnerability")]
    if vulnerable:
        traits.append("⚠️ Piercing vulnerability: " + ", ".join(vulnerable))
    add_lines(embed, "Traits", traits)
    add_lines(embed, "📋 Skill requirements", loadout.requirements())

    if weapon and loadout.heavy and combat.blocked_by_heavy_armour(weapon):
        embed.add_field(name="❌ Not compatible",
                        value=f"{weapon['name']} cannot be used with Reinforced or Heavy armour.", inline=False)

    # How many hits do common weapons need to kill you?
    threats = [enemy_weapon] if enemy_weapon else [
        data.weapons.get(k) for k in ("iron short sword", "iron longsword", "iron spear", "shortbow", "longbow", "iron mace")
    ]
    lines = []
    for w in filter(None, threats):
        for attack in (w["attacks"] if enemy_weapon else w["attacks"][:1]):
            res = combat.attack_vs_player(attack, loadout, data.damage_types)
            label = f"{w['name']} ({attack_name(w, attack).lower()})" if enemy_weapon else w["name"]
            lines.append(f"{label}: **{res.text}** ({res.damage_min:.0f}-{res.damage_max:.0f} per hit)")
    add_lines(embed, "💀 Hits you can take", lines)

    npc_lines = []
    for k in ("wolf", "bear", "reaver bandit", "stonwulfe"):
        npc = data.npcs.get(k)
        if npc and npc["damage_max"]:
            npc_lines.append(f"{npc['name']}: **{combat.npc_vs_player(npc, loadout, data.damage_types).text}**")
    add_lines(embed, "🐺 Hits you can take from NPCs", npc_lines)
    return embed


# --------------------------------------------------------------------------- NPCs


def npc_embed(data: GameData, npc: dict, weapon: dict | None = None,
              loadout: combat.Loadout | None = None) -> discord.Embed:
    embed = base_embed(data, npc["name"], "npc", f"**{npc['behaviour'] or '?'}**")
    if npc["damage_min"] == npc["damage_max"]:
        dmg = fmt_num(npc["damage_min"])
    else:
        dmg = f"{fmt_num(npc['damage_min'])}-{fmt_num(npc['damage_max'])}"
    stats = [f"❤️ Health: **{fmt_num(npc['health'])}**", f"💥 Damage: **{dmg}**"]
    if npc.get("health_regen"):
        stats.append(f"➕ Regeneration: {npc['health_regen']}")
    if npc.get("harvest_hits"):
        stats.append(f"🔪 Harvest hits: {fmt_num(npc['harvest_hits'])}")
    if npc.get("extras"):
        stats.append(f"ℹ️ {npc['extras']}")
    add_lines(embed, "Stats", stats)

    weapons = [weapon] if weapon else [
        data.weapons.get(k) for k in ("crude short sword", "flint spear", "iron short sword", "iron spear", "iron longsword", "shortbow", "longbow")
    ]
    lines = []
    for w in filter(None, weapons):
        for attack in (w["attacks"] if weapon else w["attacks"][:1]):
            res = combat.attack_vs_npc(attack, npc, data.damage_types)
            label = f"{w['name']} ({attack_name(w, attack).lower()})" if weapon else w["name"]
            lines.append(f"{label}: **{res.text}**")
    add_lines(embed, "⚔️ Hits needed to kill it", lines)

    if npc["damage_max"]:
        loadouts = [("Your gear", loadout)] if loadout else [
            ("No armour", combat.Loadout()),
            ("Crude set", combat.Loadout(data.armour.get("crude helmet"), data.armour.get("crude chest"), data.armour.get("crude leg"))),
            ("Light set", combat.Loadout(data.armour.get("light helmet"), data.armour.get("light chest"), data.armour.get("light leg"))),
            ("Reinforced set", combat.Loadout(data.armour.get("reinforced helmet"), data.armour.get("reinforced chest"), data.armour.get("reinforced leg"))),
            ("Heavy set", combat.Loadout(data.armour.get("heavy helmet"), data.armour.get("heavy chest"), data.armour.get("heavy leg"))),
        ]
        lines = [f"{label}: **{combat.npc_vs_player(npc, lo, data.damage_types).text}**" for label, lo in loadouts]
        add_lines(embed, "🩸 Hits you can take", lines)
    trophy = data.trophies.get(key(npc["name"]))
    if trophy:
        embed.add_field(name="🏆 Trophy", value=f"{trophy} - hand it in at a Town Keep bounty board for Silver.", inline=False)
    return embed


# --------------------------------------------------------------------------- food


def food_embed(data: GameData, f: dict) -> discord.Embed:
    embed = base_embed(data, f["name"], "food", f"Food type: **{f['food_type'] or '-'}**")
    embed.add_field(name="❤️ Regeneration", value=f"{fmt_num(f['regen'])} per second", inline=True)
    embed.add_field(name="⏱️ Duration", value=f["duration_text"] or "-", inline=True)
    embed.add_field(name="🍴 Hunger", value=fmt_num(f["hunger"]), inline=True)
    if f["regen"] and f["duration_s"]:
        embed.add_field(name="➕ Total healing", value=f"≈ {fmt_num(f['regen'] * f['duration_s'])} HP", inline=True)
    add_lines(embed, "🍳 How to cook it", recipe_lines(data, f["name"]))
    add_lines(embed, "⛏️ Gathered from", source_lines(data, f["name"]))
    add_lines(embed, "📦 Used in", used_in_lines(data, f["name"]))
    return embed


def foods_list_embed(data: GameData, sort: str) -> discord.Embed:
    foods = list(data.foods.values())
    keys = {
        "hunger": lambda f: f["hunger"] or 0,
        "regen": lambda f: f["regen"] or 0,
        "duration": lambda f: f["duration_s"] or 0,
        "healing": lambda f: (f["regen"] or 0) * (f["duration_s"] or 0),
    }
    foods.sort(key=keys.get(sort, keys["hunger"]), reverse=True)
    lines = [
        f"**{f['name']}** - 🍴{fmt_num(f['hunger'])} · ❤️{fmt_num(f['regen'])}/s for {f['duration_text']}"
        f" · ≈{fmt_num((f['regen'] or 0) * (f['duration_s'] or 0))} HP"
        for f in foods
    ]
    embed = discord.Embed(title=f"🍖 Foods sorted by {sort}", color=COLORS["food"])
    add_lines(embed, "Foods", lines)
    return embed


# --------------------------------------------------------------------------- crafting


def craft_embed(data: GameData, plan: Plan, kept: list[str] | None = None) -> discord.Embed:
    title = f"🔨 {fmt_num(plan.amount)}× {plan.target}"
    embed = discord.Embed(title=title, color=COLORS["craft"], url=data.wiki_url(plan.target))
    if not plan.steps:
        embed.description = "No recipe known for this item - it has to be gathered or bought."
    raw_lines = []
    for name, qty in plan.raw.items():
        where = [w["name"] for w in data.sources.get(key(name), [])[:2]]
        where += [f"{r['station']}: {', '.join(i['item'] for i in r['ingredients'])}"
                  for r in data.recipes.get(key(name), [])[:1]]
        hint = f" *(from {' or '.join(where)})*" if where else ""
        raw_lines.append(f"• **{fmt_num(qty)}×** {name}{hint}")
    add_lines(embed, "📦 Total materials to gather / bring", raw_lines)

    step_lines = []
    for i, step in enumerate(plan.steps, start=1):
        uses = ", ".join(f"{fmt_num(q)} {n}" for n, q in step.ingredients)
        crafts = f"{step.crafts}× craft" if step.crafts != 1 else "1× craft"
        line = f"**{i}. {step.output}** ×{fmt_num(step.produced)} @ {step.station} ({crafts}) ← {uses}"
        if step.note:
            line += f"\n   *{step.note}*"
        step_lines.append(line)
    add_lines(embed, "🪜 Steps (in order)", step_lines)

    if plan.surplus:
        add_lines(embed, "♻️ Left over", [", ".join(f"{fmt_num(q)} {n}" for n, q in plan.surplus.items())])
    alt = [f"{s.output}: also at {', '.join(s.other_stations)}" for s in plan.steps if s.other_stations]
    add_lines(embed, "🔁 Other stations", alt)
    if kept:
        embed.set_footer(text="Not broken down (you have them): " + ", ".join(kept))
    else:
        embed.set_footer(text="Tip: use the 'station' option to prefer e.g. Town Workshop, or 'have' to skip items you already own.")
    return embed


# --------------------------------------------------------------------------- everything else


def tool_embed(data: GameData, t: dict) -> discord.Embed:
    embed = base_embed(data, t["name"], "tool")
    embed.add_field(name="⚙️ Effectiveness", value=fmt_num(t["effectiveness"]), inline=True)
    embed.add_field(name="🔧 Durability", value=fmt_num(t["durability"]) if t["durability"] else "-", inline=True)
    gathers = [w["name"] for w in data.world_resources.values() if key(t["name"]) in {key(x) for x in w["tools"]}]
    add_lines(embed, "⛏️ Can gather", [", ".join(gathers)] if gathers else [])
    add_crafting_fields(embed, data, t["name"])
    return embed


def vehicle_embed(data: GameData, v: dict) -> discord.Embed:
    embed = base_embed(data, v["name"], "vehicle", v.get("description"))
    stats = [f"❤️ Health: {fmt_num(v['health'])}"]
    if v.get("seats"):
        stats.append(f"💺 Seats / crew: {fmt_num(v['seats'])}")
    if v.get("speed"):
        stats.append(f"🏃 Speed: {v['speed']}")
    if v.get("sprint_speed"):
        stats.append(f"💨 Sprint: {v['sprint_speed']} for {v.get('sprint_duration') or '?'}")
    if v.get("road_bonus"):
        stats.append(f"🛣️ Road bonus: {v['road_bonus']}")
    if v.get("damage"):
        stats.append(f"💥 Damage: {dmg_text(v['damage'])}")
    add_lines(embed, "Stats", stats)
    recipes = data.recipes.get(key(v["name"]), [])
    for rec in recipes:
        parts = ", ".join(f"{fmt_num(i['amount'])}× {i['item']}" for i in rec["ingredients"])
        tool = f" (tool: {rec['tool']})" if rec.get("tool") else ""
        add_lines(embed, "🔨 Build cost", [f"**{rec['station']}**{tool}: {parts}"])
    return embed


def structure_embed(data: GameData, s: dict) -> discord.Embed:
    embed = base_embed(data, s["name"], "structure", s.get("description"))
    stats = []
    if s.get("health"):
        stats.append(f"❤️ Health: {fmt_num(s['health'])}")
    if s.get("location"):
        stats.append(f"📍 Can be built: {s['location']}")
    if s.get("tools"):
        stats.append(f"🔨 Tool: {' / '.join(s['tools'])}")
    add_lines(embed, "Stats", stats)
    if s.get("ingredients"):
        add_lines(embed, "🧱 Build cost", [", ".join(f"{fmt_num(i['amount'])}× {i['item']}" for i in s["ingredients"])])
    crafted_here = sorted({r["output"] for recs in data.recipes.values() for r in recs
                           if key(r["station"]) == key(s["name"])}, key=str.lower)
    add_lines(embed, "🏭 Crafted here", [", ".join(crafted_here)] if crafted_here else [])
    return embed


def resource_embed(data: GameData, r: dict) -> discord.Embed:
    info = []
    if r.get("category"):
        info.append(r["category"])
    if r.get("size"):
        info.append(f"size: {r['size']}")
    if r.get("spoilage"):
        info.append(f"spoils after {r['spoilage']}")
    desc = r.get("description") or ""
    embed = base_embed(data, r["name"], "resource", (" · ".join(info) + "\n\n" + desc).strip())
    add_crafting_fields(embed, data, r["name"])
    return embed


def world_resource_embed(data: GameData, w: dict) -> discord.Embed:
    embed = base_embed(data, w["name"], "world_resource", w.get("description"))
    embed.add_field(name="🔨 Tool", value=", ".join(w["tools"]) or "Hands", inline=False)
    outs = [f"{o['amount'] if isinstance(o['amount'], str) else fmt_num(o['amount'])}× {o['item']}" for o in w["outputs"]]
    add_lines(embed, "📦 Drops", outs)
    return embed


def item_embed(data: GameData, e: dict) -> discord.Embed:
    embed = base_embed(data, e["name"], "item")
    add_crafting_fields(embed, data, e["name"])
    return embed


BUILDERS = {
    "weapon": weapon_embed,
    "armour": armour_embed,
    "shield": shield_embed,
    "tool": tool_embed,
    "food": food_embed,
    "npc": npc_embed,
    "vehicle": vehicle_embed,
    "structure": structure_embed,
    "resource": resource_embed,
    "world_resource": world_resource_embed,
    "item": item_embed,
}


def entry_embed(data: GameData, entry: Entry, also: list[Entry] | None = None) -> discord.Embed:
    embed = BUILDERS[entry.category](data, entry.data)
    others = [e.label for e in (also or []) if e.category != entry.category]
    footer = entry.label + (f" · also a {', '.join(others)}" if others else "")
    if not embed.footer.text:
        embed.set_footer(text=footer)
    return embed


def damage_types_embed(data: GameData) -> discord.Embed:
    table = data.damage_types
    embed = discord.Embed(title="🎯 Damage types", color=COLORS["info"],
                          description="Damage multiplier per target type. "
                                      + " ".join(f"{combat.EFFECT_EMOJI[lbl['label']]} {lbl['label']}" for lbl in table["labels"]))
    for dtype, row in table["multipliers"].items():
        lines = [f"{combat.EFFECT_EMOJI[combat.effectiveness(m)]} {t}: ×{m:g}" for t, m in row.items()]
        if dtype in combat.DAMAGE_TYPE_TIPS:
            lines.append(f"💡 {combat.DAMAGE_TYPE_TIPS[dtype]}")
        add_lines(embed, dtype, lines, inline=True)
    return embed


def not_found_embed(data: GameData, query: str, categories=None) -> discord.Embed:
    suggestions = data.search(query, categories, limit=5)
    text = f"I couldn't find **{query}**."
    if suggestions:
        text += "\nDid you mean: " + ", ".join(f"`{s}`" for s in suggestions) + "?"
    return discord.Embed(title="🤔 Not found", description=text, color=COLORS["info"])
