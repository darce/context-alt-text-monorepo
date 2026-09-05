import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { GuidedPrototypePage } from '../GuidedPrototypePage';

describe('GuidedPrototypePage', () => {
  it('supports the identity-informed practice journey through explicit apply and undo', () => {
    render(<GuidedPrototypePage />);

    expect(screen.getByRole('heading', { name: 'AltContext — guided WordPress prototype' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start the guided walkthrough' }));
    expect(screen.getByRole('navigation', { name: 'Guided review steps' })).toBeInTheDocument();
    expect(document.activeElement).toHaveAttribute('data-guided-focus-target', 'true');
    fireEvent.click(screen.getByRole('button', { name: /Confirm identity/ }));
    expect(screen.getByRole('status')).toHaveTextContent('Guide moved to: Confirm identity.');
    expect(screen.getByText('Scenario origin').nextElementSibling).toHaveTextContent('Illustrative example');

    fireEvent.click(screen.getByRole('button', { name: 'Confirm Keanu Reeves' }));
    expect(screen.getByText('Keanu Reeves wears a grey jacket against a plain background.')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Confirmed identity changes the name in the candidate; the visual facts and page context stay visible.',
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Identity confirmed from the sample record.').length).toBeGreaterThan(0);

    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: 'Keanu Reeves wears a grey jacket.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save description edit' }));
    expect(screen.getByText('Edited by you')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    expect(screen.getAllByText('Applied to the practice copy.').length).toBeGreaterThan(0);
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Keanu Reeves wears a grey jacket.');

    fireEvent.click(screen.getByRole('button', { name: 'Undo practice apply' }));
    expect(screen.getAllByText('Application undone.').length).toBeGreaterThan(0);
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');
    expect(screen.getByRole('navigation', { name: 'Guided review steps' })).toHaveTextContent('Apply deliberately');
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Portrait of a person in a grey jacket.');
    expect(screen.queryByRole('button', { name: 'Undo practice apply' })).not.toBeInTheDocument();
  });

  it('keeps the unidentified path useful without using the sample name', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the guided walkthrough' }));
    fireEvent.click(screen.getByRole('button', { name: 'Keep the person unidentified' }));

    expect(screen.getAllByText('Identity left unidentified.').length).toBeGreaterThan(0);
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(
      'Portrait of a person in a grey jacket.',
    );
    expect(screen.getByTestId('guided-candidate')).not.toHaveTextContent('Keanu Reeves');
  });

  it('blocks apply after rejection while preserving the current applied text', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the guided walkthrough' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Keanu Reeves' }));
    fireEvent.click(screen.getByRole('button', { name: 'Reject draft' }));

    expect(screen.getByRole('button', { name: 'Apply to practice copy' })).toBeDisabled();
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Portrait of a person in a grey jacket.');
  });

  it('keeps an empty edit visible and focused for correction', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the guided walkthrough' }));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save description edit' }));

    expect(screen.getByRole('alert')).toHaveTextContent('A description cannot be empty.');
    expect(editor).toHaveValue('   ');
    expect(document.activeElement).toBe(editor);
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Portrait of a person in a grey jacket.');
  });

  it('blocks applying stale textarea text until it is saved or discarded', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the guided walkthrough' }));
    await user.click(screen.getByRole('button', { name: 'Confirm Keanu Reeves' }));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    await user.clear(editor);
    await user.type(editor, 'A locally edited portrait description.');

    const applyButton = screen.getByRole('button', { name: 'Apply to practice copy' });
    expect(applyButton).toBeDisabled();
    expect(
      screen.getByText('Apply is unavailable while your draft has unsaved edits. Save or discard the edit first.'),
    ).toBeInTheDocument();
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Portrait of a person in a grey jacket.');

    await user.click(screen.getByRole('button', { name: 'Discard unsaved edit' }));
    expect(editor).toHaveValue('Keanu Reeves wears a grey jacket against a plain background.');
    expect(applyButton).not.toBeDisabled();
    await user.click(applyButton);
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(
      'Keanu Reeves wears a grey jacket against a plain background.',
    );
  });

  it('places an invalid identity edit error beside the editor without duplicating the live status', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the guided walkthrough' }));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: 'Keanu Reeves is pictured in a grey jacket.' } });
    await user.click(screen.getByRole('button', { name: 'Save description edit' }));

    expect(screen.getByRole('alert')).toHaveTextContent('Cannot use the sample name until the identity is confirmed');
    expect(document.activeElement).toBe(editor);
    expect(screen.getByRole('status')).not.toHaveTextContent('Cannot use the sample name');
  });

  it('uses labelled guide targets and restores focus when the guide or undo control disappears', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the guided walkthrough' }));
    await user.click(screen.getByRole('button', { name: /^Confirm identity/ }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-identity');

    await user.click(screen.getByRole('button', { name: 'End guide' }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-understand');

    await user.click(screen.getByRole('button', { name: 'Confirm Keanu Reeves' }));
    await user.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    await user.click(screen.getByRole('button', { name: 'Undo practice apply' }));
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');
  });

  it('keeps the latest undo available across two applied drafts and restores focus after each undo', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the guided walkthrough' }));
    await user.click(screen.getByRole('button', { name: 'Confirm Keanu Reeves' }));
    await user.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(
      'Keanu Reeves wears a grey jacket against a plain background.',
    );

    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    await user.clear(editor);
    await user.type(editor, 'Keanu Reeves wears a grey jacket.');
    await user.click(screen.getByRole('button', { name: 'Save description edit' }));
    await user.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Keanu Reeves wears a grey jacket.');

    await user.click(screen.getByRole('button', { name: 'Undo practice apply' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent(
      'Keanu Reeves wears a grey jacket against a plain background.',
    );
    expect(screen.getByRole('button', { name: 'Undo practice apply' })).toBeInTheDocument();
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');

    await user.click(screen.getByRole('button', { name: 'Undo practice apply' }));
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Portrait of a person in a grey jacket.');
    expect(screen.queryByRole('button', { name: 'Undo practice apply' })).not.toBeInTheDocument();
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-apply');
  });

  it('keeps practice changes on cancel and safely resets edits, errors, and focus on confirm', async () => {
    const user = userEvent.setup();
    render(<GuidedPrototypePage />);

    await user.click(screen.getByRole('button', { name: 'Start the guided walkthrough' }));
    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: 'Saved local practice edit.' } });
    await user.click(screen.getByRole('button', { name: 'Save description edit' }));
    fireEvent.change(editor, { target: { value: 'Pending local practice edit.' } });
    expect(editor).toHaveValue('Pending local practice edit.');

    await user.click(screen.getByRole('button', { name: 'Reset practice' }));
    expect(screen.getByRole('dialog', { name: 'Reset this practice?' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(editor).toHaveValue('Pending local practice edit.');

    await user.clear(editor);
    await user.type(editor, '   ');
    await user.click(screen.getByRole('button', { name: 'Save description edit' }));
    expect(screen.getByRole('alert')).toHaveTextContent('A description cannot be empty.');

    await user.click(screen.getByRole('button', { name: 'Reset practice' }));
    const dialog = screen.getByRole('dialog', { name: 'Reset this practice?' });
    await user.click(within(dialog).getByRole('button', { name: 'Reset practice' }));
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(
      'Portrait of a person in a grey jacket.',
    );
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

  it('renders the supplied sample photo and describes a useful fallback when it fails', () => {
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
    expect(screen.getByText(/Identity evidence comes from the sample record/)).toBeInTheDocument();
  });
});
