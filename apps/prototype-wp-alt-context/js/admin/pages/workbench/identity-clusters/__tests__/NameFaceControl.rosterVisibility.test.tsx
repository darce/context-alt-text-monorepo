import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ComboboxOption } from '../../../../../components/ui/combobox';
import { NameFaceControl, type NameFaceResolution } from '../NameFaceControl';
import { NAMING_GROUP_SUGGESTED, namingOptionValue } from '../buildNamingOptions';

const closest: ComboboxOption = {
  value: namingOptionValue('person', 7),
  label: 'Ellyn Heald',
  source: 'person',
  group: NAMING_GROUP_SUGGESTED,
  roster_entry_id: 7,
  cluster_id: '5a1e0c00-0000-4000-8000-0000000000e1',
  band: 'none',
  similarity: 0.12,
};
const ordinary: ComboboxOption[] = [
  { value: namingOptionValue('person', 9), label: 'Zoe Adams', source: 'person' },
  { value: namingOptionValue('person', 10), label: 'Pat Nguyen', source: 'person' },
];

const Harness = ({
  initialValue = '',
  options = [closest, ...ordinary],
  onCommit,
}: {
  initialValue?: string;
  options?: readonly ComboboxOption[];
  onCommit: (resolution: NameFaceResolution) => void;
}) => {
  const [value, setValue] = React.useState(initialValue);
  return (
    <NameFaceControl
      options={options}
      value={value}
      onValueChange={setValue}
      onCommit={onCommit}
      ariaLabel="Name this person"
      commitLabel="Save name"
    />
  );
};

afterEach(cleanup);

describe('F4 closest roster alternatives during manual naming', () => {
  it.each(['Unnamed person', 'Zoe'])('keeps the weak roster choice selectable with input %s', async (initialValue) => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness initialValue={initialValue} onCommit={onCommit} />);
    await user.click(screen.getByRole('combobox', { name: 'Name this person' }));
    await user.keyboard('{ArrowDown}');

    const option = screen.getByRole('option', { name: /Ellyn Heald/ });
    expect(option).toHaveTextContent('Below match threshold');
    expect(screen.queryByRole('option', { name: /Pat Nguyen/ })).not.toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled();
    await user.click(option);
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({ kind: 'roster', rosterEntryId: 7, name: 'Ellyn Heald' });
  });

  it('keeps ordinary text search filtering person rows without closest-roster metadata', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness initialValue="Zoe" options={ordinary} onCommit={onCommit} />);
    await user.click(screen.getByRole('combobox', { name: 'Name this person' }));
    await user.keyboard('{ArrowDown}');

    expect(screen.getByRole('option', { name: /Zoe Adams/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Pat Nguyen/ })).not.toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it.each(['', '   '])('abstaining with a blank name %j focuses manual entry and never commits', async (initialValue) => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness initialValue={initialValue} onCommit={onCommit} />);
    const input = screen.getByRole('combobox', { name: 'Name this person' });
    await user.click(input);
    await user.keyboard('{ArrowDown}');
    await user.click(screen.getByRole('button', { name: /No close match: name as new person/i }));

    expect(input).toHaveFocus();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('retains explicit abstention after typing Zoe and creates Zoe only on that action', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness options={[closest]} onCommit={onCommit} />);
    const input = screen.getByRole('combobox', { name: 'Name this person' });
    await user.click(input);
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('button', { name: /No close match: name as new person/i })).toBeInTheDocument();
    await user.type(input, 'Zoe');
    expect(onCommit).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /No close match: name as new person/i }));

    expect(onCommit).toHaveBeenCalledExactlyOnceWith({ kind: 'create', name: 'Zoe' });
  });

  it('typing a manual name alone commits nothing; Save explicitly creates Zoe', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness options={[closest]} onCommit={onCommit} />);
    await user.type(screen.getByRole('combobox', { name: 'Name this person' }), 'Zoe');
    expect(onCommit).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Save name' }));
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({ kind: 'create', name: 'Zoe' });
  });
});
