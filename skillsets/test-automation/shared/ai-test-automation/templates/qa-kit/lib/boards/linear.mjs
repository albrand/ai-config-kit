import { createAdapter } from './adapter.mjs';

/** Linear GraphQL API. Workspace and team workflow state IDs are configured externally. */
export function linear(config) {
  const dryRun = config.dryRun ?? true;
  const request = createAdapter({ ...config, baseUrl: config.baseUrl ?? 'https://api.linear.app' });
  const gql = (query, variables) => request({ method: 'POST', path: '/graphql', body: { query, variables } });
  const eventVerifier = async ({ rawBody, signature, secret }) => {
    const { createHmac, timingSafeEqual } = await import('node:crypto');
    const expected = createHmac('sha256', secret).update(rawBody).digest('hex');
    return Boolean(signature && Buffer.byteLength(signature) === Buffer.byteLength(expected) && timingSafeEqual(Buffer.from(signature), Buffer.from(expected)));
  };
  return {
    read: identifier => gql('query WorkItem($id: String!) { issue(id: $id) { id identifier title description url updatedAt state { id name } team { id key } } }', { id: identifier }),
    comment: async (id, body, marker) => {
      if (!dryRun) {
        const existing = await gql('query Comments($id: String!) { issue(id: $id) { comments { nodes { body } } } }', { id });
        if ((existing.data?.data?.issue?.comments?.nodes ?? []).some(comment => comment.body.includes(marker))) return { status: 200, duplicate: true, marker };
      }
      return gql('mutation Comment($id: String!, $body: String!) { commentCreate(input: { issueId: $id, body: $body }) { success comment { id body } } }', { id, body: `${body}\n\n${marker}` });
    },
    attach: (id, url) => gql('mutation Attach($id: String!, $url: String!) { attachmentLinkURL(input: { issueId: $id, url: $url, title: "QA evidence" }) { success attachment { id url } } }', { id, url }),
    transition: (id, stateId, revision) => gql('mutation Transition($id: String!, $state: String!) { issueUpdate(id: $id, input: { stateId: $state }) { success issue { id state { id name } updatedAt } } }', { id, state: stateId, expectedUpdatedAt: revision }),
    linkPr: (id, url, title = 'Pull request') => gql('mutation Link($id: String!, $url: String!, $title: String!) { attachmentLinkURL(input: { issueId: $id, url: $url, title: $title }) { success attachment { id url } } }', { id, url, title }),
    verifyEvent: eventVerifier
  };
}
