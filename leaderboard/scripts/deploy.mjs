// Production deploy: typecheck, apply db/schema.sql to the production database, then `vercel --prod`.
// The schema goes first because new code may query tables or columns the old schema doesn't have yet;
// schema.sql is idempotent and only adds things, so the old deployment keeps working in between.
// Usage: npm run deploy [-- extra vercel args]
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const run = (cmd, args, env = process.env) => execFileSync(cmd, args, { stdio: "inherit", env });

console.log("› typecheck");
run("npm", ["run", "--silent", "typecheck"]);

console.log("› production DATABASE_URL");
const dir = mkdtempSync(join(tmpdir(), "tm-deploy-"));
let databaseUrl;
try {
  const file = join(dir, "prod.env");
  execFileSync("vercel", ["env", "pull", file, "--environment=production", "--yes"], { stdio: ["ignore", "ignore", "inherit"] });
  const line = readFileSync(file, "utf8").split("\n").find((l) => l.startsWith("DATABASE_URL="));
  databaseUrl = line?.slice("DATABASE_URL=".length).trim().replace(/^"(.*)"$/, "$1");
} finally {
  rmSync(dir, { recursive: true, force: true });   // the pulled file holds every production secret
}
if (!databaseUrl) {
  console.error("DATABASE_URL is not set for production in Vercel; nothing was deployed.");
  process.exit(1);
}

console.log("› schema");
run("node", ["scripts/db-init.mjs"], { ...process.env, DATABASE_URL: databaseUrl });

console.log("› vercel --prod");
run("vercel", ["--prod", ...process.argv.slice(2)]);
