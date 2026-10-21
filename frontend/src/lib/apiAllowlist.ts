/** Convert API allowlist paths to and from the multiline editor format. */
export function formatAllowedPaths(paths: string[]): string {
  return paths.join("\n");
}

/** Parse LF and CRLF input, trimming whitespace and ignoring blank lines. */
export function parseAllowedPaths(value: string): string[] {
  return value.split(/\r?\n/).map((path) => path.trim()).filter(Boolean);
}
