const adminRoutes = [
  {
    label: 'Dashboard',
    slug: 'alt-context-dashboard',
  },
  {
    label: 'Workbench',
    slug: 'alt-context-workbench',
  },
  {
    label: 'Roster',
    slug: 'alt-context-roster',
  },
  {
    label: 'Settings',
    slug: 'alt-context-settings',
  },
  {
    label: 'Description History',
    slug: 'alt-context-description-history',
  },
] as const;

export type AcxAdminRoute = (typeof adminRoutes)[number];
export type AcxAdminRouteSlug = AcxAdminRoute['slug'];

export const acxAdminRoutes = adminRoutes;

/** Retired slug: PHP still redirects to Settings. Not a top-level admin destination. */
export const acxRedirectOnlyAdminSlugs = ['alt-context-retention'] as const;

export const getAcxAdminRouteUrl = (baseUrl: string, slug: AcxAdminRouteSlug): string => {
  const adminRoot = new URL(baseUrl);

  return new URL(`admin.php?page=${slug}`, adminRoot).toString();
};

export const getAcxAdminRouteUrlWithParams = (
  baseUrl: string,
  slug: AcxAdminRouteSlug,
  params: Record<string, string> = {},
): string => {
  const url = new URL(getAcxAdminRouteUrl(baseUrl, slug));

  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }

  return url.toString();
};

/**
 * E21-10: compose a WP admin page URL with a contract hash href in one navigation.
 * Shape: `admin.php?page=<slug>#<hashHref>` (hash may start with `#/…` or `/…`).
 * When a hash is pre-set, `ensureHashInitialized` leaves it alone (no WP-param forward).
 */
export const getAcxAdminHashUrl = (
  baseUrl: string,
  slug: AcxAdminRouteSlug,
  hashHref: string,
): string => {
  const url = new URL(getAcxAdminRouteUrl(baseUrl, slug));
  const normalized = hashHref.startsWith('#') ? hashHref.slice(1) : hashHref;
  url.hash = normalized.startsWith('/') ? normalized : `/${normalized}`;
  return url.toString();
};
