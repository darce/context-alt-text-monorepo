import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  ConflictDetailResponse,
  ConflictListResponse,
  ConflictRecord,
  ResolveConflictResponse,
  SyncTriggerResponse,
} from '../../../api/recognition';
import { createMockMutation, createMockQuery } from '../../../test-utils/mockHooks';
import { useConflictDetail } from '../../../hooks/useConflictDetail';
import { useConflicts } from '../../../hooks/useConflicts';
import { useResolveConflict } from '../../../hooks/useResolveConflict';
import { useSyncTrigger } from '../../../hooks/useSyncTrigger';
import { ConflictInbox } from '../ConflictInbox';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, ...values: (string | number)[]): string => {
    let result = text;
    for (const value of values) {
      result = result.replace(/%(?:[0-9]+\$)?[sd]/, String(value));
    }
    return result;
  },
}));

vi.mock('../../../hooks/useConflicts', () => ({
  useConflicts: vi.fn(),
}));

vi.mock('../../../hooks/useConflictDetail', () => ({
  useConflictDetail: vi.fn(),
}));

vi.mock('../../../hooks/useResolveConflict', () => ({
  useResolveConflict: vi.fn(),
}));

vi.mock('../../../hooks/useSyncTrigger', () => ({
  useSyncTrigger: vi.fn(),
}));

const buildConflict = (overrides: Partial<ConflictRecord> = {}): ConflictRecord => ({
  id: 9,
  tenant_id: 'tenant-1',
  entity_type: 'cluster',
  entity_key: 'cluster-1',
  outbox_id: 44,
  expected_base_version: 4,
  backend_version: 5,
  local_revision: 2,
  conflict_code: 'version_conflict',
  machine_payload: { label: 'Remote', confidence: 0.91 },
  local_payload: { label: 'Local', confidence: 0.63 },
  resolution_status: 'open',
  resolved_at: null,
  created_at: '2026-03-11T10:00:00Z',
  allowed_resolutions: ['accepted', 'dismissed'],
  ...overrides,
});

describe('ConflictInbox', () => {
  const mockedUseConflicts = vi.mocked(useConflicts);
  const mockedUseConflictDetail = vi.mocked(useConflictDetail);
  const mockedUseResolveConflict = vi.mocked(useResolveConflict);
  const mockedUseSyncTrigger = vi.mocked(useSyncTrigger);

  const renderInbox = () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    return render(
      <QueryClientProvider client={client}>
        <ConflictInbox />
      </QueryClientProvider>,
    );
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseConflicts.mockReturnValue(
      createMockQuery<ConflictListResponse>({
        data: {
          items: [buildConflict()],
          total: 1,
          limit: 20,
          offset: 0,
        },
      }),
    );
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        status: 'pending',
      }),
    );
    mockedUseResolveConflict.mockReturnValue(
      createMockMutation<ResolveConflictResponse, Error, { id: number; request: { resolution_status: 'accepted' | 'dismissed' } }>({
        mutateAsync: vi.fn().mockResolvedValue({ conflict: null }),
      }),
    );
    mockedUseSyncTrigger.mockReturnValue(
      createMockMutation<SyncTriggerResponse>({
        mutate: vi.fn(),
      }),
    );
  });

  it('renders loading state', () => {
    mockedUseConflicts.mockReturnValue(createMockQuery<ConflictListResponse>({ status: 'pending' }));

    renderInbox();

    expect(screen.getByText('Loading conflicts…')).toBeInTheDocument();
  });

  it('renders error state', () => {
    mockedUseConflicts.mockReturnValue(
      createMockQuery<ConflictListResponse>({
        status: 'error',
        isError: true,
        error: new Error('Boom'),
      }),
    );

    renderInbox();

    expect(screen.getByText('Unable to load conflicts.')).toBeInTheDocument();
  });

  it('renders empty state', () => {
    mockedUseConflicts.mockReturnValue(
      createMockQuery<ConflictListResponse>({
        data: { items: [], total: 0, limit: 20, offset: 0 },
      }),
    );

    renderInbox();

    expect(screen.getByText('No open conflicts.')).toBeInTheDocument();
    expect(screen.getByText('Showing 0-0 of 0 open conflicts.')).toBeInTheDocument();
  });

  it('renders conflicts with entity metadata and pagination summary', () => {
    mockedUseConflicts.mockReturnValue(
      createMockQuery<ConflictListResponse>({
        data: {
          items: [
            buildConflict(),
            buildConflict({
              id: 10,
              entity_key: 'cluster-2',
              created_at: '2026-03-11T11:00:00Z',
            }),
          ],
          total: 24,
          limit: 20,
          offset: 0,
        },
      }),
    );

    renderInbox();

    expect(screen.getByText('Showing 1-2 of 24 open conflicts.')).toBeInTheDocument();
    expect(screen.getByText('cluster-1 (Local)')).toBeInTheDocument();
    expect(screen.getAllByText('Type: cluster')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
  });

  it('renders conflict detail comparison and resolution actions from allowed_resolutions', () => {
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        data: {
          conflict: buildConflict(),
        },
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));

    expect(screen.getByText('Conflict Detail')).toBeInTheDocument();
    expect(screen.getByText('Differing fields')).toBeInTheDocument();
    expect(screen.getByText('Accept machine preview')).toBeInTheDocument();
    expect(screen.getByText('Accepting the machine version resets the cluster to backend state and clears local curation guards.')).toBeInTheDocument();
    expect(screen.getByText('confidence')).toBeInTheDocument();
    expect(screen.getByText('Machine: 0.91')).toBeInTheDocument();
    expect(screen.getByText('Local: 0.63')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept machine version' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep local version' })).toBeInTheDocument();
    expect(screen.getByText(/"label": "Remote"/)).toBeInTheDocument();
    expect(screen.getByText(/"label": "Local"/)).toBeInTheDocument();
    expect(screen.getByText(/"curation_state": "uncurated"/)).toBeInTheDocument();
    expect(screen.getByText(/"is_user_confirmed": false/)).toBeInTheDocument();
    expect(screen.getByText(/"person_id": null/)).toBeInTheDocument();
    expect(screen.queryByText(/"label": null/)).toBeInTheDocument();
  });

  it('shows cluster delete acceptance warning with affected member count when available', () => {
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        data: {
          conflict: buildConflict({
            outbox_id: 0,
            conflict_code: 'curated_cluster_deleted',
            machine_payload: { member_count: 3 },
            local_payload: { member_ids: ['a', 'b', 'c'] },
          }),
        },
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));
    fireEvent.click(screen.getByRole('button', { name: 'Accept machine version' }));

    expect(
      screen.getByText(
        'Accepting the machine version deletes the curated cluster and 3 attached member rows still linked to it.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Accepting the machine version removes this cluster from the local projection.')).toBeInTheDocument();
  });

  it('shows member delete preview without a synthesized payload', () => {
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        data: {
          conflict: buildConflict({
            outbox_id: 0,
            entity_type: 'member',
            entity_key: 'member-1',
            conflict_code: 'curated_member_deleted',
            machine_payload: { identity_uuid: 'member-1' },
            local_payload: { identity_uuid: 'member-1', cluster_uuid: 'cluster-1' },
          }),
        },
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));

    expect(screen.getByText('Accepting the machine version removes this member from the local projection.')).toBeInTheDocument();
    expect(screen.queryByText(/"is_curated": false/)).not.toBeInTheDocument();
  });

  it('shows reassignment preview payload with cleared curation', () => {
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        data: {
          conflict: buildConflict({
            outbox_id: 0,
            entity_type: 'member',
            entity_key: 'member-2',
            conflict_code: 'member_cluster_reassignment',
            machine_payload: { identity_uuid: 'member-2', cluster_uuid: 'cluster-remote' },
            local_payload: { identity_uuid: 'member-2', cluster_uuid: 'cluster-local', is_curated: true },
          }),
        },
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));

    expect(
      screen.getByText('Accepting the machine version reassigns the member to the machine cluster and clears curation.'),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/"cluster_uuid": "cluster-remote"/)).toHaveLength(2);
    expect(screen.getByText(/"is_curated": false/)).toBeInTheDocument();
  });

  it('shows revert-merge outbox preview for accepted compound topology conflicts', () => {
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        data: {
          conflict: buildConflict({
            entity_type: 'cluster',
            entity_key: 'cluster-target',
            outbox_id: 91,
            machine_payload: { cluster_uuid: 'cluster-target' },
            local_payload: {
              target_cluster_id: 'cluster-target',
              desired_source_cluster_id: 'cluster-restored',
              moved_identity_ids: ['identity-1', 'identity-2'],
            },
          }),
        },
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));
    fireEvent.click(screen.getByRole('button', { name: 'Accept machine version' }));

    expect(
      screen.getByText(
        'Accepting the machine version removes the temporary restored cluster and moves the listed members back into the machine target cluster.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/"removed_cluster_id": "cluster-restored"/)).toBeInTheDocument();
    expect(
      screen.getByText(
        'Accepting the machine version removes the temporary restored cluster, reassigns the listed members back to the machine target cluster, and discards the local revert operation.',
      ),
    ).toBeInTheDocument();
  });

  it('shows member outbox preview for accepted compound topology reassignment conflicts', () => {
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        data: {
          conflict: buildConflict({
            entity_type: 'member',
            entity_key: 'identity-7',
            outbox_id: 92,
            machine_payload: { cluster_uuid: 'cluster-machine' },
            local_payload: { identity_id: 'identity-7' },
          }),
        },
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));
    fireEvent.click(screen.getByRole('button', { name: 'Accept machine version' }));

    expect(
      screen.getByText(
        'Accepting the machine version restores the member to the backend-selected cluster and clears local curation on that assignment.',
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/"cluster_uuid": "cluster-machine"/)).toHaveLength(2);
    expect(screen.getByText(/"is_curated": false/)).toBeInTheDocument();
    expect(
      screen.getByText(
        'Accepting the machine version restores the member to the backend-selected cluster and discards the local topology operation.',
      ),
    ).toBeInTheDocument();
  });

  it('shows cluster-created preview for accepted compound topology conflicts', () => {
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        data: {
          conflict: buildConflict({
            entity_type: 'member',
            entity_key: 'identity-9',
            outbox_id: 93,
            machine_payload: { cluster_uuid: 'cluster-machine' },
            local_payload: { identity_id: 'identity-9', desired_cluster_id: 'cluster-local-new' },
          }),
        },
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));
    fireEvent.click(screen.getByRole('button', { name: 'Accept machine version' }));

    expect(
      screen.getByText(
        'Accepting the machine version restores the member to the backend-selected cluster and removes the locally created cluster.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/"removed_cluster_id": "cluster-local-new"/)).toBeInTheDocument();
    expect(
      screen.getByText(
        'Accepting the machine version moves this identity back to the backend-selected cluster, removes the locally created cluster, and discards the local topology operation.',
      ),
    ).toBeInTheDocument();
  });

  it('shows keep-local-only explanation for unsupported outbox conflicts', () => {
    const personConflict = buildConflict({
      id: 13,
      entity_type: 'person',
      entity_key: 'person-1',
      outbox_id: 88,
      machine_payload: { name: 'Remote' },
      local_payload: { name: 'Local' },
      allowed_resolutions: ['dismissed'],
    });

    mockedUseConflicts.mockReturnValue(
      createMockQuery<ConflictListResponse>({
        data: {
          items: [personConflict],
          total: 1,
          limit: 20,
          offset: 0,
        },
      }),
    );
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        data: {
          conflict: personConflict,
        },
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));

    expect(
      screen.getByText(
        'This person-side conflict only supports keeping the local version in Phase 4. Re-enqueue and retry remain available for the underlying outbox operation.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept machine version' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep local version' })).toBeInTheDocument();
  });

  it('supports batch accept for selected conflicts that all allow machine acceptance', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ conflict: null });
    mockedUseConflicts.mockReturnValue(
      createMockQuery<ConflictListResponse>({
        data: {
          items: [
            buildConflict({ id: 9 }),
            buildConflict({ id: 10, entity_key: 'cluster-2', outbox_id: 0, conflict_code: 'curated_cluster_deleted' }),
          ],
          total: 2,
          limit: 20,
          offset: 0,
        },
      }),
    );
    mockedUseResolveConflict.mockReturnValue(
      createMockMutation<ResolveConflictResponse, Error, { id: number; request: { resolution_status: 'accepted' | 'dismissed' } }>({
        mutateAsync,
      }),
    );

    renderInbox();
    fireEvent.click(screen.getAllByRole('checkbox', { name: 'Select conflict' })[0]);
    fireEvent.click(screen.getAllByRole('checkbox', { name: 'Select conflict' })[1]);

    expect(screen.getByText('2 selected')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Accept machine for selected' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm accept selected' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenNthCalledWith(1, {
        id: 9,
        request: { resolution_status: 'accepted' },
      });
      expect(mutateAsync).toHaveBeenNthCalledWith(2, {
        id: 10,
        request: { resolution_status: 'accepted' },
      });
    });

    expect(screen.getByText('Conflict resolved. Trigger sync now to converge local state with the backend.')).toBeInTheDocument();
  });

  it('limits batch actions to the shared allowed resolutions across the current selection', () => {
    mockedUseConflicts.mockReturnValue(
      createMockQuery<ConflictListResponse>({
        data: {
          items: [
            buildConflict({ id: 9 }),
            buildConflict({
              id: 11,
              entity_type: 'person',
              entity_key: 'person-11',
              allowed_resolutions: ['dismissed'],
              machine_payload: { name: 'Remote' },
              local_payload: { name: 'Local' },
            }),
          ],
          total: 2,
          limit: 20,
          offset: 0,
        },
      }),
    );

    renderInbox();
    fireEvent.click(screen.getAllByRole('checkbox', { name: 'Select conflict' })[0]);
    fireEvent.click(screen.getAllByRole('checkbox', { name: 'Select conflict' })[1]);

    expect(screen.queryByRole('button', { name: 'Accept machine for selected' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep local for selected' })).toBeInTheDocument();
  });

  it('shows detail error state when the selected conflict cannot be loaded', () => {
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        status: 'error',
        isError: true,
        error: new Error('Boom'),
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));

    expect(screen.getByText('Unable to load conflict detail.')).toBeInTheDocument();
  });

  it('shows sync now affordance after successful resolution', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ conflict: null });
    const triggerSync = vi.fn();

    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        data: {
          conflict: buildConflict(),
        },
      }),
    );
    mockedUseResolveConflict.mockReturnValue(
      createMockMutation<ResolveConflictResponse, Error, { id: number; request: { resolution_status: 'accepted' | 'dismissed' } }>({
        mutateAsync,
      }),
    );
    mockedUseSyncTrigger.mockReturnValue(
      createMockMutation<SyncTriggerResponse>({
        mutate: triggerSync,
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));
    fireEvent.click(screen.getByRole('button', { name: 'Accept machine version' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        id: 9,
        request: { resolution_status: 'accepted' },
      });
    });

    expect(screen.getByText('Conflict resolved. Trigger sync now to converge local state with the backend.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(triggerSync).toHaveBeenCalledTimes(1);
  });
});
