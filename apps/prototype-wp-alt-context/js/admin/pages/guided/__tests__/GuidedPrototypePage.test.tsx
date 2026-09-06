import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { createGuidedScenario } from '../../../guidedPrototype/state';
import { GuidedPrototypePage } from '../GuidedPrototypePage';

const SEED_ALT_TEXT = 'Two people at a film festival.';
const INITIAL_SCENARIO = createGuidedScenario();
const JUSTIN_DRAFT =
  'Justin Trudeau, in a black tuxedo and white shirt, poses with a woman in a white draped gown at the Tribeca Festival. Her hand rests on his chest.';
const BOTH_NAMES_DRAFT =
  'Justin Trudeau and Katy Perry pose side by side at the Tribeca Festival. He wears a black tuxedo with a white shirt; she wears a white draped gown with her dark hair pinned up and rests a hand on his chest.';

const flowStages = () =>
  within(screen.getByRole('list', { name: 'How the faces reach the description' })).getAllByRole('listitem');

const faceCard = (faceName: 'left' | 'right') => screen.getByRole('article', { name: `Face on the ${faceName}` });

const identitySection = (): HTMLElement => {
  const section = document.getElementById('guided-section-identity');
  if (!section) {
    throw new Error('The guided identity section is missing.');
  }
  return section;
};

const reviewSection = (): HTMLElement => screen.getByRole('region', { name: 'Review the description' });

const confirmButton = (name: 'Justin Trudeau' | 'Katy Perry') =>
  within(identitySection()).getByRole('button', { name: `Yes, this is ${name}` });

const unnamedButton = (position: 'left' | 'right') =>
  within(identitySection()).getAllByRole('button', { name: 'Keep this person unnamed' })[position === 'left' ? 0 : 1];

describe('GuidedPrototypePage shell', () => {
  it('opens with plain-language framing and five steps that name both faces', () => {
    render(<GuidedPrototypePage />);

    expect(screen.getByRole('heading', { name: 'AltContext guided demo' })).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'How two faces become two names in the description' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'Follow one photo from start to finish. AltContext finds two faces, matches each one to a person you already named, and puts their names in the image description. You choose what gets saved.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('This demo uses one saved run. It does not run recognition live.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    expect(screen.getByRole('status')).toHaveTextContent('The steps are open. Start with the photo.');
    expect(document.activeElement).toHaveAttribute('data-guided-focus-target', 'true');

    const nav = screen.getByRole('navigation', { name: 'Guided review steps' });
    expect(nav).toHaveTextContent('Step by step');
    for (const label of [
      'Look at the photo',
      'Find the faces',
      'Confirm each match',
      'Check the description',
      'Apply it yourself',
    ]) {
      expect(within(nav).getByRole('button', { name: new RegExp(`^${label}`) })).toBeInTheDocument();
    }
    expect(screen.getByText('Example').nextElementSibling).toHaveTextContent(
      'Saved from a real run on 2026-09-06, not a live run',
    );
    expect(screen.getByText('Page').nextElementSibling).toHaveTextContent('Tribeca Festival 2026: red carpet photos');
    expect(screen.getByText('People on file').nextElementSibling).toHaveTextContent(
      'Katy Perry (5 saved photos) · Justin Trudeau (2 saved photos)',
    );
    expect(screen.getByText('Photo credit').nextElementSibling).toHaveTextContent('Colleen Sturtevant, CC BY-SA 4.0');
    expect(screen.getByText('Also checked').nextElementSibling).toHaveTextContent(
      'A Coachella press photo of the same two people matched both, even with a hand over her mouth. It is not bundled because of licensing.',
    );
    expect(screen.getByText('Nothing yet. Your next action will show up here.')).toBeInTheDocument();
    expect(
      screen.getByText('AltContext found two faces in this photo. The next step shows the matches.'),
    ).toBeInTheDocument();

    const stages = flowStages();
    expect(stages.map((item) => item.textContent)).toEqual([
      expect.stringContaining('Photo'),
      expect.stringContaining('2 faces found'),
      expect.stringContaining('Matched to Justin Trudeau and Katy Perry'),
      expect.stringContaining('You confirm each match'),
      expect.stringContaining('Names in the description'),
    ]);
    expect(stages[2]).toHaveTextContent('done');
    expect(stages[3]).toHaveTextContent('now');
    expect(stages[4]).toHaveTextContent('waiting');
    expect(stages.map((item) => item.getAttribute('data-state'))).toEqual(['done', 'done', 'done', 'now', 'waiting']);
  });

  it('moves focus to the face section from the steps and closes the steps back to the photo', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the demo' }));
    await user.click(screen.getByRole('button', { name: /^Find the faces/ }));
    expect(screen.getByRole('status')).toHaveTextContent('Now on: Find the faces.');
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-face');

    await user.click(screen.getByRole('button', { name: /^Confirm each match/ }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-identity');

    await user.click(screen.getByRole('button', { name: 'Close the steps' }));
    expect(screen.getByRole('status')).toHaveTextContent('Steps closed. You can keep practising.');
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-understand');
  });

  it('keeps practice changes on cancel and resets edits, errors, decisions, and focus on confirm', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the demo' }));
    await user.click(confirmButton('Justin Trudeau'));
    await user.click(confirmButton('Katy Perry'));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: 'Saved local practice edit.' } });
    await user.click(screen.getByRole('button', { name: 'Save my edit' }));
    fireEvent.change(editor, { target: { value: 'Pending local practice edit.' } });

    await user.click(screen.getByRole('button', { name: 'Reset practice' }));
    const dialog = screen.getByRole('dialog', { name: 'Reset this practice?' });
    expect(dialog).toHaveTextContent('This removes your practice changes. The real WordPress image is not touched.');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(editor).toHaveValue('Pending local practice edit.');

    await user.clear(editor);
    await user.type(editor, '   ');
    await user.click(screen.getByRole('button', { name: 'Save my edit' }));
    expect(screen.getByRole('alert')).toHaveTextContent('A description cannot be empty.');

    await user.click(screen.getByRole('button', { name: 'Reset practice' }));
    await user.click(
      within(screen.getByRole('dialog', { name: 'Reset this practice?' })).getByRole('button', {
        name: 'Reset practice',
      }),
    );
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(INITIAL_SCENARIO.drafts.none);
    expect(screen.getByRole('status')).toHaveTextContent('Practice reset. The original text is back.');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getAllByText('You have not decided yet.')).toHaveLength(2);
    expect(flowStages()[3]).toHaveTextContent('now');
    expect(flowStages()[4]).toHaveTextContent('waiting');
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-understand');
  });

  it('returns focus to the reset trigger after cancel and Escape', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    const resetButton = screen.getByRole('button', { name: 'Reset practice' });
    await user.click(resetButton);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(document.activeElement).toBe(resetButton);

    await user.click(resetButton);
    await user.keyboard('{Escape}');
    expect(document.activeElement).toBe(resetButton);
  });

  it('renders the press photo and describes a useful fallback when it fails', () => {
    render(<GuidedPrototypePage />);

    const image = screen.getByRole('img', { name: INITIAL_SCENARIO.drafts.none });
    expect(image.tagName).toBe('IMG');
    expect(image).toHaveAttribute('src', expect.stringContaining('guided-press-tribeca-2026'));
    fireEvent.error(image);
    const fallback = screen.getByRole('img', {
      name: new RegExp(`Sample photo unavailable\\. ${INITIAL_SCENARIO.drafts.none}`),
    });
    expect(fallback.textContent).toBe(`Sample photo unavailable.${INITIAL_SCENARIO.drafts.none}`);
  });

  it('spaces the case-study link and closes the sentence without a gap before the full stop', () => {
    render(<GuidedPrototypePage />);

    const boundary = screen.getByText(/This is a practice copy\./, { selector: 'p' });
    expect(boundary.textContent).toBe(
      'This is a practice copy. Changes stay in this tab and reset when you reload the page. Live recognition and ' +
        'guest access are still in progress. Read the AltContext case study.',
    );
  });
});

describe('GuidedPrototypePage journey', () => {
  it('moves focus into review after confirming the left face', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    fireEvent.click(confirmButton('Justin Trudeau'));

    expect(reviewSection().contains(document.activeElement)).toBe(true);
  });

  it('moves focus into review after keeping the left face unnamed', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    fireEvent.click(unnamedButton('left'));

    expect(reviewSection().contains(document.activeElement)).toBe(true);
  });

  it('carries both confirmed face matches into the draft, through apply, and back out with undo', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    expect(screen.getAllByText('You have not decided yet.')).toHaveLength(2);
    expect(within(faceCard('left')).getByText(/It matches a person you named before:/)).toHaveTextContent(
      'Justin Trudeau',
    );
    expect(within(faceCard('right')).getByText(/It matches a person you named before:/)).toHaveTextContent(
      'Katy Perry',
    );

    fireEvent.click(confirmButton('Justin Trudeau'));
    expect(screen.getByRole('status')).toHaveTextContent(
      'Match confirmed. Justin Trudeau is in the draft. Nothing is applied yet.',
    );
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(JUSTIN_DRAFT);

    fireEvent.click(confirmButton('Katy Perry'));
    expect(screen.getByRole('status')).toHaveTextContent(
      'Match confirmed. Katy Perry is in the draft. Nothing is applied yet.',
    );
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(BOTH_NAMES_DRAFT);
    expect(
      screen.getByText(
        'You confirmed both matches, so both names are in the draft. The visual details and page context stay the same.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('You confirmed the face match: Justin Trudeau.', { selector: 'li' })).toBeInTheDocument();
    expect(screen.getByText('You confirmed the face match: Katy Perry.', { selector: 'li' })).toBeInTheDocument();
    expect(screen.getByText('You confirmed: Justin Trudeau.')).toBeInTheDocument();
    expect(screen.getByText('You confirmed: Katy Perry.')).toBeInTheDocument();
    expect(flowStages()[3]).toHaveTextContent('done');
    expect(flowStages()[4]).toHaveTextContent('done');
    expect(flowStages().map((item) => item.getAttribute('data-state'))).toEqual([
      'done',
      'done',
      'done',
      'done',
      'done',
    ]);
    expect(screen.getByRole('navigation', { name: 'Guided review steps' })).toHaveTextContent('Check the description');

    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: 'Justin Trudeau and Katy Perry pose at the festival.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save my edit' }));
    expect(screen.getByText('Edited by you')).toBeInTheDocument();
    expect(screen.getByText('You saved an edit.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    expect(screen.getByText('You applied the draft to the practice copy.')).toBeInTheDocument();
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(
      'Justin Trudeau and Katy Perry pose at the festival.',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(screen.getByRole('status')).toHaveTextContent('Apply undone.');
    expect(screen.getByText('You undid the apply.')).toBeInTheDocument();
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');
    expect(screen.getByRole('navigation', { name: 'Guided review steps' })).toHaveTextContent('Apply it yourself');
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(SEED_ALT_TEXT);
    expect(screen.getByRole('button', { name: 'Undo' })).toBeDisabled();
  });

  it('keeps one face unnamed while putting only the other confirmed name in the draft', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    fireEvent.click(confirmButton('Justin Trudeau'));
    fireEvent.click(unnamedButton('right'));

    expect(screen.getByRole('status')).toHaveTextContent(
      'The person on the right stays unnamed. You can still check the description.',
    );
    expect(screen.getByText('You kept the person on the right unnamed.', { selector: 'li' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(JUSTIN_DRAFT);
    expect(screen.getByTestId('guided-candidate')).not.toHaveTextContent('Katy Perry');
    expect(
      screen.getByText(
        'You confirmed one match, so one name is in the draft. The other person is described, not named.',
      ),
    ).toBeInTheDocument();
    expect(flowStages()[3]).toHaveTextContent('done');
    expect(flowStages()[4]).toHaveTextContent('done');
    expect(flowStages().map((item) => item.getAttribute('data-state'))).toEqual([
      'done',
      'done',
      'done',
      'done',
      'done',
    ]);
  });

  it('marks the names stage skipped when both faces stay unnamed', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    fireEvent.click(unnamedButton('left'));
    fireEvent.click(unnamedButton('right'));

    expect(screen.getByRole('status')).toHaveTextContent(
      'The person on the right stays unnamed. You can still check the description.',
    );
    expect(screen.getByText('You kept the person on the left unnamed.', { selector: 'li' })).toBeInTheDocument();
    expect(screen.getByText('You kept the person on the right unnamed.', { selector: 'li' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(INITIAL_SCENARIO.drafts.none);
    expect(
      screen.getByText('You kept both people unnamed, so the draft only says what is visible.'),
    ).toBeInTheDocument();
    expect(flowStages()[3]).toHaveTextContent('done');
    expect(flowStages()[4]).toHaveTextContent('skipped');
    expect(flowStages().map((item) => item.getAttribute('data-state'))).toEqual([
      'done',
      'done',
      'done',
      'done',
      'skipped',
    ]);
  });

  it('blocks apply after rejection while preserving the current applied text', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    fireEvent.click(screen.getByRole('button', { name: 'Reject this draft' }));

    expect(screen.getByRole('status')).toHaveTextContent('Draft rejected. The saved text did not change.');
    expect(screen.getByText('Rejected. The saved text did not change')).toBeInTheDocument();
    expect(reviewSection().contains(document.activeElement)).toBe(true);
    expect(document.activeElement).not.toBe(document.body);
    expect(screen.getByRole('button', { name: 'Apply to practice copy' })).toBeDisabled();
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Two people at a film festival.');
  });

  it('keeps an empty edit visible and focused for correction', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save my edit' }));

    expect(screen.getByRole('alert')).toHaveTextContent('A description cannot be empty.');
    expect(editor).toHaveValue('   ');
    expect(document.activeElement).toBe(editor);
  });

  it('blocks applying stale textarea text until it is saved or discarded', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the demo' }));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    await user.clear(editor);
    await user.type(editor, 'A locally edited portrait description.');

    const applyButton = screen.getByRole('button', { name: 'Apply to practice copy' });
    expect(applyButton).toBeDisabled();
    expect(screen.getByText('Apply is off while your edit is unsaved. Save or discard it first.')).toBeInTheDocument();
    expect(
      screen
        .getAllByRole('button', { name: 'Keep this person unnamed' })
        .every((button) => button.hasAttribute('disabled')),
    ).toBe(true);

    await user.click(screen.getByRole('button', { name: 'Discard my edit' }));
    expect(editor).toHaveValue(INITIAL_SCENARIO.drafts.none);
    expect(applyButton).not.toBeDisabled();
    await user.click(applyButton);
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(INITIAL_SCENARIO.drafts.none);
  });

  it('disables undo before an application and leaves feedback unchanged when clicked', () => {
    render(<GuidedPrototypePage />);

    const feedback = screen.getByRole('status');
    const undoButton = screen.getByRole('button', { name: 'Undo' });
    expect(undoButton).toBeDisabled();
    fireEvent.click(undoButton);
    expect(feedback).toHaveTextContent('');
  });

  it('explains in plain words why either name cannot be used before its match is confirmed', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the demo' }));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: 'Katy Perry is pictured beside a man in a tuxedo.' } });
    await user.click(screen.getByRole('button', { name: 'Save my edit' }));

    expect(screen.getByRole('alert')).toHaveTextContent(
      'You can only use the name Katy Perry after you confirm that face match.',
    );
    expect(document.activeElement).toBe(editor);
    expect(screen.getByRole('status')).not.toHaveTextContent('You can only use the name');
  });

  it('keeps the latest undo available across two applied drafts and restores focus after each undo', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the demo' }));
    await user.click(confirmButton('Justin Trudeau'));
    await user.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(JUSTIN_DRAFT);

    await user.click(confirmButton('Katy Perry'));
    await user.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(BOTH_NAMES_DRAFT);

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(JUSTIN_DRAFT);
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(SEED_ALT_TEXT);
    expect(screen.getByRole('button', { name: 'Undo' })).toBeDisabled();
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');
  });

  it('locks the right answer while an edit is unsaved and refreshes the draft after saving it', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the demo' }));
    await user.click(confirmButton('Justin Trudeau'));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    await user.clear(editor);
    await user.type(editor, 'Justin Trudeau is pictured at the festival.');

    expect(confirmButton('Katy Perry')).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Save my edit' }));
    expect(confirmButton('Katy Perry')).toBeEnabled();

    await user.click(confirmButton('Katy Perry'));
    expect(editor).toHaveValue(BOTH_NAMES_DRAFT);
  });
});
