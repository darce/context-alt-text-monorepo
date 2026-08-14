import React from 'react';
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { useRosterFaceCursor } from '../useRosterFaceCursor';

afterEach(() => {
  cleanup();
});

const Probe = ({
  visibleIds,
  requestedId,
  seen,
}: {
  visibleIds: readonly string[];
  requestedId: string | null;
  seen: (string | null)[];
}): null => {
  const { selectedId } = useRosterFaceCursor(visibleIds, requestedId);
  seen.push(selectedId);
  return null;
};

describe('useRosterFaceCursor', () => {
  it('returns a visible face on the first paint after prune or unmatched deep-link', () => {
    const seen: (string | null)[] = [];
    const { rerender } = render(
      <Probe
        visibleIds={['cluster-a:identity-1', 'cluster-a:identity-2']}
        requestedId="cluster-a:identity-2"
        seen={seen}
      />,
    );

    expect(seen[0]).toBe('cluster-a:identity-2');
    seen.length = 0;

    rerender(<Probe visibleIds={['cluster-a:identity-1']} requestedId="cluster-a:identity-2" seen={seen} />);

    expect(seen[0]).toBe('cluster-a:identity-1');
    expect(seen[0]).not.toBe('cluster-a:identity-2');

    seen.length = 0;
    rerender(<Probe visibleIds={['cluster-a:identity-1']} requestedId="missing-face" seen={seen} />);

    expect(seen[0]).toBe('cluster-a:identity-1');
  });
});
