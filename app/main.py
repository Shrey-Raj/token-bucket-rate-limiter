from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, Response, status, HTTPException
from app.core.redis import redis_manager
from app.core.limiter import check_rate_limit
from app.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    await redis_manager.initialize()
    yield
    await redis_manager.close()

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

@app.get("/v1/check")
async def evaluate_rate_limit(
    response: Response,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For")
):
    client_id = x_api_key or (x_forwarded_for.split(",")[0].strip() if x_forwarded_for else "anonymous")

    result = await check_rate_limit(client_id=client_id)
    
    if result.failed_closed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable. Please retry later.",
            headers={"Retry-After": str(result.retry_after)},
        )

    response.headers["X-RateLimit-Limit"] = str(settings.DEFAULT_CAPACITY)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.reset)

    if result.failed_open:
        response.headers["X-RateLimit-Degraded"] = "true"

    if not result.allowed:
        response.headers["Retry-After"] = str(result.retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Too many requests.",
            headers=response.headers
        )

    return {"status": "allowed", "client_id": client_id}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}