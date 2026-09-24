import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { GUIDED_OUTCOME } from '../../../guidedPrototype/state';
import { GuidedOutcome } from '../GuidedOutcome';
import { GuidedResetDialog } from '../GuidedResetDialog';

describe('GuidedOutcome per-image summary', () => {
  it('shows the public outcome only after both photos are done', () => {
    const onReturn = vi.fn();
    render(
      <GuidedOutcome
        scope="public"
        outcomeReady
        outcomes={{
          tribeca: GUIDED_OUTCOME.APPLIED,
          coachella: GUIDED_OUTCOME.KEPT,
        }}
        onReturn={onReturn}
      />,
    );

    const summaries = screen.getByTestId('guided-outcome-summaries');
    expect(summaries.children).toHaveLength(2);
    expect(summaries).toHaveTextContent('Tribeca Festival, New York, June 2026: uses the new description.');
    expect(summaries).toHaveTextContent('Coachella festival photo, 2026: kept the current description.');
    expect(screen.getByRole('heading', { name: 'You checked both photos' })).toBeInTheDocument();
    expect(screen.getByText('Nothing was saved or published. Your changes clear when you reload.')).toBeInTheDocument();
    expect(screen.getByText('In real use, you would review each new photo the same way.')).toBeInTheDocument();
    expect(
      screen.getByText(
        'AltContext suggested these names and descriptions on 9-10 September 2026. Nothing on this page compares faces.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Return to the draft' })).not.toBeInTheDocument();
    expect(onReturn).not.toHaveBeenCalled();
  });

  it('does not render before outcomeReady or when either photo is unfinished', () => {
    const { container, rerender } = render(
      <GuidedOutcome
        scope="public"
        outcomeReady={false}
        outcomes={{
          tribeca: GUIDED_OUTCOME.APPLIED,
          coachella: GUIDED_OUTCOME.KEPT,
        }}
        onReturn={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();

    rerender(
      <GuidedOutcome
        scope="public"
        outcomeReady
        outcomes={{
          tribeca: GUIDED_OUTCOME.APPLIED,
          coachella: GUIDED_OUTCOME.NOT_FINISHED,
        }}
        onReturn={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('preserves the admin summary and return action', () => {
    const onReturn = vi.fn();
    render(
      <GuidedOutcome
        outcomes={{
          tribeca: GUIDED_OUTCOME.APPLIED,
          coachella: GUIDED_OUTCOME.KEPT,
        }}
        onReturn={onReturn}
      />,
    );

    expect(screen.getByTestId('guided-outcome-summaries')).toHaveTextContent('Tribeca');
    expect(screen.getByTestId('guided-outcome-summaries')).toHaveTextContent('Coachella');
    expect(screen.getByRole('heading', { name: 'Your demo copy is updated' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Return to the draft' }));
    expect(onReturn).toHaveBeenCalledTimes(1);
  });
});

describe('GuidedResetDialog public copy', () => {
  it('shows the public reset labels and initially focuses Keep my work', async () => {
    render(<GuidedResetDialog scope="public" liveWaiting={false} onConfirm={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Reset demo' }));
    const dialog = screen.getByRole('dialog', { name: 'Start over?' });
    expect(dialog).toHaveTextContent('This clears your name choices and edits, and puts back the original descriptions.');

    const keepButton = within(dialog).getByRole('button', { name: 'Keep my work' });
    expect(within(dialog).getByRole('button', { name: 'Start over' })).toBeInTheDocument();
    await waitFor(() => expect(document.activeElement).toBe(keepButton));
  });
});
