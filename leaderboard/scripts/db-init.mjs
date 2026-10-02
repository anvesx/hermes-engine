// Applies db/schema.sql to DATABASE_URL. Usage: DATABASE_URL=... npm run db:init
import { readFileSync } from "node:fs";
import pg from "pg";

const client = new pg.Client({ connectionString: process.env.DATABASE_URL });
await client.connect();
await client.query(readFileSync(new URL("../db/schema.sql", import.meta.url), "utf8"));
await client.end();
console.log("schema applied");
