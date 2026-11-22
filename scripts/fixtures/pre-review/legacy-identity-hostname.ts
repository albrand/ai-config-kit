export function allowed(url: string): boolean {
  return new URL(url).hostname.startsWith("localhost");
}
