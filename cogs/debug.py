import discord
from discord.ext import commands
import asyncio
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)

class DebugCog(commands.Cog):
    """Debug commands for bot maintenance and troubleshooting"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="check_schema", hidden=True)
    @commands.is_owner()
    async def check_database_schema(self, ctx):
        """Check the database collections structure"""
        if not self.bot.db:
            await ctx.send("❌ Database not initialized")
            return

        try:
            collections = await self.bot.db.db.list_collection_names()

            embed = discord.Embed(title="🔍 Database Collections", color=discord.Color.blue())

            embed.add_field(
                name="Available Collections",
                value="\n".join(collections) or "No collections found",
                inline=False
            )

            # Show sample document structure from members collection
            if "members" in collections:
                sample = await self.bot.db.members.find_one()
                if sample:
                    embed.add_field(
                        name="Sample Member Document",
                        value=f"```json\n{json.dumps(sample, indent=2, default=str)}```",
                        inline=False
                    )

            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Schema check failed: {e}")

    @commands.command(name="fix_member_data", hidden=True)
    @commands.is_owner()
    async def fix_member_data(self, ctx):
        """Fix corrupted member data by rebuilding from Discord"""
        if not self.bot.db:
            await ctx.send("❌ Database not initialized")
            return

        confirmation = await ctx.send("⚠️ This will DELETE all member data and rebuild from Discord. React with ✅ to confirm.")
        await confirmation.add_reaction("✅")
        await confirmation.add_reaction("❌")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirmation.id

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)

            if str(reaction.emoji) == "❌":
                await ctx.send("❌ Operation cancelled")
                return

        except asyncio.TimeoutError:
            await ctx.send("❌ Confirmation timeout")
            return

        try:
            guild = ctx.guild
            progress_msg = await ctx.send("🔄 Rebuilding member database...")

            # Clear existing data for this guild
            await self.bot.db.members.delete_many({"guild_id": guild.id})

            # Get all members sorted properly
            humans = sorted(
                [m for m in guild.members if not m.bot],
                key=lambda m: m.joined_at or datetime.utcnow()
            )
            bots = sorted(
                [m for m in guild.members if m.bot],
                key=lambda m: m.joined_at or datetime.utcnow()
            )

            all_members = humans + bots

            # Insert members with correct data
            for position, member in enumerate(all_members, 1):
                await self.bot.db.members.insert_one({
                    "user_id": member.id,
                    "guild_id": guild.id,
                    "username": str(member),
                    "display_name": member.display_name,
                    "joined_at": member.joined_at or datetime.utcnow(),
                    "join_position": position,
                    "is_bot": member.bot,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })

            await progress_msg.edit(content=f"✅ Rebuilt database with {len(all_members)} members")

            # Verify the fix
            await ctx.invoke(self.bot.get_command('analyze_members'))

        except Exception as e:
            logger.error(f"Database rebuild failed: {e}")
            await ctx.send(f"❌ Rebuild failed: {e}")

    @commands.command(name="verify_member", hidden=True)
    @commands.is_owner()
    async def verify_member_fix(self, ctx, user_id: int):
        """Verify a specific member's data after fix"""
        if not self.bot.db:
            await ctx.send("❌ Database not initialized")
            return

        guild = ctx.guild
        discord_member = guild.get_member(user_id)

        try:
            db_member = await self.bot.db.members.find_one({
                "user_id": user_id,
                "guild_id": guild.id
            })

            embed = discord.Embed(title=f"✅ Verified Member: {user_id}", color=discord.Color.green())

            if discord_member:
                embed.add_field(
                    name="Discord Data",
                    value=f"**Name:** {discord_member}\n**Display:** {discord_member.display_name}\n**Bot:** {discord_member.bot}\n**Joined:** {discord_member.joined_at}",
                    inline=False
                )

            if db_member:
                embed.add_field(
                    name="Database Data",
                    value=f"**User ID:** {db_member.get('user_id')}\n**Username:** {db_member.get('username')}\n**Display:** {db_member.get('display_name')}\n**Joined:** {db_member.get('joined_at')}\n**Position:** {db_member.get('join_position')}\n**Bot:** {bool(db_member.get('is_bot'))}",
                    inline=False
                )

                # Check if data matches
                matches = (
                    str(discord_member) == db_member.get('username') and
                    discord_member.display_name == db_member.get('display_name') and
                    discord_member.bot == bool(db_member.get('is_bot')))

                status = "✅ Data matches!" if matches else "❌ Data mismatch!"
                embed.add_field(name="Verification", value=status, inline=False)
            else:
                embed.add_field(name="Database Data", value="❌ Not found", inline=False)

            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Database error: {e}")

    @commands.command(name="analyze_members", hidden=True)
    @commands.is_owner()
    async def analyze_members(self, ctx):
        """Analyze member discrepancies and auto-sync if needed"""
        if not self.bot.db:
            await ctx.send("❌ Database not initialized")
            return

        guild = ctx.guild
        discord_members = guild.members
        discord_humans = [m for m in discord_members if not m.bot]
        discord_bots = [m for m in discord_members if m.bot]

        # Get tracked members from database
        try:
            db_members = await self.bot.db.members.find({"guild_id": guild.id}).to_list(length=None)
            db_humans = [m for m in db_members if not m.get('is_bot')]
            db_bots = [m for m in db_members if m.get('is_bot')]
        except Exception as e:
            await ctx.send(f"❌ Database error: {e}")
            return

        # Find missing members
        tracked_user_ids = {m['user_id'] for m in db_members}
        missing_humans = [m for m in discord_humans if m.id not in tracked_user_ids]
        missing_bots = [m for m in discord_bots if m.id not in tracked_user_ids]

        # Create analysis embed
        embed = discord.Embed(
            title="👥 Member Analysis",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="Discord Totals",
            value=f"Total: {len(discord_members)}\nHumans: {len(discord_humans)}\nBots: {len(discord_bots)}",
            inline=True
        )

        embed.add_field(
            name="Database Totals",
            value=f"Total: {len(db_members)}\nHumans: {len(db_humans)}\nBots: {len(db_bots)}",
            inline=True
        )

        embed.add_field(
            name="Discrepancies",
            value=f"Missing Humans: {len(missing_humans)}\nMissing Bots: {len(missing_bots)}",
            inline=True
        )

        # Show missing members if any
        if missing_humans:
            missing_human_names = [f"{m.display_name} ({m.name})" for m in missing_humans[:5]]
            embed.add_field(
                name="Missing Human Members",
                value="\n".join(missing_human_names) + (f"\n... and {len(missing_humans)-5} more" if len(missing_humans) > 5 else ""),
                inline=False
            )

        if missing_bots:
            missing_bot_names = [f"{m.display_name} ({m.name})" for m in missing_bots[:5]]
            embed.add_field(
                name="Missing Bot Members",
                value="\n".join(missing_bot_names) + (f"\n... and {len(missing_bots)-5} more" if len(missing_bots) > 5 else ""),
                inline=False
            )

        analysis_msg = await ctx.send(embed=embed)

        # Auto-sync if there are missing members
        if missing_humans or missing_bots:
            embed.add_field(
                name="🔄 Auto-Sync",
                value="Missing members detected! Automatically syncing...",
                inline=False
            )
            await analysis_msg.edit(embed=embed)

            # Perform sync
            await self._perform_sync(ctx, guild)
        else:
            # No missing members, ask if user wants to sync anyway
            embed.add_field(
                name="✅ No Missing Members",
                value="Database is up to date! React with ✅ if you want to sync anyway.",
                inline=False
            )
            await analysis_msg.edit(embed=embed)
            await analysis_msg.add_reaction("✅")

            def check(reaction, user):
                return user == ctx.author and str(reaction.emoji) == "✅" and reaction.message.id == analysis_msg.id

            try:
                reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
                await self._perform_sync(ctx, guild)
            except asyncio.TimeoutError:
                final_embed = embed.copy()
                final_embed.set_field_at(-1, name="✅ Analysis Complete", value="No sync performed.", inline=False)
                await analysis_msg.edit(embed=final_embed)

    async def _perform_sync(self, ctx, guild):
        """Internal method to perform member synchronization"""
        all_members = guild.members

        # Sort by join date (humans first, then bots, both sorted by join date)
        humans = sorted(
            [m for m in all_members if not m.bot],
            key=lambda m: m.joined_at or datetime.utcnow()
        )
        bots = sorted(
            [m for m in all_members if m.bot],
            key=lambda m: m.joined_at or datetime.utcnow()
        )

        # Combine with humans first (they get lower join positions)
        ordered_members = humans + bots

        added = 0
        updated = 0

        progress_msg = await ctx.send("🔄 Syncing members...")

        try:
            for i, member in enumerate(ordered_members):
                # Check if member exists
                existing = await self.bot.db.members.find_one({
                    "user_id": member.id,
                    "guild_id": guild.id
                })

                if existing:
                    # Update existing member
                    await self.bot.db.members.update_one(
                        {"user_id": member.id, "guild_id": guild.id},
                        {"$set": {
                            "username": str(member),
                            "display_name": member.display_name,
                            "is_bot": member.bot,
                            "updated_at": datetime.utcnow()
                        }}
                    )
                    updated += 1
                else:
                    # Add new member
                    join_position = len(humans) + 1 if member.bot else (
                        len([m for m in ordered_members[:i] if not m.bot]) + 1
                    )

                    await self.bot.db.members.insert_one({
                        "user_id": member.id,
                        "guild_id": guild.id,
                        "username": str(member),
                        "display_name": member.display_name,
                        "joined_at": member.joined_at or datetime.utcnow(),
                        "join_position": join_position,
                        "is_bot": member.bot,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow()
                    })
                    added += 1

                # Update progress every 10 members
                if (i + 1) % 10 == 0:
                    await progress_msg.edit(content=f"🔄 Syncing members... {i+1}/{len(ordered_members)}")

            await progress_msg.edit(content=f"✅ Sync complete! Added: {added}, Updated: {updated}")

        except Exception as e:
            logger.error(f"Member sync error: {e}")
            await progress_msg.edit(content=f"❌ Sync failed: {e}")

    @commands.command(name="memberinfo", aliases=["userinfo", "memberdata"], hidden=True)
    @commands.is_owner()
    async def member_details(self, ctx, member: discord.Member = None):
        """Get detailed info about a specific member"""
        if not self.bot.db:
            await ctx.send("❌ Database not initialized")
            return

        if not member:
            await ctx.send("❌ Please mention a member")
            return

        try:
            # Get member data from database
            member_data = await self.bot.db.members.find_one({
                "user_id": member.id,
                "guild_id": ctx.guild.id
            })

            if not member_data:
                await ctx.send("❌ No data found for this member")
                return

            # Create embed with member data
            embed = discord.Embed(
                title=f"📊 Member Details: {member.display_name}",
                color=discord.Color.green()
            )

            # Basic info
            embed.add_field(name="User ID", value=member.id, inline=True)
            embed.add_field(name="Username", value=member_data.get('username', 'N/A'), inline=True)
            embed.add_field(name="Display Name", value=member_data.get('display_name', 'N/A'), inline=True)

            # Join info
            join_date = member_data.get('joined_at', 'N/A')
            if isinstance(join_date, str):
                try:
                    join_date = datetime.fromisoformat(join_date)
                except ValueError:
                    pass

            if isinstance(join_date, datetime):
                embed.add_field(name="Joined At", value=join_date.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
                embed.add_field(name="Join Position", value=f"#{member_data.get('join_position', 'N/A')}", inline=True)
            else:
                embed.add_field(name="Joined At", value="N/A", inline=True)

            # Activity stats
            embed.add_field(name="Is Bot", value="Yes" if member_data.get('is_bot') else "No", inline=True)

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error fetching member details: {e}")
            await ctx.send(f"❌ Error fetching member details: {e}")

    @commands.command(name="memberlist", aliases=["members", "listmembers"], hidden=True)
    @commands.is_owner()
    async def member_dashboard(self, ctx):
        """Display members in a dashboard view with pagination"""
        if not self.bot.db:
            await ctx.send("❌ Database not initialized")
            return

        try:
            # Get members from database
            members = await self.bot.db.members.find({"guild_id": ctx.guild.id}).sort("join_position", 1).to_list(length=1000)

            if not members:
                await ctx.send("❌ No members found in database")
                return

            # Create paginated view
            class MemberListView(discord.ui.View):
                def __init__(self, members_data, ctx):
                    super().__init__(timeout=300)
                    self.members = members_data
                    self.ctx = ctx
                    self.current_page = 0
                    self.per_page = 10
                    self.max_pages = (len(self.members) - 1) // self.per_page + 1

                def get_embed(self):
                    start_idx = self.current_page * self.per_page
                    end_idx = start_idx + self.per_page
                    page_members = self.members[start_idx:end_idx]

                    embed = discord.Embed(
                        title=f"👥 Member Dashboard - {self.ctx.guild.name}",
                        color=discord.Color.blue()
                    )

                    # Format members in the requested format: #1 User1, #2 User2, etc.
                    member_list = ""
                    for member in page_members:
                        position = member.get('join_position', '?')
                        display_name = member.get('display_name', 'Unknown')
                        bot_indicator = " 🤖" if member.get('is_bot') else ""
                        member_list += f"{position} {display_name}{bot_indicator}\n"

                    embed.add_field(
                        name="Position | Display Name",
                        value=f"```\n{member_list}```",
                        inline=False
                    )

                    embed.set_footer(
                        text=f"Page {self.current_page + 1}/{self.max_pages} | Total Members: {len(self.members)}"
                    )

                    return embed

                @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="⬅️")
                async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user != self.ctx.author:
                        await interaction.response.send_message("❌ Only the command user can navigate.", ephemeral=True)
                        return

                    if self.current_page > 0:
                        self.current_page -= 1
                        await interaction.response.edit_message(embed=self.get_embed(), view=self)
                    else:
                        await interaction.response.send_message("❌ Already on first page.", ephemeral=True)

                @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="➡️")
                async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user != self.ctx.author:
                        await interaction.response.send_message("❌ Only the command user can navigate.", ephemeral=True)
                        return

                    if self.current_page < self.max_pages - 1:
                        self.current_page += 1
                        await interaction.response.edit_message(embed=self.get_embed(), view=self)
                    else:
                        await interaction.response.send_message("❌ Already on last page.", ephemeral=True)

                @discord.ui.button(label="Jump to Page", style=discord.ButtonStyle.primary, emoji="🔢")
                async def jump_to_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user != self.ctx.author:
                        await interaction.response.send_message("❌ Only the command user can navigate.", ephemeral=True)
                        return

                    class PageModal(discord.ui.Modal, title="Jump to Page"):
                        def __init__(self, view):
                            super().__init__()
                            self.view = view

                        page_number = discord.ui.TextInput(
                            label=f"Page Number (1-{view.max_pages})",
                            placeholder="Enter page number...",
                            min_length=1,
                            max_length=3
                        )

                        async def on_submit(self, interaction: discord.Interaction):
                            try:
                                page = int(self.page_number.value) - 1
                                if 0 <= page < self.view.max_pages:
                                    self.view.current_page = page
                                    await interaction.response.edit_message(embed=self.view.get_embed(), view=self.view)
                                else:
                                    await interaction.response.send_message(f"❌ Invalid page number. Must be between 1-{self.view.max_pages}", ephemeral=True)
                            except ValueError:
                                await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)

                    modal = PageModal(self)
                    await interaction.response.send_modal(modal)

            # Create the view and send initial message
            view = MemberListView(members, ctx)
            embed = view.get_embed()
            await ctx.send(embed=embed, view=view)

        except Exception as e:
            await ctx.send(f"❌ An error occurred: {str(e)}")
            logger.error(f"Error in member_dashboard: {e}")

async def setup(bot):
    await bot.add_cog(DebugCog(bot))
