import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { guidedCopy } from '../../../guidedPrototype/copy';

vi.mock('../GuidedLiveDescriptionPanel', () => ({
  GuidedLiveDescriptionPanel: (): never => {
    throw new Error('unreachable guided live status');
  },
}));

afterEach(() => {
  vi.restoreAllMocks();
});

describe('a failing live panel does not take the lesson with it', () => {
  it('keeps the draft, apply controls and demo copy on screen', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { GuidedPrototypePage } = await import('../GuidedPrototypePage');

    render(<GuidedPrototypePage />);

    expect(screen.getByRole('alert')).toHaveTextContent(guidedCopy('live.failed'));
    expect(screen.getByRole('heading', { name: guidedCopy('step.apply') })).toBeInTheDocument();
    expect(screen.getByTestId('demo-apply')).toBeInTheDocument();
    expect(screen.getByTestId('demo-applied-image')).toBeInTheDocument();
  });
});
