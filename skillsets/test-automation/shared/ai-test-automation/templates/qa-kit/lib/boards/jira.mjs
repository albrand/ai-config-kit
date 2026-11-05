import { createAdapter } from './adapter.mjs';

/** Jira Cloud v3. `attach` accepts { filename, contentBase64 }. */
export function jira(config) {
  const dryRun = config.dryRun ?? true;
  const request = createAdapter({ ...config, headers: { 'x-atlassian-token': 'no-check' } });
  const root = id => `/rest/api/3/issue/${encodeURIComponent(id)}`;
  return {
    read: id => request({ method: 'GET', path: `${root(id)}?fields=summary,status,issuetype,updated,project,issuelinks,customfield_10020` }),
    comment: async (id, body, marker) => {
      const path = `${root(id)}/comment`;
      if (!dryRun) {
        const existing = await request({ method: 'GET', path: `${root(id)}/comment?maxResults=100` });
        const comments = existing.data?.comments ?? [];
        if (comments.some(comment => JSON.stringify(comment.body).includes(marker))) return { status: 200, duplicate: true, marker };
      }
      return request({ method: 'POST', path, body: { body: { type: 'doc', version: 1, content: [{ type: 'paragraph', content: [{ type: 'text', text: `${body}\n${marker}` }] }] } } });
    },
    attach: (id, artifact) => {
      if (!artifact?.filename || !artifact?.contentBase64) throw new Error('Jira attach requires filename and contentBase64');
      const bytes = Buffer.from(artifact.contentBase64, 'base64');
      const boundary = `qa-${Date.now().toString(16)}`;
      const prefix = Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${artifact.filename.replaceAll('"', '')}"\r\nContent-Type: ${artifact.contentType ?? 'application/octet-stream'}\r\n\r\n`);
      const suffix = Buffer.from(`\r\n--${boundary}--\r\n`);
      return request({ method: 'POST', path: `${root(id)}/attachments`, body: Buffer.concat([prefix, bytes, suffix]), contentType: `multipart/form-data; boundary=${boundary}`, headers: { 'x-atlassian-token': 'no-check' } });
    },
    transition: async (id, transitionId, revision) => {
      const headers = revision === undefined ? {} : { 'if-match': String(revision) };
      return request({ method: 'POST', path: `${root(id)}/transitions`, body: { transition: { id: String(transitionId) } }, headers });
    },
    linkPr: (id, url, title = 'Automated test report') => request({ method: 'POST', path: `${root(id)}/remotelink`, body: { object: { url, title } } }),
    verifyEvent: async ({ rawBody, signature, secret }) => {
      const { createHmac, timingSafeEqual } = await import('node:crypto');
      const expected = `sha256=${createHmac('sha256', secret).update(rawBody).digest('hex')}`;
      return Boolean(signature && Buffer.byteLength(signature) === Buffer.byteLength(expected) && timingSafeEqual(Buffer.from(signature), Buffer.from(expected)));
    }
  };
}
