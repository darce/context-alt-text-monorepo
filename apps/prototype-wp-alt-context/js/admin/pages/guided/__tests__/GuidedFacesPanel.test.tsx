import { render, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { guidedCopy } from '../../../guidedPrototype/publicGuideCopy';
import {
  GUIDED_NAME_CHOICE,
  chooseGuidedName,
  createGuidedDemoState,
  createGuidedScenario,
} from '../../../guidedPrototype/state';
import { GuidedFacesPanel } from '../GuidedFacesPanel';

const scenario = createGuidedScenario();

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
  it('keeps the admin identity landmark meaningful without duplicating photo face controls', () => {
    renderPanel();

    const section = identitySection();
    expect(section).not.toBeEmptyDOMElement();
    expect(section.childElementCount).toBeGreaterThan(0);
    expect(within(section).getByRole('button', { name: guidedCopy('names.next') })).toBeDisabled();
    expect(section.querySelector('.acx-guided-face__cards')).toBeNull();
  });

  it('keeps the continuation action in the identity landmark after both choices are made', () => {
    let state = createGuidedDemoState();
    state = chooseGuidedName(state, scenario, 'left', GUIDED_NAME_CHOICE.INCLUDE);
    state = chooseGuidedName(state, scenario, 'right', GUIDED_NAME_CHOICE.OMIT);
    renderPanel(state);

    expect(within(identitySection()).getByRole('button', { name: guidedCopy('names.next') })).toBeEnabled();
  });
});
