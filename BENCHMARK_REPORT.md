# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyễn Đức Huân
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11, WSL2 Ubuntu 24.04 (Python 3.12.3), Docker Desktop 4.92.0 (WSL2), khoảng 9 GB RAM. Agent v2 chạy một process uvicorn; `load_test.py` chạy cùng máy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Request bình thường khoảng 190 ms (p50), p95 khoảng 230 ms khi concurrency ≤ 10. Ngưỡng 500 ms còn khoảng dự phòng gấp đôi nhưng vẫn phát hiện được quá tải (concurrency 100: 3352 ms) |
| Error rate `/ask` | < 2% | Mock LLM lỗi khoảng 1%, ngưỡng 2% chừa chỗ cho dao động. Với mẫu 300 request vẫn có lần vượt do ngẫu nhiên (2,33% ở mục 2.2), nên cần đo trên mẫu lớn hơn trước khi kết luận |
| Accuracy trên golden dataset | ≥ 85% | v2 ban đầu đạt 91,3%, v1 chỉ 4,3%. Ngưỡng 85% cho phép sai tối đa 3/23 câu và chặn được bản kém như v1. Sau khi sửa knowledge base đạt 100% |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.02 | 189.5 | 227.8 | 1703.7 | 0.67% | PASS |
| 10 | 38.03 | 191.8 | 227.7 | 1698.6 | 0.67% | PASS |
| 50 | 102.61 | 196.9 | 329.8 | 1722.7 | 0.67% | PASS |
| 100 | 54.49 | 417.9 | 3352.4 | 3735.7 | 1.00% | FAIL (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json` (300 request mỗi mức, SLO p95 ≤ 500 ms và error rate ≤ 2%).

**Nhận xét:** RPS không tăng tuyến tính.

- Từ 1 lên 10: RPS tăng 9,5 lần (4,02 lên 38,03). Gần tuyến tính vì mỗi request phần lớn chỉ chờ mock LLM (`asyncio.sleep`) nên một process xử lý được nhiều request chồng nhau, và p95 gần như không đổi (227,8 và 227,7 ms).
- Từ 10 lên 50: chỉ tăng 2,7 lần (38,03 lên 102,61), p95 bắt đầu tăng (329,8 ms). Mức 50 chỉ chạy 2,92 giây, nên vài request chậm bất thường (cộng thêm 1,5 giây) ở cuối lượt chạy có thể làm RPS thấp đi đáng kể.
- Từ 50 lên 100: RPS **giảm** (54,49), p95 vọt lên 3352 ms và vi phạm SLO. Latency thấp nhất cũng tăng từ khoảng 154 lên 218 ms, tức là request phải xếp hàng ngay từ đầu. Hệ thống đã quá tải ở mức này.
- Lỗi 503 (2 đến 3 trên 300 request, khoảng 1%) khớp với `MOCK_ERROR_RATE` mặc định 1%, không do tải.
- Tôi chưa đo CPU của process agent trong lúc chạy, nên chưa kết luận chắc nguyên nhân quá tải ở mức 100. Giả thuyết hợp lý là một process uvicorn một event loop (kèm middleware ghi log JSON và metrics cho mỗi request) bão hoà, nhưng đây là suy đoán.

### 2.2 Tail latency

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 192.4 | 223.5 | 249.3 |
| 0.03 (mặc định) | 242.6 | 231.5 | 1702.0 |
| 0.1 | 349.2 | 1693.1 | 1720.6 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json` (300 request, concurrency 20, agent v2). File JSON không lưu giá trị `MOCK_SLOW_RATE`; giá trị được nhận biết qua tên file. Lần đầu cả ba lần chạy ghi chung một file, nên lần cuối (0,1) được đổi tên, còn 0 và 0,03 được chạy lại.

**Nhận xét:**

- **Chỉ số nhạy nhất là p99, rồi p95.** Khi 3% request chậm, avg chỉ tăng 26% (192 lên 243 ms) và p95 gần như không đổi (224 lên 232 ms), nhưng p99 tăng gấp 6,8 lần (249 lên 1702 ms). Khi 10% request chậm, vượt quá 5% số request nên p95 cũng bị kéo lên 1693 ms (gấp 7,6 lần), trong khi avg mới tăng 81%.
- **Vì sao:** request chậm bị cộng thêm khoảng 1,5 giây (`MOCK_SLOW_MS`). Average chia phần chậm đó cho tất cả request nên che mất nhóm này. Percentile nhìn vào vị trí trong phân phối, nên p99 thấy ngay nhóm 3% bị chậm, còn p95 chỉ thấy khi nhóm đó vượt 5%.
- **SLO không nên đặt theo average:** ở tỉ lệ 3%, avg 243 ms trông ổn nhưng cứ 100 người thì có 3 người chờ gần 1,7 giây. Ở tỉ lệ 10%, SLO p95 ≤ 500 ms báo FAIL (1693 ms) còn avg 349 ms vẫn dưới ngưỡng đó, nên SLO theo average sẽ bỏ sót sự cố. SLO nên đặt theo p95 hoặc p99.
- **Lưu ý về error rate:** lần chạy 0,03 có error rate 2,33% (7/300, vi phạm SLO error ≤ 2%) còn hai lần chạy 0 và 0,1 đều là 1,33% (4/300). Lỗi 503 do mock sinh ngẫu nhiên (`MOCK_ERROR_RATE` mặc định 1%) nên mỗi lần chạy dao động; mẫu 300 request là nhỏ. Mức chênh này không do `MOCK_SLOW_RATE`.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 57.3 | 108.8 | 113.7 |
| Tổng cost (USD) | 0.000408 | 0.000758 | 0.000790 |
| Cost / câu đúng (USD) | 0.00040755 | 0.00003607 | 0.00003436 |
| Quality gate | FAIL | PASS | PASS |

Nguồn: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`. Quality gate của v1 và v2 dùng ngưỡng mặc định accuracy ≥ 80%; lần chạy sau khi sửa dùng `--min-accuracy 1.0` và `--baseline reports/eval_v2.json`, không có câu bị regression.

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` (JWT khác gì API key) | `token`, `hết hạn`, `chữ ký` | Thêm vào `KNOWLEDGE_BASE` (`develop/utils/mock_llm.py`) một tài liệu kích hoạt bởi từ khoá `jwt`, nói JWT là token có chữ ký số và thời điểm hết hạn |
| `scaling-03` (Kubernetes HPA scale theo chỉ số nào) | `cpu`, `memory`, `custom metrics` | Thêm một tài liệu kích hoạt bởi `hpa`, `kubernetes`, `autoscal`, nói HPA scale theo CPU, memory hoặc custom metrics |

Cả hai câu trả lời ban đầu là câu chung chung (`security-02`: "Tôi là AI agent được deploy lên cloud..."; `scaling-03`: "Câu hỏi hay! Điều này phụ thuộc...") vì bước retrieval không tìm được tài liệu nào khớp. Nguyên nhân là thiếu tài liệu trong knowledge base, nên sửa knowledge base. `golden_dataset.jsonl` không bị sửa. Sau khi sửa và khởi động lại v2, kết quả 23/23, không regression (2 câu được cải thiện).

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** v2 có retrieval nên đúng 21/23 câu so với 1/23 của v1.
- **Chi phí:** prompt của v2 dài hơn vì có thêm tài liệu, nên tốn gần gấp đôi token mỗi câu (108.8 so với 57.3) và tổng cost cao hơn khoảng 1,9 lần (0.000758 so với 0.000408 USD).
- **Cost trên mỗi câu đúng** là chỉ số đáng so sánh: v2 chỉ tốn 0.00003607 USD, rẻ hơn v1 (0.00040755 USD) khoảng 11 lần, vì v1 gần như không trả lời đúng câu nào. Sau khi sửa knowledge base còn 0.00003436 USD.
- **Latency:** thêm bước retrieval thêm khoảng 20 ms mỗi request. Các giá trị p95 trong eval (187 ms với v1, 1543 ms với v2, 218 ms sau khi sửa) khác nhau chủ yếu do 23 câu là mẫu quá nhỏ: chỉ cần 1 đến 2 request rơi vào nhóm chậm bất thường (khoảng 1,5 giây) là p95 nhảy vọt. Việc p95 giảm từ 1543 xuống 218 ms sau khi sửa KB là ngẫu nhiên, không phải do thay đổi này. Latency phải đo bằng load test (mục 2), không dùng eval.
- **Kết luận:** v2 đáng để dùng; cái giá là token và một bước retrieval nhỏ.

**Quality gate trong CI:** `run_eval.py` trả exit code 1 khi accuracy thấp hơn `--min-accuracy` hoặc có regression so với `--baseline`. Trong GitHub Actions, lệnh trả khác 0 làm job fail. Bật branch protection và đặt job này là *required status check* thì PR không merge được khi job fail. Job mẫu:

```yaml
name: quality-gate
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          pip install -r requirements.txt
          AGENT_VERSION=v2 MOCK_ERROR_RATE=0 python app.py &
          sleep 3
          python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85
```

`MOCK_ERROR_RATE=0` để lỗi ngẫu nhiên của mock không làm job fail oan. Job này chưa được chạy trên GitHub.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (30 users): `screenshots/grafana-dashboard.png`
- [x] Một trace chậm trong Jaeger: `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (có event `exception`): `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với 2 alert đang **firing**: `screenshots/prometheus-alert-firing.png`

Đọc dashboard (30 users, 2 instance): 16.9 req/s, error rate 1.07%, p95 292.5 ms, p99 khoảng 1.8 giây.

### 4.2 Thí nghiệm "phá hệ thống"

Chạy với 10 users, 2 instance. Với 30 users, `LLMCostBurnRateHigh` firing sẵn khi chưa đổi gì (2.11 USD/giờ, ngưỡng 2), nên phải giảm tải để có mốc sạch. Thời gian đo bằng `/proc/uptime`, hỏi Prometheus mỗi 2 giây, tính từ lúc bắt đầu áp dụng thay đổi (gồm cả thời gian tạo lại container ở A, B, C).

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | 86 giây (`for` 60 giây) | Error rate |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | 128 giây (`for` 120 giây) | Latency p95 |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | 171 giây (`for` 120 giây) | Cost USD/giờ |
| D | `docker pause` 1 instance | `AgentInstanceDown` | 41 giây (`for` 30 giây) | Instances up |
| E | `AGENT_VERSION=v1` | Không có (theo dõi khoảng 5 phút) | Không áp dụng | Tokens/s, bảng version |

- **Unit test alert** (`promtool test rules alert_rules_test.yml`): SUCCESS.
- **Thời gian phát hiện** gồm thời gian `for`, chờ scrape và chờ số liệu trong cửa sổ `rate()` vượt ngưỡng. C tính trên cửa sổ 5 phút, A và B trên 1 phút; đây có thể là lý do C lâu nhất.
- **D:** Nginx ghi 12 lỗi 504 trên `/ask` (`upstream timed out`), `up` của instance bị pause về 0, nhưng error rate agent tự đo chỉ khoảng 1% (cao nhất 2.5%), không chạm ngưỡng 5%. Request chết ở Nginx sau `proxy_read_timeout 10s`, agent bị pause không xử lý xong nên không đếm. Metric của service chỉ phản ánh điều service đó thấy; cần giám sát thêm ở load balancer hoặc kiểm tra từ ngoài.
- Trong cùng 15 phút, Nginx còn trả 407 lỗi 502 trên `/ask`. Khả năng cao là lúc `docker compose up -d` tạo lại cả hai agent cùng lúc để đổi cấu hình. Deploy thật nên cuốn chiếu từng instance.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Khi đổi sang v1 (19:36:30 đến 19:41:30), token/giây giảm khoảng một nửa (input từ khoảng 420 xuống 203, output từ 223 xuống 111), p95 phần lớn khoảng 200 ms; alert p95 có lúc `pending` nhưng không firing. Hạ tầng trông còn tốt hơn trước, trong khi eval cho thấy accuracy của v1 chỉ 4.3% so với 91.3% của v2. Cách phát hiện: chạy eval trên golden dataset trong CI trước mỗi lần deploy và định kỳ trên production, đo tỉ lệ người dùng đánh giá không hài lòng, và đặt cảnh báo khi retrieval hit ratio hoặc token mỗi request đổi đột ngột.

### 4.3 Debug bằng trace

- `trace_id`: `2178b49463ba05168bffca90a2fee734`
- Tổng thời gian (`POST /ask`): 1722.1 ms
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (1695.3 ms, 98.4%). `agent.retrieve_context` chỉ 23.3 ms. Chậm do LLM, không do code của agent.
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-25T12:11:12.931749+00:00", "level": "INFO", "service": "observable-agent", "instance": "3cf9013ef1aa", "event": "llm_call", "trace_id": "2178b49463ba05168bffca90a2fee734", "span_id": "be06aa7ae3ce003a", "request_id": "6af939588168", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1694.7}
{"ts": "2026-11-25T12:11:12.932487+00:00", "level": "INFO", "service": "observable-agent", "instance": "3cf9013ef1aa", "event": "http_request", "trace_id": "2178b49463ba05168bffca90a2fee734", "span_id": "be06aa7ae3ce003a", "request_id": "6af939588168", "method": "POST", "route": "/ask", "status": 200, "ms": 1721.1}
```

Tôi không chọn trace dài nhất Jaeger hiển thị (`e3ea5ac74aa2ede9db82d6e3931379a0`, 4425 ms), vì log của chính request đó ghi 1690.9 ms. Span dùng đồng hồ hệ thống, còn `ms` trong log đo bằng `time.perf_counter()`. Chênh lệch cho thấy đồng hồ của máy (WSL) nhiều khả năng đã nhảy giữa chừng. Trace đã chọn khớp log (1722.1 và 1721.1 ms).

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 54.06 | 200 | 410 | 1700 | 68/7027 (0.97%) |
| 3 | 55.07 | 190 | 250 | 1700 | 74/7103 (1.04%) |

Nguồn: dòng `/ask` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv`. Percentile của Locust là giá trị làm tròn. Mỗi cấu hình chỉ đo một lượt.

**Cách bảo đảm đúng số instance:** lần đo đầu tiên tôi phải bỏ. `docker compose run locust` bật kèm service phụ thuộc và đưa agent về `replicas: 2`, nên cả hai lượt thực chất chạy 2 instance (lệnh tạo agent-2 ở lượt một, xoá agent-3 ở lượt hai). Tôi đo lại với `run --no-deps`, đếm agent trước và sau (1/1 và 3/3). Prometheus xác nhận số target là 1 và 3. Ở lượt 3 instance, mỗi agent nhận khoảng 2100 request trong 110 giây, tức Nginx chia đều.

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- **RPS gần như không đổi** (54,06 và 55,07) vì tải do số user quyết định. Mỗi user nghỉ trung bình 1,25 giây và chờ khoảng 0,24 giây, nên 100 user tạo khoảng 67 request/giây kể cả `/health`. Một instance đã đủ phục vụ mức này.
- **p95 giảm từ 410 xuống 250 ms.** Đo tại agent bằng Prometheus (cửa sổ 110 giây): p95 của HTTP giảm từ 417 xuống 295 ms, còn p95 của riêng LLM giữ nguyên 198 ms. Vậy phần được cải thiện là thời gian trong agent ngoài lời gọi LLM. Giải thích hợp lý là request chờ CPU khi một container (giới hạn 0,5 CPU) nhận toàn bộ tải; tôi chưa đo CPU để khẳng định.
- **p99 không đổi (1700 ms)** vì do khoảng 3% lời gọi LLM chậm thêm 1,5 giây. Thêm instance không làm LLM nhanh hơn, nên với p99 nút thắt là LLM.
- **Failures khoảng 1%** ở cả hai cấu hình, đều là 503 do `MOCK_ERROR_RATE=0.01`.

---

## 6. Kết luận

- 3 điều tôi học được về benchmark & observability:
  1. Trung bình che giấu đuôi chậm: với 3% request chậm, avg tăng 26% còn p99 tăng 6,8 lần (mục 2.2).
  2. Phải kiểm tra điều kiện đo trước khi tin con số. Lần đo scale đầu thực chất chạy 2 instance ở cả hai lượt, và trace 4,4 giây nhiều khả năng do đồng hồ nhảy (mục 4.3 và 5).
  3. Mỗi công cụ chỉ thấy một phần: metric của agent không thấy lỗi 504 ở Nginx (D), alert hạ tầng không thấy chất lượng giảm (E).
- Nếu đưa agent này lên production thật, tôi sẽ thêm: error rate và latency đo tại load balancer; synthetic check từ ngoài; eval định kỳ với cảnh báo accuracy; alert cho retrieval hit ratio; alert p99; đặt lại ngưỡng cost theo lưu lượng thực tế; nhiều cửa sổ burn rate để giảm báo động giả.
