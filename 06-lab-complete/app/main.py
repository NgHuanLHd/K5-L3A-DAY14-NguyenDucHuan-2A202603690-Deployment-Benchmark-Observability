import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(entry, ensure_ascii=False)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logger = logging.getLogger("agent")


def log(event: str, **fields) -> None:
    logger.info(event, extra={"fields": fields})


@asynccontextmanager
async def lifespan(app: FastAPI):
    log("startup", environment=settings.environment)
    yield
    # uvicorn chạy tới đây SAU KHI các request đang xử lý đã xong.
    r.close()
    log("shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        log("request", method=request.method, path=request.url.path, status=status,
            ms=round((time.perf_counter() - start) * 1000, 1))


@app.exception_handler(redis.RedisError)
def redis_error(request: Request, exc: redis.RedisError):
    log("redis_error", error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})


@app.exception_handler(Exception)
def unhandled_error(request: Request, exc: Exception):
    log("unhandled_error", error=type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not available")
    return {"status": "ready"}


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    cost = record_cost(estimate_tokens(body.question), estimate_tokens(answer))
    return {"question": body.question, "answer": answer, "cost_usd": round(cost, 8)}
