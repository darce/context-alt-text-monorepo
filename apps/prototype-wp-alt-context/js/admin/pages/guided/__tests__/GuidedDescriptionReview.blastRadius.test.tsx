import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
    const user = userEvent.setup();

    render(<GuidedPrototypePage />);

    expect(screen.getByRole('alert')).toHaveTextContent(guidedCopy('live.failed'));
    expect(screen.getByRole('heading', { name: guidedCopy('step.apply') })).toBeInTheDocument();
    expect(screen.getByTestId('demo-apply')).toBeInTheDocument();
    expect(screen.getByTestId('demo-applied-image')).toBeInTheDocument();

    fireEvent.click(
      within(screen.getByTestId('name-choice-left')).getByRole('radio', {
        name: guidedCopy('names.include', { name: 'Justin Trudeau' }),
      }),
    );
    fireEvent.click(
      within(screen.getByTestId('name-choice-right')).getByRole('radio', {
        name: guidedCopy('names.include', { name: 'Katy Perry' }),
      }),
    );

    const edited = 'Draft still works after the live panel crashed.';
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    fireEvent.change(editor, { target: { value: edited } });
    await user.click(screen.getByRole('button', { name: guidedCopy('draft.next') }));
    await user.click(screen.getByTestId('demo-apply'));

    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', edited);
    expect(screen.getByRole('alert')).toHaveTextContent(guidedCopy('live.failed'));
  });
});
