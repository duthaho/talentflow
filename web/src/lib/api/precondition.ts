export function ifMatch(version: number): string {
  return `"${version}"`;
}

export function isStaleVersion(status: number): boolean {
  return status === 409 || status === 412;
}
