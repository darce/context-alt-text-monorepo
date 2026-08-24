import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import { createMockQuery } from '../../../test-utils/mockHooks';
import { FullAuditLog, RecentAuditEvents } from '../AuditTimeline';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, ...values: (string | number)[]) => {
    let index = 0;
    return text.replace(/%(?:[0-9]+\$)?[sd]/g, () => String(values[index++] ?? ''));
  },
}));

describe('audit timeline empty states', () => {
  it('lets operators refresh the recent audit events', async () => {
    const onRefresh = vi.fn();
    render(<RecentAuditEvents events={[]} onRefresh={onRefresh} />);

    await userEvent.click(screen.getByRole('button', { name: 'Refresh audit events' }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('lets operators refresh an empty full audit log', async () => {
    const refetch = vi.fn();
    const auditQuery = createMockQuery({
      data: { items: [], total: 0 },
      refetch,
    });
    render(<FullAuditLog auditQuery={auditQuery} auditPage={0} dispatch={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Refresh audit log' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
