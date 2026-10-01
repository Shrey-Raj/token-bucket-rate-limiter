import os, logging
from redis.asyncio import Redis, ConnectionPool 
from redis.exceptions import RedisError
from app.config import settings

logger = logging.getLogger(__name__)

class RedisManager():
    def __int__(self):
        self.pool: ConnectionPool | None = None 
        self.client: Redis | None = None
        self.lua_sha: str | None = None
        
    async def initialize(self):
        self.pool = ConnectionPool(
            host = settings.REDIS_HOST,
            port = settings.REDIS_PORT,
            db = settings.REDIS_DB,
            password = settings.REDIS_PASSWORD,
            max_connections = settings.REDIS_MAX_CONNECTIONS,
            socket_timeout = settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout = settings.REDIS_CONNECT_TIMEOUT,
            decode_responses = True
        )
        self.client = Redis(connection_pool=self.pool)

        lua_path = os.path.join(os.path.dirname(__file__), "../../lua/token_bucket.lua")
        with open(lua_path, "r") as f:
            lua_script = f.read()
            
        try:
            self.lua_sha = await self.client.script_load(lua_script)
            logger.info(f"Loaded Token Bucket Lua Script into Redis. SHA: {self.lua_sha}")
        except RedisError as e:
            logger.error(f"Failed to load Lua script into Redis: {e}")
            raise e
        
    async def close(self):
        if self.client:
            await self.client.aclose()
        if self.pool:
            await self.pool.disconnect()
        logger.info("Closed Redis connection pool.")

redis_manager = RedisManager()