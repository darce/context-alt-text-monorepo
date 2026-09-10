import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { GUIDED_OUTCOME } from '../../../guidedPrototype/state';
import { GuidedOutcome } from '../GuidedOutcome';

describe('GuidedOutcome per-image summary', () => {
  it('summarises both image outcomes and preserves the return action', () => {
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
    expect(screen.getAllByRole('heading', { name: 'Your demo copy is updated' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Return to the draft' }));
    expect(onReturn).toHaveBeenCalledTimes(1);
  });

  it('does not render until at least one image has a finished outcome', () => {
    const { container } = render(
      <GuidedOutcome
        outcomes={{
          tribeca: GUIDED_OUTCOME.NOT_FINISHED,
          coachella: GUIDED_OUTCOME.NOT_FINISHED,
        }}
        onReturn={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
