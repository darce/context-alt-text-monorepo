/**
 * BR-38 contract: ClusterLabelingPanel.skipGuardClearOnNextValueRef assumes Combobox
 * fires onSelect, then onValueChange (echo of the selected label) synchronously.
 * A Combobox swap that reverses that order must fail this test loudly.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { Combobox } from '../../../../../components/ui/combobox';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

describe('Combobox onSelect → onValueChange echo order (BR-38)', () => {
  it('fires onSelect before onValueChange synchronously on option select', async () => {
    // Predicted first failure: order is ['onValueChange', 'onSelect'] or only one fires.
    const order: string[] = [];
    const user = userEvent.setup();

    render(
      <Combobox
        options={[{ value: 'cluster:c1', label: 'Alice' }]}
        value=""
        onSelect={() => {
          order.push('onSelect');
        }}
        onValueChange={() => {
          order.push('onValueChange');
        }}
        ariaLabel="Name"
      />,
    );

    await user.click(screen.getByRole('combobox', { name: 'Name' }));
    await user.click(await screen.findByRole('option', { name: 'Alice' }));

    expect(order).toEqual(['onSelect', 'onValueChange']);
  });
});
