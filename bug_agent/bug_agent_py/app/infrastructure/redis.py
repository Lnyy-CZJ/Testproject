"""
Redis 异步客户端

替代 Go 版 cache/redis.go，提供 Redis 连接和基础操作。
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.config import settings

# Redis 异步客户端（全局单例）
redis_client = aioredis.from_url(
    settings.redis.url,
    decode_responses=True,
    max_connections=20,
)