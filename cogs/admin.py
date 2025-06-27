import discord
from discord.ext import commands
from typing import Optional, Union
from datetime import timedelta
import logging

# Set up logger for this module
logger = logging.getLogger(__name__)

class Admin(commands.Cog, name="AdminCog"):
    """Collection of administrator commands"""
    def __init__(self, bot):
        self.bot = bot

    async def ctx_prompt(self, ctx, message: str, timeout: int = 30):
        """Custom prompt function since ctx.prompt doesn't exist in discord.py"""
        embed = discord.Embed(
            title="⚠️ Confirmation Required",
            description=f"{message}\n\nReact with ✅ to confirm or ❌ to cancel.",
            color=discord.Color.orange()
        )
        
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
        
        def check(reaction, user):
            return (user == ctx.author and 
                   str(reaction.emoji) in ["✅", "❌"] and 
                   reaction.message.id == msg.id)
        
        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=timeout, check=check)
            await msg.delete()
            return str(reaction.emoji) == "✅"
        except:
            await msg.delete()
            return False

    @commands.command()
    @commands.has_permissions(administrator=True, ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason="No reason provided"):
        """Bans a member from the server
        ---
        `!ban @user [reason]` - Bans the specified user
        Example: `!ban @spammer Breaking rules`
        """
        # Confirmation check
        confirm = await self.ctx_prompt(ctx, f"Are you sure you want to ban {member.mention}?", timeout=30)
        if not confirm:
            await ctx.send("Ban cancelled.")
            return

        try:
            await member.ban(reason=f"By {ctx.author}: {reason}")
            embed = discord.Embed(
                title="🔨 User Banned",
                description=f"{member.mention} was banned by {ctx.author.mention}",
                color=discord.Color.red()
            )
            embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed)
            logger.info(f"{ctx.author} banned {member} for: {reason}")
            
            # Log to database if available
            if self.bot.db:
                try:
                    await self.bot.db.db.log_moderation_action(
                        guild_id=ctx.guild.id,
                        moderator_id=ctx.author.id,
                        target_id=member.id,
                        action="ban",
                        reason=reason
                    )
                except Exception as e:
                    logger.warning(f"Failed to log ban to database: {e}")
                    
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to ban that user!")
        except discord.HTTPException as e:
            await ctx.send(f"❌ Failed to ban: {e}")
            logger.error(f"Ban error: {e}")

    @commands.command(aliases=["fuckoff"])
    @commands.has_permissions(administrator=True, kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason="No reason provided"):
        """Kicks a member from the server
        ---
        `!kick @user [reason]` - Kicks the specified user
        Example: `!kick @troublemaker Being disruptive`
        """
        try:
            await member.kick(reason=f"By {ctx.author}: {reason}")
            embed = discord.Embed(
                title="👢 User Kicked",
                description=f"{member.mention} was kicked by {ctx.author.mention}",
                color=discord.Color.orange()
            )
            embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed)
            logger.info(f"{ctx.author} kicked {member} for: {reason}")
            
            # Log to database if available
            if self.bot.db:
                try:
                    await self.bot.db.db.log_moderation_action(
                        guild_id=ctx.guild.id,
                        user_id=member.id,        # Changed from target_id to user_id
                        moderator_id=ctx.author.id,
                        action_type="kick",       # Changed from action to action_type
                        reason=reason
                    )
                    logger.info(f"Successfully logged kick of {member} to database")
                except Exception as e:
                    logger.warning(f"Failed to log kick to database: {e}")
                    
        except Exception as e:
            await ctx.send(f"❌ Failed to kick: {e}")
            logger.error(f"Kick error: {e}")

    @commands.command()
    @commands.has_permissions(administrator=True, moderate_members=True)
    async def mute(self, ctx, member: discord.Member, *, reason="No reason provided"):
        """Timeouts a member (1 hour)
        ---
        `!mute @user [reason]` - Mutes user for 1 hour
        Example: `!mute @noisy Spamming`
        """
        try:
            duration = timedelta(hours=1)
            await member.timeout(duration, reason=f"By {ctx.author}: {reason}")
            embed = discord.Embed(
                title="🔇 User Muted",
                description=f"{member.mention} muted by {ctx.author.mention} for 1 hour",
                color=discord.Color.dark_grey()
            )
            embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed)
            logger.info(f"{ctx.author} muted {member} for: {reason}")
            
            # Log to database if available
            if self.bot.db:
                try:
                    await self.bot.db.db.log_moderation_action(
                        guild_id=ctx.guild.id,
                        moderator_id=ctx.author.id,
                        target_id=member.id,
                        action="mute",
                        reason=reason,
                        duration=3600  # 1 hour in seconds
                    )
                except Exception as e:
                    logger.warning(f"Failed to log mute to database: {e}")
                    
        except Exception as e:
            await ctx.send(f"❌ Failed to mute: {e}")
            logger.error(f"Mute error: {e}")

    @commands.command()
    @commands.has_permissions(administrator=True, moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, duration: str, *, reason="No reason provided"):
        """Custom duration timeout
        ---
        `!timeout @user 30m [reason]` - Timeout for 30 minutes
        Supports: m (minutes), h (hours), d (days)
        Example: `!timeout @rulebreaker 2h Being rude`
        """
        try:
            # Parse duration (e.g. "30m", "2h", "1d")
            unit = duration[-1].lower()
            value = int(duration[:-1])
            
            if unit == 'm':
                delta = timedelta(minutes=value)
                duration_seconds = value * 60
            elif unit == 'h':
                delta = timedelta(hours=value)
                duration_seconds = value * 3600
            elif unit == 'd':
                delta = timedelta(days=value)
                duration_seconds = value * 86400
            else:
                await ctx.send("❌ Invalid duration unit. Use m/h/d (e.g. 30m, 2h, 1d)")
                return
                
            await member.timeout(delta, reason=f"By {ctx.author}: {reason}")
            embed = discord.Embed(
                title="⏳ User Timed Out",
                description=f"{member.mention} timed out by {ctx.author.mention} for {duration}",
                color=discord.Color.dark_purple()
            )
            embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed)
            logger.info(f"{ctx.author} timed out {member} for {duration}: {reason}")
            
            # Log to database if available
            if self.bot.db:
                try:
                    await self.bot.db.db.log_moderation_action(
                        guild_id=ctx.guild.id,
                        moderator_id=ctx.author.id,
                        target_id=member.id,
                        action="timeout",
                        reason=reason,
                        duration=duration_seconds
                    )
                except Exception as e:
                    logger.warning(f"Failed to log timeout to database: {e}")
                    
        except Exception as e:
            await ctx.send(f"❌ Failed to timeout: {e}\nUsage: `!timeout @user 30m [reason]`")
            logger.error(f"Timeout error: {e}")

    @commands.command(aliases=["purge", "delete"], hidden=True)
    @commands.has_permissions(administrator=True)
    async def clear(self, ctx, *, args: str = "5"):
        """Clears messages in current or specified channel.
        ---
        `!clear` - clears 5 messages in current channel
        `!clear max` - clears 100 messages in current channel
        `!clear {x}` - clears X messages in current channel
        `!clear <#channel>` - clears 5 messages in mentioned channel
        `!clear <#channel> max` - clears 100 messages in mentioned channel
        `!clear <#channel> {x}` - clears X messages in mentioned channel
        """
        try:
            # Initialize default values
            amount = 5
            channel = ctx.channel
            
            # Check if args starts with channel mention
            if args.startswith("<#") and ">" in args:
                parts = args.split(">", 1)
                channel_id = parts[0][2:]  # Extract channel ID
                
                # Validate channel ID
                if not channel_id.strip():
                    await ctx.send("Please specify a valid channel mention!")
                    return
                    
                channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(int(channel_id))
                
                # Process amount if provided after channel mention
                if parts[1].strip():
                    amount_str = parts[1].strip().lower()
                    if amount_str == "max":
                        amount = 100
                    else:
                        try:
                            amount = int(amount_str)
                        except ValueError:
                            await ctx.send("Please provide a valid number or 'max'!")
                            return
            else:
                # No channel mention, treat whole args as amount
                if args.lower() == "max":
                    amount = 100
                else:
                    try:
                        amount = int(args)
                    except ValueError:
                        await ctx.send("Please provide a valid number, 'max', or channel mention!")
                        return

            # Validate amount
            if amount < 1 or amount > 100:
                await ctx.send("Please specify a number between 1 and 100.")
                return
                
            # Check permissions
            if not channel.permissions_for(ctx.author).manage_messages:
                await ctx.send("You don't have permission to manage messages in that channel!")
                return
            if not channel.permissions_for(ctx.guild.me).manage_messages:
                await ctx.send("I don't have permission to manage messages in that channel!")
                return
                
            # Only add +1 to limit if we're clearing in the same channel as command
            if channel == ctx.channel:
                deleted = await channel.purge(limit=amount + 1)  # Include command message
                actual_deleted = len(deleted) - 1
            else:
                deleted = await channel.purge(limit=amount)
                actual_deleted = len(deleted)
                
            # Send confirmation message that auto-deletes
            success_msg = await ctx.send(f"✅ Cleared {actual_deleted} messages in {channel.mention}.")
            await success_msg.delete(delay=3)

        except discord.NotFound:
            await ctx.send("Channel not found!")
        except discord.Forbidden:
            await ctx.send("I don't have permission to manage messages in that channel!")
        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}")
            logger.error(f"Clear command error: {e}")

    @commands.command(hidden=True)
    @commands.has_permissions(administrator=True)
    async def say(self, ctx, *, message):
        """Makes the bot say something in the specified channel or in the current channel by default.
        ---
        `!say {message}` - say something in current channel
        `!say <#channel> {message}` - say something in the specified channel
        """
        # Check if message starts with a channel mention
        if message.startswith("<#") and ">" in message:
            try:
                # Split channel mention and actual message
                split_msg = message.split(">", 1)
                channel_part = split_msg[0][2:]  # Extract the part between <# and >
                
                # Validate channel ID exists between <# and >
                if not channel_part.strip():  # Empty channel ID case
                    await ctx.send("Please specify a valid channel mention!")
                    return
                    
                channel_id = int(channel_part)
                actual_message = split_msg[1].strip()
                
                # Check if message is empty after channel mention
                if not actual_message:
                    await ctx.send("Please include a message to send!")
                    return

                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                
                # Permission checks
                if not channel.permissions_for(ctx.author).send_messages:
                    await ctx.send("You don't have permission to send messages there!")
                    return
                if not channel.permissions_for(ctx.guild.me).send_messages:
                    await ctx.send("I don't have permission to send messages there!")
                    return
                    
                await channel.send(actual_message)
                await ctx.message.delete()  # Delete the command message
            
            except ValueError:
                await ctx.send("Invalid channel format! Please use a proper channel mention.")
            except discord.NotFound:
                await ctx.send("Channel not found!")
            except discord.Forbidden:
                await ctx.send("I don't have permission to send messages there!")
            except discord.HTTPException as e:
                await ctx.send(f"An error occurred: {e}")
            
        else:
            # Regular message in current channel
            if not message.strip():
                await ctx.send("Please include a message to send!")
                return
            
            await ctx.send(message)
            await ctx.message.delete()

    @commands.command(hidden=True)
    @commands.has_permissions(administrator=True)
    async def edit(self, ctx, message_reference: Optional[Union[discord.TextChannel, int]], *, new_content: str = None):
        """Edits the bot's own messages in any channel
        ---
        `!edit <message_id> <new_content>` - Edits bot's message in current channel
        `!edit #channel <message_id> <new_content>` - Edits bot's message in specified channel
        Example:
        `!edit 1234567890 Updated text`
        `!edit #general 987654321 New announcement`
        """
        if new_content is None:
            await ctx.send("❌ Please provide new message content!", delete_after=10)
            return

        try:
            # Parse channel and message ID
            if isinstance(message_reference, discord.TextChannel):
                # Format: !edit #channel message_id new_content
                channel = message_reference
                try:
                    message_id = int(new_content.split()[0])
                    new_content = ' '.join(new_content.split()[1:])
                except (ValueError, IndexError):
                    await ctx.send("❌ Invalid format. Use `!edit #channel message_id new_content`", delete_after=10)
                    return
            else:
                # Format: !edit message_id new_content
                channel = ctx.channel
                message_id = message_reference

            # Fetch the message
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                await ctx.send(f"❌ Message not found in {channel.mention}!", delete_after=10)
                return
            except discord.Forbidden:
                await ctx.send(f"❌ No permission to access {channel.mention}!", delete_after=10)
                return

            # Verify it's the bot's message
            if message.author.id != self.bot.user.id:
                await ctx.send("❌ I can only edit my own messages!", delete_after=10)
                return

            # Edit the message
            await message.edit(content=new_content)
            await ctx.send(f"✅ Message edited in {channel.mention}!", delete_after=2)
            await ctx.message.delete()

        except Exception as e:
            await ctx.send(f"❌ Error: {e}\nUsage: `!edit [#channel] <message_id> <new_content>`", delete_after=15)
            logger.error(f"Edit error: {e}")

    @commands.command(hidden=True)
    @commands.has_permissions(administrator=True)
    async def shutdown(self, ctx):
        """Shuts down the bot."""
        await ctx.send("Shutting down...")
        await self.bot.close()

async def setup(bot):
    await bot.add_cog(Admin(bot))
        
