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
    const input = screen.getByDisplayValue('Test Cluster') as HTMLInputElement;
    expect(input.value).toBe(defaultProps.labelInput);
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

  it('calls onLabelChange and onSave when a suggestion is clicked', async () => {
    const onLabelChange = vi.fn();
    const onSave = vi.fn();
    render(<ClusterEditForm {...defaultProps} labelInput="P" onLabelChange={onLabelChange} onSave={onSave} />);
    
    const suggestion = screen.getByText('Person B');
    fireEvent.click(suggestion);
    
    expect(onLabelChange).toHaveBeenCalledWith('Person B');
    await waitFor(() => expect(onSave).toHaveBeenCalled());
  });

  it('is disabled when isPending is true', () => {
    render(<ClusterEditForm {...defaultProps} isPending={true} />);
    const input = screen.getByDisplayValue('Test Cluster');
    const saveButton = screen.getByText('Saving…');
    
    expect(input).toBeDisabled();
    expect(saveButton).toBeDisabled();
  });
});
