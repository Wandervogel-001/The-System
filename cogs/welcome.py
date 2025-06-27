import discord
from discord.ext import commands
from database import MongoDatabaseManager
import logging
import os

logger = logging.getLogger(__name__)

class WelcomeCog(commands.Cog):
    """Welcome System - Manage member greetings and role assignments with persistent settings

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    🌟 Main Commands:
    `!welcome @member`           - Send a welcome message to the specified member
    `!welcome setchannel #channel` - Set the welcome channel (persistent)
    `!welcome setrole @role`     - Set the auto-role for new members (persistent)
    `!welcome setmessage <text>` - Set custom welcome message (persistent)
    `!welcome toggle`            - Enable/disable welcome system
    `!welcome settings`          - View current welcome settings

    ⚙️ Admin Testing:
    `!simulatejoin`              - Test the welcome system (Admin only)

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    🔄 Automatic Features:
    • Auto-welcomes new members in configured channel
    • Auto-assigns the configured role to new members
    • Tracks accurate join position (excluding bots)
    • Persistent settings that survive bot restarts

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    📝 Custom Messages Support:
    Use these placeholders in your welcome message:
    • {user_mention} - @mentions the user
    • {user_name} - User's display name
    • {guild_name} - Server name
    • {member_count} - Total member count
    • {join_position} - User's join position

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    🛠️ Requirements:
    • Manage Server permission for configuration
    • Manage Roles permission for role setup
    • Administrator for testing
    """
    def __init__(self, bot):
        self.bot = bot
        self.db = MongoDatabaseManager(os.getenv("MONGO_URI"))

    async def cog_load(self):
        """Initialize database connection when cog loads"""
        await self.db.initialize()
        logger.info("Welcome cog MongoDB initialized")

    def _format_welcome_message(self, message_template: str, member: discord.Member, join_position: int) -> str:
        """Format welcome message with placeholders"""
        return message_template.format(
            user_mention=member.mention,
            user_name=member.display_name,
            guild_name=member.guild.name,
            member_count=len([m for m in member.guild.members if not m.bot]),
            join_position=join_position
        )

    def _get_ordinal(self, n: int) -> str:
        """Convert number to ordinal (1st, 2nd, 3rd, etc.)"""
        return "%d%s" % (n, "tsnrhtdd"[(n//10%10!=1)*(n%10<4)*n%10::4])

    async def _send_welcome(self, member: discord.Member, settings: dict):
        """Send welcome message using database settings"""
        if not settings['welcome_enabled']:
            return

        channel = self.bot.get_channel(settings.get('welcome_channel_id'))
        if not channel:
            channel = member.guild.system_channel or next((ch for ch in member.guild.text_channels if ch.permissions_for(member.guild.me).send_messages), None)
        if not channel:
            logger.warning(f"No valid welcome channel found for {member.guild.name}")
            return

        member_data = await self.db.get_member(member.id, member.guild.id)
        join_position = member_data['join_position'] if member_data else 1

        message_text = self._format_welcome_message(
            settings.get('welcome_message', 'Welcome {user_mention}!'),
            member, join_position
        )

        embed = discord.Embed(
            title=f"✨ Welcome {member.display_name}!",
            description=message_text,
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Join Position",
            value=f"{member.mention} is the {self._get_ordinal(join_position)} member!",
            inline=False
        )

        try:
            await channel.send(embed=embed)
            logger.info(f"Welcome sent for {member} in {member.guild.name}")
        except discord.HTTPException as e:
            logger.error(f"Failed to send welcome message: {e}")

    async def _assign_welcome_role(self, member: discord.Member, settings: dict):
        """Assign welcome role using database settings"""
        if not settings.get('auto_role_enabled') or not settings.get('welcome_role_id'):
            return

        role = member.guild.get_role(settings['welcome_role_id'])
        if not role:
            logger.warning(f"Welcome role {settings['welcome_role_id']} not found in {member.guild.name}")
            return

        try:
            await member.add_roles(role, reason="Auto-role assignment (welcome system)")
            logger.info(f"Assigned role {role.name} to {member} in {member.guild.name}")
        except discord.Forbidden:
            logger.error(f"Missing permissions to assign role {role.name} in {member.guild.name}")
        except discord.HTTPException as e:
            logger.error(f"Failed to assign welcome role: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Automatically handle new members with database integration"""
        try:
            await self.db.add_member(
                user_id=member.id,
                guild_id=member.guild.id,
                username=str(member),
                display_name=member.display_name,
                joined_at=member.joined_at or discord.utils.utcnow(),
                is_bot=member.bot
            )
            settings = await self.db.get_server_settings(member.guild.id)
            await self._send_welcome(member, settings)
            await self._assign_welcome_role(member, settings)
        except Exception as e:
            logger.error(f"Error handling member join for {member}: {e}")

    @commands.group(invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def welcome(self, ctx, member: discord.Member):
        """Welcome system management - Send manual welcome"""
        settings = await self.db.get_server_settings(ctx.guild.id)
        if not settings['welcome_enabled']:
            await ctx.send("❌ Welcome system is disabled! Use `!welcome toggle` to enable.", delete_after=10)
            return
        await self._send_welcome(member, settings)
        await self._assign_welcome_role(member, settings)
        await ctx.send(f"✅ Welcome sent for {member.mention}!", delete_after=5)
        await ctx.message.delete(delay=1)

    @welcome.command(name="setchannel")
    @commands.has_permissions(manage_guild=True)
    async def set_welcome_channel(self, ctx, channel: discord.TextChannel):
        """Set the welcome channel (persistent across restarts)
        ---
        `!welcome setchannel #general` - Set #general as welcome channel
        """
        await self.db.update_server_setting(ctx.guild.id, 'welcome_channel_id', channel.id)
        await ctx.send(embed=discord.Embed(
            title="✅ Welcome Channel Updated",
            description=f"Welcome messages will now be sent to {channel.mention}",
            color=discord.Color.green()
        ), delete_after=10)
        await ctx.message.delete(delay=1)

    @welcome.command(name="setrole")
    @commands.has_permissions(manage_roles=True)
    async def set_welcome_role(self, ctx, role: discord.Role):
        """Set the auto-role for new members (persistent across restarts)
        ---
        `!welcome setrole @Member` - Set @Member as the auto-role
        """
        if role >= ctx.guild.me.top_role:
            await ctx.send("❌ I cannot assign this role - it's higher than my highest role!", delete_after=10)
            return
        await self.db.update_server_setting(ctx.guild.id, 'welcome_role_id', role.id)
        await ctx.send(embed=discord.Embed(
            title="✅ Welcome Role Updated",
            description=f"New members will automatically receive the {role.mention} role",
            color=discord.Color.green()
        ), delete_after=10)
        await ctx.message.delete(delay=1)

    @welcome.command(name="setmessage")
    @commands.has_permissions(manage_guild=True)
    async def set_welcome_message(self, ctx, *, message: str):
        """Set custom welcome message (persistent across restarts)
        ---
        Available placeholders:
        • {user_mention} - @mentions the user
        • {user_name} - User's display name
        • {guild_name} - Server name
        • {member_count} - Total member count
        • {join_position} - User's join position

        Example: `!welcome setmessage Welcome to {guild_name}, {user_mention}! You're our {join_position} member!`
        """
        if len(message) > 500:
            await ctx.send("❌ Welcome message must be 500 characters or less!", delete_after=10)
            return
        await self.db.update_server_setting(ctx.guild.id, 'welcome_message', message)
        preview = self._format_welcome_message(message, ctx.author, 42)
        embed = discord.Embed(
            title="✅ Welcome Message Updated",
            description="Here's how it will look:",
            color=discord.Color.green()
        )
        embed.add_field(name="Preview", value=preview, inline=False)
        await ctx.send(embed=embed, delete_after=15)
        await ctx.message.delete(delay=1)

    @welcome.command(name="toggle")
    @commands.has_permissions(manage_guild=True)
    async def toggle_welcome(self, ctx):
        """Enable/disable the welcome system
        ---
        `!welcome toggle` - Switch welcome system on/off
        """
        settings = await self.db.get_server_settings(ctx.guild.id)
        new_state = not settings['welcome_enabled']
        await self.db.update_server_setting(ctx.guild.id, 'welcome_enabled', new_state)
        status = "enabled" if new_state else "disabled"
        color = discord.Color.green() if new_state else discord.Color.red()
        embed = discord.Embed(
            title=f"✅ Welcome System {status.title()}",
            description=f"Welcome system is now **{status}**",
            color=color
        )
        await ctx.send(embed=embed, delete_after=10)

    @welcome.command(name="settings")
    @commands.has_permissions(manage_guild=True)
    async def show_settings(self, ctx):
        """Display current welcome system settings
        ---
        `!welcome settings` - View all current welcome settings
        """
        settings = await self.db.get_server_settings(ctx.guild.id)
        embed = discord.Embed(title="🛠️ Welcome System Settings", color=discord.Color.blue())
        embed.add_field(name="Status", value="✅ Enabled" if settings['welcome_enabled'] else "❌ Disabled", inline=True)
        channel = self.bot.get_channel(settings.get('welcome_channel_id'))
        embed.add_field(name="Welcome Channel", value=channel.mention if channel else "❌ Not set", inline=True)
        role = ctx.guild.get_role(settings.get('welcome_role_id'))
        embed.add_field(name="Auto-Role", value=role.mention if role else "❌ Not set", inline=True)
        embed.add_field(name="Auto-Role Assignment", value="✅ Enabled" if settings.get('auto_role_enabled') else "❌ Disabled", inline=True)
        embed.add_field(name="Welcome Message", value=f"```{settings.get('welcome_message', '')[:100]}...```", inline=False)
        await ctx.send(embed=embed)

    @commands.command(aliases=["join"], hidden=True)
    @commands.has_permissions(administrator=True)
    async def simulatejoin(self, ctx):
        """Test the welcome system by simulating a member join
        ---
        `!simulatejoin` - Test welcome message and auto-role assignment
        """
        settings = await self.db.get_server_settings(ctx.guild.id)
        await self._send_welcome(ctx.author, settings)
        await self._assign_welcome_role(ctx.author, settings)
        await ctx.send("✅ Simulated member join event! Check the welcome channel.", delete_after=5)
        await ctx.message.delete(delay=1)

async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
