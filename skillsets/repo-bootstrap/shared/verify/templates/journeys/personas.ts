// One entry per kind of user. Each persona is a seeded test account that exists in every
// environment the journeys run against (local, preview, staging). Its credentials come from the
// environment (the runner's env file or a local .env.journeys that is gitignored), never from the repo.
export type Persona = {
  name: string;
  /** Where this person starts. */
  entry: string;
  emailEnv: string;
  passwordEnv: string;
};

export const PERSONAS: Persona[] = [
  { name: 'visitor', entry: '/', emailEnv: '', passwordEnv: '' },
  { name: 'member', entry: '/login', emailEnv: 'JOURNEY_MEMBER_EMAIL', passwordEnv: 'JOURNEY_MEMBER_PASSWORD' },
  { name: 'admin', entry: '/login', emailEnv: 'JOURNEY_ADMIN_EMAIL', passwordEnv: 'JOURNEY_ADMIN_PASSWORD' },
];

export const storageStatePath = (persona: string) => `.auth/${persona}.json`;
