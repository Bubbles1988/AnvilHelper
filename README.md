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
| `/loadout helmet chest legs garment bottoms shield weapon enemy quality …_quality` | Full gear check incl. clothing worn under armour and a quality per piece: total mitigation, effective health, stability, warnings (e.g. bow + heavy armour), hits you can take from weapons and NPCs |
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
3. **Install Python 3.10+** on the Windows server from <https://www.python.org/downloads/windows/>.
   In the installer tick **"Add python.exe to PATH"** and, under *Customize installation*,
   **"Install for all users"** (the bot runs as a background task, not as your user).
4. **Get the code** onto the server (Download ZIP from GitHub, or `git clone`), e.g. to `C:\AnvilHelper`.
5. **Add your token**: copy `.env.example` to `.env` and put your token in it
   (and your server ID in `GUILD_ID`, so commands appear instantly).
6. **Test it**: double-click `windows\start_bot.bat`. The first start creates a Python environment
   and installs everything. When the console says *Logged in as …*, try `/help` in Discord.
   Close the window to stop it.
7. **Run it 24/7**: open PowerShell **as administrator** in the bot folder and run

   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\install_task.ps1
   ```

   This creates the scheduled task *AnvilHelper Discord Bot*: it starts when the server boots,
   runs without anyone logged in and restarts the bot if it ever crashes (e.g. internet outage).

**Day-to-day on the server**

| What | How |
|---|---|
| See what the bot is doing | `logs\bot.log` |
| Restart (e.g. after a data update) | `windows\restart_bot.bat` as administrator |
| Stop | `Stop-ScheduledTask -TaskName "AnvilHelper Discord Bot"` |
| Remove the task | `Unregister-ScheduledTask -TaskName "AnvilHelper Discord Bot"` |

On Linux / macOS the same works with `python -m venv .venv`, `pip install -r requirements.txt`
and `python -m anvilhelper`.

## Updating the data

The spreadsheet stays the place where you edit things:

1. Edit the Google Sheet like before.
2. *File → Download → Microsoft Excel (.xlsx)* and save it as `data/source/Anvil_Helper.xlsx`.
3. Double-click `windows\update_data.bat` (or run `python tools/import_xlsx.py`) – this rewrites `data/sheet/*.json`.
4. Check the result with `python tools/preview.py wiki "Iron Longsword"` (or `craft`, `npc`, `loadout`, `compare`)
   and run the tests: `pip install -r requirements-dev.txt && pytest`.
5. Restart the bot (`windows\restart_bot.bat`).

Hand-made fixes that survive every import live in `data/manual/`:

* `aliases.json` – different spellings of the same thing (e.g. "Long Bow" → "Longbow") and station names.
* `extra_recipes.json` – steps missing in the sheet (heating ingots in the Forge, Smashing Plate).
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

* **Damage mitigation** stacks multiplicatively over every worn piece, clothing included:
  `1 - (1-helmet) × (1-chest) × (1-legs) × (1-garment) × (1-bottoms)`.
  Quality 1/2/3 multiplies a piece by 1.1/1.2/1.3 and can be set per piece.
* **Piercing vulnerability** (Heavy armour): Piercing damage against the wearer is ×2.
* **Stability / temperature mitigation** add up and ignore quality.
* **Effective health** = `100 / (1 - mitigation)`.
* **Damage per hit on a player** = weapon damage × damage-type table vs Infantry (e.g. Piercing ×0.75)
  × 2 if Piercing vs Heavy armour × (1 - mitigation). Against NPCs the NPC column is used
  (e.g. Impaling ×1.5). Hits are shown as a range for max-roll and min-roll damage.
* **NPC damage** against players goes through the damage-type table vs Infantry (Reaver slashing ×0.75,
  animals and missiles ×1), then armour.
* **Crafting** picks, when there is a choice: your preferred station → no Silver → not a town building
  → the fewest steps. Batch recipes are rounded up and leftovers are shown.
  Things you can pick up in the world (e.g. Iron Ore Fragment) are listed as materials to gather,
  with the Smashing Plate alternative next to them.
