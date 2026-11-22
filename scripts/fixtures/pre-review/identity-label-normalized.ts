export function sameIdentity(label: string, expected: string): boolean {
  return label.normalize("NFKC") === expected.normalize("NFKC");
}
