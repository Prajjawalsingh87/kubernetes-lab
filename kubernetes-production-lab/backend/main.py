import os
import sys
import asyncpg
from fastapi import FastAPI, Response
from pydantic import BaseModel
from typing import Optional
from contextlib import asynccontextmanager

required_variables = [
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
]

missing_variables = [var for var in required_variables if not os.environ.get(var)]

if missing_variables:
    print(f"Missing required variables: {', '.join(missing_variables)}", file=sys.stderr)
    sys.exit(1)

# Global pool
db_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    # Startup
    db_pool = await asyncpg.create_pool(
        host=os.environ.get("DB_HOST"),
        port=int(os.environ.get("DB_PORT", 5432)),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        min_size=1,
        max_size=10,
        command_timeout=5.0
    )
    yield
    # Shutdown
    if db_pool:
        await db_pool.close()

app = FastAPI(lifespan=lifespan)
# FastAPI disables x-powered-by by default, unlike Express

@app.get("/api/health/live")
async def health_live():
    return {"status": "alive"}

@app.get("/api/health/ready")
async def health_ready(response: Response):
    try:
        if db_pool:
            async with db_pool.acquire() as connection:
                await connection.execute("SELECT 1")
        response.status_code = 200
        return {"status": "ready"}
    except Exception:
        response.status_code = 503
        return {"status": "not-ready"}

@app.get("/api/database")
async def database(response: Response):
    try:
        if db_pool:
            async with db_pool.acquire() as connection:
                row = await connection.fetchrow("SELECT NOW() AS database_time, current_database() AS database_name")
        return {
            "message": "Backend and PostgreSQL are working",
            "database": dict(row)
        }
    except Exception as e:
        print(f"Database request failed: {str(e)}", file=sys.stderr)
        response.status_code = 500
        return {"message": "Database request failed"}
