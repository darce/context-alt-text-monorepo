import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { guidedCopy } from '../publicGuideCopy';
import { RecordedWalkthrough } from '../RecordedWalkthrough';

const choose = (position: 'left' | 'right', option: 'include' | 'omit'): void => {
  const fieldset = screen.getByTestId(`name-choice-tribeca-${position}`);
  const name =
    option === 'include'
      ? guidedCopy('names.include', { name: position === 'left' ? 'Justin Trudeau' : 'Katy Perry' })
      : guidedCopy('names.omit');
  fireEvent.click(within(fieldset).getByRole('radio', { name }));
};

describe('RecordedWalkthrough behavior', () => {
  it('keeps public Review drafts disabled until both choices are decided and labels the reason', () => {
    render(<RecordedWalkthrough scope="public" />);

    const reviewDrafts = screen.getByTestId('guided-review-draft');
    expect(reviewDrafts).toBeDisabled();
    expect(reviewDrafts).toHaveAttribute('aria-describedby', 'guided-choices-help');
    const choicesHelp = screen.getByTestId('guided-choices-help');
    expect(choicesHelp).toHaveAttribute('id', 'guided-choices-help');
    expect(choicesHelp).toHaveTextContent(guidedCopy('choices.help.public'));
    expect(screen.getByRole('heading', { level: 2, name: guidedCopy('step.names.public') })).toBeInTheDocument();

    choose('left', 'include');
    expect(reviewDrafts).toBeDisabled();

    choose('right', 'omit');
    expect(reviewDrafts).toBeEnabled();
    expect(reviewDrafts).not.toHaveAttribute('aria-describedby');
  });

  it('flushes a pending Coachella edit before advancing can replace the draft', () => {
    render(<RecordedWalkthrough scope="admin" />);

    choose('left', 'include');
    choose('right', 'include');
    const edited = 'A Coachella edit that must survive advancing.';
    const editor = within(screen.getByTestId('guided-description-review-coachella')).getByRole('textbox', {
      name: guidedCopy('draft.label'),
    });
    fireEvent.change(editor, { target: { value: edited } });

    fireEvent.click(screen.getByRole('button', { name: guidedCopy('names.next') }));
    choose('left', 'omit');
    const replacementDialog = screen.getByRole('dialog', { name: guidedCopy('names.change_title') });
    fireEvent.click(within(replacementDialog).getByRole('button', { name: guidedCopy('names.change_confirm') }));

    expect(screen.getByTestId('guided-description-review-coachella')).toHaveTextContent(edited);
  });
});
