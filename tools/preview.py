"""Print what the bot would answer, without Discord. Handy for checking data changes.

    python tools/preview.py wiki "Iron Longsword"
    python tools/preview.py craft "Catapult Boulder" 5
    python tools/preview.py npc Bear
    python tools/preview.py loadout "Reinforced Helmet" "Reinforced Chest" "Reinforced Leg"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anvilhelper import combat, crafting, embeds  # noqa: E402
from anvilhelper.data import GameData  # noqa: E402


def show(embed):
    print(f"# {embed.title}" + (f"  <{embed.url}>" if embed.url else ""))
    if embed.description:
        print(embed.description)
    for f in embed.fields:
        print(f"\n## {f.name}\n{f.value}")
    if embed.footer.text:
        print(f"\n-- {embed.footer.text}")
    print(f"\n[{len(embed)} characters, {len(embed.fields)} fields]")


def main(argv):
    data = GameData()
    if len(argv) < 2:
        raise SystemExit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "wiki":
        entries = data.find_all(args[0])
        show(embeds.entry_embed(data, entries[0], entries) if entries else embeds.not_found_embed(data, args[0]))
    elif cmd == "craft":
        amount = int(args[1]) if len(args) > 1 else 1
        station = args[2] if len(args) > 2 else None
        entry = data.find(args[0])
        show(embeds.craft_embed(data, crafting.plan(data, entry.name, amount, prefer_station=station)))
    elif cmd == "npc":
        weapon = data.find(args[1], {"weapon"}).data if len(args) > 1 else None
        show(embeds.npc_embed(data, data.find(args[0], {"npc"}).data, weapon))
    elif cmd == "loadout":
        pieces = [data.find(a, {"armour"}).data for a in args[:3]]
        pieces += [None] * (3 - len(pieces))
        show(embeds.loadout_embed(data, combat.Loadout(*pieces)))
    elif cmd == "compare":
        show(embeds.compare_embed(data, data.find(args[0], {"weapon"}).data, data.find(args[1], {"weapon"}).data))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
