import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createGuidedScenario } from '../../../guidedPrototype/state';

// The live panel is optional enrichment sitting inside the lesson's own tree.
// It calls assertNever on an unreachable status, and a hook of its own can
// throw on a shape the service was never supposed to send. Unwrapped, either
// unmounts the entire review step -- the learner loses the description, the
// edit box and Apply, over a feature they did not ask for.
vi.mock('../GuidedLiveDescriptionPanel', () => ({
  GuidedLiveDescriptionPanel: (): never => {
    throw new Error('unreachable guided live status');
  },
}));

afterEach(() => {
  vi.restoreAllMocks();
});

describe('a failing live panel does not take the lesson with it', () => {
  it('keeps the description, the editor and Apply on screen', async () => {
    // React logs the caught error; the boundary is the behaviour under test.
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { GuidedDescriptionReview } = await import('../GuidedDescriptionReview');

    render(
      <GuidedDescriptionReview
        scenario={createGuidedScenario()}
        liveMediaId={4211}
        resetVersion={0}
        onSaveEdit={() => undefined}
        onReject={() => undefined}
        onApply={() => undefined}
        onUndo={() => undefined}
      />,
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Apply it yourself' })).toBeInTheDocument();
  });
});
