# Deployment Information

## Public URL
https://day14-agent-cjvz.onrender.com

## Platform
Render (Blueprint từ `06-lab-complete/render.yaml`): web service Docker `day14-agent` và Key Value (Redis) `day14-redis`, cùng region Singapore, plan Free.

Gói Free "ngủ" khi không có request, nên lần gọi đầu có thể chậm tới khoảng một phút.

## Test Commands

Đặt `BASE` và nhập key khi được hỏi (key không hiện trên màn hình):

```bash
BASE=https://day14-agent-cjvz.onrender.com
read -rsp "Key: " AGENT_API_KEY; echo
```

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"       # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'                                    # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'    # 200
```

Kết quả đã chạy: `200`, `200`, `401`, `200`.

`/ready` trả 200 nghĩa là agent kết nối được Redis trên Render.

## Environment Variables Set (tên biến, không ghi giá trị)

Đặt qua `render.yaml` và dashboard Render:

- `ENVIRONMENT`
- `RATE_LIMIT_PER_MINUTE`
- `DAILY_BUDGET_USD`
- `AGENT_API_KEY` (nhập tay trên dashboard, `sync: false`)
- `REDIS_URL` (tự nối tới `day14-redis`)

`PORT` do Render cấp tự động; agent đọc biến này trong `CMD` của Dockerfile.

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
