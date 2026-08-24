import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
      createMockMutation<
        ResolveConflictResponse,
        Error,
        { id: number; request: { resolution_status: 'accepted' | 'dismissed' | 'accept_backend' | 'merge' | 'restore_local' } }
      >({
        mutateAsync: vi.fn().mockResolvedValue({ conflict: null }),
      }),
    );
    mockedUseSyncTrigger.mockReturnValue(
      createMockMutation<SyncTriggerResponse>({
        mutate: vi.fn(),
      }),
    );
  });

  it('keeps visible loading copy alongside the screen-reader status', () => {
    mockedUseConflicts.mockReturnValue(createMockQuery<ConflictListResponse>({ status: 'pending' }));

    renderInbox();

    const visibleLoading = screen
      .getAllByText('Loading conflicts…')
      .find((node) => !node.classList.contains('screen-reader-text'));
    expect(visibleLoading).toBeVisible();
  });

  it('mounts the empty inbox status before announcing loading on the same node', () => {
    vi.useFakeTimers();
    try {
      mockedUseConflicts.mockReturnValue(createMockQuery<ConflictListResponse>({ status: 'pending' }));

      renderInbox();

      const status = screen.getByTestId('acx-conflict-inbox-status');
      expect(status).toBeEmptyDOMElement();
      expect(screen.getByRole('region', { name: 'Conflict inbox' })).toHaveAttribute('aria-busy', 'true');

      act(() => {
        vi.runOnlyPendingTimers();
      });

      expect(screen.getByTestId('acx-conflict-inbox-status')).toBe(status);
      expect(status).toHaveTextContent('Loading conflicts…');
    } finally {
      vi.useRealTimers();
    }
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

  it('announces inbox load failure assertively with a non-colour warning icon', () => {
    mockedUseConflicts.mockReturnValue(
      createMockQuery<ConflictListResponse>({
        status: 'error',
        isError: true,
        error: new Error('Boom'),
      }),
    );

    renderInbox();

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Unable to load conflicts.');
    expect(alert.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it('always renders an initially empty polite resolution status region', () => {
    renderInbox();

    const status = screen.getByTestId('acx-conflict-inbox-status');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toBeEmptyDOMElement();
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
    expect(screen.getAllByText('Type: Version conflict')).toHaveLength(2);
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
    expect(screen.getByText('Accept backend preview')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Accepting the machine version resets the cluster to backend state and clears local curation guards.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('confidence')).toBeInTheDocument();
    expect(screen.getByText('Machine: 0.91')).toBeInTheDocument();
    expect(screen.getByText('Local: 0.63')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept backend version' })).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: 'Accept backend version' }));

    expect(
      screen.getByText(
        'Accepting the machine version deletes the curated cluster and 3 attached member rows still linked to it.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Accepting the machine version removes this cluster from the local projection.'),
    ).toBeInTheDocument();
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

    expect(
      screen.getByText('Accepting the machine version removes this member from the local projection.'),
    ).toBeInTheDocument();
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
      screen.getByText(
        'Accepting the machine version reassigns the member to the machine cluster and clears curation.',
      ),
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
    fireEvent.click(screen.getByRole('button', { name: 'Accept backend version' }));

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
    fireEvent.click(screen.getByRole('button', { name: 'Accept backend version' }));

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
    fireEvent.click(screen.getByRole('button', { name: 'Accept backend version' }));

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
    expect(screen.queryByRole('button', { name: 'Accept backend version' })).not.toBeInTheDocument();
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
      createMockMutation<
        ResolveConflictResponse,
        Error,
        { id: number; request: { resolution_status: 'accepted' | 'dismissed' | 'accept_backend' | 'merge' | 'restore_local' } }
      >({
        mutateAsync,
      }),
    );

    renderInbox();
    fireEvent.click(screen.getAllByRole('checkbox', { name: 'Select conflict' })[0]);
    fireEvent.click(screen.getAllByRole('checkbox', { name: 'Select conflict' })[1]);

    expect(screen.getByText('2 selected')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Accept backend for selected' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm accept backend selected' }));

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

    expect(screen.getByTestId('acx-conflict-inbox-status')).toHaveTextContent(
      'Conflict resolved. Trigger sync now to converge local state with the backend.',
    );
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

    expect(screen.queryByRole('button', { name: 'Accept backend for selected' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep local for selected' })).toBeInTheDocument();
  });

  it('shows person name conflict labeling and merge action', () => {
    const personConflict = buildConflict({
      entity_type: 'person',
      entity_key: 'person-22',
      conflict_code: 'person_name_conflict',
      machine_payload: { name: 'Backend Name' },
      local_payload: { name: 'Local Name' },
      allowed_resolutions: ['accept_backend', 'dismissed', 'merge'],
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

    expect(screen.getByText('Person name conflict')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Merge versions' })).toBeInTheDocument();
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

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Unable to load conflict detail.');
    expect(alert.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it('keeps one initially empty detail status node and fills it after selection', () => {
    renderInbox();

    const status = screen.getByTestId('acx-conflict-detail-status');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toBeEmptyDOMElement();

    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));

    expect(screen.getByTestId('acx-conflict-detail-status')).toBe(status);
    expect(status).toHaveTextContent('Loading conflict detail…');
  });

  it('announces single-conflict confirmation arming with conflict scope', () => {
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({ data: { conflict: buildConflict() } }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));
    fireEvent.click(screen.getByRole('button', { name: 'Accept backend version' }));

    expect(screen.getByTestId('acx-conflict-inbox-status')).toHaveTextContent(
      'Accept backend version armed for conflict cluster-1. Activate Confirm to continue.',
    );
  });

  it('announces batch confirmation arming with the selected scope', () => {
    mockedUseConflicts.mockReturnValue(
      createMockQuery<ConflictListResponse>({
        data: {
          items: [buildConflict(), buildConflict({ id: 10, entity_key: 'cluster-2' })],
          total: 2,
          limit: 20,
          offset: 0,
        },
      }),
    );

    renderInbox();
    for (const checkbox of screen.getAllByRole('checkbox', { name: 'Select conflict' })) {
      fireEvent.click(checkbox);
    }
    fireEvent.click(screen.getByRole('button', { name: 'Accept backend for selected' }));

    expect(screen.getByTestId('acx-conflict-inbox-status')).toHaveTextContent(
      'Accept backend resolution armed for 2 selected conflicts. Activate Confirm accept backend selected to continue.',
    );
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
      createMockMutation<
        ResolveConflictResponse,
        Error,
        { id: number; request: { resolution_status: 'accepted' | 'dismissed' | 'accept_backend' | 'merge' | 'restore_local' } }
      >({
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
    fireEvent.click(screen.getByRole('button', { name: 'Accept backend version' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        id: 9,
        request: { resolution_status: 'accepted' },
      });
    });

    expect(
      screen.getByRole('status'),
    ).toHaveTextContent('Conflict resolved. Trigger sync now to converge local state with the backend.');
    fireEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(triggerSync).toHaveBeenCalledTimes(1);
  });

  it('announces resolution failures assertively with a non-colour warning icon', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('boom'));
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({ data: { conflict: buildConflict() } }),
    );
    mockedUseResolveConflict.mockReturnValue(
      createMockMutation<
        ResolveConflictResponse,
        Error,
        { id: number; request: { resolution_status: 'accepted' | 'dismissed' | 'accept_backend' | 'merge' | 'restore_local' } }
      >({ mutateAsync }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));
    fireEvent.click(screen.getByRole('button', { name: 'Accept backend version' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Unable to resolve this conflict. Please try again.');
    expect(alert.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it('marks resolution pending and gives disabled resolution controls a visible reason', () => {
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({ data: { conflict: buildConflict() } }),
    );
    mockedUseResolveConflict.mockReturnValue(
      createMockMutation<
        ResolveConflictResponse,
        Error,
        { id: number; request: { resolution_status: 'accepted' | 'dismissed' | 'accept_backend' | 'merge' | 'restore_local' } }
      >({ isPending: true, mutateAsync: vi.fn() }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));

    const button = screen.getByRole('button', { name: 'Accept backend version' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    const reasonId = button.getAttribute('aria-describedby');
    expect(reasonId).toBeTruthy();
    expect(document.getElementById(reasonId!)).toHaveTextContent('Conflict resolution in progress. Please wait.');
    expect(document.getElementById(reasonId!)).not.toHaveClass('screen-reader-text');
    expect(screen.getByRole('region', { name: 'Conflict inbox' })).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByTestId('acx-conflict-inbox-status')).toHaveTextContent('Resolving conflict…');
  });

  it('describes the disabled sync control and announces sync progress', () => {
    mockedUseSyncTrigger.mockReturnValue(
      createMockMutation<SyncTriggerResponse>({ isPending: true, mutate: vi.fn() }),
    );

    renderInbox();

    const button = screen.getByRole('button', { name: 'Sync now' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    const reasonId = button.getAttribute('aria-describedby');
    expect(reasonId).toBeTruthy();
    expect(document.getElementById(reasonId!)).toHaveTextContent('Sync in progress. Please wait.');
    expect(screen.getByRole('region', { name: 'Conflict inbox' })).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByTestId('acx-conflict-inbox-status')).toHaveTextContent('Syncing resolved conflicts…');
  });

  it('renders the backend-regression aggregate with both resolution actions', async () => {
    const aggregate = buildConflict({
      id: 61,
      entity_type: 'roster',
      entity_key: 'backend_roster',
      outbox_id: 0,
      conflict_code: 'backend_roster_regressed',
      machine_payload: {
        backend_version: 41,
        counts: { curated_cluster_deleted: 25, curated_member_deleted: 2, member_cluster_reassignment: 1 },
        entities: { curated_cluster_deleted: ['cluster-a'], curated_member_deleted: [], member_cluster_reassignment: [] },
        entity_set_truncated: false,
      },
      local_payload: { curated_clusters: 25, curated_members: 3 },
      allowed_resolutions: ['restore_local', 'accept_backend', 'dismissed'],
    });
    const mutateAsync = vi.fn().mockResolvedValue({ conflict: null });

    mockedUseConflicts.mockReturnValue(
      createMockQuery<ConflictListResponse>({
        data: { items: [aggregate], total: 1, limit: 20, offset: 0 },
      }),
    );
    mockedUseConflictDetail.mockReturnValue(
      createMockQuery<ConflictDetailResponse>({
        data: { conflict: aggregate },
      }),
    );
    mockedUseResolveConflict.mockReturnValue(
      createMockMutation<
        ResolveConflictResponse,
        Error,
        { id: number; request: { resolution_status: 'accepted' | 'dismissed' | 'accept_backend' | 'merge' | 'restore_local' } }
      >({
        mutateAsync,
      }),
    );

    renderInbox();
    fireEvent.click(screen.getByRole('button', { name: 'Review conflict' }));

    expect(screen.getAllByText('Backend roster appears rolled back').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Restore local curation' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept backend version' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Restore local curation' }));
    expect(
      screen.getByText(
        'Restore local curation by re-sending every affected curated cluster and member to the backend? Local data is preserved.',
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        id: 61,
        request: { resolution_status: 'restore_local' },
      });
    });
  });
});
