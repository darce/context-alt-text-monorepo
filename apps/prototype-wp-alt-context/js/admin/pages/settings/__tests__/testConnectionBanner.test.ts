import { describe, expect, it, vi } from 'vitest';

import { TestConnectionOutcome, type TestConnectionResponse } from '../../../api/settingsApi';
import { renderBanner, TONE_CLASS, TONE_ICON } from '../testConnectionBanner';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
}));

const probe = (overrides: Partial<TestConnectionResponse> = {}): TestConnectionResponse => ({
  outcome: TestConnectionOutcome.STARTING,
  probe_mode: 'service_auth',
  ...overrides,
});

describe('renderBanner starting outcome', () => {
  it('renders an info banner with ETA copy when warmup_eta_seconds is present', () => {
    const banner = renderBanner(probe({ warmup_eta_seconds: 90 }));

    expect(banner.tone).toBe('info');
    expect(banner.role).toBe('status');
    expect(banner.icon).toBe(TONE_ICON.info);
    expect(TONE_CLASS[banner.tone]).toBe('notice-info');
    expect(banner.primary).toContain(TONE_ICON.info);
    expect(banner.primary).toContain('Description service is starting — ready in ~90 s');
    expect(banner.remediation).toContain('warming up');
  });

  it('uses retry_after_seconds when warmup_eta_seconds is absent', () => {
    const banner = renderBanner(probe({ retry_after_seconds: 45 }));

    expect(banner.tone).toBe('info');
    expect(banner.primary).toContain('Description service is starting — ready in ~45 s');
  });

  it('renders starting copy without an invented countdown when no ETA is present', () => {
    const banner = renderBanner(probe());

    expect(banner.tone).toBe('info');
    expect(banner.role).toBe('status');
    expect(banner.icon).toBe(TONE_ICON.info);
    expect(banner.primary).toContain(TONE_ICON.info);
    expect(banner.primary).toContain('Description service is starting.');
    expect(banner.primary).not.toMatch(/\d/);
    expect(banner.remediation).toBe('Warming up, this can take a few minutes');
    expect(banner.remediation).not.toMatch(/\d/);
  });

  it('keeps connected copy unchanged', () => {
    const banner = renderBanner({ outcome: TestConnectionOutcome.CONNECTED, probe_mode: 'service_auth' });

    expect(banner.tone).toBe('success');
    expect(banner.primary).toBe('Connection successful.');
    expect(banner.primary).not.toContain(TONE_ICON.success);
  });
});
