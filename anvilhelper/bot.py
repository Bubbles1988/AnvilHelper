"""The Discord bot: slash commands with autocomplete."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import discord
from discord import app_commands

from . import combat, crafting, embeds
from .data import GameData, armour_slot
from .images import ImageFinder
from .text import clean_name, key

log = logging.getLogger("anvilhelper")


class BadInput(Exception):
    """Shown to the player as-is."""


class NotFound(Exception):
    def __init__(self, query: str, categories=None):
        super().__init__(query)
        self.query = query
        self.categories = categories


class AnvilHelper(discord.Client):
    def __init__(self, data: GameData, guild_id: int | None = None, fetch_images: bool = True):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.data = data
        self.images = ImageFinder(data, enabled=fetch_images)
        self.guild_id = guild_id
        register_commands(self.tree, data)

    async def setup_hook(self):
        if self.guild_id:
            # Guild commands show up instantly - handy while testing.
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Commands synced to guild %s", self.guild_id)
        else:
            await self.tree.sync()
            log.info("Commands synced globally (can take a while to appear)")

    async def close(self):
        await self.images.close()
        await super().close()

    async def on_ready(self):
        log.info("Logged in as %s", self.user)


def wiki_button(url: str) -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Open wiki", url=url, emoji="📖"))
    return view


async def send(interaction: discord.Interaction, embed: discord.Embed, image_for: str | None = None):
    """Send an embed (after defer) with a wiki thumbnail and button when available."""
    client: AnvilHelper = interaction.client  # type: ignore[assignment]
    if image_for:
        url = await client.images.find(image_for)
        if url:
            embed.set_thumbnail(url=url)
    view = wiki_button(embed.url) if embed.url else discord.utils.MISSING
    await interaction.followup.send(embed=embed, view=view)


def register_commands(tree: app_commands.CommandTree, data: GameData):
    # ---------------------------------------------------------------- autocomplete

    def completer(categories=None):
        async def complete(interaction: discord.Interaction, current: str):
            return [app_commands.Choice(name=n[:100], value=n[:100]) for n in data.search(current, categories)]
        return complete

    def slot_completer(slot):
        names = data.armour_for_slot(slot)

        async def complete(interaction: discord.Interaction, current: str):
            q = current.lower()
            return [app_commands.Choice(name=n, value=n) for n in names if q in n.lower()][:25]
        return complete

    async def station_complete(interaction: discord.Interaction, current: str):
        q = current.lower()
        return [app_commands.Choice(name=s[:100], value=s[:100]) for s in data.stations() if q in s.lower()][:25]

    all_items = completer()
    weapon_names = completer({"weapon"})
    shield_names = completer({"shield"})
    npc_names = completer({"npc"})
    food_names = completer({"food"})
    armour_names = completer({"armour"})
    craftable = completer(None)

    def need(query, categories):
        entry = data.find(query, categories)
        if entry is None:
            raise NotFound(query, categories)
        return entry

    def optional(query, categories):
        if not query:
            return None
        entry = data.find(query, categories)
        if entry is None:
            raise NotFound(query, categories)
        return entry.data

    def build_loadout(pieces: dict, shield=None, quality=0, qualities=None):
        """pieces: slot -> name typed by the player, e.g. {"head": "Heavy Helmet"}."""
        lo = combat.Loadout(shield=optional(shield, {"shield"}), quality=quality,
                            qualities={k: v for k, v in (qualities or {}).items() if v is not None})
        for slot, name in pieces.items():
            piece = optional(name, {"armour"})
            if piece and armour_slot(piece) != slot:
                raise BadInput(f"**{piece['name']}** is not a {combat.SLOT_LABELS[slot].lower()} "
                               f"- it goes in the {combat.SLOT_LABELS[armour_slot(piece)].lower()} slot.")
            setattr(lo, slot, piece)
        return lo

    # ---------------------------------------------------------------- commands

    @tree.command(name="wiki", description="Look up anything: weapons, armour, animals, food, resources, buildings…")
    @app_commands.describe(name="What do you want to look up?")
    @app_commands.autocomplete(name=all_items)
    async def wiki(interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        entries = data.find_all(name)
        if not entries:
            return await interaction.followup.send(embed=embeds.not_found_embed(data, name))
        await send(interaction, embeds.entry_embed(data, entries[0], entries), entries[0].name)

    @tree.command(name="weapon", description="Weapon stats and what it is good against")
    @app_commands.autocomplete(name=weapon_names)
    async def weapon(interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        entry = need(name, {"weapon"})
        await send(interaction, embeds.weapon_embed(data, entry.data), entry.name)

    @tree.command(name="compare", description="Compare two weapons side by side")
    @app_commands.autocomplete(first=weapon_names, second=weapon_names)
    async def compare(interaction: discord.Interaction, first: str, second: str):
        await interaction.response.defer()
        a = need(first, {"weapon"}).data
        b = need(second, {"weapon"}).data
        await send(interaction, embeds.compare_embed(data, a, b))

    @tree.command(name="armour", description="Stats of one armour piece")
    @app_commands.describe(quality="Crafting quality (0 = base, 1-3 add 10/20/30% mitigation)")
    @app_commands.autocomplete(name=armour_names)
    async def armour(interaction: discord.Interaction, name: str, quality: app_commands.Range[int, 0, 3] = 0):
        await interaction.response.defer()
        entry = need(name, {"armour", "shield"})
        if entry.category == "shield":
            embed = embeds.shield_embed(data, entry.data)
        else:
            embed = embeds.armour_embed(data, entry.data, quality)
        await send(interaction, embed, entry.name)

    @tree.command(name="loadout", description="Check a full gear set: protection, effective health, hits you can take")
    @app_commands.describe(
        helmet="Head armour", chest="Chest armour", legs="Leg armour",
        garment="Clothing under the chest armour (e.g. Light Garment)",
        bottoms="Clothing under the leg armour (e.g. Light Bottoms)", shield="Shield",
        weapon="Your weapon (checks if it works with your armour)",
        enemy="Enemy weapon: show exactly how many hits it needs on you",
        quality="Quality for all pieces (0 = base, 1-3 add 10/20/30% mitigation)",
        helmet_quality="Quality of the helmet only (overrides 'quality')",
        chest_quality="Quality of the chest only (overrides 'quality')",
        legs_quality="Quality of the legs only (overrides 'quality')",
        garment_quality="Quality of the garment only (overrides 'quality')",
        bottoms_quality="Quality of the bottoms only (overrides 'quality')",
    )
    @app_commands.autocomplete(helmet=slot_completer("head"), chest=slot_completer("chest"),
                               legs=slot_completer("legs"), garment=slot_completer("garment"),
                               bottoms=slot_completer("bottoms"), shield=shield_names,
                               weapon=weapon_names, enemy=weapon_names)
    async def loadout(interaction: discord.Interaction, helmet: str | None = None, chest: str | None = None,
                      legs: str | None = None, garment: str | None = None, bottoms: str | None = None,
                      shield: str | None = None, weapon: str | None = None, enemy: str | None = None,
                      quality: app_commands.Range[int, 0, 3] = 0,
                      helmet_quality: app_commands.Range[int, 0, 3] | None = None,
                      chest_quality: app_commands.Range[int, 0, 3] | None = None,
                      legs_quality: app_commands.Range[int, 0, 3] | None = None,
                      garment_quality: app_commands.Range[int, 0, 3] | None = None,
                      bottoms_quality: app_commands.Range[int, 0, 3] | None = None):
        await interaction.response.defer()
        lo = build_loadout(
            {"head": helmet, "chest": chest, "legs": legs, "garment": garment, "bottoms": bottoms},
            shield, quality,
            {"head": helmet_quality, "chest": chest_quality, "legs": legs_quality,
             "garment": garment_quality, "bottoms": bottoms_quality},
        )
        await send(interaction, embeds.loadout_embed(data, lo, optional(weapon, {"weapon"}), optional(enemy, {"weapon"})))

    @tree.command(name="npc", description="How strong is an animal / NPC and how many hits to kill it?")
    @app_commands.describe(weapon="Your weapon (shows all its attacks)", helmet="Your helmet",
                           chest="Your chest armour", legs="Your leg armour", garment="Your garment (clothing)",
                           bottoms="Your bottoms (clothing)", quality="Armour quality 0-3")
    @app_commands.autocomplete(name=npc_names, weapon=weapon_names, helmet=slot_completer("head"),
                               chest=slot_completer("chest"), legs=slot_completer("legs"),
                               garment=slot_completer("garment"), bottoms=slot_completer("bottoms"))
    async def npc(interaction: discord.Interaction, name: str, weapon: str | None = None,
                  helmet: str | None = None, chest: str | None = None, legs: str | None = None,
                  garment: str | None = None, bottoms: str | None = None,
                  quality: app_commands.Range[int, 0, 3] = 0):
        await interaction.response.defer()
        entry = need(name, {"npc"})
        pieces = {"head": helmet, "chest": chest, "legs": legs, "garment": garment, "bottoms": bottoms}
        lo = build_loadout(pieces, None, quality) if any(pieces.values()) else None
        await send(interaction, embeds.npc_embed(data, entry.data, optional(weapon, {"weapon"}), lo), entry.name)

    @tree.command(name="craft", description="Everything you need to craft something, including all the steps in between")
    @app_commands.describe(
        item="What do you want to make?",
        amount="How many?",
        station="Prefer this crafting station when there is a choice (e.g. Town Workshop)",
        have="Items you already have, comma separated - they won't be broken down (e.g. Wood Planks, Iron Ingot)",
    )
    @app_commands.autocomplete(item=craftable, station=station_complete)
    async def craft(interaction: discord.Interaction, item: str, amount: app_commands.Range[int, 1, 10000] = 1,
                    station: str | None = None, have: str | None = None):
        await interaction.response.defer()
        entry = need(item, None)
        kept = [clean_name(x) for x in (have or "").split(",") if clean_name(x)]
        kept = [data.find(x).name if data.find(x) else x for x in kept]
        plan = crafting.plan(data, entry.name, amount, prefer_station=station, keep_as_raw=set(kept))
        await send(interaction, embeds.craft_embed(data, plan, kept), entry.name)

    @tree.command(name="food", description="Food stats and how to cook it")
    @app_commands.autocomplete(name=food_names)
    async def food(interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        entry = need(name, {"food"})
        embed = embeds.food_embed(data, entry.data)
        plan = crafting.plan(data, entry.name, 1)
        if len(plan.steps) > 1:
            steps = [f"{i}. {s.output} @ {s.station}" for i, s in enumerate(plan.steps, 1)]
            embeds.add_lines(embed, "🪜 All steps (from raw ingredients)", steps)
            embeds.add_lines(embed, "🧺 Raw ingredients for one", [", ".join(f"{q:g}× {n}" for n, q in plan.raw.items())])
        await send(interaction, embed, entry.name)

    @tree.command(name="foods", description="List all foods sorted by hunger, regeneration, duration or total healing")
    @app_commands.choices(sort=[app_commands.Choice(name=n, value=n) for n in ("hunger", "regen", "duration", "healing")])
    async def foods(interaction: discord.Interaction, sort: str = "hunger"):
        await interaction.response.send_message(embed=embeds.foods_list_embed(data, sort))

    @tree.command(name="gather", description="Where do I get this resource and which tool do I need?")
    @app_commands.autocomplete(item=all_items)
    async def gather(interaction: discord.Interaction, item: str):
        await interaction.response.defer()
        entry = need(item, None)
        embed = embeds.base_embed(data, entry.name, "world_resource")
        lines = embeds.source_lines(data, entry.name)
        if not lines and entry.category == "world_resource":
            embed = embeds.world_resource_embed(data, entry.data)
        elif not lines:
            recipes = embeds.recipe_lines(data, entry.name)
            embed.description = ("This is not gathered - it is crafted:\n" + "\n".join(recipes)) if recipes \
                else "No gathering spot known for this item yet."
        else:
            embeds.add_lines(embed, "⛏️ Gathered from", lines)
        await send(interaction, embed, entry.name)

    @tree.command(name="usedin", description="What can I make with this item?")
    @app_commands.autocomplete(item=all_items)
    async def usedin(interaction: discord.Interaction, item: str):
        await interaction.response.defer()
        entry = need(item, None)
        users = data.used_in.get(key(entry.name), [])
        embed = embeds.base_embed(data, f"What uses {entry.name}?", "item", wiki=False)
        lines = sorted({f"**{u['output']}** ({u['station']})" for u in users}, key=str.lower)
        embeds.add_lines(embed, f"{len(lines)} recipes", lines or ["Nothing known uses this item."])
        await send(interaction, embed)

    @tree.command(name="damagetypes", description="Which damage type is good against what?")
    async def damagetypes(interaction: discord.Interaction):
        await interaction.response.send_message(embed=embeds.damage_types_embed(data))

    @tree.command(name="help", description="What can this bot do?")
    async def help_cmd(interaction: discord.Interaction):
        embed = discord.Embed(title="⚒️ Anvil Helper", color=embeds.COLORS["info"],
                              description="Anvil Empires info straight from the community spreadsheet / wiki.")
        lines = [
            "`/wiki` - look up anything",
            "`/weapon` - weapon stats & what it's good against",
            "`/compare` - two weapons side by side",
            "`/armour` - one armour piece (with quality)",
            "`/loadout` - full gear check incl. clothing and quality per piece: mitigation, effective health, hits you can take",
            "`/npc` - animal / NPC strength and hits to kill it",
            "`/craft` - full material list and steps for anything",
            "`/food` · `/foods` - food stats, recipes and rankings",
            "`/gather` - where a resource comes from and which tool you need",
            "`/usedin` - what an item is used for",
            "`/damagetypes` - damage type effectiveness table",
        ]
        embed.add_field(name="Commands", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.error
    async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, "original", error)
        if isinstance(original, NotFound):
            embed = embeds.not_found_embed(data, original.query, original.categories)
        elif isinstance(original, BadInput):
            embed = discord.Embed(title="🤔 Check your input", description=str(original), color=embeds.COLORS["info"])
        else:
            log.exception("Command failed", exc_info=original)
            embed = discord.Embed(title="Something went wrong", description=str(original)[:500],
                                  color=embeds.COLORS["info"])
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)


ROOT = Path(__file__).resolve().parent.parent
EXIT_CONFIG_ERROR = 2  # start_bot.bat stops restarting on this code: retrying won't help


def setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = os.environ.get("LOG_FILE", str(ROOT / "logs" / "bot.log"))
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(fmt)
        root.addHandler(handler)


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    setup_logging()
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token or token == "put-your-bot-token-here":
        log.error("DISCORD_TOKEN is not set. Copy .env.example to .env and put your bot token in it.")
        sys.exit(EXIT_CONFIG_ERROR)
    guild = os.environ.get("GUILD_ID", "").strip()
    fetch_images = os.environ.get("WIKI_IMAGES", "1") != "0"
    discord.VoiceClient.warn_nacl = False  # the bot never uses voice
    client = AnvilHelper(GameData(), int(guild) if guild else None, fetch_images)
    try:
        client.run(token, log_handler=None)
    except discord.LoginFailure:
        log.error("Discord rejected the token. Check DISCORD_TOKEN in .env.")
        sys.exit(EXIT_CONFIG_ERROR)
    except Exception:
        # e.g. no internet: log it to the file; start_bot.bat restarts the bot.
        log.exception("Bot crashed")
        sys.exit(1)
