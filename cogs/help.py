import discord
from discord.ext import commands
from typing import Optional

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _is_admin(self, ctx) -> bool:
        """Check if user is admin or owner"""
        return ctx.author.guild_permissions.administrator or ctx.author.id == self.bot.owner_id

    @commands.command(name="help")
    async def custom_help(self, ctx, *, search_term: Optional[str] = None):
        """Shows help information
        ---
        `!help` - Basic command list (admin: shows admin overview)
        `!help basic` - Force basic command list (admin only)
        `!help <command>` - Details about a command
        `!help <category>` - List commands in category (admin only)
        """
        is_admin = self._is_admin(ctx)
        
        # Special case: admin requesting basic help
        if is_admin and search_term and search_term.lower() == "basic":
            return await self._show_basic_help(ctx)
            
        if not search_term:
            return await self._show_admin_help(ctx) if is_admin else await self._show_basic_help(ctx)
        
        # Try to find command first
        if command := self.bot.get_command(search_term.lower()):
            if not command.hidden or is_admin:
                return await self._show_command_help(ctx, command)
        
        # If admin, try to find cog
        if is_admin and (cog := self._find_cog(search_term)):
            return await self._show_cog_help(ctx, cog)
        
        # No matches found
        await self._handle_no_match(ctx, search_term, is_admin)

    async def _show_basic_help(self, ctx):
        """Simplified help for regular members (also used for admin testing)"""
        embed = discord.Embed(
            title="Available Commands",
            description="Use `!help <command>` for details",
            color=discord.Color.blue()
        )
        
        commands_list = [
            f"`{cmd.name}` - {cmd.help.split('---')[0].strip() if cmd.help else 'No description'}"
            for cmd in self.bot.commands if not cmd.hidden
        ]
        
        if commands_list:
            embed.add_field(
                name="Commands", 
                value="\n".join(commands_list) or "No commands available",
                inline=False
            )
        
        await ctx.send(embed=embed)

    def _find_cog(self, search_term: str) -> Optional[commands.Cog]:
        """Find cog by name with flexible matching"""
        search_term = search_term.lower()
        return next(
            (cog for cog in self.bot.cogs.values() 
             if search_term in cog.qualified_name.lower()),
            None
        )

    async def _show_command_help(self, ctx, command):
        """Display detailed help for a single command"""
        help_text = command.help or "No description provided."
        main_help, *usage = help_text.split("---", 1)
        
        embed = discord.Embed(
            title=f"`{ctx.prefix}{command.name}`",
            description=main_help.strip(),
            color=discord.Color.green()
        )
        
        if usage:
            embed.add_field(name="📝 Usage", value=usage[0].strip(), inline=False)
        if command.aliases:
            embed.add_field(name="🔀 Aliases", value=", ".join(f"`{alias}`" for alias in command.aliases), inline=False)
        if command.hidden and self._is_admin(ctx):
            embed.set_footer(text="⚠️ Hidden command (admin only)")
        
        await ctx.send(embed=embed)

    async def _show_cog_help(self, ctx, cog):
        """Display all commands in a cog (admin only)"""
        embed = discord.Embed(
            title=f"🔧 {cog.qualified_name}",
            description=cog.description or "",
            color=discord.Color.blue()
        )
        
        for cmd in cog.get_commands():
            brief = cmd.help.split("---")[0].strip() if cmd.help else "No description"
            embed.add_field(
                name=f"`{ctx.prefix}{cmd.name}`" + (" 👁️" if cmd.hidden else ""),
                value=brief,
                inline=False
            )
        
        await ctx.send(embed=embed)

    async def _show_admin_help(self, ctx):
        """Full help menu for admins"""
        embed = discord.Embed(
            title="Admin Command Overview",
            description="Use `!help <command/category>` for details",
            color=discord.Color.gold()
        )
        
        for cog_name, cog in sorted(self.bot.cogs.items()):
            if commands := cog.get_commands():
                embed.add_field(
                    name=f"🔹 {cog.qualified_name}",
                    value=", ".join(f"`{cmd.name}`" for cmd in commands),
                    inline=False
                )
        
        await ctx.send(embed=embed)

    async def _handle_no_match(self, ctx, search_term: str, is_admin: bool):
        """Handle cases where no command/cog is found"""
        if is_admin:
            all_options = (
                [cog.qualified_name for cog in self.bot.cogs.values()] +
                [cmd.name for cmd in self.bot.commands] +
                ["basic"]  # Include the basic help command in suggestions
            )
            suggestions = [
                opt for opt in all_options 
                if search_term.lower() in opt.lower()
            ][:3]
            
            if suggestions:
                await ctx.send(f"❌ No exact match. Did you mean: {', '.join(f'`{s}`' for s in suggestions)}?")
            else:
                await ctx.send(f"❌ No command/category named `{search_term}` found.")
        else:
            await ctx.send(f"Command `{search_term}` not found. Try `!help`")

async def setup(bot):
    await bot.add_cog(HelpCog(bot))