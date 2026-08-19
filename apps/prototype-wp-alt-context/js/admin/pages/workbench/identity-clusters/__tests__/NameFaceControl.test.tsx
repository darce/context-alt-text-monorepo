import React from 'react';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ComboboxOption } from '../../../../../components/ui/combobox';
import {
  NameFaceControl,
  normalizeNameFaceLabel,
  resolveNameFaceInput,
} from '../NameFaceControl';
import { namingOptionValue } from '../buildNamingOptions';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let sequential = 0;
    return template.replace(/%((\d+)\$)?[sd]/g, (_match, _pos, explicit) => {
      if (explicit) {
        return String(args[Number(explicit) - 1] ?? '');
      }
      return String(args[sequential++] ?? '');
    });
  },
}));

const person = (id: number, label: string, extra: Partial<ComboboxOption> = {}): ComboboxOption => ({
  value: namingOptionValue('person', String(id)),
  label,
  source: 'person',
  ...extra,
});

const defaultProps = {
  options: [person(1, 'Ada Lovelace'), person(2, 'Grace Hopper'), person(3, 'Alan Turing')] as const,
  value: '',
  onValueChange: vi.fn(),
  onCommit: vi.fn(),
  commitLabel: 'Save name',
  ariaLabel: 'Name this person',
};

const renderControl = (overrides: Partial<React.ComponentProps<typeof NameFaceControl>> = {}) => {
  const onCommit = overrides.onCommit ?? vi.fn();
  const onOptionConfirm =
    'onOptionConfirm' in overrides ? overrides.onOptionConfirm : vi.fn();
  const onValueChange = overrides.onValueChange ?? vi.fn();
  const props: React.ComponentProps<typeof NameFaceControl> = {
    ...defaultProps,
    onCommit,
    onValueChange,
    ...overrides,
  };
  if (!('onOptionConfirm' in overrides) && onOptionConfirm) {
    props.onOptionConfirm = onOptionConfirm;
  }
  const view = render(<NameFaceControl {...props} />);
  return { ...view, onCommit, onOptionConfirm, onValueChange };
};

const TypedNameFace = ({
  options = defaultProps.options,
  onCommit,
}: {
  options?: readonly ComboboxOption[];
  onCommit: ReturnType<typeof vi.fn>;
}): React.JSX.Element => {
  const [value, setValue] = React.useState('');
  return (
    <NameFaceControl
      options={options}
      value={value}
      onValueChange={setValue}
      onCommit={onCommit}
      commitLabel="Save name"
      ariaLabel="Name this person"
    />
  );
};

describe('NameFaceControl combobox pattern (UXW2-3-R1-01)', () => {
  it('ArrowDown twice then Enter confirms the second option', async () => {
    const { onOptionConfirm, onCommit } = renderControl();
    const user = userEvent.setup();
    const input = screen.getByRole('combobox', { name: 'Name this person' });

    expect(input).toHaveAttribute('aria-autocomplete', 'list');
    expect(input).toHaveAttribute('aria-haspopup', 'listbox');
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getAllByRole('option')).toHaveLength(3);

    input.focus();
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');

    expect(onOptionConfirm).toHaveBeenCalledTimes(1);
    expect(onOptionConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'Grace Hopper', value: namingOptionValue('person', '2') }),
    );
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('Enter with no active option commits the typed value', async () => {
    const { onCommit, onOptionConfirm } = renderControl({ value: 'Pat Rivera' });
    const user = userEvent.setup();

    await user.type(screen.getByRole('combobox'), '{Enter}');

    expect(onCommit).toHaveBeenCalledWith({ kind: 'create', name: 'Pat Rivera' });
    expect(onOptionConfirm).not.toHaveBeenCalled();
  });

  it('Home / End / Escape move the active option and close', async () => {
    const onCancel = vi.fn();
    renderControl({ onCancel });
    const user = userEvent.setup();
    const input = screen.getByRole('combobox');

    input.focus();
    await user.keyboard('{End}');
    expect(input).toHaveAttribute(
      'aria-activedescendant',
      screen.getByRole('option', { name: /Alan Turing/ }).id,
    );

    await user.keyboard('{Home}');
    expect(input).toHaveAttribute(
      'aria-activedescendant',
      screen.getByRole('option', { name: /Ada Lovelace/ }).id,
    );

    await user.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalled();
  });
});

describe('NameFaceControl create-vs-bind (UXW2-3-R1-07)', () => {
  it('normalises NFC + case + whitespace before comparing', () => {
    const nfd = 'Cafe\u0301'.normalize('NFD');
    const options = [person(9, 'Café')];
    expect(normalizeNameFaceLabel(nfd)).toBe(normalizeNameFaceLabel('CAFÉ'));
    expect(resolveNameFaceInput(options, `  ${nfd}  `)).toEqual({
      kind: 'roster',
      rosterEntryId: 9,
      name: 'Café',
    });
  });

  it('typed Zed shows Zed Offslice; typed Gra does not (UXW2-3-R2-01)', async () => {
    const options = [
      ...Array.from({ length: 6 }, (_, index) => person(index + 1, `Suggested ${index}`)),
      person(99, 'Zed Offslice'),
    ];
    const { rerender, onCommit } = renderControl({ options, value: 'Zed' });

    expect(screen.getByRole('option', { name: /Zed Offslice/ })).toBeInTheDocument();

    rerender(
      <NameFaceControl
        options={options}
        value="Gra"
        onValueChange={onCommit}
        onCommit={onCommit}
        commitLabel="Save name"
        ariaLabel="Name this person"
      />,
    );
    expect(screen.queryByRole('option', { name: /Zed Offslice/ })).not.toBeInTheDocument();
  });

  it('binds a roster person who fell outside the unfiltered display budget', async () => {
    const options = [
      ...Array.from({ length: 6 }, (_, index) => person(index + 1, `Suggested ${index}`)),
      person(99, 'Zed Offslice'),
    ];
    const { onCommit } = renderControl({ options, value: 'zed offslice' });
    const user = userEvent.setup();

    expect(screen.getByRole('option', { name: /Zed Offslice/ })).toBeInTheDocument();
    await user.type(screen.getByRole('combobox'), '{Enter}');

    expect(onCommit).toHaveBeenCalledWith({
      kind: 'roster',
      rosterEntryId: 99,
      name: 'Zed Offslice',
    });
  });

  it('type Gra, ArrowDown, Enter binds Grace and never a non-match (UXW2-3-R2-01a)', async () => {
    const onCommit = vi.fn();
    render(<TypedNameFace onCommit={onCommit} />);
    const user = userEvent.setup();
    const input = screen.getByRole('combobox', { name: 'Name this person' });

    await user.type(input, 'Gra');
    await user.keyboard('{ArrowDown}{Enter}');

    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith({
      kind: 'roster',
      rosterEntryId: 2,
      name: 'Grace Hopper',
    });
  });

  it('clicking confirm on the second same-fold person binds that id (UXW2-3-R2-01b)', async () => {
    const options = [person(1, 'Alex Carter'), person(2, 'ALEX CARTER')];
    const { onCommit } = renderControl({
      options,
      value: 'alex carter',
      onOptionConfirm: undefined,
    });
    const user = userEvent.setup();

    const confirmOptions = screen.getAllByRole('option', { name: /Confirm match with/ });
    expect(confirmOptions).toHaveLength(2);
    await user.click(confirmOptions[1]);

    expect(onCommit).toHaveBeenCalledWith({
      kind: 'roster',
      rosterEntryId: 2,
      name: 'ALEX CARTER',
    });
    expect(screen.getByRole('button', { name: 'Save name' })).toBeEnabled();
  });

  it('forces an explicit choice when two roster people fold to the same name', async () => {
    const options = [person(1, 'Alex Carter'), person(2, 'ALEX CARTER')];
    const { onCommit } = renderControl({ options, value: 'alex carter' });
    const user = userEvent.setup();

    await user.type(screen.getByRole('combobox'), '{Enter}');

    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent(/multiple people match/i);
  });

  it('highlights the matched substring in each row', () => {
    renderControl({ value: 'ada' });
    const mark = document.querySelector('mark');
    expect(mark).not.toBeNull();
    expect(mark).toHaveTextContent(/ada/i);
  });
});

describe('NameFaceControl live region (UXW2-3-R1-14)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('announces the true match total after debounce, pluralised', () => {
    const options = [
      ...Array.from({ length: 8 }, (_, index) => person(index + 1, `Pat ${index}`)),
    ];
    renderControl({ options, value: 'Pat' });

    expect(screen.getByRole('status')).not.toHaveTextContent('8 naming options');

    act(() => {
      vi.advanceTimersByTime(400);
    });

    expect(screen.getByRole('status')).toHaveTextContent('8 naming options');
  });

  it('uses the singular form for one match', () => {
    renderControl({ options: [person(1, 'Ada')], value: 'Ada' });
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(screen.getByRole('status')).toHaveTextContent('1 naming option');
  });
});

describe('NameFaceControl distinct confirm names (UXW2-3-R1-15)', () => {
  it('gives each row a distinct confirm and reject accessible name', () => {
    renderControl({
      options: [
        { ...person(1, 'Ada Lovelace'), suggestion_id: 's-ada' },
        { ...person(2, 'Grace Hopper'), suggestion_id: 's-grace' },
      ],
      onRejectSuggestion: vi.fn(),
    });

    expect(screen.getByRole('option', { name: 'Confirm match with Ada Lovelace (Person)' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Confirm match with Grace Hopper (Person)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject Ada Lovelace' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject Grace Hopper' })).toBeInTheDocument();
    expect(screen.queryAllByRole('button', { name: 'Confirm match' })).toHaveLength(0);
  });
});

describe('NameFaceControl APG overlay (UXW2-3-R2-03)', () => {
  it('exposes aria-controls and toggles aria-expanded on Escape / ArrowDown', async () => {
    const onCancel = vi.fn();
    renderControl({ onCancel });
    const user = userEvent.setup();
    const input = screen.getByRole('combobox', { name: 'Name this person' });
    const listbox = screen.getByRole('listbox');

    expect(input).toHaveAttribute('aria-controls', listbox.id);
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(listbox).toHaveAttribute('aria-labelledby', `${listbox.id}-label`);
    for (const option of screen.getAllByRole('option')) {
      expect(option.querySelector('button')).toBeNull();
    }

    input.focus();
    await user.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalled();
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

    await user.keyboard('{ArrowDown}');
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('listbox')).toBeInTheDocument();
  });

  it('reject is reachable via keyboard Delete on the active option', async () => {
    const onRejectSuggestion = vi.fn();
    renderControl({
      options: [{ ...person(1, 'Ada Lovelace'), suggestion_id: 's-ada' }],
      onRejectSuggestion,
    });
    const user = userEvent.setup();
    const input = screen.getByRole('combobox', { name: 'Name this person' });
    input.focus();
    await user.keyboard('{ArrowDown}{Delete}');
    expect(onRejectSuggestion).toHaveBeenCalledWith('s-ada');
  });
});

describe('NameFaceControl pending Enter (UXW2-3-R1-04)', () => {
  it('ignores Enter while isPending', async () => {
    const { onCommit } = renderControl({ value: 'Pat', isPending: true });
    const user = userEvent.setup();
    await user.type(screen.getByRole('combobox'), '{Enter}');
    expect(onCommit).not.toHaveBeenCalled();
  });
});

describe('NameFaceControl header + loading (UXW2-3-R1-16)', () => {
  it('uses a configurable suggestions header', () => {
    renderControl({ suggestionsHeader: 'People' });
    expect(screen.getByText('People')).toBeInTheDocument();
    expect(screen.queryByText('Suggested')).not.toBeInTheDocument();
  });

  it('surfaces isLoading as an announced pending state', () => {
    renderControl({ isLoading: true, options: [] });
    expect(screen.getByRole('status')).toHaveTextContent('Loading people…');
    expect(screen.getByRole('combobox')).toBeDisabled();
  });
});
