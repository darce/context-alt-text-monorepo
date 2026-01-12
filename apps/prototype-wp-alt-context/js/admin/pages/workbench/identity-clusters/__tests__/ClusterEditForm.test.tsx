import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ClusterEditForm } from '../ClusterEditForm';

describe('ClusterEditForm', () => {
  const defaultProps = {
    labelInput: 'Test Cluster',
    onLabelChange: vi.fn(),
    options: [
      { value: '1', label: 'Person A', similarity: 0.95 },
      { value: '2', label: 'Person B', similarity: 0.85 },
    ],
    isLoading: false,
    isPending: false,
    onSave: vi.fn(),
    onCancel: vi.fn(),
  };

  it('renders with initial label and autofocus', () => {
    render(<ClusterEditForm {...defaultProps} />);
    const input = screen.getByDisplayValue('Test Cluster');
    expect((input as HTMLInputElement).value).toBe(defaultProps.labelInput);
    expect(document.activeElement).toBe(input);
  });

  it('calls onLabelChange when typing', () => {
    const onLabelChange = vi.fn();
    render(<ClusterEditForm {...defaultProps} onLabelChange={onLabelChange} />);
    const input = screen.getByDisplayValue('Test Cluster');

    fireEvent.change(input, { target: { value: 'New Label' } });
    expect(onLabelChange).toHaveBeenCalledWith('New Label');
  });

  it('calls onSave when Enter is pressed', () => {
    const onSave = vi.fn();
    render(<ClusterEditForm {...defaultProps} onSave={onSave} />);
    const input = screen.getByDisplayValue('Test Cluster');

    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    expect(onSave).toHaveBeenCalled();
  });

  it('calls onCancel when Escape is pressed', () => {
    const onCancel = vi.fn();
    render(<ClusterEditForm {...defaultProps} onCancel={onCancel} />);
    const input = screen.getByDisplayValue('Test Cluster');

    fireEvent.keyDown(input, { key: 'Escape', code: 'Escape' });
    expect(onCancel).toHaveBeenCalled();
  });

  it('shows suggestions overlay when typing a partial match', () => {
    render(<ClusterEditForm {...defaultProps} labelInput="Per" />);

    expect(screen.getByText('Person A')).toBeInTheDocument();
    expect(screen.getByText('95%')).toBeInTheDocument();
  });

  it('calls onLabelChange when a suggestion is clicked, and onConfirmSuggestion when confirm is clicked', async () => {
    const onLabelChange = vi.fn();
    const onSave = vi.fn();
    const onConfirmSuggestion = vi.fn();
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="P"
        onLabelChange={onLabelChange}
        onSave={onSave}
        onConfirmSuggestion={onConfirmSuggestion}
      />,
    );

    // Clicking the suggestion item only changes label
    const suggestion = screen.getByText('Person B');
    fireEvent.click(suggestion);
    expect(onLabelChange).toHaveBeenCalledWith('Person B');
    expect(onSave).not.toHaveBeenCalled();

    // Clicking the confirm button calls onConfirmSuggestion
    const confirmButton = screen.getAllByRole('button', { name: /confirm match/i })[1]; // Index 1 for Person B
    fireEvent.click(confirmButton);
    await waitFor(() => expect(onConfirmSuggestion).toHaveBeenCalledWith('2', 'Person B'));
  });

  it('is disabled when isPending is true', () => {
    render(<ClusterEditForm {...defaultProps} isPending={true} />);
    const input = screen.getByDisplayValue('Test Cluster');
    const saveButton = screen.getByText('Saving…');

    expect(input).toBeDisabled();
    expect(saveButton).toBeDisabled();
  });

  it('renders a custom save label when provided', () => {
    render(<ClusterEditForm {...defaultProps} saveLabel="Saving queued" />);
    expect(screen.getByText('Saving queued')).toBeInTheDocument();
  });

  it('calls onRejectSuggestion when Reject button is clicked', () => {
    const onRejectSuggestion = vi.fn();
    const optionsWithSuggestion = [
      { value: '1', label: 'Person A', similarity: 0.95, suggestion_id: 's-1' },
      { value: '2', label: 'Person B', similarity: 0.85 },
    ];

    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="P"
        options={optionsWithSuggestion}
        onRejectSuggestion={onRejectSuggestion}
      />,
    );

    const rejectButton = screen.getByRole('button', { name: /reject/i });
    fireEvent.click(rejectButton);

    expect(onRejectSuggestion).toHaveBeenCalledWith('s-1');
  });
});
