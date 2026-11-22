import { Pool } from "pg";
import { assertSafeTarget } from "./database-target-guard";

assertSafeTarget(process.env.DATABASE_URL);
export const pool = new Pool({ connectionString: process.env.DATABASE_URL });
export const seed = { password: "demo-password" };
