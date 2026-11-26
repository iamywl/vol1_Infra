import os
import random
import socket
import time
import logging
import json
from contextlib import asynccontextmanager

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Structured JSON logging for Loki ingestion
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("order-service")

APP_VERSION = os.getenv("APP_VERSION", "v1.0.0")
SIMULATE_ERROR_RATE = float(os.getenv("SIMULATE_ERROR_RATE", "0.0"))
DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "orders")
DB_USER = os.getenv("DB_USER", "orderapp")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status", "version"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path", "version"],
)

if OTEL_ENDPOINT:
    resource = Resource(attributes={"service.name": "order-service", "service.version": APP_VERSION})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
    )
    trace.set_tracer_provider(provider)


def get_conn():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=3,
    )


def ensure_schema():
    if not DB_HOST:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    item VARCHAR(120) NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    version_tag VARCHAR(40) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        conn.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    for attempt in range(5):
        try:
            ensure_schema()
            break
        except Exception as exc:
            logger.warning(json.dumps({"event": "schema_init_retry", "attempt": attempt + 1, "error": str(exc)}))
            time.sleep(2)
    yield


app = FastAPI(title="order-service", version=APP_VERSION, lifespan=lifespan)
if OTEL_ENDPOINT:
    FastAPIInstrumentor.instrument_app(app)


class OrderCreate(BaseModel):
    item: str
    quantity: int = 1


@app.middleware("http")
async def metrics_and_chaos_middleware(request: Request, call_next):
    start = time.perf_counter()
    path = request.url.path
    status_code = "500"
    try:
        response = await call_next(request)
        status_code = str(response.status_code)
        return response
    finally:
        elapsed = time.perf_counter() - start
        if path != "/metrics":
            REQUEST_COUNT.labels(request.method, path, status_code, APP_VERSION).inc()
            REQUEST_LATENCY.labels(request.method, path, APP_VERSION).observe(elapsed)
            logger.info(
                json.dumps(
                    {
                        "service": "order-service",
                        "version": APP_VERSION,
                        "method": request.method,
                        "path": path,
                        "status": status_code,
                        "duration_ms": round(elapsed * 1000, 2),
                        "pod": socket.gethostname(),
                    }
                )
            )


@app.get("/livez")
def livez():
    return {"status": "alive", "version": APP_VERSION, "pod": socket.gethostname()}


@app.get("/healthz")
def healthz():
    db_ok = True
    if DB_HOST:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
        except Exception as exc:
            db_ok = False
            raise HTTPException(status_code=503, detail=f"db unhealthy: {exc}")
    return {"status": "ok", "version": APP_VERSION, "db_connected": db_ok, "pod": socket.gethostname()}


@app.get("/api/v1/version")
def version():
    api_key = os.getenv("API_KEY", "")
    return {
        "version": APP_VERSION,
        "pod": socket.gethostname(),
        "simulate_error_rate": SIMULATE_ERROR_RATE,
        "vault_secret_present": bool(api_key),
        "api_key_prefix": api_key[:8] if api_key else "",
    }


@app.get("/api/v1/orders")
def list_orders():
    if SIMULATE_ERROR_RATE > 0 and random.random() < SIMULATE_ERROR_RATE:
        raise HTTPException(status_code=500, detail=f"injected error in {APP_VERSION}")
    if not DB_HOST:
        return {"version": APP_VERSION, "orders": []}
    ensure_schema()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, item, quantity, version_tag, created_at FROM orders ORDER BY id DESC LIMIT 20;")
            rows = cur.fetchall()
    return {"version": APP_VERSION, "pod": socket.gethostname(), "orders": rows}


@app.post("/api/v1/orders", status_code=201)
def create_order(payload: OrderCreate):
    if SIMULATE_ERROR_RATE > 0 and random.random() < SIMULATE_ERROR_RATE:
        raise HTTPException(status_code=500, detail=f"injected error in {APP_VERSION}")
    if not DB_HOST:
        return {"id": 0, "item": payload.item, "quantity": payload.quantity, "version": APP_VERSION}
    ensure_schema()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO orders (item, quantity, version_tag) VALUES (%s, %s, %s) RETURNING id, item, quantity, version_tag, created_at;",
                (payload.item, payload.quantity, APP_VERSION),
            )
            row = cur.fetchone()
        conn.commit()
    return {"version": APP_VERSION, "pod": socket.gethostname(), "order": row}


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
