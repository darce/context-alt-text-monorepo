import { describe, expect, it, vi } from 'vitest';

import { useRemoteActionGate } from '../useRemoteActionGate';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

describe('useRemoteActionGate', () => {
  it('returns disabled props with reason when offline', () => {
    expect(useRemoteActionGate(true)).toEqual({
      disabled: true,
      'aria-disabled': true,
      title: 'Unavailable while the recognition service is offline',
    });
  });

  it('returns enabled props without reason when online', () => {
    expect(useRemoteActionGate(false)).toEqual({
      disabled: false,
      'aria-disabled': undefined,
      title: undefined,
    });
  });
});
