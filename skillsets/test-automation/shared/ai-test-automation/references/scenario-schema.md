# Scenario schema

A versioned scenario set contains `schemaVersion`, `workItem {id, revision}`, `criteria[]`, `scenarios[]`, and `approval`. Scenario fields: `id` (`QAS-<item>-<nn>`), `criterionIds[]`, `kind` (`automated|manual|awaiting`), `surface` (`api|browser`), `mandatory` (boolean), `title`, `steps`, `expected`, `owner`. Manual requires procedure and owner; awaiting requires reason, owner and revisit date. IDs remain stable when wording changes; never recycle deleted IDs.
