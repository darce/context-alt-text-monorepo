import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { guidedCopy } from '../copy';
import { guidedCopy as publicGuidedCopy } from '../publicGuideCopy';
import { createGuidedScenario } from '../state';
import { RecordedWalkthrough } from '../RecordedWalkthrough';

const choose = (
  position: 'left' | 'right',
  option: 'include' | 'omit',
  imageKey: 'tribeca' | 'coachella' = 'tribeca',
): void => {
  const fieldset = screen.getByTestId(`name-choice-${imageKey}-${position}`);
  const name =
    option === 'include'
      ? publicGuidedCopy('names.use.public', { name: position === 'left' ? 'Justin Trudeau' : 'Katy Perry' })
      : publicGuidedCopy('names.omit.public');
  const group = within(fieldset);
  fireEvent.click(group.getByRole('radio', { name }));
};

describe('RecordedWalkthrough behavior', () => {
  it('shows each public draft only after that photo has both name choices', () => {
    render(<RecordedWalkthrough scope="public" />);

    expect(screen.queryByTestId('guided-demo-stepper')).not.toBeInTheDocument();
    for (const imageKey of ['tribeca', 'coachella'] as const) {
      const review = screen.getByTestId(`guided-description-review-${imageKey}`);
      expect(review).toHaveTextContent(publicGuidedCopy('choices.help.public'));
      expect(within(review).queryByRole('textbox')).not.toBeInTheDocument();
      expect(screen.queryByTestId(`demo-apply-${imageKey}`)).not.toBeInTheDocument();
    }

    choose('left', 'include', 'tribeca');
    expect(within(screen.getByTestId('guided-description-review-tribeca')).queryByRole('textbox')).not.toBeInTheDocument();

    choose('right', 'omit', 'tribeca');
    expect(within(screen.getByTestId('guided-description-review-tribeca')).getByRole('textbox')).toBeInTheDocument();
    expect(within(screen.getByTestId('guided-description-review-coachella')).queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByTestId('demo-apply-coachella')).not.toBeInTheDocument();

    choose('left', 'include', 'coachella');
    expect(within(screen.getByTestId('guided-description-review-coachella')).queryByRole('textbox')).not.toBeInTheDocument();
    choose('right', 'omit', 'coachella');
    expect(within(screen.getByTestId('guided-description-review-coachella')).getByRole('textbox')).toBeInTheDocument();
    expect(screen.getByTestId('demo-apply-coachella')).toBeEnabled();
  });

  it('flushes a pending Coachella edit before replacing its name choice', () => {
    render(<RecordedWalkthrough scope="admin" />);

    choose('left', 'include');
    choose('right', 'include');
    choose('left', 'include', 'coachella');
    choose('right', 'include', 'coachella');
    const edited = 'A Coachella edit that must survive advancing.';
    const editor = within(screen.getByTestId('guided-description-review-coachella')).getByRole('textbox', {
      name: guidedCopy('draft.label'),
    });
    fireEvent.change(editor, { target: { value: edited } });

    choose('left', 'omit', 'coachella');
    const replacementDialog = screen.getByRole('dialog', { name: guidedCopy('names.change_title') });
    fireEvent.click(within(replacementDialog).getByRole('button', { name: guidedCopy('names.change_confirm') }));

    const review = screen.getByTestId('guided-description-review-coachella');
    expect(within(review).getByRole('textbox', { name: guidedCopy('draft.label') })).toHaveValue(
      createGuidedScenario().samples.coachella['katy-perry'],
    );
    expect(review).toHaveTextContent(guidedCopy('draft.history'));
    expect(review).toHaveTextContent(edited);
  });
});
