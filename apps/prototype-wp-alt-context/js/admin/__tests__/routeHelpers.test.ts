import { extractRouteFromHash, ensureHashInitialized } from '../utils/routeHelpers';

describe('routeHelpers', () => {
  const originalLocation = window.location;

  beforeEach(() => {
    // Mock window.location
    // @ts-expect-error - Mocking window.location for tests
    delete window.location;
    // @ts-expect-error - JSDOM window.location type mismatch in tests
    window.location = { ...originalLocation };
  });

  afterEach(() => {
    // @ts-expect-error - JSDOM window.location type mismatch in tests
    window.location = originalLocation;
    vi.restoreAllMocks();
  });

  describe('extractRouteFromHash', () => {
    it('handles #/workbench without query params', () => {
      window.location.hash = '#/workbench';
      expect(extractRouteFromHash()).toBe('/workbench');
    });

    it('handles #/retention without query params', () => {
      window.location.hash = '#/retention';
      expect(extractRouteFromHash()).toBe('/retention');
    });

    it('handles #/workbench?tab=confirm without stripping query params from the hash itself (just parses path)', () => {
      window.location.hash = '#/workbench?tab=confirm';
      expect(extractRouteFromHash()).toBe('/workbench');
      // The hash itself should remain unchanged
      expect(window.location.hash).toBe('#/workbench?tab=confirm');
    });

    it('returns null for unknown routes', () => {
      window.location.hash = '#/unknown';
      expect(extractRouteFromHash()).toBeNull();
    });

    it('returns null for empty hash', () => {
      window.location.hash = '';
      expect(extractRouteFromHash()).toBeNull();
    });
  });

  describe('ensureHashInitialized', () => {
    it('does nothing if hash already has a valid route', () => {
      window.location.hash = '#/workbench?tab=confirm';
      ensureHashInitialized('/workbench');
      expect(window.location.hash).toBe('#/workbench?tab=confirm');
    });

    it('does nothing if hash already targets retention', () => {
      window.location.hash = '#/retention';
      ensureHashInitialized('/retention');
      expect(window.location.hash).toBe('#/retention');
    });

    it('initializes hash with initialRoute if hash is empty', () => {
      window.location.hash = '';
      window.location.search = '?page=alt-context-workbench';
      ensureHashInitialized('/workbench');
      expect(window.location.hash).toBe('#/workbench');
    });

    it('preserves query parameters from window.location.search when initializing hash', () => {
      window.location.hash = '';
      window.location.search = '?page=alt-context-workbench&tab=confirm&perPage=50';
      ensureHashInitialized('/workbench');
      expect(window.location.hash).toBe('#/workbench?tab=confirm&perPage=50');
    });
  });
});
