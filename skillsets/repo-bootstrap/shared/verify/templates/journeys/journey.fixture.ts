// Journeys walk the running app the way a person does, against the real backend.
// This fixture enforces that: a journey fails when it answers the app's own requests itself,
// when the app's backend returns a server error, when an API call returns 4xx, or when the
// page throws. Blocking or faking third-party origins (payments, analytics) is allowed.
import { test as base, expect, type Page, type Request, type Route } from '@playwright/test';

type Options = {
  /** Own-origin URLs whose 4xx/5xx are expected in this journey (for example a deliberate 404 page). */
  allowedErrors: RegExp[];
};

const API_PATH = /\/api\/|\/trpc\/|\/graphql\b/;

export const test = base.extend<Options & { realBackend: void }>({
  allowedErrors: [[], { option: true }],

  realBackend: [
    async ({ page, baseURL, allowedErrors }, use) => {
      if (!baseURL) throw new Error('journeys need BASE_URL (or use.baseURL) so they know which origin is the app');
      const own = new URL(baseURL).origin;
      const isOwn = (url: string) => {
        try {
          return new URL(url).origin === own;
        } catch {
          return false;
        }
      };
      const allowed = (url: string) => allowedErrors.some((re) => re.test(url));
      const problems: string[] = [];

      guardRoutes(page, isOwn);

      page.on('response', (r) => {
        const url = r.url();
        if (!isOwn(url) || allowed(url)) return;
        const status = r.status();
        if (status >= 500 || (status >= 400 && API_PATH.test(new URL(url).pathname))) {
          problems.push(`${status} ${r.request().method()} ${url}`);
        }
      });
      page.on('requestfailed', (r: Request) => {
        const why = r.failure()?.errorText ?? '';
        // ERR_ABORTED is the browser cancelling a request when the user navigates on; not a backend fault.
        if (isOwn(r.url()) && !allowed(r.url()) && !/ERR_ABORTED|NS_BINDING_ABORTED|cancelled/i.test(why)) {
          problems.push(`failed ${r.method()} ${r.url()}: ${why}`);
        }
      });
      page.on('pageerror', (e) => problems.push(`uncaught in page: ${e.message}`));

      await use();

      expect(problems, "the app's own backend or page failed during the journey").toEqual([]);
    },
    { auto: true },
  ],
});

/** Wrap page.route and context.route so a handler that fulfills an own-origin request throws. */
function guardRoutes(page: Page, isOwn: (url: string) => boolean) {
  const wrap = (handler: (route: Route, request: Request) => unknown) => (route: Route, request: Request) => {
    const guarded = new Proxy(route, {
      get(target, prop, receiver) {
        if (prop === 'fulfill' && isOwn(request.url())) {
          return () => {
            throw new Error(
              `journey answered ${request.url()} itself; journeys must reach the real backend. ` +
                'Move this to a component test, or seed the data the backend needs.',
            );
          };
        }
        const value = Reflect.get(target, prop, receiver);
        return typeof value === 'function' ? value.bind(target) : value;
      },
    });
    return handler(guarded, request);
  };
  const pageRoute = page.route.bind(page);
  page.route = ((url: Parameters<Page['route']>[0], handler: (route: Route, request: Request) => unknown, options?: Parameters<Page['route']>[2]) =>
    pageRoute(url, wrap(handler), options)) as Page['route'];
  const context = page.context();
  const contextRoute = context.route.bind(context);
  context.route = ((url: Parameters<typeof context.route>[0], handler: (route: Route, request: Request) => unknown, options?: Parameters<typeof context.route>[2]) =>
    contextRoute(url, wrap(handler), options)) as typeof context.route;
}

export { expect };
