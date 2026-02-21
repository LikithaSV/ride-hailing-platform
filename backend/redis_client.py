import json
import time
from collections.abc import Callable

import redis

from backend.config import settings


class LocalTTLCache:
    def __init__(self):
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str):
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._store.pop(key, None)
            return None
        return json.loads(value)

    def set(self, key: str, value: dict, ttl_sec: int):
        self._store[key] = (time.time() + ttl_sec, json.dumps(value))


_local_cache = LocalTTLCache()


def get_redis_client():
    if not settings.redis_enabled:
        return None
    try:
        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def cached_json(key: str, ttl_sec: int, producer: Callable[[], dict]):
    redis_client = get_redis_client()
    if redis_client:
        raw = redis_client.get(key)
        if raw:
            return json.loads(raw)
        value = producer()
        redis_client.setex(key, ttl_sec, json.dumps(value))
        return value

    local = _local_cache.get(key)
    if local is not None:
        return local
    value = producer()
    _local_cache.set(key, value, ttl_sec)
    return value
