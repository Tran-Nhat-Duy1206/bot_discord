from .data import CRAFT_RECIPES
from .db import add_inventory, remove_inventory


_RECIPES_BY_ID = {str(r.get("id")): r for r in CRAFT_RECIPES}


def list_recipes():
    return CRAFT_RECIPES


def get_recipe(recipe_id: str):
    return _RECIPES_BY_ID.get(str(recipe_id))


async def craft_recipe(conn, guild_id: int, user_id: int, recipe_id: str, amount: int = 1) -> tuple[bool, str]:
    if amount <= 0:
        return False, "Amount phải > 0."

    recipe = get_recipe(recipe_id)
    if not recipe:
        return False, "Recipe không tồn tại."

    cost_gold = int(recipe.get("gold", 0)) * amount
    requires = recipe.get("requires", {}) or {}
    output = recipe.get("output", {}) or {}

    async with conn.execute(
        "SELECT gold FROM players WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    cur_gold = int(row[0]) if row else 0
    if cur_gold < cost_gold:
        return False, "Không đủ gold để craft."

    consumed: list[tuple[str, int]] = []
    for item_id, req in requires.items():
        need = int(req) * amount
        ok = await remove_inventory(conn, guild_id, user_id, str(item_id), need)
        if not ok:
            for rollback_item, rollback_qty in consumed:
                await add_inventory(conn, guild_id, user_id, rollback_item, rollback_qty)
            return False, f"Thiếu nguyên liệu: `{item_id}` x{need}"
        consumed.append((str(item_id), need))

    await conn.execute(
        "UPDATE players SET gold = gold - ? WHERE guild_id = ? AND user_id = ?",
        (cost_gold, guild_id, user_id),
    )

    for item_id, qty in output.items():
        give = int(qty) * amount
        await add_inventory(conn, guild_id, user_id, str(item_id), give)

    return True, "crafted"
