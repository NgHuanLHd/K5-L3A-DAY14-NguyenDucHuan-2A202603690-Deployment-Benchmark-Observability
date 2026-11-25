import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    # Băm key để không lưu API key thật trong Redis.
    bucket = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    now = time.time()
    member = f"{now}:{uuid.uuid4().hex}"

    # Bốn lệnh chạy trong một transaction (MULTI/EXEC), nên hai worker
    # không thể cùng đọc một số đếm cũ rồi cùng cho qua.
    pipe = r.pipeline(transaction=True)
    pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
    pipe.zadd(bucket, {member: now})
    pipe.zcard(bucket)
    pipe.expire(bucket, WINDOW_SECONDS)
    _, _, count, _ = pipe.execute()

    if count > settings.rate_limit_per_minute:
        r.zrem(bucket, member)  # request bị chặn thì không tính vào cửa sổ
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(WINDOW_SECONDS)},
        )
