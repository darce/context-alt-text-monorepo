import { describe, expect, it, vi } from 'vitest';

import { parseRosterRoute } from '../rosterRoute';
import { readReviewFromParams } from '../../workbench/ClusterPanelContext';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

describe('cluster deep-link boundary', () => {
  it.each(['..%2F..%2Fusers', '%2e%2e', 'a%2Fb', 'a%3Fx%3D1', '%252e%252e', '%20x%20', ''])(
    'treats unsafe cluster=%s as absent',
    (value) => {
      const params = new URLSearchParams(`cluster=${value}&panel=review`);
      expect(parseRosterRoute(params).selectedClusterId).toBeNull();
      expect(readReviewFromParams(params)).toEqual({ mode: 'none', clusterId: null });
    },
  );

  it('preserves a valid cluster deep link', () => {
    const params = new URLSearchParams('cluster=cluster-1&panel=review');
    expect(parseRosterRoute(params).selectedClusterId).toBe('cluster-1');
    expect(readReviewFromParams(params)).toEqual({ mode: 'review', clusterId: 'cluster-1' });
  });
});
