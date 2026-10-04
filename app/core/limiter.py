import logging
from redis.exceptions import NoScriptError, RedisError
from app.core.redis import redis_manager
from app.config import settings
from app.core.circuit_breaker import breaker

logger = logging.getLogger(__name__)


class RateLimiterResult:
    def __init__(
        self,
        allowed: bool,
        remaining: int,
        retry_after: int,
        reset: int,
        failed_open: bool = False,
        failed_closed: bool = False,
    ):
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after = retry_after
        self.reset = reset
        self.failed_open = failed_open
        self.failed_closed = failed_closed


def _degraded_result(
    client_id: str,
    capacity: int,
    reason: str,
    retry_after: int = 5,
    log: bool = True,
) -> RateLimiterResult:
    """Single place that decides what happens when the limiter can't decide."""
    if settings.FAIL_OPEN:
        if log:
            logger.warning("Limiter degraded, FAILING OPEN for '%s': %s", client_id, reason)
        return RateLimiterResult(True, capacity, 0, 0, failed_open=True)
    if log:
        logger.error("Limiter degraded, FAILING CLOSED for '%s': %s", client_id, reason)
    return RateLimiterResult(False, 0, retry_after, retry_after, failed_closed=True)


async def check_rate_limit(
    client_id: str,
    capacity: int = settings.DEFAULT_CAPACITY,
    refill_rate: float = settings.DEFAULT_REFILL_RATE,
    cost: int = 1,
) -> RateLimiterResult:
    """Executes the Token Bucket check against Redis with EVALSHA."""
    redis_key = f"rate_limit:{client_id}"

    if not breaker.allow():
        return _degraded_result(
            client_id, capacity, "circuit open",
            retry_after=breaker.retry_after(), log=False,
        )



    try:
        if not redis_manager.lua_sha:
            await redis_manager.initialize()
        try:
            res = await redis_manager.client.evalsha(
                redis_manager.lua_sha, 1, redis_key, capacity, refill_rate, cost
            )
        except NoScriptError:
            logger.warning("Lua script SHA not found in Redis. Reloading script...")
            await redis_manager.initialize()
            res = await redis_manager.client.evalsha(
                redis_manager.lua_sha, 1, redis_key, capacity, refill_rate, cost
            )

        result = RateLimiterResult(
            allowed=bool(res[0]),
            remaining=int(res[1]),
            retry_after=int(res[2]),
            reset=int(res[3]),
        )
        breaker.record_success()
        return result

    except RedisError as e:
        breaker.record_failure()
        return _degraded_result(client_id, capacity, f"Redis error: {e}")
    except Exception as e:
        breaker.record_failure()
        logger.exception("Unexpected error in rate limiter")
        return _degraded_result(client_id, capacity, f"Unexpected error: {e}")