import os
import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorClient
from bson.objectid import ObjectId
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

class MongoDatabaseManager:
    def __init__(self, uri: str, db_name: str = "TheSystem"):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client[db_name]
        self.members = self.db.members
        self.settings = self.db.server_settings
        self.mod_logs = self.db.moderation_logs

    async def initialize(self):
        logger.info("MongoDB connected and initialized.")

    # ========== SERVER SETTINGS ==========

    async def get_server_settings(self, guild_id: int) -> Dict[str, Any]:
        settings = await self.settings.find_one({"guild_id": guild_id})
        if settings:
            return settings
        return await self.create_default_settings(guild_id)

    async def create_default_settings(self, guild_id: int) -> Dict[str, Any]:
        default_settings = {
            "guild_id": guild_id,
            "welcome_channel_id": None,
            "welcome_role_id": None,
            "welcome_message": "Welcome to {guild_name}, {user_mention}!",
            "auto_role_enabled": True,
            "welcome_enabled": True,
            "settings_json": {},
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await self.settings.insert_one(default_settings)
        return default_settings

    async def update_server_setting(self, guild_id: int, setting: str, value: Any):
        await self.settings.update_one(
            {"guild_id": guild_id},
            {"$set": {setting: value, "updated_at": datetime.utcnow()}},
            upsert=True
        )

    # ========== MEMBER DATA ==========

    async def add_member(self, user_id: int, guild_id: int, username: str,
                     display_name: str, joined_at: datetime, is_bot: bool = False) -> int:
      join_position = await self.calculate_join_position(guild_id, joined_at)
      await self.members.update_one(
          {"user_id": user_id, "guild_id": guild_id},
          {"$set": {
              "username": username,
              "display_name": display_name,
              "joined_at": joined_at,
              "join_position": join_position,
              "is_bot": is_bot,
              "habit_count": 0,
              "last_increment": None,
              "last_active": datetime.utcnow(),
              "updated_at": datetime.utcnow()
          }, "$setOnInsert": {"created_at": datetime.utcnow()}},
          upsert=True
      )
      return join_position

    async def remove_member(self, user_id: int, guild_id: int) -> bool:
        result = await self.members.delete_one({"user_id": user_id, "guild_id": guild_id})
        return result.deleted_count > 0

    async def update_member(self, user_id: int, guild_id: int, **kwargs):
        allowed_fields = ["username", "display_name", "last_active", "last_increment"]  # Added last_increment
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if update_fields:
            update_fields["updated_at"] = datetime.utcnow()
            await self.members.update_one(
                {"user_id": user_id, "guild_id": guild_id},
                {"$set": update_fields}
            )

    async def increment_habit(self, user_id: int, guild_id: int) -> str:
      user = await self.get_member(user_id, guild_id)
      now = datetime.now(timezone.utc)

      last = user.get("last_increment")

      if last:
          # Convert to offset-aware datetime
          if last.tzinfo is None:
              last = last.replace(tzinfo=timezone.utc)

          if last.date() == now.date():
              return "already_incremented"  # User already pressed today

      await self.members.update_one(
          {"user_id": user_id, "guild_id": guild_id},
          {
              "$inc": {"habit_count": 1},
              "$set": {
                  "last_increment": now,
                  "updated_at": now
              }
          }
      )
      return "incremented"

    async def get_top_habit_members(self, guild_id: int, limit: int = 10):
      cursor = self.members.find({
          "guild_id": guild_id,
          "habit_count": {"$gte": 1}
      }).sort("habit_count", -1).limit(limit)
      return await cursor.to_list(length=limit)

    async def get_member(self, user_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
        return await self.members.find_one({"user_id": user_id, "guild_id": guild_id})

    async def get_server_members(self, guild_id: int, limit: int = 100, skip: int = 0) -> List[Dict[str, Any]]:
        cursor = self.members.find({"guild_id": guild_id}).sort("join_position", 1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def calculate_join_position(self, guild_id: int, joined_at: datetime) -> int:
        count = await self.members.count_documents({
            "guild_id": guild_id,
            "joined_at": {"$lt": joined_at},
            "is_bot": False
        })
        return count + 1

    # ========== MODERATION LOGS ==========

    async def log_moderation_action(self, guild_id: int, user_id: int, moderator_id: int,
                                     action_type: str, reason: str = None, duration: str = None):
        await self.mod_logs.insert_one({
            "guild_id": guild_id,
            "user_id": user_id,
            "moderator_id": moderator_id,
            "action_type": action_type,
            "reason": reason,
            "duration": duration,
            "created_at": datetime.utcnow()
        })

    async def get_moderation_history(self, guild_id: int, user_id: int = None, limit: int = 50) -> List[Dict[str, Any]]:
        query = {"guild_id": guild_id}
        if user_id:
            query["user_id"] = user_id
        cursor = self.mod_logs.find(query).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    # ========== UTILITIES ==========

    async def cleanup_old_data(self, days: int = 90):
        threshold_date = datetime.utcnow() - timedelta(days=days)
        result = await self.members.delete_many({"last_active": {"$lt": threshold_date}})
        logger.info(f"Deleted {result.deleted_count} inactive members")

    async def get_database_stats(self) -> Dict[str, int]:
        return {
            "servers": await self.settings.count_documents({}),
            "members": await self.members.count_documents({}),
            "mod_logs": await self.mod_logs.count_documents({})
        }

    async def delete_guild_data(self, guild_id: int):
        await self.settings.delete_one({"guild_id": guild_id})
        await self.members.delete_many({"guild_id": guild_id})
        await self.mod_logs.delete_many({"guild_id": guild_id})
        logger.info(f"Deleted all data for guild_id {guild_id}")
