#!/usr/bin/env python3
"""
Webhook Relay v2.0 - Enterprise Webhook Routing Platform
Multi-destination webhook routing with filtering, transformation, and dead letter queue

Features:
- Multi-destination routing (Slack, Discord, Teams, Telegram)
- Smart filtering with JSONPath conditions
- Payload transformation with Jinja2 templates
- Redis-based dead letter queue
- HMAC-SHA256 signature verification
- Retry logic with exponential backoff
- REST API for configuration management
- Prometheus metrics
- WebSocket real-time logs
- Docker & Kubernetes ready

Author: Drajat Sukma
License: MIT
"""

__version__ = "2.0.0"

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Request, BackgroundTasks, WebSocket
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import yaml
from pydantic import BaseModel, HttpUrl, Field
import redis.asyncio as redis
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import jinja2
import jsonpath_ng

# Prometheus metrics
WEBHOOK_RECEIVED = Counter('webhooks_received_total', 'Total webhooks received', ['route'])
WEBHOOK_FORWARDED = Counter('webhooks_forwarded_total', 'Total webhooks forwarded', ['destination', 'status'])
WEBHOOK_LATENCY = Histogram('webhook_forward_latency_seconds', 'Webhook forwarding latency')
DLQ_COUNT = Counter('dlq_messages_total', 'Total messages in dead letter queue')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# Global state
redis_client: Optional[redis.Redis] = None
config_cache: Dict = {}
template_env = jinja2.Environment()

# Pydantic models
class RouteConfig(BaseModel):
    """Route configuration model"""
    name: str = Field(..., description="Route name")
    source_path: str = Field(..., description="Incoming webhook path")
    destinations: List[Dict[str, Any]] = Field(..., description="Destination endpoints")
    filter_condition: Optional[str] = Field(None, description="JSONPath filter condition")
    transform_template: Optional[str] = Field(None, description="Jinja2 transform template")
    secret: Optional[str] = Field(None, description="HMAC secret for verification")
    retry_config: Optional[Dict] = Field(None, description="Retry configuration")
    enabled: bool = Field(True, description="Is route enabled")

class DestinationConfig(BaseModel):
    """Destination configuration"""
    name: str
    url: str
    method: str = "POST"
    headers: Optional[Dict[str, str]] = None
    timeout: int = 30
    retry_attempts: int = 3
    retry_delay: float = 1.0
    transform_override: Optional[str] = None

class WebhookMetrics(BaseModel):
    """Webhook metrics response"""
    total_received: int
    total_forwarded: int
    total_failed: int
    dlq_size: int
    avg_latency_ms: float
    routes_active: int

# FastAPI app
app = FastAPI(
    title="Webhook Relay",
    version="2.0.0",
    description="Enterprise webhook routing platform"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    global redis_client
    
    # Startup
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_client = await redis.from_url(redis_url, decode_responses=True)
    
    # Load config
    await load_config()
    
    logger.info("🚀 Webhook Relay started")
    
    yield
    
    # Shutdown
    if redis_client:
        await redis_client.close()
    logger.info("👋 Webhook Relay stopped")

app.router.lifespan_context = lifespan

# Helper functions
def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature"""
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)

async def load_config() -> Dict:
    """Load route configuration from file or Redis"""
    global config_cache
    
    try:
        with open("config/routes.yaml", "r") as f:
            config_cache = yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning("Config file not found, using defaults")
        config_cache = get_default_config()
    
    return config_cache

def get_default_config() -> Dict:
    """Default configuration"""
    return {
        "routes": [
            {
                "name": "github-to-slack",
                "source_path": "/github",
                "filter": "$.repository.name",
                "destinations": [
                    {
                        "name": "slack",
                        "url": "${SLACK_WEBHOOK_URL}",
                        "method": "POST"
                    }
                ]
            }
        ]
    }

def apply_filter(payload: dict, condition: str) -> bool:
    """Apply JSONPath filter condition"""
    try:
        jsonpath_expr = jsonpath_ng.parse(condition)
        matches = jsonpath_expr.find(payload)
        return len(matches) > 0
    except Exception as e:
        logger.error(f"Filter error: {e}")
        return True

def transform_payload(payload: dict, template: str) -> dict:
    """Transform payload using Jinja2 template"""
    try:
        jinja_template = template_env.from_string(template)
        transformed = jinja_template.render(**payload)
        return json.loads(transformed)
    except Exception as e:
        logger.error(f"Transform error: {e}")
        return payload

async def send_with_retry(
    client: httpx.AsyncClient,
    dest: Dict,
    payload: dict,
    headers: dict
) -> bool:
    """Send webhook with retry logic"""
    url = dest.get("url")
    method = dest.get("method", "POST")
    timeout = dest.get("timeout", 30)
    max_retries = dest.get("retry_attempts", 3)
    retry_delay = dest.get("retry_delay", 1.0)
    
    for attempt in range(max_retries):
        try:
            with WEBHOOK_LATENCY.time():
                if method.upper() == "POST":
                    response = await client.post(url, json=payload, headers=headers, timeout=timeout)
                elif method.upper() == "PUT":
                    response = await client.put(url, json=payload, headers=headers, timeout=timeout)
                else:
                    response = await client.request(method, url, json=payload, headers=headers, timeout=timeout)
            
            if response.status_code < 400:
                WEBHOOK_FORWARDED.labels(destination=dest.get("name", "unknown"), status="success").inc()
                return True
            else:
                logger.warning(f"Attempt {attempt + 1}: HTTP {response.status_code}")
                
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}: {str(e)}")
        
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
    
    WEBHOOK_FORWARDED.labels(destination=dest.get("name", "unknown"), status="failed").inc()
    return False

async def send_to_destination(
    dest: Dict,
    payload: dict,
    headers: dict,
    route_name: str
):
    """Send webhook to destination with full error handling"""
    success = False
    
    try:
        async with httpx.AsyncClient() as client:
            success = await send_with_retry(client, dest, payload, headers)
    except Exception as e:
        logger.error(f"Failed to send to {dest.get('name')}: {e}")
    
    if not success:
        # Add to dead letter queue
        dlq_entry = {
            "route": route_name,
            "destination": dest,
            "payload": payload,
            "headers": headers,
            "timestamp": datetime.now().isoformat(),
            "attempts": dest.get("retry_attempts", 3)
        }
        
        await redis_client.lpush("webhook_dlq", json.dumps(dlq_entry))
        DLQ_COUNT.inc()
        logger.warning(f"Added to DLQ: {dest.get('name')}")

# API Endpoints
@app.post("/{path:path}")
async def receive_webhook(
    request: Request,
    path: str,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None),
    x_webhook_signature: Optional[str] = Header(None)
):
    """
    Receive and route webhooks
    
    - **path**: Webhook endpoint path
    - **x-hub-signature-256**: GitHub-style HMAC signature
    - **x-webhook-signature**: Generic signature header
    """
    start_time = time.time()
    
    try:
        body = await request.body()
        
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw_body": body.decode()}
        
        headers = dict(request.headers)
        source_path = f"/{path}"
        
        WEBHOOK_RECEIVED.labels(route=source_path).inc()
        
        # Find matching routes
        routes = [r for r in config_cache.get("routes", []) if r.get("source_path") == source_path and r.get("enabled", True)]
        
        if not routes:
            raise HTTPException(status_code=404, detail=f"No route configured for {source_path}")
        
        routed_count = 0
        
        for route in routes:
            # Verify signature if configured
            if route.get("secret"):
                sig = x_hub_signature_256 or x_webhook_signature
                if not sig or not verify_signature(body, sig, route["secret"]):
                    logger.warning(f"Signature verification failed for route: {route['name']}")
                    continue
            
            # Apply filter
            if route.get("filter"):
                if not apply_filter(payload, route["filter"]):
                    logger.info(f"Filter blocked for route: {route['name']}")
                    continue
            
            # Transform payload
            transformed = payload
            if route.get("transform"):
                transformed = transform_payload(payload, route["transform"])
            
            # Send to all destinations
            for dest in route.get("destinations", []):
                # Apply destination-specific transform if exists
                final_payload = transformed
                if dest.get("transform_override"):
                    final_payload = transform_payload(payload, dest["transform_override"])
                
                background_tasks.add_task(
                    send_to_destination,
                    dest,
                    final_payload,
                    headers,
                    route["name"]
                )
                routed_count += 1
        
        latency = (time.time() - start_time) * 1000
        
        return JSONResponse({
            "status": "accepted",
            "routed_to": routed_count,
            "routes_matched": len(routes),
            "latency_ms": round(latency, 2),
            "timestamp": datetime.now().isoformat()
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    redis_status = "connected" if redis_client else "disconnected"
    
    try:
        if redis_client:
            await redis_client.ping()
    except:
        redis_status = "error"
    
    return {
        "status": "healthy",
        "version": __version__,
        "redis": redis_status,
        "routes_loaded": len(config_cache.get("routes", [])),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return JSONResponse(
        content=generate_latest().decode(),
        media_type=CONTENT_TYPE_LATEST
    )

@app.get("/api/v1/routes")
async def list_routes():
    """List all configured routes"""
    return {
        "routes": config_cache.get("routes", []),
        "count": len(config_cache.get("routes", []))
    }

@app.get("/api/v1/dlq")
async def get_dlq(limit: int = 100):
    """Get dead letter queue items"""
    items = await redis_client.lrange("webhook_dlq", 0, limit - 1)
    return {
        "dlq_size": await redis_client.llen("webhook_dlq"),
        "items": [json.loads(item) for item in items]
    }

@app.post("/api/v1/dlq/retry")
async def retry_dlq(background_tasks: BackgroundTasks):
    """Retry all DLQ items"""
    items = await redis_client.lrange("webhook_dlq", 0, -1)
    
    retried = 0
    for item in items:
        data = json.loads(item)
        background_tasks.add_task(
            send_to_destination,
            data["destination"],
            data["payload"],
            data.get("headers", {}),
            data["route"]
        )
        retried += 1
    
    # Clear DLQ
    await redis_client.delete("webhook_dlq")
    
    return {"retried": retried, "status": "retrying"}

@app.get("/api/v1/metrics/summary")
async def get_metrics_summary() -> WebhookMetrics:
    """Get webhook metrics summary"""
    dlq_size = await redis_client.llen("webhook_dlq")
    
    return WebhookMetrics(
        total_received=int(WEBHOOK_RECEIVED._value.get()),
        total_forwarded=int(WEBHOOK_FORWARDED._value.get()),
        total_failed=int(DLQ_COUNT._value.get()),
        dlq_size=dlq_size,
        avg_latency_ms=0.0,  # Calculate from histogram
        routes_active=len(config_cache.get("routes", []))
    )

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket endpoint for real-time logs"""
    await websocket.accept()
    
    try:
        while True:
            # Send current metrics every second
            metrics = {
                "timestamp": datetime.now().isoformat(),
                "total_received": int(WEBHOOK_RECEIVED._value.get()),
                "dlq_size": await redis_client.llen("webhook_dlq")
            }
            await websocket.send_json(metrics)
            await asyncio.sleep(1)
    except:
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
