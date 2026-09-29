import { Pool } from "pg";

export function connect(databaseUrl: string): Pool {
  const parsed = new URL(databaseUrl);
  if (parsed.hostname !== "localhost") {
    throw new Error("Only the local database is permitted");
  }
  return new Pool({ connectionString: databaseUrl });
}
