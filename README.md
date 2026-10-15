# AnvilHelper
Little helper for the anvil community to use in their discord at any time needed.

A Discord bot for **Anvil Empires** that answers questions with data from the community
spreadsheet (collected from the [Anvil Empires wiki](https://anvilempires.wiki.gg)).

## Commands

| Command | What it does |
|---|---|
| `/wiki name` | Look up anything: weapons, armour, animals, food, resources, buildings, vehicles, tools |
| `/weapon name` | Damage of every attack, stamina, requirements, what it's good / bad against, recipe |
| `/compare first second` | Two weapons side by side, plus hits-to-kill vs armour sets and animals |
| `/armour name [quality]` | One armour piece: mitigation (incl. vs Piercing), traits, recipe |
| `/loadout helmet chest legs shield weapon enemy quality` | Full gear check: total mitigation, effective health, stability, warnings (e.g. bow + heavy armour), hits you can take from weapons and NPCs |
| `/npc name [weapon] [armour…]` | Animal / NPC health, damage, hits needed to kill it, hits you survive, trophy |
| `/craft item [amount] [station] [have]` | Full material list **and every step in between** (logs → planks → wood blank → …), leftovers and alternative stations |
| `/food name` | Regen, duration, hunger, total healing, how to cook it (all steps) |
| `/foods [sort]` | All foods ranked by hunger, regen, duration or total healing |
| `/gather item` | Where a resource comes from and which tool you need |
| `/usedin item` | Everything that uses an item |
| `/damagetypes` | Damage type effectiveness table |
| `/help` | Command list |

All name options have autocomplete and typo-tolerant search ("long bow", "iron longswrod" both work).
Pictures are taken automatically from the wiki and every answer has an "Open wiki" button.

## Setup

1. **Create the bot** at <https://discord.com/developers/applications> → *New Application* →
   *Bot* → *Reset Token* and copy the token.
2. **Invite it**: *OAuth2 → URL Generator*, tick `bot` and `applications.commands`,
   permissions `Send Messages` + `Embed Links`, open the generated link.
3. **Install and run** (Python 3.10 or newer):

   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env               # then put your token (and server ID) in .env
   python -m anvilhelper
   ```

   With `GUILD_ID` set, the commands appear in that server immediately.

The bot has to run somewhere 24/7 to be "always there": a small VPS, a Raspberry Pi, or a
host such as Railway / fly.io / a Discord bot host. It needs no database and very little memory.

## Updating the data

The spreadsheet stays the place where you edit things:

1. Edit the Google Sheet like before.
2. *File → Download → Microsoft Excel (.xlsx)* and save it as `data/source/Anvil_Helper.xlsx`.
3. Run `python tools/import_xlsx.py` – this rewrites `data/sheet/*.json`.
4. Check the result with `python tools/preview.py wiki "Iron Longsword"` (or `craft`, `npc`, `loadout`, `compare`)
   and run the tests: `pip install -r requirements-dev.txt && pytest`.
5. Restart the bot.

Hand-made fixes that survive every import live in `data/manual/`:

* `aliases.json` – different spellings of the same thing (e.g. "Long Bow" → "Longbow") and station names.
* `extra_recipes.json` – steps missing in the sheet (e.g. heating ingots in the Forge).
* `images.json` – picture URL or wiki page name when the automatic one is wrong.
* `trophies.json` – which trophy an NPC drops.

### Keeping the spreadsheet bot-friendly

* One row per thing, one column per value, no merged cells.
* Use the exact same name everywhere (or add the other spelling to `aliases.json`).
* Numbers as numbers (`0.36`, not `36 %` in text) where possible.
* Damage as `Type min - max` (e.g. `Slashing 27 - 33`).

## Project layout

```
anvilhelper/      the bot
  bot.py          slash commands
  embeds.py       how answers look
  combat.py       armour / damage / hits-to-kill math
  crafting.py     crafting calculator
  data.py         loading + searching the data
  images.py       wiki pictures
data/sheet/       generated from the spreadsheet (don't edit by hand)
data/manual/      hand-made fixes
data/source/      the spreadsheet
tools/            import_xlsx.py, preview.py
tests/
```

## How the numbers are calculated

* **Damage mitigation** stacks multiplicatively: `1 - (1-head) × (1-chest) × (1-legs)`.
  Quality 1/2/3 multiplies each piece by 1.1/1.2/1.3.
* **Piercing vulnerability** (Light and Reinforced armour) halves that piece's mitigation vs Piercing damage.
* **Stability / temperature mitigation** add up and ignore quality.
* **Effective health** = `100 / (1 - mitigation)`.
* **Weapon damage** is multiplied by the damage-type table (e.g. Impaling ×1.5 vs NPCs, ×3 vs mounted),
  then reduced by armour. Hits are shown as a range for max-roll and min-roll damage.
* **NPC damage** against players is taken as listed in the sheet and only reduced by armour.
* **Crafting** picks, when there is a choice: your preferred station → no Silver → not a town building
  → the fewest steps. Batch recipes are rounded up and leftovers are shown.
