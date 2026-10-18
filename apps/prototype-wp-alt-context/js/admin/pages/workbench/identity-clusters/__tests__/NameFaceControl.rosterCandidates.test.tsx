/**
 * RED (c82 FIR roster-candidates): the naming control must present closest
 * roster matches below the automatic floor as clearly weak options, with an
 * explicit abstain path. Presentational only: options are fed in by the host,
 * so no fetch and no new module is involved here.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ComboboxOption } from '../../../../../components/ui/combobox';
import { NameFaceControl, type NameFaceResolution } from '../NameFaceControl';
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

/** Below-floor closest named person: band none, similarity under the automatic threshold (roster-candidates shape). */
const weakEllyn = {
  value: namingOptionValue('person', '7'),
  label: 'Ellyn Heald',
  source: 'person',
  similarity: 0.42,
  band: 'none',
  cluster_id: 'c-ellyn',
} as unknown as ComboboxOption;

const Harness = ({
  options,
  onCommit,
}: {
  options: readonly ComboboxOption[];
  onCommit: (resolution: NameFaceResolution) => void;
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

describe('NameFaceControl closest roster matches (RED c82 FIR)', () => {
  it('renders a below-floor closest match as a clearly weak option, not as a medium-confidence match', async () => {
    // Predicted first failure: row shows '42% medium' (no weak label); band none is not honoured.
    const user = userEvent.setup();
    render(<Harness options={[weakEllyn]} onCommit={vi.fn()} />);

    await user.type(screen.getByRole('combobox', { name: 'Name this person' }), 'Ell');

    const option = screen.getByRole('option', { name: /Ellyn Heald/ });
    expect(option).toHaveTextContent('Below match threshold');
    expect(option).not.toHaveTextContent(/medium/i);
  });

  it('offers an explicit abstain path that creates a new person instead of forcing the weak match', async () => {
    // Predicted first failure: no 'new person' abstain control exists when only weak candidates are offered.
    const onCommit = vi.fn();
    const user = userEvent.setup();
    render(<Harness options={[weakEllyn]} onCommit={onCommit} />);

    await user.type(screen.getByRole('combobox', { name: 'Name this person' }), 'Ell');

    const abstain = screen.getByRole('button', { name: /no close match|name as new person/i });
    await user.click(abstain);

    expect(onCommit).toHaveBeenCalledWith({ kind: 'create', name: 'Ell' });
  });

  it('displaying a weak candidate commits nothing (no mutation on display control)', async () => {
    // Control: passes on the current tree. Pins that presenting the weak option is read-only.
    const onCommit = vi.fn();
    const user = userEvent.setup();
    render(<Harness options={[weakEllyn]} onCommit={onCommit} />);

    await user.type(screen.getByRole('combobox', { name: 'Name this person' }), 'Ell');

    expect(screen.getByRole('option', { name: /Ellyn Heald/ })).toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled();
  });
});
