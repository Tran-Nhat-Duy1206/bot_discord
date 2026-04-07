import asyncio
import time
import copy
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Any


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


@dataclass
class _PendingRequest:
    event: asyncio.Event
    value: Any


class TTLCache:
    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: float = 10.0,
        num_shards: int = 16,
        purge_interval: float = 60.0,
    ):
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._num_shards = num_shards
        self._purge_interval = purge_interval
        
        self._shards: list[OrderedDict[tuple, CacheEntry]] = [
            OrderedDict() for _ in range(num_shards)
        ]
        self._shard_locks: list[asyncio.Lock] = [
            asyncio.Lock() for _ in range(num_shards)
        ]
        self._pending: list[dict[tuple, _PendingRequest]] = [
            {} for _ in range(num_shards)
        ]
        self._pending_locks: list[asyncio.Lock] = [
            asyncio.Lock() for _ in range(num_shards)
        ]
        
        self._stats_lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        
        self._purge_task: Optional[asyncio.Task] = None
        self._running = False
        self._global_lock = asyncio.Lock()

    def _get_shard_index(self, key: tuple) -> int:
        return hash(key) % self._num_shards

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._purge_task = asyncio.create_task(self._purge_loop())

    async def stop(self) -> None:
        self._running = False
        if self._purge_task:
            self._purge_task.cancel()
            try:
                await self._purge_task
            except asyncio.CancelledError:
                pass
        async with self._global_lock:
            pass

    async def _purge_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._purge_interval)
            await self.purge_expired()

    async def purge_expired(self) -> int:
        now = time.monotonic()
        purged = 0
        for i in range(self._num_shards):
            async with self._shard_locks[i]:
                shard = self._shards[i]
                expired_keys = [k for k, e in shard.items() if now > e.expires_at]
                for key in expired_keys:
                    del shard[key]
                    purged += 1
        return purged

    async def get(self, *args: Any) -> Optional[Any]:
        key = tuple(args)
        shard_idx = self._get_shard_index(key)
        now = time.monotonic()
        
        async with self._shard_locks[shard_idx]:
            shard = self._shards[shard_idx]
            entry = shard.get(key)
            
            if entry is None:
                async with self._stats_lock:
                    self._misses += 1
                return None
            
            if now > entry.expires_at:
                del shard[key]
                async with self._stats_lock:
                    self._misses += 1
                return None
            
            shard.move_to_end(key)
            async with self._stats_lock:
                self._hits += 1
            
            value = entry.value
            if isinstance(value, (list, dict, set)):
                return copy.deepcopy(value)
            return value

    async def set(self, value: Any, *args: Any, ttl: Optional[float] = None) -> None:
        key = tuple(args)
        shard_idx = self._get_shard_index(key)
        ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.monotonic() + ttl
        
        async with self._shard_locks[shard_idx]:
            shard = self._shards[shard_idx]
            
            if key not in shard and len(shard) >= self._max_size:
                shard.popitem(last=False)
                async with self._stats_lock:
                    self._evictions += 1
            
            if isinstance(value, (list, dict, set)):
                value = copy.deepcopy(value)
            shard[key] = CacheEntry(value=value, expires_at=expires_at)
            shard.move_to_end(key)

    async def get_or_fetch(
        self,
        *args: Any,
        fetch_fn,
        ttl: Optional[float] = None,
    ) -> Any:
        key = tuple(args)
        shard_idx = self._get_shard_index(key)
        now = time.monotonic()
        
        async with self._shard_locks[shard_idx]:
            shard = self._shards[shard_idx]
            entry = shard.get(key)
            
            if entry is not None and now <= entry.expires_at:
                shard.move_to_end(key)
                async with self._stats_lock:
                    self._hits += 1
                value = entry.value
                if isinstance(value, (list, dict, set)):
                    return copy.deepcopy(value)
                return value
        
        pending = None
        async with self._pending_locks[shard_idx]:
            pending_map = self._pending[shard_idx]
            if key in pending_map:
                pending = pending_map[key]
        
        if pending is not None:
            await pending.event.wait()
            async with self._shard_locks[shard_idx]:
                shard = self._shards[shard_idx]
                entry = shard.get(key)
                if entry is not None:
                    value = entry.value
                    if isinstance(value, (list, dict, set)):
                        return copy.deepcopy(value)
                    return value
            return pending.value
        
        event = asyncio.Event()
        async with self._pending_locks[shard_idx]:
            self._pending[shard_idx][key] = _PendingRequest(event=event, value=None)
        
        try:
            value = await fetch_fn(*args)
            
            async with self._shard_locks[shard_idx]:
                shard = self._shards[shard_idx]
                if key not in shard and len(shard) >= self._max_size:
                    shard.popitem(last=False)
                    async with self._stats_lock:
                        self._evictions += 1
                
                ttl_val = ttl if ttl is not None else self._default_ttl
                expires_at = time.monotonic() + ttl_val
                
                if isinstance(value, (list, dict, set)):
                    value_copy = copy.deepcopy(value)
                else:
                    value_copy = value
                    
                shard[key] = CacheEntry(value=value_copy, expires_at=expires_at)
                shard.move_to_end(key)
            
            async with self._pending_locks[shard_idx]:
                self._pending[shard_idx][key].value = value
                self._pending[shard_idx][key].event.set()
        except Exception as e:
            async with self._pending_locks[shard_idx]:
                self._pending[shard_idx].pop(key, None)
                if key in self._pending[shard_idx]:
                    self._pending[shard_idx][key].event.set()
            raise
        
        async with self._pending_locks[shard_idx]:
            self._pending[shard_idx].pop(key, None)
        
        async with self._stats_lock:
            self._misses += 1
        
        return value

    async def invalidate(self, *args: Any) -> None:
        key = tuple(args)
        shard_idx = self._get_shard_index(key)
        
        async with self._shard_locks[shard_idx]:
            self._shards[shard_idx].pop(key, None)

    async def invalidate_many(self, keys: list[tuple]) -> int:
        count = 0
        for key in keys:
            shard_idx = self._get_shard_index(key)
            async with self._shard_locks[shard_idx]:
                if self._shards[shard_idx].pop(key, None) is not None:
                    count += 1
        return count

    async def clear(self) -> None:
        for i in range(self._num_shards):
            async with self._shard_locks[i]:
                self._shards[i].clear()
        async with self._stats_lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    async def stats(self) -> dict:
        async with self._stats_lock:
            total = self._hits + self._misses
            total_size = sum(len(s) for s in self._shards)
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "size": total_size,
                "hit_rate": self._hits / total if total > 0 else 0.0,
            }
