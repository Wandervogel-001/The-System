import os
import asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands
import threading
import sys
import logging
from database import MongoDatabaseManager
from support import (
    console_listener,
    load_cogs,
    reload_all_cogs,
    shutdown_procedure
)
import webserver

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")  # new env variable

if not TOKEN or not MONGO_URI:
    logger.error("Missing DISCORD_TOKEN or MONGO_URI in environment variables!")
    sys.exit(1)

# Configure intents
intents = discord.Intents.default()
intents.members = True  # Required for welcome messages and member tracking
intents.message_content = True  # Required for command processing
intents.guilds = True  # Required for guild events

# Initialize bot
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Initialize Mongo database
bot.db = MongoDatabaseManager(os.getenv("MONGO_URI"), db_name="GumBall")

@bot.event
async def on_ready():
    try:
        logger.info(f"Bot logged in as {bot.user.name}#{bot.user.discriminator}")
        logger.info(f"Bot ID: {bot.user.id}")
        logger.info(f"Connected to {len(bot.guilds)} guilds")

        await bot.db.initialize()
        await load_cogs(bot, logger)
        for guild in bot.guilds:
          # Sync global commands (for the badge)
          synced_global = await bot.tree.sync()
          logger.info(f"Synced {len(synced_global)} global commands")

        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(bot.guilds)} servers | !help"
            )
        )

        print(f"\n🤖 {bot.user.name} is now online!")
        print(f"📊 Connected to {len(bot.guilds)} servers")
        print(f"🔧 Loaded {len(bot.cogs)} cogs with {len(bot.commands)} commands")

        def start_console_listener(bot, logger):
            asyncio.run(console_listener(bot, logger))

        threading.Thread(target=start_console_listener, args=(bot, logger), daemon=True).start()

    except Exception as e:
        logger.error(f"Startup error: {e}")
        await shutdown_procedure(bot, logger)

@bot.event
async def on_member_join(member):
    if not bot.db:
        logger.warning(f"Database not available when {member} joined {member.guild.name}")
        return
    try:
        await bot.db.add_member(
            user_id=member.id,
            guild_id=member.guild.id,
            username=str(member),
            display_name=member.display_name,
            joined_at=member.joined_at or discord.utils.utcnow(),
            is_bot=member.bot
        )
        logger.info(f"Successfully processed join for {member} in {member.guild.name}")
    except Exception as e:
        logger.error(f"Error in on_member_join for {member}: {e}")

@bot.event
async def on_member_remove(member):
    if not bot.db:
        logger.warning(f"Database not available when {member} left {member.guild.name}")
        return
    try:
        success = await bot.db.remove_member(member.id, member.guild.id)
        if success:
            logger.info(f"Successfully processed leave for {member} in {member.guild.name}")
        else:
            logger.warning(f"Member {member} was not in database for {member.guild.name}")
    except Exception as e:
        logger.error(f"Error in on_member_remove for {member}: {e}")

@bot.event
async def on_guild_join(guild):
    try:
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        if bot.db:
            await bot.db.create_default_settings(guild.id)
            logger.info(f"Created default settings for {guild.name}")

        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(bot.guilds)} servers | !help"
            )
        )
    except Exception as e:
        logger.error(f"Error handling guild join: {e}")

@bot.event
async def on_guild_remove(guild):
    try:
        logger.info(f"Left guild: {guild.name} (ID: {guild.id})")
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(bot.guilds)} servers | !help"
            )
        )
    except Exception as e:
        logger.error(f"Error handling guild leave: {e}")

@bot.event
async def on_command_error(ctx, error):
    logger.error(f"Command error in {ctx.guild.name if ctx.guild else 'DM'}: {error}")
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Command not found. Use `!help` to see available commands.", delete_after=10)
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.", delete_after=10)
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send("❌ I don't have the required permissions to execute this command.", delete_after=10)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏰ Command on cooldown. Try again in {error.retry_after:.1f} seconds.", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: `{error.param.name}`. Use `!help {ctx.command.name}` for usage.", delete_after=15)
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument provided. Use `!help {ctx.command.name}` for usage.", delete_after=15)
    else:
        await ctx.send("❌ An unexpected error occurred. Please try again later.", delete_after=10)
        logger.exception(f"Unexpected error in command {ctx.command}: {error}")

@bot.command(name="reload", hidden=True)
@commands.is_owner()
async def reload_cog(ctx, cog_name: str = None):
    if cog_name:
        try:
            await bot.reload_extension(f"cogs.{cog_name.lower()}")
            await ctx.send(f"✅ Reloaded cog: {cog_name}")
        except Exception as e:
            await ctx.send(f"❌ Failed to reload {cog_name}: {e}")
    else:
        await reload_all_cogs(bot, logger)
        await ctx.send("✅ All cogs reloaded!")

@bot.command(name="clear_slash", hidden=True)
@commands.is_owner()
async def clear_slash(ctx):
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    await ctx.send("✅ All global slash commands cleared.")

@bot.command(name="resync", hidden=True)
@commands.is_owner()
async def resync(ctx):
    synced = 0
    for guild in bot.guilds:
        await bot.tree.sync(guild=guild)
        synced += 1
    await ctx.send(f"✅ Slash commands re-synced to {synced} guild(s).")


if __name__ == "__main__":
    try:
        webserver.keep_alive()
        bot.run(TOKEN, log_handler=None)
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
