from .ttl import TTLCache

PLAYER_CACHE = TTLCache(max_size=2000, default_ttl=30.0)
INVENTORY_CACHE = TTLCache(max_size=2000, default_ttl=15.0)
EQUIPPED_CACHE = TTLCache(max_size=2000, default_ttl=20.0)
SKILLS_CACHE = TTLCache(max_size=2000, default_ttl=30.0)
QUERY_CACHE = TTLCache(max_size=500, default_ttl=5.0)
