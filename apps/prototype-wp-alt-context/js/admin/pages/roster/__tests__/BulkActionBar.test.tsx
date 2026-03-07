import { render, screen } from '@testing-library/react';

import { BulkActionBar } from '../BulkActionBar';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

describe('BulkActionBar', () => {
  it('shows loading and disables merge action while merging', () => {
    render(
      <BulkActionBar
        count={3}
        onMerge={vi.fn()}
        onDismiss={vi.fn()}
        onClear={vi.fn()}
        isMerging
        isDismissing={false}
      />,
    );

    const mergeButton = screen.getByRole('button', { name: /merging/i });
    expect(mergeButton).toBeDisabled();
    expect(screen.getByRole('button', { name: /dismiss/i })).toBeDisabled();
  });
});
