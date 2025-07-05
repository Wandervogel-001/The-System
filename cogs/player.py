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
                        f"⚠️ You can only increment once per day!\nNext available: <t:{int(reset_time.timestamp())}:R>",
                        ephemeral=True
                    )
                    return

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
            view.add_item(ShowMoreButton(self.db, self.guild_id, interaction.user))

            await interaction.response.edit_message(embed=embed, view=view)

            # Send success message
            await interaction.followup.send(
                f"🎉 Level up! You're now at level {member_data.get('habit_count', 0) + 1}!",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in increment button: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred while processing your request.",
                    ephemeral=True
                )

async def generate_leaderboard_embed(db, guild_id, user_id=None, offset=0, limit=10):
    """Generate a leaderboard embed with improved formatting and error handling."""
    try:
        # Fetch data with proper error handling
        all_members = await db.members.find(
            {"guild_id": guild_id, "habit_count": {"$gte": 1}}
        ).sort("habit_count", -1).to_list(length=None)

        if not all_members:
            # Handle empty leaderboard
            embed = discord.Embed(
                title="🏆 Guild Ranking",
                description="No members with levels found. Start leveling up!",
                color=discord.Color.gold()
            )
            embed.set_footer(text="You can increment once per day (UTC)")
            return embed

        # Paginate results
        total_members = len(all_members)
        top = all_members[offset:offset+limit]

        if not top:
            # Handle out of range pagination
            embed = discord.Embed(
                title="🏆 Guild Ranking",
                description="No members found on this page.",
                color=discord.Color.gold()
            )
            embed.set_footer(text="You can increment once per day (UTC)")
            return embed

        # Normalize names and prepare data
        levels = [m.get("habit_count", 0) for m in top]
        names = [unidecode(m.get("display_name", "Unknown"))[:20] for m in top]  # Truncate long names
        ranks = list(range(offset + 1, offset + len(top) + 1))

        # Column headers
        headers = ["Rank", "Display Name", "Level"]

        # Compute column widths with minimum widths
        w_rank = max(len(str(x)) for x in ranks + [headers[0]]) + 2
        w_name = max(len(x) for x in names + [headers[1]]) + 2
        w_level = max(len(str(x)) for x in levels + [headers[2]]) + 2

        # Ensure minimum widths for readability
        w_rank = max(w_rank, 6)
        w_name = max(w_name, 15)
        w_level = max(w_level, 7)

        # Box-drawing characters
        TL, TM, TR = "┏", "┳", "┓"
        ML, MM, MR = "┣", "╋", "┫"
        BL, BM, BR = "┗", "┻", "┛"
        V, H = "┃", "━"

        # Build table
        lines = []

        # Top border
        lines.append(TL + H * w_rank + TM + H * w_name + TM + H * w_level + TR)

        # Header row
        lines.append(
            f"{V}{headers[0].center(w_rank)}"
            f"{V}{headers[1].center(w_name)}"
            f"{V}{headers[2].center(w_level)}{V}"
        )

        # Separator
        lines.append(ML + H * w_rank + MM + H * w_name + MM + H * w_level + MR)

        # Data rows
        for rank, name, level in zip(ranks, names, levels):
            name_display = name

            lines.append(
                f"{V}{str(rank).center(w_rank)}"
                f"{V}{name_display.ljust(w_name)}"
                f"{V}{str(level).center(w_level)}{V}"
            )

        # Bottom border
        lines.append(BL + H * w_rank + BM + H * w_name + BM + H * w_level + BR)

        # Final table
        table = "\n".join(lines)
        desc = f"```{table}```"

        embed = discord.Embed(
            title="🏆 Guild Ranking",
            description=desc,
            color=discord.Color.gold()
        )

        # Add pagination info if needed
        if total_members > limit:
            page_num = (offset // limit) + 1
            total_pages = (total_members - 1) // limit + 1
            embed.set_footer(text=f"Page {page_num}/{total_pages} • You can increment once per day (UTC)")
        else:
            embed.set_footer(text="You can increment once per day (UTC)")

        return embed

    except Exception as e:
        logger.error(f"Error generating leaderboard embed: {e}")
        # Return error embed
        embed = discord.Embed(
            title="🏆 Guild Ranking",
            description="Error loading leaderboard. Please try again later.",
            color=discord.Color.red()
        )
        return embed

def generate_leaderboard_view(db, guild_id):
    """Generate the leaderboard view with buttons."""
    view = View(timeout=None)
    view.add_item(IncrementButton(db, guild_id))
    return view

class ShowMoreButton(Button):
    """Button to show more leaderboard entries."""
    def __init__(self, db, guild_id, user):
        super().__init__(label="Show More", style=discord.ButtonStyle.secondary)
        self.db = db
        self.guild_id = guild_id
        self.user = user

    async def callback(self, interaction: discord.Interaction):
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

class PaginatedLeaderboardView(View):
    """View for paginated leaderboard navigation."""
    def __init__(self, db, guild_id, offset=0, limit=10, user=None):
        super().__init__(timeout=60)
        self.db = db
        self.guild_id = guild_id
        self.offset = offset
        self.limit = limit
        self.user = user
        self.add_item(self.PreviousPageButton())
        self.add_item(self.NextPageButton())

    class NextPageButton(Button):
        def __init__(self):
            super().__init__(label="Next", style=discord.ButtonStyle.blurple)

        async def callback(self, interaction: discord.Interaction):
            view: PaginatedLeaderboardView = self.view
            if interaction.user != view.user:
                await interaction.response.send_message("You can't control this pagination.", ephemeral=True)
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

    class PreviousPageButton(Button):
        def __init__(self):
            super().__init__(label="Previous", style=discord.ButtonStyle.blurple)

        async def callback(self, interaction: discord.Interaction):
            view: PaginatedLeaderboardView = self.view
            if interaction.user != view.user:
                await interaction.response.send_message("You can't control this pagination.", ephemeral=True)
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

class Players(commands.Cog):
    def __init__(self, bot, db: MongoDatabaseManager):
        self.bot = bot
        self.db = db
        self.leaderboard_data = {}  # {guild_id: {"channel_id": int, "message_id": int}}

    async def cog_load(self):
        """Load existing leaderboards on startup."""
        await self.bot.wait_until_ready()
        await self.restore_leaderboard_views()

    async def restore_leaderboard_views(self):
        """Restore views for existing leaderboards without updating content."""
        try:
            # Get all guilds with leaderboards
            async for settings in self.db.settings.find({"leaderboard_message_id": {"$ne": None}}):
                guild_id = settings["guild_id"]
                channel_id = settings["leaderboard_channel_id"]
                message_id = settings["leaderboard_message_id"]

                logger.info(f"Restoring leaderboard view for guild {guild_id}")

                try:
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

                except discord.NotFound:
                    logger.warning(f"Leaderboard message not found for guild {guild_id}, cleaning up")
                    await self.db.update_server_setting(guild_id, "leaderboard_message_id", None)
                    await self.db.update_server_setting(guild_id, "leaderboard_channel_id", None)
                except discord.Forbidden:
                    logger.warning(f"No permission to access leaderboard for guild {guild_id}")
                except Exception as e:
                    logger.error(f"Failed to restore leaderboard view for guild {guild_id}: {e}")

            logger.info(f"Restored {len(self.leaderboard_data)} leaderboard views")

        except Exception as e:
            logger.error(f"Error restoring leaderboard views: {e}")

    @commands.command(name="leaderboard")
    @commands.has_permissions(manage_messages=True)
    async def leaderboard(self, ctx):
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
                    await ctx.send(f"Leaderboard already exists in {channel.mention}!")
                    return
                except discord.NotFound:
                    # Message was deleted — clean DB
                    await self.db.update_server_setting(ctx.guild.id, "leaderboard_message_id", None)
                    await self.db.update_server_setting(ctx.guild.id, "leaderboard_channel_id", None)

            # Create new leaderboard
            embed = await generate_leaderboard_embed(self.db, ctx.guild.id, ctx.author.id, offset=0, limit=10)
            view = generate_leaderboard_view(self.db, ctx.guild.id)

            # Add show more button
            view.add_item(ShowMoreButton(self.db, ctx.guild.id, ctx.author))

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
            await ctx.send("An error occurred while creating the leaderboard. Please try again later.")

    @commands.command(name="refresh_leaderboard")
    @commands.has_permissions(manage_messages=True)
    async def refresh_leaderboard(self, ctx):
        """Manually refresh the leaderboard (admin only)."""
        try:
            settings = await self.db.get_server_settings(ctx.guild.id)
            message_id = settings.get("leaderboard_message_id")
            channel_id = settings.get("leaderboard_channel_id")

            if not message_id or not channel_id:
                await ctx.send("No leaderboard found for this server.")
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
                await ctx.send("Leaderboard message not found. Please recreate it with `!leaderboard`.")
                await self.db.update_server_setting(ctx.guild.id, "leaderboard_message_id", None)
                await self.db.update_server_setting(ctx.guild.id, "leaderboard_channel_id", None)

        except Exception as e:
            logger.error(f"Error refreshing leaderboard: {e}")
            await ctx.send("An error occurred while refreshing the leaderboard.")

async def setup(bot):
    """Setup function for the cog."""
    db = MongoDatabaseManager(os.getenv("MONGO_URI"))
    await db.initialize()
    await bot.add_cog(Players(bot, db))
