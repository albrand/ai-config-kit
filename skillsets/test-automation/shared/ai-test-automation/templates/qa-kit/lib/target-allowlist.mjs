// Deployment target allowlist. A run against a URL that is not loopback must name an environment whose
// declared `origins` contain that URL's origin; otherwise it refuses to start with TARGET_NOT_ALLOWED.
const LOOPBACK = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

export function parseOrigin(url) {
  try { const u = new URL(url); return /^https?:$/.test(u.protocol) ? { origin: u.origin, hostname: u.hostname } : null; } catch { return null; }
}

export const isLoopbackUrl = url => { const p = parseOrigin(url); return Boolean(p) && LOOPBACK.has(p.hostname); };

/** A target is deployed when a base URL is set and it is not loopback. Environment checks apply only then. */
export const isDeployedTarget = baseUrl => Boolean(baseUrl) && !isLoopbackUrl(baseUrl);

export function checkTarget({ baseUrl, environment = 'local', config = {} }) {
  if (!baseUrl) return { ok: true, deployed: false };
  const refuse = detail => ({ ok: false, code: 'TARGET_NOT_ALLOWED', reason: `TARGET_NOT_ALLOWED: ${detail}` });
  const parsed = parseOrigin(baseUrl);
  if (!parsed) return refuse('base URL is not a valid http(s) URL');
  if (LOOPBACK.has(parsed.hostname)) return { ok: true, deployed: false };
  if (environment === 'local') return refuse(`environment "local" may only target loopback hosts, got ${parsed.origin}`);
  const origins = config.environments?.[environment]?.origins;
  if (!Array.isArray(origins) || !origins.length) return refuse(`environment "${environment}" declares no origins`);
  const allowed = origins.map(o => parseOrigin(o)?.origin).filter(Boolean);
  if (!allowed.includes(parsed.origin)) return refuse(`${parsed.origin} is not in the declared origins of "${environment}"`);
  return { ok: true, deployed: true };
}
