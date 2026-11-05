const normalize = item => String(typeof item === 'object' ? (item.id ?? item.identifier ?? item.workItemId ?? '') : item);

export function resolveBoardAssociations(hints, associatedItems) {
  const linked = new Map();
  for (const item of associatedItems ?? []) {
    const id = normalize(item);
    if (id) linked.set(id, typeof item === 'object' ? { ...item, id } : { id });
  }
  const named = [...new Set((hints ?? []).map(normalize).filter(Boolean))];
  // Forge/board associations are authoritative even when their identifiers are
  // not mentioned in text. Hints are only used to explain rejected mentions.
  const namedNotLinked = named.filter(id => !linked.has(id));
  return { linked: [...linked.values()], namedNotLinked };
}

export function extractWorkItemHints(values, pattern = '\\b[A-Z][A-Z0-9]+-\\d+\\b') {
  const expression = new RegExp(pattern, 'g');
  return [...new Set(values.flatMap(value => String(value ?? '').match(expression) ?? []))];
}

export function buildAssociatedScenarioScope(linkedItems, currentScenarios, baseScenarios) {
  const ids = new Set(linkedItems.map(item => String(item.id)));
  const belongsTo = (scenario, owner) => String(scenario.workItemId ?? '') === String(owner) || scenario.id.startsWith(`QAS-${owner}-`);
  const current = currentScenarios.filter(scenario => [...ids].some(id => belongsTo(scenario, id)));
  const base = baseScenarios.filter(scenario => [...ids].some(id => belongsTo(scenario, id)));
  const items = linkedItems.map(item => ({
    ...item,
    relation: 'linked',
    scenarioIds: [...new Set([...current, ...base].filter(scenario => belongsTo(scenario, item.id)).map(scenario => scenario.id))],
    linkedItems: [...ids].filter(id => id !== String(item.id))
  }));
  return {
    items,
    scenarioIds: [...new Set([...current, ...base].map(scenario => scenario.id))],
    regressionIds: [...new Set(base.map(scenario => scenario.id))]
  };
}
