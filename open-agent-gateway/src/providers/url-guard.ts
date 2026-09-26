/**
 * Allow only safe https base URLs for upstream providers (SSRF guard).
 */

const BLOCKED_HOSTS = new Set([
  "localhost",
  "metadata.google.internal",
  "metadata",
]);

function isPrivateIpv4(hostname: string): boolean {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(hostname);
  if (!m) return false;
  const parts = m.slice(1).map((x) => Number(x));
  if (parts.some((n) => n > 255)) return true;
  const [a, b] = parts;
  if (a === 10) return true;
  if (a === 127) return true;
  if (a === 0) return true;
  if (a === 169 && b === 254) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 192 && b === 168) return true;
  return false;
}

export function assertSafeBaseUrl(
  raw: string,
  opts: { allowPrivate?: boolean } = {},
): URL {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`Invalid provider baseUrl`);
  }
  if (url.protocol !== "https:") {
    throw new Error(`Provider baseUrl must use https`);
  }
  if (url.username || url.password) {
    throw new Error(`Provider baseUrl must not include credentials`);
  }
  const host = url.hostname.toLowerCase();
  if (BLOCKED_HOSTS.has(host) || host.endsWith(".localhost") || host.endsWith(".local")) {
    if (!opts.allowPrivate) {
      throw new Error(`Provider baseUrl host is not allowed`);
    }
  }
  if (!opts.allowPrivate && isPrivateIpv4(host)) {
    throw new Error(`Provider baseUrl private IP is not allowed`);
  }
  // Strip trailing slash for consistent join
  if (url.pathname.endsWith("/") && url.pathname !== "/") {
    url.pathname = url.pathname.replace(/\/+$/, "");
  }
  return url;
}

/** Join base (…/v1) with path (/chat/completions). */
export function joinUrl(base: string, path: string): string {
  const b = base.replace(/\/+$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${b}${p}`;
}
