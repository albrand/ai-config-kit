import { Pool } from "pg";

export const pool = new Pool({ connectionString: process.env.DATABASE_URL });
export const seed = { password: "demo-password" };
