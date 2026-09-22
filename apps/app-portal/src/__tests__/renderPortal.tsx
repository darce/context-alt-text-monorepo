import { render, type RenderResult } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { App, type AppProps } from '../App';
import type { PortalRuntimeConfig } from '../config';

export const TEST_CONFIG: PortalRuntimeConfig = {
  publishableKey: 'pk_test_portal_offline',
  fapiOrigin: 'https://clerk.altcontext.com',
  portalEnabled: true,
};

export function renderPortal(
  options: {
    path?: string;
    config?: PortalRuntimeConfig;
    fetchImpl?: typeof fetch;
    clerkLoadTimeoutMs?: number;
    portalMeTimeoutMs?: number;
  } = {},
): RenderResult {
  const props: AppProps = {
    config: options.config ?? TEST_CONFIG,
    fetchImpl: options.fetchImpl,
    clerkLoadTimeoutMs: options.clerkLoadTimeoutMs ?? 8_000,
    portalMeTimeoutMs: options.portalMeTimeoutMs ?? 8_000,
  };
  return render(
    <MemoryRouter initialEntries={[options.path ?? '/']}>
      <App {...props} />
    </MemoryRouter>,
  );
}
