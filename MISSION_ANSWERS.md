# Day 14 Lab - Mission Answers
## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Trong `01-localhost-vs-production/develop/app.py`:

1. **API key hardcode** (dòng 17): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"`. Push lên GitHub là lộ key.
2. **Mật khẩu database hardcode** (dòng 18): `DATABASE_URL` chứa `admin:password123`.
3. **In secret ra log** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Log được thu thập và lưu lâu dài nên key bị lộ ở nhiều nơi.
4. **Dùng `print` thay vì logging có cấu trúc** (dòng 33, 34, 38): không có level, không có timestamp, không phải JSON nên công cụ log không lọc được.
5. **Không có health check**: file không có `/health` hay `/ready`, nên nền tảng không biết khi nào agent chết để restart.
6. **Host `localhost`** (dòng 51): trong container, process chỉ nghe `localhost` thì không nhận được kết nối từ ngoài.
7. **Port cố định** (dòng 52): không đọc biến `PORT`, trong khi Railway và Render cấp port qua biến môi trường.
8. **`reload=True`** (dòng 53) và **`DEBUG = True`** (dòng 21): bật chế độ debug và tự nạp lại code khi chạy thật.
9. **Không có bước tắt riêng của app**: không có `lifespan` để đóng kết nối, không đổi trạng thái readiness, không log khi tắt. App phó mặc việc tắt cho uvicorn.

### Exercise 1.2: Chạy bản develop

```bash
cd 01-localhost-vs-production/develop
pip install -r requirements.txt
python app.py
curl -i -X POST "http://localhost:8000/ask?question=Hello"
```

Kết quả: `HTTP/1.1 200 OK`, body `{"answer":"Đây là câu trả lời từ AI agent (mock). ..."}`.

Bản develop nhận `question` qua query string, không nhận JSON. Log của server in ra dòng `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`, tức là key đã bị lộ ngay trong log.

Agent chạy được nhưng chưa sẵn sàng cho production vì các vấn đề ở mục 1.1.

### Exercise 1.3: Comparison table

Chạy bản production: `PORT=8000 ENVIRONMENT=staging python app.py`. Các lệnh `curl -i` tới `/health`, `/ready`, `/ask` đều trả `200 OK`. `/health` trả `"environment":"staging"` đúng giá trị biến vừa đặt, và log khởi động ghi `Uvicorn running on http://0.0.0.0:8000`.

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hardcode trong code (dòng 17, 18, 21) | Đọc từ biến môi trường qua `config.py` (`os.getenv`) | Cùng một image chạy được ở dev, staging, production chỉ bằng cách đổi biến. Secret không nằm trong code hay lịch sử git. |
| Health check | Không có | `GET /health` (liveness) và `GET /ready` (readiness) | Nền tảng biết khi nào cần restart container và khi nào chưa nên chuyển traffic vào. |
| Logging | `print()`, có in cả secret | Code khai báo log JSON (`app.py` dòng 28–30), không log secret. Khi chạy, log JSON không hiện: `config.py` gọi `logging.warning` trước nên Python tự cấu hình logging mặc định, `basicConfig` sau đó không còn tác dụng | Công cụ log (Datadog, Loki) lọc và tìm được theo field. Không làm lộ secret. |
| Shutdown | Không có bước dọn dẹp | Graceful: `lifespan` đổi `is_ready` về False và dọn dẹp, có handler SIGTERM để ghi log | Request đang chạy được hoàn thành khi deploy bản mới, không mất request của người dùng. |
| Host, port | `localhost`, port 8000 cố định | `0.0.0.0`, port lấy từ `PORT` | Trong container phải nghe `0.0.0.0` mới nhận được kết nối từ ngoài. Cloud cấp port qua biến `PORT`. |
| Debug, reload | `reload=True`, `DEBUG = True` | Chỉ bật khi `DEBUG=true` | Reload làm tốn tài nguyên và có thể làm lộ thông tin lỗi khi chạy thật. |

### Checkpoint 1

- Hardcode secret nguy hiểm vì chỉ cần push nhầm lên GitHub là key bị lộ; xoá file rồi key vẫn nằm trong lịch sử git, nên phải thu hồi và tạo key mới. Dùng biến môi trường để tách secret khỏi code.
- Health check giúp nền tảng tự phát hiện agent chết và restart. Readiness giúp load balancer không gửi traffic vào instance chưa sẵn sàng.
- Graceful shutdown nghĩa là khi nhận SIGTERM, agent ngừng nhận request mới, hoàn thành request đang chạy rồi mới thoát.
## Part 2: Docker

### Exercise 2.1: Dockerfile questions

Đọc `02-docker/develop/Dockerfile`:

1. **Base image:** `python:3.11`, bản đầy đủ (OS và Python, kèm nhiều công cụ không cần để chạy app). Bản production dùng `python:3.11-slim`.
2. **Working directory:** `/app` (lệnh `WORKDIR /app`), mọi `COPY` và `CMD` sau đó chạy trong thư mục này.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo từng layer. Nếu chỉ sửa code mà `requirements.txt` không đổi thì layer `pip install` được dùng lại, build nhanh hơn nhiều. Copy cả code trước thì mỗi lần sửa code phải cài lại toàn bộ thư viện.
4. **CMD khác ENTRYPOINT:** `CMD` là lệnh mặc định và có thể bị thay khi chạy `docker run <image> <lệnh khác>`. `ENTRYPOINT` là lệnh cố định, phần tham số truyền vào `docker run` được nối thêm phía sau nó. Dockerfile này dùng `CMD ["python", "app.py"]`.

### Exercise 2.2: Build và chạy bản develop

Build từ gốc repo vì Dockerfile `COPY` theo đường dẫn tính từ gốc:

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --rm --name agent-dev -p 8000:8000 my-agent:develop
curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
docker stop agent-dev
```

Kết quả: `HTTP/1.1 200 OK`, body `{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}`.

### Exercise 2.3: Multi-stage build

Đọc `02-docker/production/Dockerfile`:

- **Stage 1 (`builder`):** từ `python:3.11-slim`, cài `gcc` và `libpq-dev`, rồi `pip install --user` các thư viện vào `/root/.local`. Stage này chỉ để build, không dùng để chạy.
- **Stage 2 (`runtime`):** bắt đầu lại từ `python:3.11-slim` sạch, tạo user không phải root (`appuser`), chỉ `COPY --from=builder` thư mục site-packages và code ứng dụng, rồi chuyển sang `USER appuser`. Có `HEALTHCHECK` và chạy `uvicorn` với 2 worker.
- **Vì sao nhỏ hơn:** image cuối không chứa `gcc`, pip cache hay công cụ build ở stage 1, và dùng base `slim` thay cho bản đầy đủ. Ít thành phần hơn cũng nghĩa là bề mặt tấn công nhỏ hơn.

Kích thước đo bằng `docker images my-agent` trên máy của tôi:

| Image | DISK USAGE | CONTENT SIZE |
|-------|-----------:|-------------:|
| `my-agent:develop` | 1.67 GB | 426 MB |
| `my-agent:advanced` | 240 MB | 57.4 MB |

- **Giảm theo DISK USAGE:** (1670 − 240) ÷ 1670 ≈ **86%**.
- **Giảm theo CONTENT SIZE:** (426 − 57.4) ÷ 426 ≈ **86%**.

Hai cột là hai cách đo của Docker Desktop (có dùng containerd image store). Kích thước thực tế trên đĩa là DISK USAGE, nên tôi dùng cột này khi so sánh.

### Exercise 2.4: Docker Compose stack

Chạy stack:

```bash
cd 02-docker/production
touch .env.local
docker compose -p k5-day14-docker up -d --build
docker compose -p k5-day14-docker ps
```

`docker compose ps` cho thấy 4 service đang chạy:

| Service | Image | Trạng thái | Cổng mở ra máy host |
|---------|-------|-----------|---------------------|
| `agent` | `k5-day14-docker-agent` (build từ Dockerfile production) | Up, healthy | không (chỉ `8000/tcp` nội bộ) |
| `nginx` | `nginx:alpine` | Up | `80` và `443` |
| `redis` | `redis:7-alpine` | Up, healthy | không (chỉ `6379/tcp` nội bộ) |
| `qdrant` | `qdrant/qdrant:v1.9.0` | Up, healthy | không (chỉ `6333-6334/tcp` nội bộ) |

Sơ đồ kiến trúc:

```
Client ──► Nginx :80 ──► agent :8000
                           │
                           ├──► redis  :6379   (cache, session, rate limit)
                           └──► qdrant :6333   (vector database cho RAG)

Tất cả service nằm trong network "internal". Chỉ Nginx mở cổng ra ngoài.
```

Các service gọi nhau bằng **tên service** (`redis`, `qdrant`, `agent`) qua DNS của network `internal` do Docker Compose tạo. Agent được cấp địa chỉ Redis và Qdrant qua `REDIS_URL` và `QDRANT_URL` trong `docker-compose.yml`, nhưng `main.py` mẫu chưa dùng hai biến này, nên hai mũi tên agent → redis/qdrant là kết nối được cấu hình sẵn. `depends_on` kèm `condition: service_healthy` bảo đảm agent chỉ khởi động sau khi Redis và Qdrant đã healthy.

Test qua Nginx (cổng 80, không phải 8000):

```bash
curl -i http://localhost/health
curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
```

- `/health` trả `HTTP/1.1 200 OK`, body `{"status":"ok","uptime_seconds":162.6,"version":"2.0.0",...}`.
- `/ask` trả `HTTP/1.1 200 OK`, body `{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}`.
- Cả hai response có header `Server: nginx` và các header bảo mật (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`), chứng tỏ request đi qua Nginx chứ không gọi thẳng agent.

Sau khi test, dọn stack: `docker compose -p k5-day14-docker down` (đã gỡ 4 container và network).

### Checkpoint 2

- Dockerfile gồm base image, `WORKDIR`, `COPY`, `RUN` và lệnh chạy; thứ tự layer ảnh hưởng đến cache.
- Multi-stage giảm dung lượng vì image cuối không mang theo công cụ build (kết quả đo: 1.67 GB xuống 240 MB).
- Docker Compose chạy nhiều service bằng một lệnh, tự tạo network để các service gọi nhau bằng tên.
- Debug container: `docker logs <container>` để xem log, `docker exec -it <container> sh` để vào bên trong.
## Part 3: Cloud Deployment

### Exercise 3.1: Deploy agent Part 6

- URL: (điền sau khi deploy ở CP6)
- Ảnh: (điền sau khi deploy ở CP6)

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

So sánh hai file mẫu trong `03-cloud-deployment/`:

| Điểm | `railway.toml` | `render.yaml` |
|------|----------------|---------------|
| Phạm vi | Cách build và deploy một service | Cả hạ tầng (Blueprint): web service và Redis |
| Build | `builder = "NIXPACKS"`, tự nhận dạng Python | `runtime: python` và `buildCommand` ghi rõ |
| Lệnh chạy | `startCommand` dùng `$PORT` | `startCommand` dùng `$PORT` |
| Health check | `healthcheckPath`, `healthcheckTimeout` | `healthCheckPath` |
| Restart | `restartPolicyType`, `restartPolicyMaxRetries` | Không khai báo trong file |
| Biến môi trường | Không nằm trong file, đặt qua dashboard hoặc CLI | `envVars`: giá trị thường ghi thẳng, secret dùng `sync: false` (nhập tay) hoặc `generateValue: true` (tự sinh) |
| Redis | Tạo riêng trên Railway | Khai báo `type: redis` trong cùng file |
| Region, plan | Không có trong file | `region: singapore`, `plan: free` |

Khác nhau vì hai file có mục đích khác nhau: `railway.toml` chỉ cấu hình một service, phần còn lại làm trên dashboard; `render.yaml` mô tả toàn bộ hạ tầng để Render dựng lại được từ git. Cả hai đều không ghi secret thật.

### Exercise 3.3: Cloud Run (đọc, không deploy)

`cloudbuild.yaml` chạy 4 bước nối tiếp: (1) **test** cài thư viện và chạy `pytest`; (2) **build** image với tag `$COMMIT_SHA` và `latest`; (3) **push** image lên Container Registry; (4) **deploy** bằng `gcloud run deploy` tới `asia-southeast1`. Ba bước sau có `waitFor` bước trước, nên test fail thì không deploy. Tag `$COMMIT_SHA` cho biết bản đang chạy là commit nào, dễ rollback. `OPENAI_API_KEY` lấy từ Secret Manager. `service.yaml` khai báo scale 1–10 instance, 80 request đồng thời mỗi instance, liveness `/health` và startup probe `/ready`.

## Part 4: API Security

### Exercise 4.1: API key authentication

Chạy bản develop: `AGENT_API_KEY=secret-key-123 python app.py` trong `04-api-gateway/develop`.

- **Key được kiểm tra ở đâu:** hàm `verify_api_key` (dòng 39). Header `X-API-Key` được đọc bằng `APIKeyHeader` (dòng 36, `auto_error=False` để tự trả mã lỗi), và endpoint `/ask` gắn vào bằng `Depends(verify_api_key)` (dòng 70). Key đúng lấy từ biến môi trường `AGENT_API_KEY` (dòng 35).
- **Sai key thì sao:** thiếu header trả **401** (dòng 46), có header nhưng sai trả **403** (dòng 51). Request bị chặn trước khi tới code gọi LLM.
- **Rotate key:** đặt `AGENT_API_KEY` bằng giá trị mới rồi restart. Muốn không gián đoạn thì tạm chấp nhận cả key cũ và mới, sau khi mọi client đã đổi thì bỏ key cũ.

Kết quả test (`curl -i -X POST http://localhost:8000/ask ...`):

| Trường hợp | Kết quả | Body |
|------------|---------|------|
| Không có key | `401 Unauthorized` | `{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}` |
| Key sai (`sai`) | `403 Forbidden` | `{"detail":"Invalid API key."}` |
| Key đúng (`secret-key-123`) | `200 OK` | `{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. ..."}` |

Lưu ý: bản mẫu tách 401 (thiếu key) và 403 (sai key). Ở Part 6, đề yêu cầu cả hai đều trả 401.

### Exercise 4.2: JWT authentication

Đọc `04-api-gateway/production/auth.py`. Luồng JWT:

1. Client gửi `POST /auth/token` kèm username và password. Hàm `authenticate_user` (dòng 70) so với `DEMO_USERS` (dòng 27); sai thì trả 401.
2. `create_token` (dòng 35) ký một payload gồm `sub` (tên user), `role`, `iat` và `exp` (hết hạn sau 60 phút, dòng 24) bằng `SECRET_KEY` (dòng 22) với thuật toán HS256.
3. Client gọi `/ask` kèm header `Authorization: Bearer <token>`.
4. `verify_token` (dòng 46) kiểm tra chữ ký và hạn của token, rồi lấy `username` và `role` từ payload. Không cần tra database ở mỗi request nên server là stateless.

Mã lỗi: thiếu token trả 401 (dòng 53), token hết hạn trả 401 (dòng 65), token sai chữ ký trả 403 (dòng 67).

Tài khoản demo: `student` (role `user`) và `teacher` (role `admin`). Lấy token bằng `POST /auth/token` với `student` và mật khẩu demo của lab; token được dùng cho vòng lặp 4.3 và đã được che trong báo cáo này.

### Exercise 4.3: Rate limiting

Đọc `04-api-gateway/production/rate_limiter.py`:

- **Thuật toán:** sliding window (lưu từng mốc thời gian). Mỗi user có một `deque` lưu thời điểm các request. Mỗi lần gọi, các mốc cũ hơn 60 giây bị bỏ đi (`popleft`, dòng 40); nếu số mốc còn lại đã bằng giới hạn thì trả 429.
- **Giới hạn:** user thường 10 request/phút (dòng 86), admin 100 request/phút (dòng 87).
- **Admin không "bypass" mà dùng limiter riêng:** `app.py` dòng 141 chọn `rate_limiter_admin` nếu `role == "admin"`, nên giới hạn của admin cao hơn chứ không bị bỏ.
- **Hạn chế:** state nằm trong RAM của process. Chạy nhiều instance hoặc nhiều worker thì mỗi nơi đếm riêng và restart là mất số đếm. Production phải chuyển sang Redis (làm ở Part 6).

Kết quả gọi 12 lần liên tiếp bằng token của `student`:

```
--- 1 đến 10: HTTP/1.1 200 OK
--- 11: HTTP/1.1 429 Too Many Requests   retry-after: 59
--- 12: HTTP/1.1 429 Too Many Requests   retry-after: 59
```

10 request đầu thành công, từ request thứ 11 bị chặn đúng giới hạn 10 request/phút. Header `retry-after: 59` cho client biết cần chờ khoảng 59 giây.

### Exercise 4.4: Cost guard

**Cách bản mẫu làm** (`04-api-gateway/production/cost_guard.py`):

- **Trước khi gọi LLM:** `check_budget` (dòng 60). Tổng chi phí toàn hệ thống đạt 10 USD thì trả 503 (dòng 71); chi phí của user đạt 1 USD/ngày thì trả 402 (dòng 78); dùng từ 80% thì ghi log cảnh báo (dòng 88).
- **Sau khi gọi LLM:** `record_usage` (dòng 93) cộng số token và chi phí. Chi phí = input_tokens/1000 × giá input + output_tokens/1000 × giá output.
- **Hạn chế:** số liệu nằm trong RAM nên restart là mất và mỗi instance đếm riêng. Ngoài ra `_global_cost` không được reset khi sang ngày mới (`_global_today` được gán nhưng không dùng), và `app.py` trả `total_cost_usd` (đã tiêu) trong field tên `budget_remaining_usd`.

**Cách làm với Redis** (10 USD/user/tháng theo đề):

```python
import redis
from datetime import datetime, timezone

r = redis.Redis()

def check_budget(user_id: str, estimated_cost: float) -> bool:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"budget:{user_id}:{month}"
    current = float(r.get(key) or 0)
    if current + estimated_cost > 10:
        return False
    r.incrbyfloat(key, estimated_cost)
    r.expire(key, 32 * 24 * 3600)
    return True
```

- Key chứa user và tháng: mỗi user một ngân sách riêng, sang tháng dùng key mới nên tự về 0. `expire` 32 ngày để Redis tự dọn key cũ.
- Redis dùng chung cho mọi worker và không mất khi agent restart.
- Vẫn có race: hai request cùng đọc `current` trước khi request nào kịp cộng thì cả hai đều qua. Muốn chặt thì gộp đọc, so sánh và cộng vào một Lua script.

Đoạn code trên là phương án giải thích, chưa chạy thử. Bản chạy thật nằm ở Part 6.

**Vì sao cần cả rate limit và cost guard:** rate limit giới hạn số request theo thời gian, cost guard giới hạn số tiền. Ít request nhưng prompt dài vẫn tốn nhiều tiền; nhiều request rẻ vẫn có thể làm nghẽn hệ thống.
## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks

Chạy `05-scaling-reliability/develop/app.py`:

| Endpoint | Kết quả | Body |
|----------|---------|------|
| `GET /health` | `200 OK` | `{"status":"ok","uptime_seconds":1.8,...,"checks":{"memory":{"status":"ok","used_percent":49.0}}}` |
| `GET /ready` | `200 OK` | `{"ready":true,"in_flight_requests":1}` |

- **Liveness (`/health`)**: process còn sống không. Fail thì nền tảng restart container.
- **Readiness (`/ready`)**: có nhận traffic được không. Fail (503) thì load balancer ngừng chuyển request tới instance, không restart.
- `in_flight_requests` bằng 1 vì middleware đếm luôn chính request `/ready` đang chạy.
- Bản mẫu này chỉ kiểm tra cờ `_is_ready`. Bản thật nên kiểm tra cả Redis hoặc database.

### Exercise 5.2: Graceful shutdown

Gửi `POST /ask?question=Long`, sau 0,05 giây gửi `kill -TERM` cho server. Thứ tự log:

```
INFO:     Shutting down
INFO:     127.0.0.1:33374 - "POST /ask?question=Long HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
15:34:11,543 INFO Graceful shutdown initiated...
15:34:11,543 INFO Shutdown complete
INFO:     Finished server process [11996]
15:34:11,544 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

- Request vẫn nhận `200 OK` **sau** dòng `Shutting down`: server chờ request đang chạy xong rồi mới chạy phần shutdown của `lifespan` và thoát.
- Dòng `Received signal 15` in ra **cuối cùng**: khi chạy, uvicorn thay handler của app bằng handler của nó. Tắt xong, uvicorn khôi phục handler cũ và phát lại signal, lúc đó `handle_sigterm` của app mới chạy. Vì vậy người thực hiện graceful shutdown là uvicorn; handler của app chỉ ghi log.

### Exercise 5.3: Stateless design

`05-scaling-reliability/production/app.py` lưu history trong Redis với key `session:<session_id>` và hạn 3600 giây (`save_session`, `load_session`). Instance không giữ session trong RAM nên instance nào cũng phục vụ được mọi user. Nếu không có Redis, app tự chuyển sang dict trong RAM; cách này chỉ đúng khi chạy một instance.

Hạn chế: `append_to_history` đọc cả session, thêm message rồi ghi lại. Hai request cùng session chạy đồng thời có thể ghi đè nhau. Dùng Redis list (`RPUSH`) sẽ tránh được.

### Exercise 5.4: Load balancing

```bash
docker compose -p k5-day14-scaling up -d --build --scale agent=3
```

Nginx (cổng 8080) phân phối 5 request theo round-robin:

| Request | Instance |
|---------|----------|
| 1 | `instance-ab434c` |
| 2 | `instance-98b998` |
| 3 | `instance-7576f3` |
| 4 | `instance-ab434c` |
| 5 | `instance-98b998` |

### Exercise 5.5: Test stateless

Output của `python test_stateless.py`:

```
Total requests: 5
Instances used: {'instance-98b998', 'instance-ab434c', 'instance-7576f3'}
Total messages: 10
Session history preserved across all instances via Redis!
```

- 5 câu hỏi và 5 câu trả lời thành 10 message, không mất message nào dù đi qua 3 instance.
- Nếu history nằm trong RAM: `ab434c` chỉ có 4 message (request 1, 4), `98b998` có 4 (request 2, 5), `7576f3` có 2 (request 3). Lệnh đọc history sẽ ra 2 hoặc 4 message tuỳ rơi vào instance nào, không bao giờ đủ 10.
- Script chỉ gửi request và đọc history, không tự tắt instance nào. Tôi chưa thử tắt một instance giữa chừng, nên kết quả này chứng minh state được chia sẻ, chưa chứng minh failover.

### Checkpoint 5

- Liveness fail thì restart, readiness fail thì ngừng nhận traffic.
- State trong RAM hỏng khi chạy nhiều instance vì mỗi process có bộ nhớ riêng.
- Dọn stack: `docker compose -p k5-day14-scaling down`.
## Part 6: Output check_production_ready.py

Chạy `python check_production_ready.py` (bản đầy đủ, có Docker) trong `06-lab-complete/`, trên WSL2:

```
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 41/41 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

Số đo trong lần chạy: image 238 MB; `docker stop` thoát với exit code 0 sau 0,7 giây; rate limit trả 429 sau 5 request thành công (`RATE_LIMIT_PER_MINUTE=5`) và vẫn 429 sau khi restart agent.

## AI log

Công cụ: Claude (Claude Code).

| Phần | Hỏi gì | Nhận gì |
|------|--------|---------|
| Toàn lab | Tóm tắt lab và hướng dẫn từng bước | Trang hướng dẫn CP0–CP8, kèm code tham khảo Part 6 |
| Part 1, 2, 4, 5 | Viết bài trả lời từ output lệnh tôi đã chạy | Bản nháp các mục Part 1, 2, 4, 5 |
| Part 6 | Điền code CP5 | Code cho các file bản khung trong `06-lab-complete/` (trừ `render.yaml` giữ nguyên), gồm cả `check_budget` |
| Part 3 | Hoàn thiện báo cáo | Bản nháp so sánh `railway.toml` với `render.yaml` và mô tả Cloud Run |

Tôi tự sửa và tự kiểm tra: (tự viết 3–5 dòng)
