const express = require("express");
const { Pool } = require("pg");

const app = express();

const port = Number(process.env.PORT || 8080);

const requiredVariables = [
  "DB_HOST",
  "DB_PORT",
  "DB_NAME",
  "DB_USER",
  "DB_PASSWORD",
];

const missingVariables = requiredVariables.filter(
  (variable) => !process.env[variable]
);

if (missingVariables.length > 0) {
  console.error(
    `Missing required variables: ${missingVariables.join(", ")}`
  );
  process.exit(1);
}

const pool = new Pool({
  host: process.env.DB_HOST,
  port: Number(process.env.DB_PORT),
  database: process.env.DB_NAME,
  user: process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  max: 10,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
});

app.disable("x-powered-by");

app.get("/api/health/live", (request, response) => {
  response.status(200).json({
    status: "alive",
  });
});

app.get("/api/health/ready", async (request, response) => {
  try {
    await pool.query("SELECT 1");

    response.status(200).json({
      status: "ready",
    });
  } catch (error) {
    response.status(503).json({
      status: "not-ready",
    });
  }
});

app.get("/api/database", async (request, response) => {
  try {
    const result = await pool.query(`
      SELECT
        NOW() AS database_time,
        current_database() AS database_name
    `);

    response.status(200).json({
      message: "Backend and PostgreSQL are working",
      database: result.rows[0],
    });
  } catch (error) {
    console.error("Database request failed:", error.message);

    response.status(500).json({
      message: "Database request failed",
    });
  }
});

const server = app.listen(port, "0.0.0.0", () => {
  console.log(`Backend listening on port ${port}`);
});

async function shutdown(signal) {
  console.log(`Received ${signal}; shutting down`);

  server.close(async () => {
    await pool.end();
    process.exit(0);
  });

  setTimeout(() => {
    process.exit(1);
  }, 10000).unref();
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));