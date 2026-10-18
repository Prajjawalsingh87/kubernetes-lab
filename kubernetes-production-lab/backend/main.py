import logging
import os
import sys
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Response

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


@app.get("/api/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/api/health/ready")
async def health_ready(response: Response):
    if db_pool is None:
        response.status_code = 503
        return {"status": "not-ready"}
    try:
        async with db_pool.acquire() as connection:
            await connection.execute("SELECT 1")
    except Exception:
        logger.warning("Readiness check failed", exc_info=True)
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
