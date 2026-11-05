import { createAdapter } from './adapter.mjs';

/** GitHub Issues and Projects v2. repo is owner/name; project operations need configured IDs. */
export function github(config) {
  if (!config.repo || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(config.repo)) throw new Error('GitHub adapter requires repo=owner/name');
  const dryRun = config.dryRun ?? true;
  const request = createAdapter({ ...config, headers: { 'x-github-api-version': '2022-11-28', ...config.headers } });
  const issue = number => {
    const id = String(number);
    if (!/^\d+$/.test(id)) throw new Error('GitHub issue ID must be a number in the configured repository');
    return `/repos/${config.repo}/issues/${encodeURIComponent(id)}`;
  };
  const gql = (query, variables) => request({ method: 'POST', path: '/graphql', body: { query, variables } });
  const [owner, name] = config.repo.split('/');
  return {
    linkedItemsForChange: async change => {
      if (!change?.number) throw new Error('GitHub association lookup requires a pull request number');
      const result = await gql('query LinkedIssues($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) { pullRequest(number: $number) { closingIssuesReferences(first: 100) { nodes { number title url repository { nameWithOwner } } } } } }', { owner: change.owner ?? owner, name: change.repositoryName ?? name, number: Number(change.number) });
      const errors = result.data?.errors;
      if (errors?.length) throw new Error(`GitHub linked issue lookup failed: ${errors.map(error => error.message).join('; ')}`);
      return (result.data?.data?.repository?.pullRequest?.closingIssuesReferences?.nodes ?? []).map(item => {
        const pathMatch = new URL(item.url).pathname.match(/^\/([^/]+)\/([^/]+)\/issues\/(\d+)\/?$/);
        const repository = item.repository?.nameWithOwner ?? (pathMatch ? `${pathMatch[1]}/${pathMatch[2]}` : '');
        const number = String(item.number ?? pathMatch?.[3] ?? '');
        if (!repository || !/^\d+$/.test(number)) throw new Error('GitHub linked issue omitted its repository or issue number');
        const crossRepo = repository.toLowerCase() !== config.repo.toLowerCase();
        return { id: crossRepo ? `${repository}#${number}` : number, number, repository, title: item.title, url: item.url, ...(crossRepo ? { crossRepo: true } : {}) };
      });
    },
    read: number => request({ method: 'GET', path: `${issue(number)}?per_page=100` }),
    comment: async (number, body, marker) => {
      const path = `${issue(number)}/comments?per_page=100`;
      if (!dryRun) {
        const existing = await request({ method: 'GET', path });
        if ((existing.data ?? []).some(comment => (comment.body ?? '').includes(marker))) return { status: 200, duplicate: true, marker };
      }
      return request({ method: 'POST', path: `${issue(number)}/comments`, body: { body: `${body}\n\n${marker}` } });
    },
    // GitHub issues do not provide binary attachment upload. Store the artifact in CI and attach its URL.
    attach: (number, url, title = 'QA evidence') => request({ method: 'POST', path: `${issue(number)}/comments`, body: { body: `[${title}](${url})` } }),
    transition: (number, state) => request({ method: 'PATCH', path: issue(number), body: { state } }),
    linkPr: (number, url) => request({ method: 'POST', path: `${issue(number)}/comments`, body: { body: `Pull request: ${url}` } }),
    moveProjectItem: (projectId, itemId, fieldId, optionId) => gql('mutation Move($project: ID!, $item: ID!, $field: ID!, $option: String!) { updateProjectV2ItemFieldValue(input: { projectId: $project, itemId: $item, fieldId: $field, value: { singleSelectOptionId: $option } }) { projectV2Item { id } } }', { project: projectId, item: itemId, field: fieldId, option: optionId }),
    verifyEvent: async ({ rawBody, signature, secret }) => {
      const { createHmac, timingSafeEqual } = await import('node:crypto');
      const expected = `sha256=${createHmac('sha256', secret).update(rawBody).digest('hex')}`;
      return Boolean(signature && Buffer.byteLength(signature) === Buffer.byteLength(expected) && timingSafeEqual(Buffer.from(signature), Buffer.from(expected)));
    }
  };
}
