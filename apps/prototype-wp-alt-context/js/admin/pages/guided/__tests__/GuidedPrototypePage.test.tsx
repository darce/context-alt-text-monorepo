import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { GuidedPrototypePage } from '../GuidedPrototypePage';

describe('GuidedPrototypePage', () => {
  it('supports the identity-informed practice journey through explicit apply and undo', () => {
    render(<GuidedPrototypePage />);

    expect(screen.getByRole('heading', { name: 'Guided description review' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start the guided review' }));
    expect(screen.getByRole('navigation', { name: 'Guided review steps' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm Keanu Reeves' }));
    expect(screen.getByText('Keanu Reeves wears a grey jacket against a plain background.')).toBeInTheDocument();
    expect(screen.getAllByText('Identity confirmed from the sample record.').length).toBeGreaterThan(0);

    const editor = screen.getByRole('textbox', { name: 'Description draft' });
    fireEvent.change(editor, { target: { value: 'Keanu Reeves wears a grey jacket.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save description edit' }));
    expect(screen.getByText('Edited by you')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Apply to practice copy' }));
    expect(screen.getAllByText('Applied to the practice copy.').length).toBeGreaterThan(0);
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Keanu Reeves wears a grey jacket.');

    fireEvent.click(screen.getByRole('button', { name: 'Undo practice apply' }));
    expect(screen.getAllByText('Application undone.').length).toBeGreaterThan(0);
    expect(document.querySelector('[data-applied-text]')).toHaveTextContent('Portrait of a person in a grey jacket.');
  });

  it('keeps the unidentified path useful without using the sample name', () => {
    render(<GuidedPrototypePage />);

    fireEvent.click(screen.getByRole('button', { name: 'Start the guided review' }));
    fireEvent.click(screen.getByRole('button', { name: 'Keep the person unidentified' }));

    expect(screen.getAllByText('Identity left unidentified.').length).toBeGreaterThan(0);
    expect(screen.getByRole('textbox', { name: 'Description draft' })).toHaveValue(
      'Portrait of a person in a grey jacket.',
    );
    expect(screen.getByTestId('guided-candidate')).not.toHaveTextContent('Keanu Reeves');
  });
});
