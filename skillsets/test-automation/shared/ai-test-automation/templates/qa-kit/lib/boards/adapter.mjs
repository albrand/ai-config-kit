import { createHash } from 'node:crypto';

/** Small request executor shared by board adapters. No request is sent by default. */
export function createAdapter({ baseUrl, token, authorization, fetchImpl = fetch, dryRun = true, headers = {} }) {
  if (!baseUrl) throw new Error('baseUrl is required');
  const parsedBase = new URL(baseUrl);
  if (parsedBase.protocol !== 'https:' || parsedBase.username || parsedBase.password || parsedBase.search || parsedBase.hash) throw new Error('board baseUrl must be a clean HTTPS origin/path');
  return async function request({ method, path, body, headers: extra = {}, contentType = 'application/json' }) {
    const requestHeaders = { accept: 'application/json', ...headers, ...extra };
    if (authorization) requestHeaders.authorization = authorization;
    else if (token) requestHeaders.authorization = `Bearer ${token}`;
    if (contentType) requestHeaders['content-type'] = contentType;
    const url = new URL(path, baseUrl).toString();
    const requestBody = body === undefined ? undefined : (typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body));
    const request = { method, url, headers: requestHeaders, body: requestBody };
    if (dryRun) return { dryRun: true, request: { ...request, headers: { ...requestHeaders, ...(requestHeaders.authorization ? { authorization: '[redacted]' } : {}) }, authConfigured: Boolean(requestHeaders.authorization) } };
    const response = await fetchImpl(url, { method, headers: requestHeaders, body: requestBody });
    const text = await response.text();
    let data = text;
    try { data = text ? JSON.parse(text) : null; } catch { /* keep non-JSON response */ }
    if (!response.ok) {
      const error = new Error(`board request failed: ${method} ${url} returned ${response.status}`);
      error.status = response.status;
      error.retryAfter = response.headers?.get?.('retry-after');
      error.response = data;
      throw error;
    }
    return { status: response.status, headers: Object.fromEntries(response.headers ?? []), data };
  };
}

export function commentMarker(workItem, commit, content) {
  const hash = createHash('sha256').update(String(content)).digest('hex').slice(0, 16);
  return `<!-- qa-report:${workItem}:${commit}:${hash} -->`;
}
