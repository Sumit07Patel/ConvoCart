# Design note: running ConvoCart in a client's private cloud

*This is a design, not something built or tested in this project.*

## Goal

The client's shopper conversations, order data and prompts never leave their cloud account, and the model runs inside it too.

## What already supports this

- **Swappable model wrapper.** Every model call goes through one OpenAI-compatible client chosen by `LLM_PROVIDER` / `LLM_BASE_URL`. Pointing it at a model server inside the VPC is a configuration change, not a code change. The Ollama option in this repo is the small-scale version: the model runs on the same machine and no data goes out.
- **Agent layer separate from the store.** The agent talks to commerce only through the `Commerce` interface over HTTP. Swapping the demo store for the client's Medusa, Shopify Plus or SAP backend means writing one adapter.
- **Rules in code.** Because guardrails don't depend on the model, a smaller self-hosted model can be used without loosening any rule. The eval gate measures whether it is good enough.
- **Everything in containers**, configured by environment variables, with Postgres as the only stateful dependency.

## Proposed layout (AWS names; GCP and Azure have equivalents)

| Part | Where |
| --- | --- |
| Agent service, store adapter, cron | Containers on ECS Fargate or EKS in private subnets |
| Model | vLLM or Ollama on a GPU instance (or a managed model endpoint inside the account, such as Bedrock with a VPC endpoint), reachable only from the agent's security group |
| Database | RDS Postgres with pgvector, encrypted, private subnets, automated backups |
| Inbound traffic | A public load balancer with WAF serves the chat API and `/unsubscribe`, and accepts `/webhooks/store`; everything else is internal |
| Web chat | Static files on S3 + CloudFront; API through the same load balancer with auth |
| Secrets | Secrets Manager for the mail credentials, store API key, admin token |
| Traces | The `trace_events` table, or a self-hosted Langfuse in the same VPC |
| Egress | NAT with an allow list: Meta Graph API and the store backend only |

## Data handling

- Conversation history kept 30 days by default, then deleted; traces keep tool names and error codes, and redact message text after 30 days.
- Phone numbers and names stay in the store database; prompts carry only what a turn needs.
- The mail provider is the one unavoidable external hop: it delivers the come-back emails and order confirmations.

## Model sizing (to measure, not assume)

Run `eval/tool_calling_test.py` and `eval/run_scenarios.py --provider ollama` (or the in-VPC endpoint) on 7-8B and 14B-class tool-calling models. Pick the smallest that passes the gate (zero violations, task success above the agreed bar, Hindi/Hinglish replies reviewed by a native speaker), then load-test it with Locust at the expected peak concurrency to size the GPU.

## Open questions for the client

Which commerce backend and how its auth works; which mail provider and sending domain they use; retention rules required by their legal team; who staffs the handover queue and in which hours.
