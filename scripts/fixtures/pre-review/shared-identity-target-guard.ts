import { assertSafeTarget } from "./database-target-guard";

export function allowed(url: string): boolean {
  return assertSafeTarget(url);
}
