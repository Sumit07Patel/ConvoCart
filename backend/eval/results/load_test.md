# Load test (Locust)

Measured on 2026-10-31 in the build sandbox, not on Render.

| Setting | Value |
| --- | --- |
| Concurrent simulated shoppers | 20 (spawn 5/s), think time 1-3 s, 45 s run |
| Endpoint | POST /chat (agent service, 1 uvicorn worker) |
| Store | separate store service over HTTP (STORE_MODE=http) |
| Database | SQLite (WAL) |
| Model | scripted (no model latency) |

| Requests | Failures | Median | 95th pct | 99th pct | Throughput |
| --- | --- | --- | --- | --- | --- |
| 1050 | 0 (0%) | 48 ms | 130 ms | 220 ms | 23.4 req/s |

These numbers are orchestration overhead only (routing, tools, store calls over HTTP, guards,
traces). With a real model, each turn adds one router call plus one or more specialist calls;
rerun with LLM_PROVIDER set and report those numbers separately. Free hosted quotas will not
survive a load test, so use Ollama for that run.

Command:
`locust -f locustfile.py --host http://localhost:8000 --headless -u 20 -r 5 -t 45s --csv eval/results/load`
