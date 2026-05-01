const IMAGE_REMOTE_PATTERNS = [
  "**.githubusercontent.com",
  "**.githubassets.com",
  "raw.githubusercontent.com",
  "images.unsplash.com",
  "cdn.jsdelivr.net",
  "**.openai.com",
  "**.openaiusercontent.com",
] as const;

function matchesRemotePattern(hostname: string, pattern: string) {
  if (pattern.startsWith("**.")) {
    const suffix = pattern.slice(3);
    return hostname === suffix || hostname.endsWith(`.${suffix}`);
  }
  return hostname === pattern;
}

export function hostMatchesImageAllowlist(src: string) {
  try {
    const url = new URL(src);
    if (url.protocol !== "https:") return false;
    return IMAGE_REMOTE_PATTERNS.some((pattern) =>
      matchesRemotePattern(url.hostname, pattern),
    );
  } catch {
    return false;
  }
}
