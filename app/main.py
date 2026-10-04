from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, Request, Response, status, HTTPException
from app.core.redis import redis_manager
from app.core.limiter import check_rate_limit, RateLimiterResult
from app.core.identity import client_ip, key_identity
from app.config import settings
from app.core.circuit_breaker import breaker
import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await redis_manager.initialize()
    except Exception as e:
        logger.error("Redis unavailable at startup, will retry on demand: %s", e)
    yield
    await redis_manager.close()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)


def _rate_headers(result: RateLimiterResult) -> dict:
    return {
        "X-RateLimit-Limit": str(settings.DEFAULT_CAPACITY),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(result.reset),
    }


def _enforce(result: RateLimiterResult) -> None:
    """Raise 503 (limiter down, failed closed) or 429 (over limit); otherwise return."""
    if result.failed_closed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable. Please retry later.",
            headers={"Retry-After": str(result.retry_after)},
        )
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Too many requests.",
            headers={**_rate_headers(result), "Retry-After": str(result.retry_after)},
        )


@app.get("/v1/check")
async def evaluate_rate_limit(
    request: Request,
    response: Response,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    peer = request.client.host if request.client else None
    ip_id = f"ip:{client_ip(peer, request.headers.get('x-forwarded-for'))}"

    client_id = None
    if x_api_key is not None:
        client_id = key_identity(x_api_key)          
    elif settings.ALLOW_ANONYMOUS:
        client_id = ip_id

    if client_id is None:
        _enforce(await check_rate_limit(client_id=ip_id))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )

    result = await check_rate_limit(client_id=client_id)
    _enforce(result)

    for name, value in _rate_headers(result).items():
        response.headers[name] = value
    if result.failed_open:
        response.headers["X-RateLimit-Degraded"] = "true"

    return {"status": "allowed", "client_id": client_id}

@app.get("/ready")
async def ready():
    try:
        if not redis_manager.lua_sha:
            await redis_manager.initialize()
        await redis_manager.client.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Redis unreachable")
    return {"status": "ready", "circuit": breaker.state}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}