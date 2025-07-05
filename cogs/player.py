import discord
from discord.ext import commands
from discord.ui import View, Button
from database import MongoDatabaseManager
import os
from datetime import datetime, timedelta, timezone
from unidecode import unidecode
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

def smart_truncate(name, width):
    return name if len(name) <= width else name[:width - 1] + "…"

class ProfileButton(Button):
    def __init__(self, db: MongoDatabaseManager, guild_id: int):
        super().__init__(label="📋 Profile", style=discord.ButtonStyle.gray, custom_id="profile_button")
        self.db = db
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        try:
            user = interaction.user
            user_id = user.id

            # Get all ranked members
            members = await self.db.members.find({
                "guild_id": self.guild_id,
                "habit_count": {"$gte": 1}
            }).sort("habit_count", -1).to_list(length=None)

            if not members:
                await interaction.response.send_message("❌ No ranked members found in this server.", ephemeral=True)
                return

            # Find user's data + rank
            user_data = next((m for m in members if m["user_id"] == user_id), None)
            if not user_data:
                await interaction.response.send_message("❌ You're not ranked yet. Use the Level Up button first!", ephemeral=True)
                return

            rank = members.index(user_data) + 1
            count = user_data.get("habit_count", 0)
            name = user_data.get("display_name", user.display_name)

            # Medal logic
            medal = {
                1: "🥇",
                2: "🥈",
                3: "🥉"
            }.get(rank, "🎖️")

            # Create monospaced profile body with perfect alignment
            profile_body = (
                f"```\n"
                f"{medal} {name}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"► Rank   | {rank}\n"
                f"► Level  | {count}\n"
                f"```"
            )

            embed = discord.Embed(
                description=profile_body,
                color=discord.Color.blurple()
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in profile button callback: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An error occurred while loading your profile. Please try again later.",
                    ephemeral=True
                )

class IncrementButton(Button):
    def __init__(self, db: MongoDatabaseManager, guild_id: int):
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
                # Ensure timezone awareness
                if last_increment.tzinfo is None:
                    last_increment = last_increment.replace(tzinfo=timezone.utc)

                time_diff = now - last_increment
                if time_diff < timedelta(days=1):
                    reset_time = last_increment + timedelta(days=1)
                    await interaction.response.send_message(
                        f"⚠️ You can only increment once per day!\nNext available: <t:{int(reset_time.timestamp())}:R>",
                        ephemeral=True
                    )
                    return

            # Get current habit count before increment
            current_count = member_data.get("habit_count", 0)

            # Increment in DB
            await self.db.increment_habit(user_id, self.guild_id)

            # Update member info
            await self.db.update_member(
                user_id,
                self.guild_id,
                last_increment=now,
                username=user.name,
                display_name=user.display_name
            )

            # Update the leaderboard ONLY when someone successfully increments
            embed = await generate_leaderboard_embed(self.db, self.guild_id, user_id, offset=0, limit=10)

            # Get the current view to preserve other buttons
            view = generate_leaderboard_view(self.db, self.guild_id)

            await interaction.response.edit_message(embed=embed, view=view)

            # Send success message with correct new level
            new_level = current_count + 1
            await interaction.followup.send(
                f"🎉 Level up! You're now at level {new_level}!",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in increment button callback: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An error occurred while processing your request. Please try again later.",
                    ephemeral=True
                )

class ShowMoreButton(Button):
    """Button to show more leaderboard entries."""
    def __init__(self, db: MongoDatabaseManager, guild_id: int, user: Optional[discord.User] = None):
        super().__init__(label="Show More", style=discord.ButtonStyle.secondary, custom_id="show_more_button")
        self.db = db
        self.guild_id = guild_id
        self.user = user

    async def callback(self, interaction: discord.Interaction):
        try:
            # Check if there are more than 10 members total
            total_members = await self.db.members.count_documents(
                {"guild_id": self.guild_id, "habit_count": {"$gte": 1}}
            )

            if total_members <= 10:
                await interaction.response.send_message(
                    "📄 No more pages available! All members are shown on the first page.",
                    ephemeral=True
                )
                return

            embed = await generate_leaderboard_embed(self.db, self.guild_id, offset=10, limit=10)
            view = PaginatedLeaderboardView(self.db, self.guild_id, offset=10, limit=10, user=interaction.user)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in show more button callback: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An error occurred while loading more entries. Please try again later.",
                    ephemeral=True
                )

class PaginatedLeaderboardView(View):
    """View for paginated leaderboard navigation."""
    def __init__(self, db: MongoDatabaseManager, guild_id: int, offset: int = 0, limit: int = 10, user: Optional[discord.User] = None):
        super().__init__(timeout=300)  # Increased timeout to 5 minutes
        self.db = db
        self.guild_id = guild_id
        self.offset = offset
        self.limit = limit
        self.user = user
        self.add_item(self.PreviousPageButton())
        self.add_item(self.NextPageButton())

    async def on_timeout(self):
        """Handle view timeout."""
        try:
            # Disable all buttons when view times out
            for item in self.children:
                if isinstance(item, Button):
                    item.disabled = True
        except Exception as e:
            logger.error(f"Error handling view timeout: {e}")

    class PreviousPageButton(Button):
        def __init__(self):
            super().__init__(label="Previous", style=discord.ButtonStyle.blurple, custom_id="prev_page_button")

        async def callback(self, interaction: discord.Interaction):
            try:
                view: PaginatedLeaderboardView = self.view

                # Check if user has permission to control pagination
                if view.user and interaction.user != view.user:
                    await interaction.response.send_message("❌ You can't control this pagination.", ephemeral=True)
                    return

                if view.offset <= 0:
                    await interaction.response.send_message(
                        "📄 You're already on the first page!",
                        ephemeral=True
                    )
                    return

                view.offset = max(0, view.offset - view.limit)
                embed = await generate_leaderboard_embed(view.db, view.guild_id, offset=view.offset, limit=view.limit)
                await interaction.response.edit_message(embed=embed, view=view)

            except Exception as e:
                logger.error(f"Error in previous page button callback: {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred while navigating. Please try again later.",
                        ephemeral=True
                    )

    class NextPageButton(Button):
        def __init__(self):
            super().__init__(label="Next", style=discord.ButtonStyle.blurple, custom_id="next_page_button")

        async def callback(self, interaction: discord.Interaction):
            try:
                view: PaginatedLeaderboardView = self.view

                # Check if user has permission to control pagination
                if view.user and interaction.user != view.user:
                    await interaction.response.send_message("❌ You can't control this pagination.", ephemeral=True)
                    return

                # Check if there are more members beyond the next page
                total_members = await view.db.members.count_documents(
                    {"guild_id": view.guild_id, "habit_count": {"$gte": 1}}
                )

                next_offset = view.offset + view.limit
                if next_offset >= total_members:
                    await interaction.response.send_message(
                        "📄 You're already on the last page!",
                        ephemeral=True
                    )
                    return

                view.offset = next_offset
                embed = await generate_leaderboard_embed(view.db, view.guild_id, offset=view.offset, limit=view.limit)
                await interaction.response.edit_message(embed=embed, view=view)

            except Exception as e:
                logger.error(f"Error in next page button callback: {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred while navigating. Please try again later.",
                        ephemeral=True
                    )

async def generate_leaderboard_embed(db, guild_id, user_id=None, offset=0, limit=10):
    try:
        all_members = await db.members.find(
            {"guild_id": guild_id, "habit_count": {"$gte": 1}}
        ).sort("habit_count", -1).to_list(length=None)

        if not all_members:
            embed = discord.Embed(
                title="🏆 Guild Ranking",
                description="No members with levels found. Start leveling up!",
                color=discord.Color.gold()
            )
            embed.set_footer(text="You can increment once per day (UTC)")
            return embed

        total_members = len(all_members)
        top = all_members[offset:offset + limit]

        if not top:
            embed = discord.Embed(
                title="🏆 Guild Ranking",
                description="No members found on this page.",
                color=discord.Color.gold()
            )
            embed.set_footer(text="You can increment once per day (UTC)")
            return embed

        # Fixed column widths
        w_rank = 6
        w_name = 17
        w_level = 7

        levels = [m.get("habit_count", 0) for m in top]
        names = [smart_truncate(unidecode(m.get("display_name", "Unknown")), w_name) for m in top]
        ranks = list(range(offset + 1, offset + len(top) + 1))

        TL, TM, TR = "┏", "┳", "┓"
        ML, MM, MR = "┣", "╋", "┫"
        BL, BM, BR = "┗", "┻", "┛"
        V, H = "┃", "━"

        lines = []
        lines.append(TL + H * w_rank + TM + H * w_name + TM + H * w_level + TR)
        lines.append(f"{V}{'Rank'.center(w_rank)}{V}{'Display Name'.center(w_name)}{V}{'Level'.center(w_level)}{V}")
        lines.append(ML + H * w_rank + MM + H * w_name + MM + H * w_level + MR)

        for rank, name, level in zip(ranks, names, levels):
            lines.append(
                f"{V}{str(rank).center(w_rank)}"
                f"{V}{name.ljust(w_name)}"
                f"{V}{str(level).center(w_level)}{V}"
            )

        lines.append(BL + H * w_rank + BM + H * w_name + BM + H * w_level + BR)
        desc = f"```\n" + "\n".join(lines) + "\n```"

        embed = discord.Embed(
            title="🏆 Guild Ranking",
            description=desc,
            color=discord.Color.gold()
        )

        if total_members > limit:
            page_num = (offset // limit) + 1
            total_pages = (total_members - 1) // limit + 1
            embed.set_footer(text=f"Page {page_num}/{total_pages} • You can increment once per day (UTC)")
        else:
            embed.set_footer(text="You can increment once per day (UTC)")

        return embed

    except Exception as e:
        logger.error(f"Error generating leaderboard embed: {e}")
        embed = discord.Embed(
            title="🏆 Guild Ranking",
            description="Error loading leaderboard. Please try again later.",
            color=discord.Color.red()
        )
        return embed

def generate_leaderboard_view(db: MongoDatabaseManager, guild_id: int, user: Optional[discord.User] = None) -> View:
    """Generate the main leaderboard view with all buttons."""
    view = View(timeout=None)
    view.add_item(IncrementButton(db, guild_id))
    view.add_item(ShowMoreButton(db, guild_id, user))
    view.add_item(ProfileButton(db, guild_id))
    return view

class Players(commands.Cog):
    def __init__(self, bot: commands.Bot, db: MongoDatabaseManager):
        self.bot = bot
        self.db = db
        self.leaderboard_data: Dict[int, Dict[str, int]] = {}  # {guild_id: {"channel_id": int, "message_id": int}}

    async def cog_load(self):
        """Load existing leaderboards on startup."""
        await self.bot.wait_until_ready()
        await self.restore_leaderboard_views()

    async def restore_leaderboard_views(self):
        """Restore views for existing leaderboards without updating content."""
        try:
            # Get all guilds with leaderboards
            settings_cursor = self.db.settings.find({"leaderboard_message_id": {"$ne": None}})

            restored_count = 0
            async for settings in settings_cursor:
                guild_id = settings["guild_id"]
                channel_id = settings["leaderboard_channel_id"]
                message_id = settings["leaderboard_message_id"]

                logger.info(f"Restoring leaderboard view for guild {guild_id}")

                try:
                    # Validate guild exists
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        logger.warning(f"Guild {guild_id} not found, skipping leaderboard restoration")
                        continue

                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        channel = await self.bot.fetch_channel(channel_id)

                    message = await channel.fetch_message(message_id)

                    # Store leaderboard data
                    self.leaderboard_data[guild_id] = {
                        "channel_id": channel_id,
                        "message_id": message_id
                    }

                    # Restore the view (buttons only, no content update)
                    view = generate_leaderboard_view(self.db, guild_id)
                    await message.edit(view=view)

                    logger.info(f"Successfully restored leaderboard view for guild {guild_id}")
                    restored_count += 1

                except discord.NotFound:
                    logger.warning(f"Leaderboard message not found for guild {guild_id}, cleaning up")
                    await self.db.update_server_setting(guild_id, "leaderboard_message_id", None)
                    await self.db.update_server_setting(guild_id, "leaderboard_channel_id", None)
                except discord.Forbidden:
                    logger.warning(f"No permission to access leaderboard for guild {guild_id}")
                except Exception as e:
                    logger.error(f"Failed to restore leaderboard view for guild {guild_id}: {e}")

            logger.info(f"Restored {restored_count} leaderboard views")

        except Exception as e:
            logger.error(f"Error restoring leaderboard views: {e}")

    @commands.command(name="leaderboard", help="Create or display the guild leaderboard")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def leaderboard(self, ctx: commands.Context):
        """Create or display the guild leaderboard."""
        try:
            settings = await self.db.get_server_settings(ctx.guild.id)

            # If settings claim message exists, verify it really does
            message_id = settings.get("leaderboard_message_id")
            channel_id = settings.get("leaderboard_channel_id")

            if message_id and channel_id:
                try:
                    channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                    message = await channel.fetch_message(message_id)
                    await ctx.send(f"✅ Leaderboard already exists in {channel.mention}!")
                    return
                except discord.NotFound:
                    # Message was deleted — clean DB
                    await self.db.update_server_setting(ctx.guild.id, "leaderboard_message_id", None)
                    await self.db.update_server_setting(ctx.guild.id, "leaderboard_channel_id", None)
                    # Remove from cache
                    self.leaderboard_data.pop(ctx.guild.id, None)

            # Create new leaderboard
            embed = await generate_leaderboard_embed(self.db, ctx.guild.id, ctx.author.id, offset=0, limit=10)
            view = generate_leaderboard_view(self.db, ctx.guild.id)

            message = await ctx.send(embed=embed, view=view)

            # Save leaderboard info
            await self.db.update_server_setting(ctx.guild.id, "leaderboard_channel_id", ctx.channel.id)
            await self.db.update_server_setting(ctx.guild.id, "leaderboard_message_id", message.id)

            self.leaderboard_data[ctx.guild.id] = {
                "channel_id": ctx.channel.id,
                "message_id": message.id
            }

            logger.info(f"Created new leaderboard for guild {ctx.guild.id}")

        except Exception as e:
            logger.error(f"Error creating leaderboard: {e}")
            await ctx.send("❌ An error occurred while creating the leaderboard. Please try again later.")

    @commands.command(name="refresh_leaderboard", help="Manually refresh the leaderboard (admin only)")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def refresh_leaderboard(self, ctx: commands.Context):
        """Manually refresh the leaderboard (admin only)."""
        try:
            settings = await self.db.get_server_settings(ctx.guild.id)
            message_id = settings.get("leaderboard_message_id")
            channel_id = settings.get("leaderboard_channel_id")

            if not message_id or not channel_id:
                await ctx.send("❌ No leaderboard found for this server. Use `!leaderboard` to create one.")
                return

            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                message = await channel.fetch_message(message_id)

                # Update the leaderboard
                embed = await generate_leaderboard_embed(self.db, ctx.guild.id, offset=0, limit=10)
                view = generate_leaderboard_view(self.db, ctx.guild.id)

                await message.edit(embed=embed, view=view)
                await ctx.send("✅ Leaderboard refreshed successfully!")

            except discord.NotFound:
                await ctx.send("❌ Leaderboard message not found. Please recreate it with `!leaderboard`.")
                await self.db.update_server_setting(ctx.guild.id, "leaderboard_message_id", None)
                await self.db.update_server_setting(ctx.guild.id, "leaderboard_channel_id", None)
                # Remove from cache
                self.leaderboard_data.pop(ctx.guild.id, None)

        except Exception as e:
            logger.error(f"Error refreshing leaderboard: {e}")
            await ctx.send("❌ An error occurred while refreshing the leaderboard. Please try again later.")

    @leaderboard.error
    @refresh_leaderboard.error
    async def command_error_handler(self, ctx: commands.Context, error: commands.CommandError):
        """Handle command errors."""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command. You need the 'Manage Messages' permission.")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("❌ This command can only be used in a server.")
        else:
            logger.error(f"Unexpected error in command {ctx.command}: {error}")
            await ctx.send("❌ An unexpected error occurred. Please try again later.")

async def setup(bot: commands.Bot):
    """Setup function for the cog."""
    db = MongoDatabaseManager(os.getenv("MONGO_URI"))
    await db.initialize()
    await bot.add_cog(Players(bot, db))
