import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { guidedCopy } from '../../../guidedPrototype/copy';
import { createGuidedScenario } from '../../../guidedPrototype/state';
import { GuidedPrototypePage } from '../GuidedPrototypePage';

const SEED_ALT_TEXT = 'Two people at a film festival.';
const SCENARIO = createGuidedScenario();
const JUSTIN_DRAFT = SCENARIO.samples['justin-trudeau'];
const BOTH_NAMES_DRAFT = SCENARIO.samples.both;
const NONE_DRAFT = SCENARIO.samples.none;
const KATY_DRAFT = SCENARIO.samples['katy-perry'];

const choose = (position: 'left' | 'right', option: 'include' | 'omit'): void => {
  const fieldset = screen.getByTestId(`name-choice-${position}`);
  const name =
    option === 'include'
      ? guidedCopy('names.include', { name: position === 'left' ? 'Justin Trudeau' : 'Katy Perry' })
      : guidedCopy('names.omit');
  fireEvent.click(within(fieldset).getByRole('radio', { name }));
};

const stepButton = (step: 'context' | 'names' | 'draft' | 'apply') =>
  within(screen.getByTestId('guided-demo-stepper')).getByRole('button', {
    name: guidedCopy(`step.${step}`),
  });

describe('GuidedPrototypePage shell', () => {
  it('opens with catalog copy, four steps, and no pre-choice success story', () => {
    render(<GuidedPrototypePage />);

    expect(screen.getByTestId('guided-demo-root')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: guidedCopy('page.title') })).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('page.intro'))).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('page.scope'))).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('page.live_scope'))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: guidedCopy('page.start') })).toBeInTheDocument();
    const caseStudy = screen.getByRole('link', {
      name: new RegExp(`${guidedCopy('page.case_study')}.*opens in a new window`, 'i'),
    });
    expect(caseStudy).toHaveAttribute('href', 'https://darce.xyz/projects/altcontext/');
    expect(caseStudy).toHaveAttribute('target', '_blank');

    const stepper = screen.getByTestId('guided-demo-stepper');
    expect(stepper).toHaveTextContent(
      guidedCopy('guide.current', {
        stepNumber: 1,
        stepTitle: guidedCopy('step.context'),
      }),
    );
    for (const label of [
      guidedCopy('step.context'),
      guidedCopy('step.names'),
      guidedCopy('step.draft'),
      guidedCopy('step.apply'),
    ]) {
      expect(within(stepper).getByRole('button', { name: label })).toBeInTheDocument();
    }

    expect(screen.queryByText(/How two faces become two names/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Matched to Justin Trudeau/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Coachella/)).not.toBeInTheDocument();
    expect(screen.queryByText(/real GPU/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Match strength/)).not.toBeInTheDocument();
    expect(screen.getByText(guidedCopy('history.empty'))).toBeInTheDocument();
  });

  it('keeps the guided-prototype hash when moving between steps', async () => {
    const user = userEvent.setup();
    window.location.hash = '#/guided-prototype';
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: guidedCopy('page.start') }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-understand');
    expect(window.location.hash).toBe('#/guided-prototype');

    await user.click(stepButton('names'));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-identity');
    expect(window.location.hash).toBe('#/guided-prototype');

    await user.click(stepButton('draft'));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-review');
    expect(window.location.hash).not.toMatch(/guided-section-/);
  });

  it('resets choices and the demo copy after confirm, and restores focus on cancel', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    choose('left', 'include');
    choose('right', 'include');
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    fireEvent.change(editor, { target: { value: 'Pending local demo edit.' } });

    const resetButton = screen.getByRole('button', { name: guidedCopy('page.reset') });
    await user.click(resetButton);
    const dialog = screen.getByRole('dialog', { name: guidedCopy('reset.title') });
    expect(dialog).toHaveTextContent(guidedCopy('reset.body'));
    expect(dialog).not.toHaveTextContent(guidedCopy('reset.active_live_note'));
    await user.click(within(dialog).getByRole('button', { name: guidedCopy('reset.cancel') }));
    expect(editor).toHaveValue('Pending local demo edit.');
    expect(document.activeElement).toBe(resetButton);

    await user.click(resetButton);
    await user.click(
      within(screen.getByRole('dialog', { name: guidedCopy('reset.title') })).getByRole('button', {
        name: guidedCopy('reset.confirm'),
      }),
    );
    expect(screen.getByTestId('guided-page-feedback')).toHaveTextContent(guidedCopy('reset.status'));
    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', SEED_ALT_TEXT);
    expect(
      within(screen.getByTestId('name-choice-left')).getByRole('radio', { name: /Use Justin Trudeau/ }),
    ).not.toBeChecked();
    expect(
      within(screen.getByTestId('name-choice-right')).getByRole('radio', { name: /Use Katy Perry/ }),
    ).not.toBeChecked();
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-understand');
  });

  it('keeps the evidence image inspectable when the applied preview uses the weak alt', () => {
    render(<GuidedPrototypePage />);

    const evidence = screen.getByRole('img', { name: NONE_DRAFT ?? '' });
    expect(evidence).toHaveAttribute('src', expect.stringContaining('guided-press-tribeca-2026'));
    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', SEED_ALT_TEXT);
    expect(screen.getByTestId('demo-applied-image')).not.toBe(evidence);
    fireEvent.error(evidence);
    expect(screen.getByRole('img', { name: NONE_DRAFT ?? '' })).toBeInTheDocument();
  });
});

describe('GuidedPrototypePage journey', () => {
  it('leaves both radios unchecked until a visitor chooses, then loads the matching sample', () => {
    render(<GuidedPrototypePage />);

    const left = screen.getByTestId('name-choice-left');
    const right = screen.getByTestId('name-choice-right');
    expect(
      within(left)
        .getAllByRole('radio')
        .every((radio) => !(radio as HTMLInputElement).checked),
    ).toBe(true);
    expect(
      within(right)
        .getAllByRole('radio')
        .every((radio) => !(radio as HTMLInputElement).checked),
    ).toBe(true);
    expect(screen.getByRole('button', { name: guidedCopy('names.next') })).toBeDisabled();
    expect(screen.getByText(guidedCopy('names.next_blocked'))).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: guidedCopy('draft.label') })).not.toBeInTheDocument();

    choose('left', 'include');
    expect(screen.queryByRole('textbox', { name: guidedCopy('draft.label') })).not.toBeInTheDocument();

    choose('right', 'omit');
    expect(screen.getByRole('textbox', { name: guidedCopy('draft.label') })).toHaveValue(JUSTIN_DRAFT);
    expect(screen.getByTestId('guided-candidate')).not.toHaveTextContent('Katy Perry');
    expect(screen.getByRole('button', { name: guidedCopy('names.next') })).toBeEnabled();
  });

  it('treats omit/omit and include/include as ordinary completed choices', () => {
    render(<GuidedPrototypePage />);

    choose('left', 'omit');
    choose('right', 'omit');
    expect(screen.getByRole('textbox', { name: guidedCopy('draft.label') })).toHaveValue(NONE_DRAFT);

    choose('left', 'include');
    choose('right', 'include');
    expect(screen.getByRole('textbox', { name: guidedCopy('draft.label') })).toHaveValue(BOTH_NAMES_DRAFT);
    expect(screen.queryByText(/failed step/i)).not.toBeInTheDocument();
  });

  it('previews then applies the visible edited text exactly, and undoes twice', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    choose('left', 'include');
    choose('right', 'include');
    const edited = 'Justin Trudeau and Katy Perry pose at the festival.';
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    fireEvent.change(editor, { target: { value: edited } });

    const applyButton = screen.getByTestId('demo-apply');
    expect(applyButton).toBeDisabled();
    await user.click(screen.getByRole('button', { name: guidedCopy('draft.next') }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');
    await user.click(applyButton);

    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', edited);
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(edited);
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.applied'));
    expect(screen.getByTestId('guided-page-feedback')).toHaveTextContent(guidedCopy('apply.success'));
    expect(screen.getByTestId('guided-page-feedback-icon')).toHaveAttribute('aria-hidden', 'true');

    await user.click(applyButton);
    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', edited);

    fireEvent.change(editor, { target: { value: BOTH_NAMES_DRAFT ?? '' } });
    await user.click(screen.getByRole('button', { name: guidedCopy('draft.next') }));
    await user.click(applyButton);
    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', BOTH_NAMES_DRAFT);

    await user.click(screen.getByTestId('demo-undo'));
    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', edited);
    await user.click(screen.getByTestId('demo-undo'));
    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', SEED_ALT_TEXT);
    expect(screen.getByTestId('demo-undo')).toBeDisabled();
    expect(document.activeElement).toBe(screen.getByTestId('demo-undo'));
  });

  it('asks before replacing a manual edit and keeps the previous text in draft history', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    choose('left', 'include');
    choose('right', 'omit');
    const editor = screen.getByRole('textbox', { name: guidedCopy('draft.label') });
    fireEvent.change(editor, { target: { value: 'A locally edited portrait description.' } });
    await user.click(screen.getByRole('button', { name: guidedCopy('draft.next') }));

    choose('right', 'include');
    const dialog = screen.getByRole('dialog', { name: guidedCopy('names.change_title') });
    expect(dialog).toHaveTextContent(guidedCopy('names.change_body'));
    await user.click(within(dialog).getByRole('button', { name: guidedCopy('names.change_cancel') }));
    expect(editor).toHaveValue('A locally edited portrait description.');
    expect(
      within(screen.getByTestId('name-choice-right')).getByRole('radio', { name: guidedCopy('names.omit') }),
    ).toBeChecked();

    choose('right', 'include');
    await user.click(
      within(screen.getByRole('dialog', { name: guidedCopy('names.change_title') })).getByRole('button', {
        name: guidedCopy('names.change_confirm'),
      }),
    );
    expect(screen.getByRole('textbox', { name: guidedCopy('draft.label') })).toHaveValue(BOTH_NAMES_DRAFT);
    expect(screen.getByText('A locally edited portrait description.')).toBeInTheDocument();
    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', SEED_ALT_TEXT);
  });

  it('rejects a stale preview even after the draft text changes', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    choose('left', 'include');
    choose('right', 'include');
    await user.click(screen.getByRole('button', { name: guidedCopy('draft.next') }));
    expect(screen.getByTestId('demo-apply')).toBeEnabled();

    fireEvent.change(screen.getByRole('textbox', { name: guidedCopy('draft.label') }), {
      target: { value: 'Stale after preview.' },
    });
    expect(screen.getByTestId('demo-apply')).toBeDisabled();
    expect(screen.getByText(guidedCopy('apply.stale'))).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('demo-apply'));
    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', SEED_ALT_TEXT);
  });

  it('keeps current alt text as a finished outcome without applying', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: guidedCopy('draft.keep') }));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.kept'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.kept_body'));
    expect(screen.getByTestId('demo-applied-image')).toHaveAttribute('alt', SEED_ALT_TEXT);
    await user.click(screen.getByRole('button', { name: guidedCopy('outcome.return') }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-review');
  });

  it('mounts the live panel last, closed, and independent of name choices', () => {
    render(<GuidedPrototypePage />);

    const root = screen.getByTestId('guided-demo-root');
    const live = screen.getByTestId('guided-live');
    expect(live).not.toHaveAttribute('open');
    expect(
      root.lastElementChild?.querySelector('[data-testid="guided-live"]') ??
        root.querySelector('[data-testid="guided-live"]'),
    ).toBe(live);

    const sectionIds = [
      'guided-section-understand',
      'guided-section-face',
      'guided-section-identity',
      'guided-section-review',
      'guided-section-apply',
    ];
    for (const id of sectionIds) {
      expect(document.getElementById(id)).not.toBeNull();
    }

    const liveIndex = Array.from(root.querySelectorAll('section, details, [data-testid="guided-live"]')).indexOf(live);
    const applyIndex = Array.from(root.querySelectorAll('section, details, [data-testid="guided-live"]')).indexOf(
      document.getElementById('guided-section-apply') as HTMLElement,
    );
    expect(liveIndex).toBeGreaterThan(applyIndex);
    expect(screen.getByText(guidedCopy('notes.title'))).toBeInTheDocument();
  });

  it('shows honest reference coverage inside each face comparison', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    const summaries = screen.getAllByText(/Compare the (left|right) face and reference photos/);
    await user.click(summaries[0]);
    await user.click(summaries[1]);
    expect(screen.getByText(guidedCopy('names.coverage_all', { total: 2 }))).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('names.coverage_partial', { shown: 3, total: 5 }))).toBeInTheDocument();
    expect(screen.queryByText(/Show all 5/)).not.toBeInTheDocument();
    expect(screen.getAllByText('© European Union, 2025, EU reuse licence, resized').length).toBeGreaterThan(0);
  });

  it('loads the katy-only sample when the right face is included and the left is omitted', () => {
    render(<GuidedPrototypePage />);

    choose('left', 'omit');
    choose('right', 'include');
    expect(screen.getByRole('textbox', { name: guidedCopy('draft.label') })).toHaveValue(KATY_DRAFT);
  });
});
