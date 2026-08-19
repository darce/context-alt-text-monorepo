import { act, render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ClusterEditForm } from '../ClusterEditForm';
import { selectClusterSuggestions } from '../useClusterSuggestions';

describe('ClusterEditForm', () => {
  const defaultProps = {
    labelInput: 'Test Cluster',
    onLabelChange: vi.fn(),
    options: [
      { value: 'cluster:1', label: 'Person A', source: 'cluster' as const, group: 'Suggested', similarity: 0.95 },
      { value: 'cluster:2', label: 'Person B', source: 'cluster' as const, group: 'Suggested', similarity: 0.85 },
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

  it('calls onSave when Enter is pressed on a changed name', () => {
    const onSave = vi.fn();
    const { rerender } = render(<ClusterEditForm {...defaultProps} onSave={onSave} />);
    rerender(<ClusterEditForm {...defaultProps} labelInput="New Name" onSave={onSave} />);
    fireEvent.keyDown(screen.getByDisplayValue('New Name'), { key: 'Enter', code: 'Enter' });
    expect(onSave).toHaveBeenCalledWith('New Name');
  });

  it('no-ops Enter when the resolved name matches the prefill (UXW2-3-R1-13)', () => {
    const onSave = vi.fn();
    const onPersonSelect = vi.fn();
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="Pat Roster"
        options={[{ value: 'person:42', label: 'Pat Roster', source: 'person', group: 'All Labels' }]}
        onSave={onSave}
        onPersonSelect={onPersonSelect}
      />,
    );
    fireEvent.keyDown(screen.getByDisplayValue('Pat Roster'), { key: 'Enter', code: 'Enter' });
    expect(onSave).not.toHaveBeenCalled();
    expect(onPersonSelect).not.toHaveBeenCalled();
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

    expect(document.querySelector('.acx-identity-cluster__suggestion-row')).not.toBeNull();
    expect(screen.getByText(/95%/)).toBeInTheDocument();
  });

  it('pairs match-score color with a textual quality band (high/medium)', () => {
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="P"
        options={[
          { value: 'cluster:1', label: 'Person A', source: 'cluster', group: 'Suggested', similarity: 0.95 },
          { value: 'cluster:2', label: 'Person B', source: 'cluster', group: 'Suggested', similarity: 0.55 },
        ]}
      />,
    );

    const high = document.querySelector('.acx-identity-cluster__match-score--high');
    const medium = document.querySelector('.acx-identity-cluster__match-score--medium');
    expect(high?.textContent).toMatch(/95%\s*high/i);
    expect(medium?.textContent).toMatch(/55%\s*medium/i);
    expect(screen.getByText('high')).toBeInTheDocument();
    expect(screen.getByText('medium')).toBeInTheDocument();
  });

  it('suggestion row click fills the name and does not commit (UXW2-3-R3-27)', () => {
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

    fireEvent.click(screen.getAllByRole('option', { name: /confirm match/i })[1]);
    expect(onLabelChange).toHaveBeenCalledWith('Person B');
    expect(onSave).not.toHaveBeenCalled();
    expect(onConfirmSuggestion).not.toHaveBeenCalled();
  });

  it('calls onLabelChange when a suggestion is clicked, and onConfirmSuggestion when confirm is clicked', async () => {
    const onLabelChange = vi.fn();
    const onSave = vi.fn();
    const onConfirmSuggestion = vi.fn();
    const { rerender } = render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="P"
        onLabelChange={onLabelChange}
        onSave={onSave}
        onConfirmSuggestion={onConfirmSuggestion}
      />,
    );

    const confirmOption = screen.getAllByRole('option', { name: /confirm match/i })[1]; // Index 1 for Person B
    fireEvent.click(confirmOption);
    expect(onLabelChange).toHaveBeenCalledWith('Person B');
    expect(onSave).not.toHaveBeenCalled();
    expect(onConfirmSuggestion).not.toHaveBeenCalled();

    rerender(
      <ClusterEditForm
        {...defaultProps}
        labelInput="Person B"
        onLabelChange={onLabelChange}
        onSave={onSave}
        onConfirmSuggestion={onConfirmSuggestion}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(onConfirmSuggestion).toHaveBeenCalledWith('2', 'Person B', undefined),
    );
  });

  it('clicking the second of two same-fold people binds that roster id (UXW2-3-R3-12)', async () => {
    const onPersonSelect = vi.fn();
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="alex carter"
        options={[
          { value: 'person:1', label: 'Alex Carter', source: 'person', group: 'All Labels' },
          { value: 'person:2', label: 'ALEX CARTER', source: 'person', group: 'All Labels' },
        ]}
        onPersonSelect={onPersonSelect}
      />,
    );

    const confirmOptions = screen.getAllByRole('option', { name: /Confirm match with/ });
    expect(confirmOptions).toHaveLength(2);
    fireEvent.click(confirmOptions[1]);
    await waitFor(() => expect(onPersonSelect).toHaveBeenCalledWith('ALEX CARTER'));
    expect(onPersonSelect).not.toHaveBeenCalledWith('Alex Carter');
  });

  it('person-source confirm uses onPersonSelect and never onConfirmSuggestion (PR-16 / FIX-1)', async () => {
    // Predicted first failure: onConfirmSuggestion or onSave called instead of onPersonSelect
    const onSave = vi.fn();
    const onPersonSelect = vi.fn();
    const onConfirmSuggestion = vi.fn();
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="P"
        options={[{ value: 'person:42', label: 'Pat Roster', source: 'person', group: 'All Labels' }]}
        onSave={onSave}
        onPersonSelect={onPersonSelect}
        onConfirmSuggestion={onConfirmSuggestion}
      />,
    );

    fireEvent.click(screen.getByRole('option', { name: /confirm match/i }));
    await waitFor(() => expect(onPersonSelect).toHaveBeenCalledWith('Pat Roster'));
    expect(onSave).not.toHaveBeenCalled();
    expect(onConfirmSuggestion).not.toHaveBeenCalled();
  });

  it('falls back to onSave for person confirm when onPersonSelect is absent', async () => {
    const onSave = vi.fn();
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="P"
        options={[{ value: 'person:42', label: 'Pat Roster', source: 'person', group: 'All Labels' }]}
        onSave={onSave}
      />,
    );

    fireEvent.click(screen.getByRole('option', { name: /confirm match/i }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('Pat Roster'));
  });

  it('budgets overlay so a person survives five Suggested rows (FIX-6)', () => {
    // Predicted first failure: person not rendered when options.slice(0,5) is all Suggested
    const options = [
      ...Array.from({ length: 5 }, (_, index) => ({
        value: `cluster:s${index}`,
        label: `Suggested ${index}`,
        source: 'cluster' as const,
        group: 'Suggested',
        similarity: 0.9 - index * 0.05,
      })),
      { value: 'person:1', label: 'Alice Person', source: 'person' as const, group: 'All Labels' },
    ];
    render(<ClusterEditForm {...defaultProps} labelInput="A" options={options} />);

    expect(screen.getByRole('option', { name: /Alice Person/ })).toBeInTheDocument();
    expect(screen.queryByText('Suggested 3')).not.toBeInTheDocument();
    expect(screen.queryByText('Suggested 4')).not.toBeInTheDocument();
  });

  it('announces option count in a polite live region (A11Y-21 / FIX-7)', () => {
    vi.useFakeTimers();
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="P"
        options={[
          { value: 'cluster:1', label: 'Person A', source: 'cluster', group: 'Suggested', similarity: 0.9 },
          { value: 'person:2', label: 'Pat', source: 'person', group: 'All Labels' },
        ]}
      />,
    );

    act(() => {
      vi.advanceTimersByTime(400);
    });
    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toHaveTextContent(/2 naming options/);
    vi.useRealTimers();
  });

  it('includes source in Suggested cluster accessible names (A11Y-04 / FIX-7)', () => {
    // Predicted first failure: aria-label is bare "Person A" without Cluster source
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="P"
        options={[{ value: 'cluster:1', label: 'Person A', source: 'cluster', group: 'Suggested', similarity: 0.95 }]}
      />,
    );

    expect(screen.getByRole('option', { name: /Person A \(Group\)/i })).toBeInTheDocument();
  });

  it('unwraps cluster: namespaced values on confirm', async () => {
    const onConfirmSuggestion = vi.fn();
    const onLabelChange = vi.fn();
    const { rerender } = render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="B"
        options={[{ value: 'cluster:c-bob', label: 'Bob', source: 'cluster', group: 'Suggested' }]}
        onLabelChange={onLabelChange}
        onConfirmSuggestion={onConfirmSuggestion}
      />,
    );

    fireEvent.click(screen.getByRole('option', { name: /confirm match/i }));
    expect(onConfirmSuggestion).not.toHaveBeenCalled();
    rerender(
      <ClusterEditForm
        {...defaultProps}
        labelInput="Bob"
        options={[{ value: 'cluster:c-bob', label: 'Bob', source: 'cluster', group: 'Suggested' }]}
        onLabelChange={onLabelChange}
        onConfirmSuggestion={onConfirmSuggestion}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(onConfirmSuggestion).toHaveBeenCalledWith('c-bob', 'Bob', undefined),
    );
  });

  it('is disabled when isPending is true', () => {
    render(<ClusterEditForm {...defaultProps} isPending={true} />);
    const input = screen.getByDisplayValue('Test Cluster');
    const saveButton = screen.getByRole('button', { name: 'Saving…' });

    expect(input).toBeDisabled();
    expect(saveButton).toBeDisabled();
  });

  it('renders a custom save label when provided', () => {
    render(<ClusterEditForm {...defaultProps} saveLabel="Saving queued" />);
    expect(screen.getByText('Saving queued')).toBeInTheDocument();
  });

  it('announces Saved! in the field live region during case-only rename success (PERC-05 / A11Y-21)', () => {
    // Predicted first failure: live region empty while isPending (prior behavior cleared status)
    render(<ClusterEditForm {...defaultProps} isPending saveLabel="Saved!" />);

    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toHaveTextContent('Saved!');
    // Fovea-first: same status also on the save button next to the field
    expect(screen.getByRole('button', { name: 'Saved!' })).toBeInTheDocument();
  });

  it('announces Saving… in the field live region while pending without custom label', () => {
    render(<ClusterEditForm {...defaultProps} isPending />);

    expect(screen.getByRole('status')).toHaveTextContent('Saving…');
  });

  it('calls onRejectSuggestion when Reject button is clicked', () => {
    const onRejectSuggestion = vi.fn();
    const optionsWithSuggestion = [
      {
        value: 'cluster:1',
        label: 'Person A',
        source: 'cluster' as const,
        group: 'Suggested',
        similarity: 0.95,
        suggestion_id: 's-1',
      },
      { value: 'cluster:2', label: 'Person B', source: 'cluster' as const, group: 'Suggested', similarity: 0.85 },
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

  it('threads projected suggestionId into reject via selectClusterSuggestions (BR-16)', () => {
    // Predicted first failure: selector drops suggestionId → no reject button / wrong id
    const onRejectSuggestion = vi.fn();
    const options = selectClusterSuggestions({
      identityProjection: [
        {
          identityId: 'identity-1',
          clusterId: 'cluster-alice',
          label: 'Alice',
          similarity: 0.91,
          identityCount: 4,
          suggestionId: 'sug-real-alice',
        },
      ],
      namingOptions: [],
      labelInput: '',
    });

    expect(options[0]?.suggestion_id).toBe('sug-real-alice');

    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="A"
        options={options}
        onRejectSuggestion={onRejectSuggestion}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /reject/i }));
    expect(onRejectSuggestion).toHaveBeenCalledWith('sug-real-alice');
  });

  it('shows an at-rest incomplete-list hint from envelope total, not option count (REV1-01)', () => {
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput=""
        atRestTruncated
        atRestTotal={80}
        isAtRestMode
      />,
    );

    expect(screen.getByText('Showing 2 of 80 labels — type to search for more')).toBeInTheDocument();
  });

  it('pins the at-rest hint first number to the rendered overlay row count', () => {
    const options = Array.from({ length: 12 }, (_, index) => ({
      value: `cluster:u${index}`,
      label: `Union Label ${index}`,
      source: 'cluster' as const,
      group: 'All Labels',
    }));

    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput=""
        options={options}
        atRestTruncated
        atRestTotal={80}
        isAtRestMode
      />,
    );

    const renderedOptionRows = screen.getAllByRole('option', { name: /confirm match/i });
    expect(screen.getByText(`Showing ${renderedOptionRows.length} of 80 labels — type to search for more`)).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Person name' })).toHaveAccessibleDescription(
      `Showing ${renderedOptionRows.length} of 80 labels — type to search for more`,
    );
  });

  it('scopes the at-rest hint id per form instance so each combobox describes its own total', () => {
    render(
      <>
        <div data-testid="form-a">
          <ClusterEditForm
            {...defaultProps}
            labelInput=""
            atRestTruncated
            atRestTotal={80}
            isAtRestMode
          />
        </div>
        <div data-testid="form-b">
          <ClusterEditForm
            {...defaultProps}
            labelInput=""
            atRestTruncated
            atRestTotal={40}
            isAtRestMode
          />
        </div>
      </>,
    );

    const formA = within(screen.getByTestId('form-a'));
    const formB = within(screen.getByTestId('form-b'));
    const hintA = formA.getByText('Showing 2 of 80 labels — type to search for more');
    const hintB = formB.getByText('Showing 2 of 40 labels — type to search for more');

    expect(hintA.id).not.toBe(hintB.id);
    expect(formA.getByRole('combobox', { name: 'Person name' })).toHaveAccessibleDescription(
      'Showing 2 of 80 labels — type to search for more',
    );
    expect(formB.getByRole('combobox', { name: 'Person name' })).toHaveAccessibleDescription(
      'Showing 2 of 40 labels — type to search for more',
    );
  });

  it('hides the at-rest incomplete-list hint once the loader leaves at-rest mode', () => {
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="To"
        atRestTruncated
        atRestTotal={80}
        isAtRestMode={false}
      />,
    );

    expect(screen.queryByText(/Showing \d+ of \d+ labels — type to search for more/)).not.toBeInTheDocument();
  });

  it('does not invent an incomplete-list hint when the at-rest page is complete', () => {
    render(
      <ClusterEditForm
        {...defaultProps}
        labelInput=""
        atRestTruncated={false}
        atRestTotal={12}
      />,
    );

    expect(screen.queryByText(/Showing \d+ of \d+ labels/)).not.toBeInTheDocument();
  });

  it('threads option.suggestion_id into onConfirmSuggestion (BR-16 / L1R-01)', async () => {
    // Predicted first failure on f54f7c87 production: called with (clusterId, label) only —
    // confirm branch dropped option.suggestion_id so the pending row was never resolved by id.
    const onConfirmSuggestion = vi.fn();
    const { rerender } = render(
      <ClusterEditForm
        {...defaultProps}
        labelInput="A"
        options={[
          {
            value: 'cluster:cluster-alice',
            label: 'Alice',
            source: 'cluster',
            group: 'Suggested',
            similarity: 0.91,
            suggestion_id: 'sug-confirm-alice',
          },
        ]}
        onConfirmSuggestion={onConfirmSuggestion}
      />,
    );

    fireEvent.click(screen.getByRole('option', { name: /confirm match/i }));
    expect(onConfirmSuggestion).not.toHaveBeenCalled();
    rerender(
      <ClusterEditForm
        {...defaultProps}
        labelInput="Alice"
        options={[
          {
            value: 'cluster:cluster-alice',
            label: 'Alice',
            source: 'cluster',
            group: 'Suggested',
            similarity: 0.91,
            suggestion_id: 'sug-confirm-alice',
          },
        ]}
        onConfirmSuggestion={onConfirmSuggestion}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(onConfirmSuggestion).toHaveBeenCalledWith(
        'cluster-alice',
        'Alice',
        'sug-confirm-alice',
      ),
    );
  });
});
