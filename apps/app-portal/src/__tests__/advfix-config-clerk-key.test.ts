import { describe, expect, it } from 'vitest';
import { parsePortalConfig } from '../config';

describe('Clerk publishable key build-mode validation', () => {
  const env = {
    VITE_CLERK_PUBLISHABLE_KEY: 'pk_test_Y2xlcmsuZXhhbXBsZS5kZXYk',
    VITE_CLERK_FAPI: 'https://clerk.altcontext.com',
    VITE_PORTAL_ENABLED: 'true',
  };

  it('rejects development publishable keys in production while allowing development mode', () => {
    expect(parsePortalConfig(env, false).publishableKey).toBe(env.VITE_CLERK_PUBLISHABLE_KEY);
    expect(parsePortalConfig(env, true).publishableKey).toBeNull();
  });
});
