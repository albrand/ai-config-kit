# <Repo name>

<One paragraph: what the product does, for whom, and what must never break.>

## Done

A change is done when `python3 ~/.agents/skills/verify/scripts/verify.py run . --strict` is green
for its commit. Report each stage's result. A `missing` stage means NOT VERIFIED: write it if you
can, then run it.

## Run it

- Setup: `<install command>`
- App: `<start command>` on `<http://localhost:PORT>`
- Test data: `<seed command>`; personas and their entry points are in `journeys/personas.ts`
- Services for integration tests: `<docker compose ... up -d --wait>`

## Rules for this repo

- <Architecture boundary, for example: the API is the only code that talks to the database.>
- <Data rule, for example: patient fields are encrypted at rest; never log them.>
- <Release rule, for example: migrations ship one PR before the code that needs them.>

## Where things are

- `<src/...>`: <what lives here>
- `<journeys/>`: user journeys; they hit the real backend
- `<evals/>`: eval set for the LLM features, if any
