import os
import discord
import asyncio
from database import MongoDatabaseManager
import sys

async def console_listener(bot, logger):
    """Enhanced console command listener"""
    print("\n=== Console Commands ===")
    print("shutdown - Gracefully shutdown the bot")
    print("restart - Restart bot presence")
    print("status - Show bot status")
    print("stats - Show database statistics")
    print("help - Show this help message")
    print("==========================\n")

    while True:
        try:
            cmd = input().strip().lower()

            if cmd == "shutdown":
                confirm = input("Confirm shutdown? (y/n): ").lower()
                if confirm == 'y':
                    print("Initiating shutdown sequence...")
                    asyncio.run_coroutine_threadsafe(
                        shutdown_procedure(bot, logger),
                        bot.loop
                    )
                else:
                    print("Shutdown cancelled")

            elif cmd == "restart":
                print("Restarting bot presence...")
                asyncio.run_coroutine_threadsafe(
                    restart_procedure(bot, logger),
                    bot.loop
                )

            elif cmd == "status":
                asyncio.run_coroutine_threadsafe(
                    show_status(bot, logger),
                    bot.loop
                )

            elif cmd == "stats":
                asyncio.run_coroutine_threadsafe(
                    show_database_stats(bot, logger),
                    bot.loop
                )

            elif cmd == "help":
                print("\n=== Available Commands ===")
                print("shutdown - Gracefully shutdown the bot")
                print("restart - Restart bot presence")
                print("status - Show bot status")
                print("stats - Show database statistics")
                print("help - Show this help message")
                print("==========================\n")

            elif cmd.strip() == "":
                continue

            else:
                print(f"Unknown command: '{cmd}'. Type 'help' for available commands.")

        except EOFError:
            print("\nConsole input ended. Bot continues running...")
            break
        except Exception as e:
            logger.error(f"Console listener error: {e}")

async def restart_procedure(bot, logger):
    try:
        print("Setting bot status to idle...")
        await bot.change_presence(status=discord.Status.idle)

        print("Reloading cogs...")
        await reload_all_cogs(bot, logger)

        print("Setting bot status back to online...")
        await bot.change_presence(status=discord.Status.online)

        print("Bot restart complete!")

    except Exception as e:
        logger.error(f"Restart procedure failed: {e}")
        print(f"Restart failed: {e}")

async def show_status(bot, logger):
    try:
        print(f"\n=== Bot Status ===")
        print(f"Bot Name: {bot.user.name}#{bot.user.discriminator}")
        print(f"Bot ID: {bot.user.id}")
        print(f"Connected Guilds: {len(bot.guilds)}")
        print(f"Total Members: {sum(len(guild.members) for guild in bot.guilds)}")
        print(f"Loaded Cogs: {len(bot.cogs)}")
        print(f"Registered Commands: {len(bot.commands)}")
        print(f"Latency: {round(bot.latency * 1000)}ms")

        if bot.db:
            stats = await bot.db.get_database_stats()
            print(f"Database - Servers: {stats.get('servers', 0)}")
            print(f"Database - Members: {stats.get('members', 0)}")
            print(f"Database - Mod Logs: {stats.get('mod_logs', 0)}")
        else:
            print("Database: Not connected")

        print("==================\n")

    except Exception as e:
        logger.error(f"Status display error: {e}")
        print(f"Status error: {e}")

async def show_database_stats(bot, logger):
    try:
        if not bot.db:
            print("Database not connected")
            return

        stats = await bot.db.get_database_stats()
        print(f"\n=== Database Statistics ===")
        print(f"Total Servers: {stats.get('servers', 0)}")
        print(f"Total Members: {stats.get('members', 0)}")
        print(f"Moderation Logs: {stats.get('mod_logs', 0)}")

        print(f"\n=== Per-Guild Breakdown ===")
        for guild in bot.guilds:
            members = await bot.db.get_server_members(guild.id, limit=1000)
            print(f"{guild.name}: {len(members)} tracked members")

        print("===========================\n")

    except Exception as e:
        logger.error(f"Database stats error: {e}")
        print(f"\u274c Database stats error: {e}")

async def shutdown_procedure(bot, logger):
    try:
        print("Starting graceful shutdown...")

        await bot.change_presence(status=discord.Status.invisible)

        if bot.db:
            print("Database connection closing (MongoDB handled automatically)")

        print("Shutdown preparation complete")
        await bot.close()

    except Exception as e:
        logger.error(f"Shutdown error: {e}")
        print(f"Shutdown error: {e}")

    finally:
        print("Bot offline. Exiting...")
        sys.exit(0)

async def load_cogs(bot, logger):
    cogs_dir = "./cogs"
    if not os.path.exists(cogs_dir):
        logger.warning("Cogs directory not found. Creating...")
        os.makedirs(cogs_dir)
        return

    loaded_count = 0
    failed_count = 0

    for filename in os.listdir(cogs_dir):
        if filename.endswith(".py") and not filename.startswith("_"):
            cog_name = filename[:-3]
            try:
                await bot.load_extension(f"cogs.{cog_name}")
                logger.info(f"Loaded cog: {cog_name}")
                loaded_count += 1
            except Exception as e:
                logger.error(f"Failed to load cog {cog_name}: {e}")
                failed_count += 1

    print(f"Cog loading complete: {loaded_count} loaded, {failed_count} failed")
    print("Loaded cogs:", list(bot.cogs.keys()))

async def reload_all_cogs(bot, logger):
    cogs_dir = "./cogs"
    if not os.path.exists(cogs_dir):
        logger.warning("Cogs directory not found. Creating...")
        os.makedirs(cogs_dir)
        return

    reloaded_count = 0
    failed_count = 0

    for filename in os.listdir(cogs_dir):
        if filename.endswith(".py") and not filename.startswith("_"):
            cog_name = filename[:-3]
            try:
                await bot.reload_extension(f"cogs.{cog_name}")
                logger.info(f"Reloaded cog: {cog_name}")
                reloaded_count += 1
            except Exception as e:
                logger.error(f"Failed to reload cog {cog_name}: {e}")
                failed_count += 1

    print(f"Cog reloading complete: {reloaded_count} reloaded, {failed_count} failed")
