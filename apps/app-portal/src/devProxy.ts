const DEFAULT_PORTAL_PROXY_TARGET = 'http://127.0.0.1:8000';

function invalidTarget(): Error {
  return new Error('Invalid PORTAL_API_PROXY_TARGET');
}

export function resolvePortalProxyTarget(raw: string | undefined): string {
  if (raw === undefined || raw.trim() === '') {
    return DEFAULT_PORTAL_PROXY_TARGET;
  }

  const value = raw.trim();
  const parts = /^([a-z][a-z\d+.-]*):\/\/([^/?#]*)(.*)$/i.exec(value);
  if (!parts || /[\\\u0000-\u0020\u007f]/.test(value)) {
    throw invalidTarget();
  }

  const scheme = parts[1];
  const authority = parts[2];
  const suffix = parts[3];
  if (
    !scheme ||
    !authority ||
    authority.includes('@') ||
    !/^(?:\[[^\]]+\]|[^:]+)(?::\d+)?$/.test(authority) ||
    (suffix !== '' && suffix !== '/')
  ) {
    throw invalidTarget();
  }

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw invalidTarget();
  }

  if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw invalidTarget();
  }

  if (scheme.toLowerCase() === 'https' && url.protocol === 'https:') {
    return url.origin;
  }

  if (scheme.toLowerCase() === 'http' && url.protocol === 'http:') {
    const portSeparator = authority.indexOf(':');
    const hostnameEnd = authority.startsWith('[')
      ? authority.indexOf(']') + 1
      : portSeparator === -1
        ? authority.length
        : portSeparator;
    const hostname = authority.slice(0, hostnameEnd).toLowerCase();
    if (hostname === '127.0.0.1' || hostname === 'localhost' || hostname === '[::1]') {
      return url.origin;
    }
  }

  throw invalidTarget();
}
