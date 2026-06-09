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
] as const;

export type AcxAdminRoute = (typeof adminRoutes)[number];
export type AcxAdminRouteSlug = AcxAdminRoute['slug'];

export const acxAdminRoutes = adminRoutes;

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