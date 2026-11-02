"""Phase 8 load test: concurrent simulated shoppers on the web chat endpoint.

locust -f locustfile.py --host http://localhost:8000 --headless -u 20 -r 5 -t 60s --csv results/load
Report the number of concurrent users, the model provider and the database with the numbers:
latency with the scripted model measures orchestration overhead only, not model time.
"""
import random

from locust import HttpUser, between, task

CUSTOMERS = ["C0001", "C0003", "C0004", None]
FLOWS = [
    ["monsoon ke liye ek halki waterproof jacket dikhao, 3000 ke andar", "pehla wala, size M", "20% discount do na", "haan"],
    ["show me running shoes under 4000", "add the first one in UK9", "checkout"],
    ["बारिश के लिए जूते दिखाओ", "पहला वाला UK9 में चाहिए"],
    ["ORD-10002 kab aayega?", "ORD-10001 return karna hai"],
    ["linen shirt for a Goa holiday", "tell me more about the second one"],
]


class Shopper(HttpUser):
    wait_time = between(1, 3)  # think time between messages

    @task
    def conversation(self):
        customer = random.choice(CUSTOMERS)
        sid = None
        for msg in random.choice(FLOWS):
            with self.client.post("/chat", json={"message": msg, "session_id": sid, "customer_id": customer},
                                  name="/chat", catch_response=True) as r:
                if r.status_code != 200:
                    r.failure(f"HTTP {r.status_code}")
                    return
                body = r.json()
                sid = body["session_id"]
                if not body.get("reply"):
                    r.failure("empty reply")
