import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { GuidedPrototypePage } from '../GuidedPrototypePage';

const NAMED_DRAFT = 'Keanu Reeves wears a grey jacket against a plain background.';
const GENERIC_DRAFT = 'Portrait of a person in a grey jacket.';

const flowStages = () =>
  within(screen.getByRole('list', { name: 'How the face reaches the description' })).getAllByRole('listitem');

describe('GuidedPrototypePage shell', () => {
  it('opens with plain-language framing and five steps that name the face stage', () => {
    render(<GuidedPrototypePage />);

    expect(screen.getByRole('heading', { name: 'AltContext guided demo' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'How a face becomes a name in the description' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    expect(screen.getByRole('status')).toHaveTextContent('The steps are open. Start with the photo.');
    expect(document.activeElement).toHaveAttribute('data-guided-focus-target', 'true');

    const nav = screen.getByRole('navigation', { name: 'Guided review steps' });
    expect(nav).toHaveTextContent('Step by step');
    for (const label of ['Look at the photo', 'Find the face', 'Confirm the match', 'Check the description', 'Apply it yourself']) {
      expect(within(nav).getByRole('button', { name: new RegExp(`^${label}`) })).toBeInTheDocument();
    }
    expect(screen.getByText('Example').nextElementSibling).toHaveTextContent('Saved example, not a live run');
    expect(screen.getByText('Person on file').nextElementSibling).toHaveTextContent('Keanu Reeves');
    expect(screen.getByText('Nothing yet. Your next action will show up here.')).toBeInTheDocument();
    expect(screen.getByText('AltContext found one face in this photo. The next step shows the match.')).toBeInTheDocument();

    const stages = flowStages();
    expect(stages.map((item) => item.textContent)).toEqual([
      expect.stringContaining('Photo'),
      expect.stringContaining('Face found'),
      expect.stringContaining('Matched to Keanu Reeves'),
      expect.stringContaining('You confirm'),
      expect.stringContaining('Name in the description'),
    ]);
    expect(stages[2]).toHaveTextContent('done');
    expect(stages[3]).toHaveTextContent('now');
    expect(stages[4]).toHaveTextContent('waiting');
  });

  it('moves focus to the face section from the steps and closes the steps back to the photo', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the demo' }));
    await user.click(screen.getByRole('button', { name: /^Find the face/ }));
    expect(screen.getByRole('status')).toHaveTextContent('Now on: Find the face.');
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-face');

    await user.click(screen.getByRole('button', { name: /^Confirm the match/ }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-identity');

    await user.click(screen.getByRole('button', { name: 'Close the steps' }));
    expect(screen.getByRole('status')).toHaveTextContent('Steps closed. You can keep practising.');
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-understand');
  });

  it('keeps practice changes on cancel and resets edits, errors, and focus on confirm', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the demo' }));
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
      within(screen.getByRole('dialog', { name: 'Reset this practice?' })).getByRole('button', { name: 'Reset practice' }),
    );
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(GENERIC_DRAFT);
    expect(screen.getByRole('status')).toHaveTextContent('Practice reset. The original text is back.');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
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

  it('renders the sample photo and describes a useful fallback when it fails', () => {
    render(<GuidedPrototypePage />);

    const image = screen.getByRole('img', {
      name: 'Portrait photograph of a man with shoulder-length dark hair and a beard, wearing a grey jacket over a dark shirt, against a light background.',
    });
    expect(image.tagName).toBe('IMG');
    fireEvent.error(image);
    expect(
      screen.getByRole('img', {
        name: /Sample photo unavailable\. Portrait photograph of a man with shoulder-length dark hair/,
      }),
    ).toHaveTextContent('Sample photo unavailable');
  });
});

describe('GuidedPrototypePage journey', () => {
  it('carries a confirmed face match into the draft, through apply, and back out with undo', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    expect(screen.getByText('You have not decided yet.')).toBeInTheDocument();
    expect(screen.getByText(/It matches a person you named before:/)).toHaveTextContent('Keanu Reeves');

    fireEvent.click(screen.getByRole('button', { name: 'Yes, this is Keanu Reeves' }));
    expect(screen.getByRole('status')).toHaveTextContent('Match confirmed. The name is in the draft. Nothing is applied yet.');
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(NAMED_DRAFT);
    expect(
      screen.getByText(
        'You confirmed the match, so the name is in the draft. The visual details and page context stay the same.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('You confirmed: Keanu Reeves.')).toBeInTheDocument();
    expect(screen.getByText('You confirmed the face match: Keanu Reeves.')).toBeInTheDocument();
    expect(flowStages()[3]).toHaveTextContent('done');
    expect(flowStages()[4]).toHaveTextContent('done');
    expect(screen.getByRole('navigation', { name: 'Guided review steps' })).toHaveTextContent('Check the description');

    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: 'Keanu Reeves wears a grey jacket.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save my edit' }));
    expect(screen.getByText('Edited by you')).toBeInTheDocument();
    expect(screen.getByText('You saved an edit.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    expect(screen.getByText('You applied the draft to the practice copy.')).toBeInTheDocument();
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Keanu Reeves wears a grey jacket.');

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(screen.getByRole('status')).toHaveTextContent('Apply undone.');
    expect(screen.getByText('You undid the apply.')).toBeInTheDocument();
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');
    expect(screen.getByRole('navigation', { name: 'Guided review steps' })).toHaveTextContent('Apply it yourself');
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(GENERIC_DRAFT);
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
  });

  it('keeps the unnamed path useful without using the matched name', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    fireEvent.click(screen.getByRole('button', { name: 'Keep the person unnamed' }));

    expect(screen.getByRole('status')).toHaveTextContent('The person stays unnamed. You can still check the description.');
    expect(screen.getByText('You kept the person unnamed.', { selector: 'li' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(GENERIC_DRAFT);
    expect(screen.getByTestId('guided-candidate')).not.toHaveTextContent('Keanu Reeves');
    expect(
      screen.getByText('You kept the person unnamed, so the draft only says what is visible.'),
    ).toBeInTheDocument();
    expect(flowStages()[4]).toHaveTextContent('skipped');
  });

  it('blocks apply after rejection while preserving the current applied text', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the demo' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes, this is Keanu Reeves' }));
    fireEvent.click(screen.getByRole('button', { name: 'Reject this draft' }));

    expect(screen.getByRole('status')).toHaveTextContent('Draft rejected. The saved text did not change.');
    expect(screen.getByText('Rejected. The saved text did not change')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply to practice copy' })).toBeDisabled();
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(GENERIC_DRAFT);
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
    await user.click(screen.getByRole('button', { name: 'Yes, this is Keanu Reeves' }));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    await user.clear(editor);
    await user.type(editor, 'A locally edited portrait description.');

    const applyButton = screen.getByRole('button', { name: 'Apply to practice copy' });
    expect(applyButton).toBeDisabled();
    expect(screen.getByText('Apply is off while your edit is unsaved. Save or discard it first.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep the person unnamed' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Discard my edit' }));
    expect(editor).toHaveValue(NAMED_DRAFT);
    expect(applyButton).not.toBeDisabled();
    await user.click(applyButton);
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(NAMED_DRAFT);
  });

  it('explains in plain words why the name cannot be used before the match is confirmed', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the demo' }));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: 'Keanu Reeves is pictured in a grey jacket.' } });
    await user.click(screen.getByRole('button', { name: 'Save my edit' }));

    expect(screen.getByRole('alert')).toHaveTextContent('You can only use the name after you confirm the face match.');
    expect(document.activeElement).toBe(editor);
    expect(screen.getByRole('status')).not.toHaveTextContent('You can only use the name');
  });

  it('keeps the latest undo available across two applied drafts and restores focus after each undo', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the demo' }));
    await user.click(screen.getByRole('button', { name: 'Yes, this is Keanu Reeves' }));
    await user.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(NAMED_DRAFT);

    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    await user.clear(editor);
    await user.type(editor, 'Keanu Reeves wears a grey jacket.');
    await user.click(screen.getByRole('button', { name: 'Save my edit' }));
    await user.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Keanu Reeves wears a grey jacket.');

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(NAMED_DRAFT);
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(GENERIC_DRAFT);
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');
  });
});
