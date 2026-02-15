import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import type { UseQueryResult } from '@tanstack/react-query';
import type { SyncStatusResponse } from '../../../api/recognition';

const mockReturn = {
  data: null as SyncStatusResponse | null | undefined,
  isLoading: false,
  isError: false,
};

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, value: string) => text.replace('%s', value),
}));

vi.mock('../../../hooks/useSyncStatus', () => ({
  useSyncStatus: () => mockReturn as unknown as UseQueryResult<SyncStatusResponse>,
}));

// Static import AFTER vi.mock hoisting
import { SyncStatusIndicator } from '../SyncStatusIndicator';

describe('SyncStatusIndicator', () => {
  beforeEach(() => {
    mockReturn.data = null;
    mockReturn.isLoading = false;
    mockReturn.isError = false;
  });

  it('renders stale status badge when is_stale is true', () => {
    mockReturn.data = { last_snapshot_version: 2, last_synced_at: '2026-02-14 00:00:00', is_stale: true };

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Stale')).toBeInTheDocument();
    expect(screen.getByText(/Last sync/)).toBeInTheDocument();
  });

  it('renders fresh badge when is_stale is false', () => {
    mockReturn.data = { last_snapshot_version: 5, last_synced_at: '2026-02-14 12:00:00', is_stale: false };

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Fresh')).toBeInTheDocument();
    expect(screen.getByText(/Last sync/)).toBeInTheDocument();
  });

  it('returns null when loading', () => {
    mockReturn.isLoading = true;

    const { container } = render(<SyncStatusIndicator />);
    expect(container.firstChild).toBeNull();
  });

  it('renders unavailable message when error occurs', () => {
    mockReturn.isError = true;

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Sync status unavailable')).toBeInTheDocument();
  });

  it('renders unavailable message when data is null', () => {
    render(<SyncStatusIndicator />);

    expect(screen.getByText('Sync status unavailable')).toBeInTheDocument();
  });
});
