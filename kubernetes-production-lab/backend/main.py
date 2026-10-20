import logging
import os
import sys
import time
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REQUIRED_VARIABLES = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("backend")

missing_variables = [var for var in REQUIRED_VARIABLES if not os.environ.get(var)]
if missing_variables:
    print(f"Missing required variables: {', '.join(missing_variables)}", file=sys.stderr)
    sys.exit(1)

# Global connection pool, created on startup.
db_pool: asyncpg.Pool | None = None

# Prometheus metrics. Labels use the route *template* (e.g. "/api/health/ready"),
# never the raw URL path, so label cardinality stays bounded.
REQUEST_COUNT = Counter(
    "http_requests_total",
    "HTTP requests handled by the backend.",
    ["method", "route", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
DB_UP = Gauge("database_up", "1 if the last PostgreSQL check succeeded, else 0.")
DB_CHECK_TIMEOUT_SECONDS = 2.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    db_pool = await asyncpg.create_pool(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        min_size=1,
        max_size=10,
        command_timeout=5.0,
    )
    logger.info("Database pool created for %s:%s", os.environ["DB_HOST"], os.environ["DB_PORT"])
    yield
    if db_pool:
        await db_pool.close()


app = FastAPI(lifespan=lifespan)


def route_template(request: Request) -> str:
    """Matched route path template, or a fixed label for unmatched paths (404s)."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = route_template(request)
        REQUEST_LATENCY.labels(request.method, route).observe(time.perf_counter() - start)
        REQUEST_COUNT.labels(request.method, route, str(status)).inc()


async def check_database() -> bool:
    """Run SELECT 1 against the pool and record the result in database_up."""
    if db_pool is None:
        DB_UP.set(0)
        return False
    try:
        async with db_pool.acquire(timeout=DB_CHECK_TIMEOUT_SECONDS) as connection:
            await connection.execute("SELECT 1", timeout=DB_CHECK_TIMEOUT_SECONDS)
    except Exception:  # includes TimeoutError
        logger.warning("Database check failed", exc_info=True)
        DB_UP.set(0)
        return False
    DB_UP.set(1)
    return True


@app.get("/metrics", include_in_schema=False)
async def metrics():
    # Not under /api, so the Ingress never exposes it; scrape it in-cluster.
    await check_database()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/api/health/ready")
async def health_ready(response: Response):
    if not await check_database():
        response.status_code = 503
        return {"status": "not-ready"}
    return {"status": "ready"}


@app.get("/api/database")
async def database(response: Response):
    if db_pool is None:
        response.status_code = 503
        return {"message": "Database pool is not initialised"}
    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT NOW() AS database_time, current_database() AS database_name"
            )
    except Exception:
        logger.exception("Database request failed")
        response.status_code = 500
        return {"message": "Database request failed"}
    return {
        "message": "Backend and PostgreSQL are working",
        "database": dict(row),
    }
