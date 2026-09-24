import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { guidedCopy } from '../../../guidedPrototype/publicGuideCopy';
import {
  GUIDED_IMAGE_KEYS,
  GUIDED_NAME_CHOICE,
  chooseGuidedName,
  createGuidedDemoState,
  createGuidedScenario,
} from '../../../guidedPrototype/state';
import { GuidedChoiceChangeDialog } from '../GuidedChoiceChangeDialog';
import { GuidedFacesPanel } from '../GuidedFacesPanel';

const scenario = createGuidedScenario();

const answerPhoto = (imageKey: (typeof GUIDED_IMAGE_KEYS)[number]) => {
  let state = createGuidedDemoState();
  state = chooseGuidedName(state, scenario, 'left', GUIDED_NAME_CHOICE.USE, imageKey);
  return chooseGuidedName(state, scenario, 'right', GUIDED_NAME_CHOICE.LEAVE_UNNAMED, imageKey);
};

const renderPanel = (state = createGuidedDemoState()): void => {
  render(<GuidedFacesPanel scenario={scenario} state={state} onChoose={vi.fn()} onContinue={vi.fn()} />);
};

const identitySection = (): HTMLElement => {
  const section = document.getElementById('guided-section-identity');
  if (!(section instanceof HTMLElement)) {
    throw new Error('Expected the guided identity section to be rendered.');
  }
  return section;
};

describe('GuidedFacesPanel', () => {
  it('keeps the continuation action meaningful without embedding the choice dialog', () => {
    renderPanel();

    const section = identitySection();
    expect(section).not.toBeEmptyDOMElement();
    expect(section.childElementCount).toBeGreaterThan(0);
    expect(within(section).getByRole('button', { name: guidedCopy('names.next') })).toBeDisabled();
    expect(section.querySelector('.acx-guided-face__cards')).toBeNull();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByText(/threshold|\d+%/i)).not.toBeInTheDocument();
  });

  it('requires answers for both photos before enabling continuation', () => {
    const tribecaAnswered = answerPhoto('tribeca');
    const view = render(
      <GuidedFacesPanel scenario={scenario} state={tribecaAnswered} onChoose={vi.fn()} onContinue={vi.fn()} />,
    );
    expect(within(identitySection()).getByRole('button', { name: guidedCopy('names.next') })).toBeDisabled();

    let bothAnswered = answerPhoto('tribeca');
    bothAnswered = chooseGuidedName(bothAnswered, scenario, 'left', GUIDED_NAME_CHOICE.USE, 'coachella');
    bothAnswered = chooseGuidedName(bothAnswered, scenario, 'right', GUIDED_NAME_CHOICE.LEAVE_UNNAMED, 'coachella');
    view.rerender(
      <GuidedFacesPanel scenario={scenario} state={bothAnswered} onChoose={vi.fn()} onContinue={vi.fn()} />,
    );
    expect(within(identitySection()).getByRole('button', { name: guidedCopy('names.next') })).toBeEnabled();
  });
});

describe('GuidedChoiceChangeDialog', () => {
  it('shows the public replacement copy and puts focus on Keep my edits', async () => {
    const user = userEvent.setup();
    const onKeepEdits = vi.fn();
    const onChangeName = vi.fn();
    render(<GuidedChoiceChangeDialog open onKeepEdits={onKeepEdits} onChangeName={onChangeName} />);

    const dialog = await screen.findByRole('dialog', { name: guidedCopy('name_change.title.public') });
    expect(within(dialog).getByText(guidedCopy('name_change.body.public'))).toBeInTheDocument();
    const keepButton = within(dialog).getByRole('button', { name: guidedCopy('name_change.keep.public') });
    expect(keepButton).toHaveFocus();
    await user.click(keepButton);
    expect(onKeepEdits).toHaveBeenCalledOnce();

    await user.click(within(dialog).getByRole('button', { name: guidedCopy('name_change.confirm.public') }));
    expect(onChangeName).toHaveBeenCalledOnce();
  });

  it('keeps the edit when Escape dismisses the dialog', async () => {
    const user = userEvent.setup();
    const onKeepEdits = vi.fn();
    render(<GuidedChoiceChangeDialog open onKeepEdits={onKeepEdits} onChangeName={vi.fn()} />);
    await screen.findByRole('dialog');

    await user.keyboard('{Escape}');
    expect(onKeepEdits).toHaveBeenCalledOnce();
  });
});
