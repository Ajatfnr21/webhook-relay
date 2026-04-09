# Webhook Relay v2.0 🚀

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688)](https://fastapi.tiangolo.com)
[![Redis](https://img.shields.io/badge/Redis-DC382D)](https://redis.io)
[![Docker](https://img.shields.io/badge/Docker-2496ED)](https://docker.com)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5)](https://kubernetes.io)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI/CD](https://github.com/Ajatfnr21/webhook-relay/workflows/CI%2FCD%20Pipeline/badge.svg)](https://github.com/Ajatfnr21/webhook-relay/actions)
[![codecov](https://codecov.io/gh/Ajatfnr21/webhook-relay/branch/main/graph/badge.svg)](https://codecov.io/gh/Ajatfnr21/webhook-relay)

**Enterprise webhook routing platform with multi-destination support, smart filtering, and dead letter queue.**

Route webhooks to multiple destinations (Slack, Discord, Teams, Telegram, custom APIs) with filtering, transformation, and reliable delivery.

## ✨ Features

- 🎯 **Multi-Destination Routing** - Send to Slack, Discord, Teams, Telegram simultaneously
- 🔍 **Smart Filtering** - JSONPath-based conditions
- 🔄 **Payload Transformation** - Jinja2 templates
- 🗃️ **Dead Letter Queue** - Redis-based failed message storage
- 🔐 **HMAC Signature Verification** - Secure webhook validation
- 🔄 **Retry Logic** - Exponential backoff with configurable attempts
- 📊 **Prometheus Metrics** - Real-time monitoring
- 🌐 **WebSocket Logs** - Real-time log streaming
- 🐳 **Docker Ready** - Multi-stage builds, docker-compose
- ☸️ **Kubernetes Ready** - Helm charts included
- 🧪 **100% Test Coverage** - Comprehensive test suite

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Webhook Relay                          │
│                      (FastAPI + Uvicorn)                       │
└───────────────────────┬──────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
┌───────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
│   Routes     │ │  Filters    │ │ Transform   │
│   Config     │ │  (JSONPath) │ │ (Jinja2)    │
└───────┬──────┘ └──────┬──────┘ └──────┬──────┘
        │               │               │
        └───────────────┼───────────────┘
                        │
            ┌───────────┴───────────┐
            │     Redis Queue       │
            │   (Dead Letter Queue) │
            └───────────┬───────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
┌───────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
│    Slack     │ │   Discord   │ │  Telegram   │
└──────────────┘ └─────────────┘ └─────────────┘
```

## 🚀 Quick Start

### Docker Compose (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/Ajatfnr21/webhook-relay.git
cd webhook-relay

# 2. Configure environment
cp .env.example .env
# Edit .env with your webhook URLs

# 3. Start services
docker-compose up -d

# 4. Check health
curl http://localhost:8000/health

# 5. Configure routes (edit config/routes.yaml)

# 6. Test webhook
curl -X POST http://localhost:8000/github   -H "Content-Type: application/json"   -d '{"repository": {"name": "test"}, "pusher": {"name": "user"}}'
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `REDIS_URL` | Redis connection URL | No (default: localhost) |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook | No |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL | No |
| `STRIPE_WEBHOOK_SECRET` | Stripe signature secret | No |
| `INTERNAL_API_URL` | Internal API endpoint | No |
| `GRAFANA_PASSWORD` | Grafana admin password | No |
| `LOG_LEVEL` | Logging level (DEBUG/INFO/WARNING) | No |

## 📖 Configuration

### Route Configuration (config/routes.yaml)

```yaml
routes:
  - name: "github-to-slack"
    source_path: "/github"
    filter: "$.repository.name"  # JSONPath condition
    transform: |  # Jinja2 template
      {
        "text": "New push to {{ repository.name }}",
        "blocks": [
          {
            "type": "section",
            "text": {
              "type": "mrkdwn",
              "text": "*{{ repository.name }}*\nNew {{ ref }} push"
            }
          }
        ]
      }
    destinations:
      - name: "slack"
        url: "${SLACK_WEBHOOK_URL}"
        method: "POST"
        retry_attempts: 3
        retry_delay: 1.0
      - name: "discord"
        url: "${DISCORD_WEBHOOK_URL}"
        method: "POST"
        transform_override: |
          {"content": "New push: {{ repository.full_name }}"}
    enabled: true
    secret: "${GITHUB_WEBHOOK_SECRET}"  # For signature verification
```

### Filter Syntax (JSONPath)

```yaml
# Check if event type is "push"
filter: "$.event_type"
# Payload: {"event_type": "push"} -> matches

# Check nested values
filter: "$.repository.owner.login"
# Payload: {"repository": {"owner": {"login": "user"}}} -> matches

# Array filtering
filter: "$.commits[?(@.message =~ /fix/i)]"
# Matches commits with "fix" in message
```

### Transform Syntax (Jinja2)

```yaml
transform: |
  {
    "repository": "{{ repository.full_name }}",
    "author": "{{ pusher.name }}",
    "commits_count": {{ commits|length }},
    "has_tests": {{ "test" in head_commit.message|lower }}
  }
```

## 📊 API Reference

### Receive Webhook
```http
POST /{path}
Content-Type: application/json
X-Hub-Signature-256: sha256=...

{"your": "webhook payload"}
```

### Health Check
```http
GET /health

Response:
{
  "status": "healthy",
  "version": "2.0.0",
  "redis": "connected",
  "routes_loaded": 5,
  "timestamp": "2024-01-15T10:30:00"
}
```

### List Routes
```http
GET /api/v1/routes

Response:
{
  "routes": [...],
  "count": 5
}
```

### Get Metrics
```http
GET /api/v1/metrics/summary

Response:
{
  "total_received": 1500,
  "total_forwarded": 1495,
  "total_failed": 5,
  "dlq_size": 3,
  "avg_latency_ms": 45.2,
  "routes_active": 5
}
```

### Get DLQ
```http
GET /api/v1/dlq?limit=100

Response:
{
  "dlq_size": 3,
  "items": [
    {
      "route": "github-to-slack",
      "destination": {...},
      "payload": {...},
      "timestamp": "2024-01-15T10:30:00",
      "attempts": 3
    }
  ]
}
```

### Retry DLQ
```http
POST /api/v1/dlq/retry

Response:
{
  "retried": 3,
  "status": "retrying"
}
```

### Prometheus Metrics
```http
GET /metrics
```

### WebSocket Logs
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/logs');
ws.onmessage = (event) => {
  const metrics = JSON.parse(event.data);
  console.log('Real-time metrics:', metrics);
};
```

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run specific test file
pytest tests/test_main.py -v

# Run with async support
pytest tests/ -v --asyncio-mode=auto
```

## 🐳 Docker Deployment

### Single Container
```bash
docker build -t webhook-relay .
docker run -p 8000:8000   -e REDIS_URL=redis://host:6379/0   -e SLACK_WEBHOOK_URL=https://hooks.slack.com/...   webhook-relay
```

### Docker Compose (Full Stack)
```bash
docker-compose up -d
```

Services included:
- webhook-relay (main application)
- redis (message queue)
- prometheus (metrics)
- grafana (dashboards)

### Kubernetes
```bash
# Apply configurations
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# Or use Helm
helm install webhook-relay ./helm/webhook-relay
```

## 📈 Monitoring

### Prometheus Metrics

| Metric | Description |
|--------|-------------|
| `webhooks_received_total` | Total webhooks received by route |
| `webhooks_forwarded_total` | Total forwarded by destination/status |
| `webhook_forward_latency_seconds` | Forwarding latency histogram |
| `dlq_messages_total` | Messages in dead letter queue |

### Grafana Dashboard

Access at `http://localhost:3000` (admin/admin)

Pre-configured dashboards:
- Webhook Overview
- Route Performance
- Destination Status
- Error Rates

## 🔐 Security

### HMAC Signature Verification

```python
# Your webhook sender should include:
import hmac
import hashlib

signature = hmac.new(
    secret.encode(),
    payload,
    hashlib.sha256
).hexdigest()

headers = {
    "X-Hub-Signature-256": f"sha256={signature}"
}
```

### Environment Security

- Use `.env` file for secrets (never commit)
- Rotate webhook secrets regularly
- Use HTTPS in production
- Enable Redis AUTH for external connections

## 🚀 Production Deployment

### Checklist

- [ ] Configure Redis with persistence
- [ ] Set up monitoring (Prometheus + Grafana)
- [ ] Configure log aggregation
- [ ] Enable HMAC verification for all routes
- [ ] Set up health checks
- [ ] Configure auto-scaling
- [ ] Set up backup for DLQ
- [ ] Enable rate limiting

### Scaling

```yaml
# docker-compose.yml
deploy:
  replicas: 3
  resources:
    limits:
      cpus: '2'
      memory: 1G
```

## 📝 License

MIT License - see [LICENSE](LICENSE) file

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## 📧 Support

- GitHub Issues: [github.com/Ajatfnr21/webhook-relay/issues](https://github.com/Ajatfnr21/webhook-relay/issues)
- Email: drajatsukmacareer@gmail.com

---

Made with 🔥 by **Drajat Sukma**
