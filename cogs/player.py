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
