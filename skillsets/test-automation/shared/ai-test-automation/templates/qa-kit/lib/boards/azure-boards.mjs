import { createAdapter } from './adapter.mjs';

/** Azure Boards Work Item Tracking 7.1. Attach uses { filename, contentBase64 }. */
export function azureBoards(config) {
  const dryRun = config.dryRun ?? true;
  const request = createAdapter(config);
  const item = id => `/_apis/wit/workitems/${encodeURIComponent(id)}`;
  return {
    linkedItemsForChange: async change => {
      if (!change?.pullRequestId || !change?.project || !change?.repositoryId || !change?.organizationUrl) throw new Error('Azure association lookup requires organizationUrl, project, repositoryId and pullRequestId');
      const origin = new URL(config.baseUrl).origin;
      if (new URL(change.organizationUrl).origin !== origin) throw new Error('Azure change organization must match the configured board origin');
      const project = encodeURIComponent(change.project);
      const repository = encodeURIComponent(change.repositoryId);
      const pr = encodeURIComponent(change.pullRequestId);
      const path = `/${encodeURIComponent(new URL(change.organizationUrl).pathname.split('/').filter(Boolean)[0] ?? '')}/${project}/_apis/git/repositories/${repository}/pullRequests/${pr}/workitems?api-version=7.1`;
      const result = await request({ method: 'GET', path });
      return (result.data?.value ?? []).map(ref => ({ id: String(ref.id ?? ref.url?.split('/').at(-1) ?? '') })).filter(item => item.id);
    },
    read: id => request({ method: 'GET', path: `${item(id)}?$expand=relations&api-version=7.1` }),
    comment: async (id, body, marker) => {
      const path = `${item(id)}/comments?format=markdown&api-version=7.1-preview.4`;
      if (!dryRun) {
        const existing = await request({ method: 'GET', path });
        if ((existing.data?.comments ?? []).some(comment => (comment.text ?? '').includes(marker))) return { status: 200, duplicate: true, marker };
      }
      return request({ method: 'POST', path, body: { text: `${body}\n\n${marker}` } });
    },
    attach: async (id, artifact) => {
      if (!artifact?.filename || !artifact?.contentBase64) throw new Error('Azure attach requires filename and contentBase64');
      const upload = await request({ method: 'POST', path: `/_apis/wit/attachments?fileName=${encodeURIComponent(artifact.filename)}&api-version=7.1`, body: Buffer.from(artifact.contentBase64, 'base64'), contentType: artifact.contentType ?? 'application/octet-stream' });
      if (upload.dryRun) return { ...upload, followUp: { method: 'PATCH', path: `${item(id)}?api-version=7.1`, body: [{ op: 'add', path: '/relations/-', value: { rel: 'AttachedFile', url: '<upload.response.url>', attributes: { comment: artifact.filename } } }] } };
      const url = upload.data?.url;
      if (!url) throw new Error('Azure attachment upload response omitted url');
      const relation = await request({ method: 'PATCH', path: `${item(id)}?api-version=7.1`, body: [{ op: 'add', path: '/relations/-', value: { rel: 'AttachedFile', url, attributes: { comment: artifact.filename } } }] });
      return { upload, relation, confirmed: relation.status >= 200 && relation.status < 300 };
    },
    transition: (id, state, revision) => request({ method: 'PATCH', path: `${item(id)}?api-version=7.1`, body: [{ op: 'test', path: '/rev', value: Number(revision) }, { op: 'add', path: '/fields/System.State', value: state }] }),
    linkPr: (id, url, title = 'Pull request') => request({ method: 'PATCH', path: `${item(id)}?api-version=7.1`, body: [{ op: 'add', path: '/relations/-', value: { rel: 'Hyperlink', url, attributes: { comment: title } } }] }),
    verifyEvent: async ({ rawBody, signature, secret }) => {
      const { createHmac, timingSafeEqual } = await import('node:crypto');
      const expected = createHmac('sha256', secret).update(rawBody).digest('hex');
      return Boolean(signature && Buffer.byteLength(signature) === Buffer.byteLength(expected) && timingSafeEqual(Buffer.from(signature), Buffer.from(expected)));
    }
  };
}
