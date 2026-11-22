import { Pool } from "pg";
import { parse } from "pg-connection-string";

export function connect(databaseUrl: string): Pool {
  const parsed = parse(databaseUrl);
  if (parsed.host !== "localhost") {
    throw new Error("Only the local database is permitted");
  }
  return new Pool({ connectionString: databaseUrl });
}
