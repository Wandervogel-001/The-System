import discord
from discord.ext import commands
from discord.ui import View, Button
from database import MongoDatabaseManager
import os
from datetime import datetime, timedelta, timezone
from unidecode import unidecode
import logging
logger = logging.getLogger(__name__)


class IncrementButton(Button):
    def __init__(self, db, guild_id):
        super().__init__(
            label="Level Up",
            style=discord.ButtonStyle.green,
            custom_id="increment_button"
        )
        self.db = db
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        try:
            user = interaction.user
            user_id = user.id

            # Get or create member data
            member_data = await self.db.get_member(user_id, self.guild_id)

            if not member_data:
                await self.db.add_member(
                    user_id=user_id,
                    guild_id=self.guild_id,
                    username=user.name,
                    display_name=user.display_name,
                    joined_at=user.joined_at or datetime.now(timezone.utc),
                    is_bot=user.bot
                )
                member_data = {"last_increment": None, "habit_count": 0}

            now = datetime.now(timezone.utc)
            last_increment = member_data.get("last_increment")

            if last_increment:
                if last_increment.tzinfo is None:
                    last_increment = last_increment.replace(tzinfo=timezone.utc)

                if (now - last_increment) < timedelta(days=1):
                    reset_time = last_increment + timedelta(days=1)
                    await interaction.response.send_message(
                        f"⚠️ You can only increment once per day! Next available: <t:{int(reset_time.timestamp())}:R>",
                        ephemeral=True
                    )
                    return

            # Increment in DB
            await self.db.increment_habit(user_id, self.guild_id)
            await self.db.update_member(
                user_id,
                self.guild_id,
                last_increment=now,
                username=user.name,
                display_name=user.display_name
            )

            # Refresh leaderboard
            embed = await generate_leaderboard_embed(self.db, self.guild_id, user_id)
            await interaction.response.edit_message(embed=embed)

        except Exception as e:
            logger.error(f"Error in increment button: {e}")
            await interaction.response.send_message(
                "An error occurred while processing your request.",
                ephemeral=True
            )


async def generate_leaderboard_embed(db, guild_id, user_id=None):
    # Fetch data
    top = await db.get_top_habit_members(guild_id, limit=10)
    all_members = await db.members.find(
        {"guild_id": guild_id, "habit_count": {"$gte": 1}}
    ).sort("habit_count", -1).to_list(length=None)

    levels = [m.get("habit_count", 0) for m in top]
    names = [unidecode(m.get("display_name", "Unknown")) for m in top]
    ranks = list(range(1, len(top) + 1))

    if user_id:
        idx = next((i for i, m in enumerate(all_members) if m["user_id"] == user_id), None)
        if idx is not None and idx >= 10:
            u = all_members[idx]
            levels.append(u.get("habit_count", 0))
            names.append(unidecode(u.get("display_name", "You")))
            ranks.append(idx + 1)

    hdrs = ["Rank", "Display Name", "Level"]
    w_rank = max(len(str(x)) for x in ranks + [hdrs[0]]) + 2
    w_name = max(len(x) for x in names + [hdrs[1]]) + 2
    w_level = max(len(str(x)) for x in levels + [hdrs[2]]) + 2

    TL, TM, TR = "┏", "┳", "┓"
    ML, MM, MR = "┣", "╋", "┫"
    BL, BM, BR = "┗", "┻", "┛"
    V, H = "┃", "━"

    top_line = TL + H * w_rank + TM + H * w_name + TM + H * w_level + TR
    hdr = (
        f"{V}{hdrs[0].center(w_rank)}"
        f"{V}{hdrs[1].center(w_name)}"
        f"{V}{hdrs[2].center(w_level)}{V}"
    )
    sep = ML + H * w_rank + MM + H * w_name + MM + H * w_level + MR

    rows = []
    for rnk, name, lvl in zip(ranks, names, levels):
        rows.append(
            f"{V}{str(rnk).center(w_rank)}"
            f"{V}{name.ljust(w_name)}"
            f"{V}{str(lvl).center(w_level)}{V}"
        )

    bot_line = BL + H * w_rank + BM + H * w_name + BM + H * w_level + BR
    table = "\n".join([top_line, hdr, sep, *rows, bot_line])
    desc = f"```{table}```"

    embed = discord.Embed(
        title="🏆 Guild Ranking",
        description=desc,
        color=discord.Color.gold()
    )
    embed.set_footer(text="You can increment once per day (UTC)")
    return embed


def generate_leaderboard_view(db, guild_id):
    view = View(timeout=None)
    view.add_item(IncrementButton(db, guild_id))
    return view


class Players(commands.Cog):
    def __init__(self, bot, db: MongoDatabaseManager):
        self.bot = bot
        self.db = db
        self.leaderboard_data = {}
        self.bot.loop.create_task(self.load_existing_leaderboards())

    async def load_existing_leaderboards(self):
        await self.bot.wait_until_ready()

        async for settings in self.db.settings.find({"leaderboard_message_id": {"$ne": None}}):
            logger.info(f"Loading leaderboard for guild {settings['guild_id']} "
                        f"(channel: {settings['leaderboard_channel_id']}, message: {settings['leaderboard_message_id']})")
            try:
                channel = self.bot.get_channel(settings["leaderboard_channel_id"])
                message = await channel.fetch_message(settings["leaderboard_message_id"])

                self.leaderboard_data[settings["guild_id"]] = {
                    "channel_id": settings["leaderboard_channel_id"],
                    "message_id": settings["leaderboard_message_id"]
                }

                view = View(timeout=None)
                view.add_item(IncrementButton(self.db, settings["guild_id"]))
                await message.edit(view=view)

            except Exception as e:
                logger.error(f"Failed to load leaderboard for guild {settings['guild_id']}: {e}")
                if isinstance(e, discord.NotFound):
                    await self.db.update_server_setting(settings["guild_id"], "leaderboard_message_id", None)

    @commands.command(name="leaderboard")
    @commands.has_permissions(manage_messages=True)
    async def leaderboard(self, ctx):
        settings = await self.db.get_server_settings(ctx.guild.id)

        message_id = settings.get("leaderboard_message_id")
        channel_id = settings.get("leaderboard_channel_id")

        if message_id and channel_id:
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                await channel.fetch_message(message_id)
                await ctx.send("Leaderboard already exists in this server!")
                return
            except discord.NotFound:
                await self.db.update_server_setting(ctx.guild.id, "leaderboard_message_id", None)

        embed = await generate_leaderboard_embed(self.db, ctx.guild.id, ctx.author.id)
        view = generate_leaderboard_view(self.db, ctx.guild.id)
        message = await ctx.send(embed=embed, view=view)

        await self.db.update_server_setting(ctx.guild.id, "leaderboard_channel_id", ctx.channel.id)
        await self.db.update_server_setting(ctx.guild.id, "leaderboard_message_id", message.id)

        self.leaderboard_data[ctx.guild.id] = {
            "channel_id": ctx.channel.id,
            "message_id": message.id
        }


async def setup(bot):
    db = MongoDatabaseManager(os.getenv("MONGO_URI"))
    await db.initialize()
    await bot.add_cog(Players(bot, db))
