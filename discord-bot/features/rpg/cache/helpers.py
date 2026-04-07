import asyncio
from typing import Optional, Any

from .instances import PLAYER_CACHE, INVENTORY_CACHE, EQUIPPED_CACHE, SKILLS_CACHE


async def get_player_cached(
    guild_id: int,
    user_id: int,
    fetch_fn,
) -> Optional[tuple]:
    return await PLAYER_CACHE.get_or_fetch(
        guild_id, user_id,
        fetch_fn=lambda g, u: fetch_fn(g, u),
    )


async def get_inventory_cached(
    guild_id: int,
    user_id: int,
    fetch_fn,
) -> list:
    return await INVENTORY_CACHE.get_or_fetch(
        guild_id, user_id,
        fetch_fn=lambda g, u: fetch_fn(g, u),
    )


async def get_equipped_cached(
    guild_id: int,
    user_id: int,
    fetch_fn,
) -> dict:
    return await EQUIPPED_CACHE.get_or_fetch(
        guild_id, user_id,
        fetch_fn=lambda g, u: fetch_fn(g, u),
    )


async def get_skills_cached(
    guild_id: int,
    user_id: int,
    fetch_fn,
) -> set:
    return await SKILLS_CACHE.get_or_fetch(
        guild_id, user_id,
        fetch_fn=lambda g, u: fetch_fn(g, u),
    )


async def invalidate_player(guild_id: int, user_id: int) -> None:
    await PLAYER_CACHE.invalidate(guild_id, user_id)


async def invalidate_inventory(guild_id: int, user_id: int) -> None:
    await INVENTORY_CACHE.invalidate(guild_id, user_id)


async def invalidate_equipped(guild_id: int, user_id: int) -> None:
    await EQUIPPED_CACHE.invalidate(guild_id, user_id)


async def invalidate_skills(guild_id: int, user_id: int) -> None:
    await SKILLS_CACHE.invalidate(guild_id, user_id)


async def invalidate_all(guild_id: int, user_id: int) -> None:
    await asyncio.gather(
        PLAYER_CACHE.invalidate(guild_id, user_id),
        INVENTORY_CACHE.invalidate(guild_id, user_id),
        EQUIPPED_CACHE.invalidate(guild_id, user_id),
        SKILLS_CACHE.invalidate(guild_id, user_id),
    )
