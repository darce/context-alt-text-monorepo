/**
 * W3-C-12 / NAV-01: composed workbench-control chrome has exactly one
 * `.button-primary`. Residual naming CTAs (label-panel Done, lightbox Save name,
 * review-card name-commit) must not compete with the control-pane primary.
 */
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../api/queryKeys';
import {
  listRecognitionClusters,
  mergeCluster,
  revertMergeCluster,
  updateClusterLabel,
  fetchClusterMembers,
} from '../../../api/recognition';
import { commitClusterToRosterEntry, listRosterEntries } from '../../../api/rosterApi';
import { useRosterEntries } from '../../../hooks/useRosterHooks';
import { createMockQuery } from '../../../test-utils/mockHooks';
import { ClusterLabelingPanel } from '../identity-clusters/ClusterLabelingPanel';
import { LightboxNameFace } from '../identity-clusters/LightboxNameFace';
import { PersonCommitControl } from '../identity-clusters/PersonCommitControl';
import { SuggestionCard } from '../identity-clusters/SuggestionCards';
import type { ClusterListResponse, ClusterMembersResponse } from '../../../api/recognition';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template
      .replace(/%(\d+)\$[sd]/g, (_match, group: string) => String(args[Number(group) - 1] ?? ''))
      .replace(/%[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

vi.mock('../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../api/recognition')>(
    '../../../api/recognition',
  );
  return {
    ...actual,
    fetchClusterMembers: vi.fn(),
    listRecognitionClusters: vi.fn(),
    updateClusterLabel: vi.fn(),
    mergeCluster: vi.fn(),
    revertMergeCluster: vi.fn(),
  };
});

vi.mock('../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

vi.mock('../../../api/rosterApi', async () => {
  const actual = await vi.importActual<typeof import('../../../api/rosterApi')>(
    '../../../api/rosterApi',
  );
  return {
    ...actual,
    commitClusterToRosterEntry: vi.fn(),
    listRosterEntries: vi.fn(),
  };
});

vi.mock('@radix-ui/react-avatar', async () => {
  const ReactMod = await import('react');
  return {
    Root: ReactMod.forwardRef(function MockRoot(
      { children, ...props }: Record<string, unknown>,
      ref: unknown,
    ) {
      return ReactMod.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: ReactMod.forwardRef(function MockImage(props: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement('img', {
        ...(props as React.ImgHTMLAttributes<HTMLImageElement>),
        ref,
      } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: ReactMod.forwardRef(function MockFallback() {
      return null;
    }),
  };
});

const duplicateClusterMatch = {
  id: 'target-cluster-id',
  label: 'Slate Willow',
  is_auto_label: false,
  identity_count: 10,
  member_ids: [],
  representative_identity: {
    media_id: 1,
    bbox: { x: 0, y: 0, width: 1, height: 1 },
  },
  sample_identities: [],
};

const makeClusterListResponse = (
  clusters: ClusterListResponse['clusters'] = [duplicateClusterMatch],
): ClusterListResponse => ({
  clusters,
  limit: 10,
  total: clusters.length,
  truncated: false,
});

const makeClusterMembersResponse = (): ClusterMembersResponse => ({
  members: [],
  limit: 500,
  total: 0,
  truncated: false,
});

const primaryButtons = (container: HTMLElement): HTMLElement[] =>
  Array.from(container.querySelectorAll('.button-primary'));

describe('W3-C-12 composed workbench-control one primary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchClusterMembers).mockResolvedValue(makeClusterMembersResponse());
    vi.mocked(updateClusterLabel).mockResolvedValue(undefined);
    vi.mocked(commitClusterToRosterEntry).mockResolvedValue({
      cluster_id: 'source-cluster-id',
      person_id: 1,
      person_uuid: 'p1',
      person_name: 'Alex Carter',
      updated_at: '',
    });
    vi.mocked(mergeCluster).mockResolvedValue({
      source_id: 'retired-source-id',
      source_label: null,
      target_id: 'target-cluster-id',
      target_label: 'Slate Willow',
      identities_moved: 5,
      moved_identity_ids: ['id-1'],
      target_identity_count: 10,
    });
    vi.mocked(revertMergeCluster).mockResolvedValue({
      restored_cluster_id: 'panel-cluster-id',
      restored_label: null,
      restored_identity_count: 5,
      target_cluster_id: 'target-cluster-id',
      target_identity_count: 5,
    });
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse());
    vi.mocked(listRosterEntries).mockResolvedValue([]);
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
  });

  it('counts exactly one .button-primary across labeling Done, lightbox name, and review-card commit', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    queryClient.setQueryData(queryKeys.roster.entries(), []);

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <div data-testid="workbench-control">
          <SuggestionCard
            suggestion={{
              suggestionId: 'sugg-1',
              identityId: 'identity-1',
              clusterId: 'cluster-1',
              label: 'Alex',
              similarity: 0.9,
              identityCount: 3,
            }}
            onAccept={vi.fn()}
            onReject={vi.fn()}
            isPending={false}
            lowConfidenceThreshold={0.5}
            queuePosition={1}
            queueTotal={1}
          />
          <ClusterLabelingPanel
            clusterId="panel-cluster-id"
            onClose={() => undefined}
            onLabel={vi.fn()}
          />
          <LightboxNameFace
            clusterId="cluster-1"
            phase="idle"
            errorMessage={null}
            onCommit={vi.fn()}
            onCancel={vi.fn()}
            onRetry={vi.fn()}
          />
          <PersonCommitControl
            clusterId="cluster-1"
            isPrimary
            accentPrimary
            phase="idle"
            errorMessage={null}
            onCommit={vi.fn()}
            onRetry={vi.fn()}
          />
        </div>
      </QueryClientProvider>,
    );

    const user = userEvent.setup();
    const nameInput = await screen.findByRole('combobox', { name: 'Name' });
    await user.clear(nameInput);
    await user.type(nameInput, 'Slate Willow');
    await user.click(await screen.findByRole('option', { name: /confirm match/i }));
    await user.click(screen.getByRole('button', { name: 'Merge into group "Slate Willow"' }));
    await screen.findByRole('button', { name: 'Done' });

    await waitFor(() => {
      expect(primaryButtons(container)).toHaveLength(1);
    });

    expect(screen.getByRole('button', { name: 'Yes' })).toHaveClass('button-primary');
    expect(screen.getByRole('button', { name: 'Done' })).toHaveClass('button-secondary');
    expect(screen.getByRole('button', { name: 'Done' })).not.toHaveClass('button-primary');

    const lightboxSave = within(screen.getByTestId('acx-lightbox-name-face')).getByRole('button', {
      name: 'Save name',
    });
    expect(lightboxSave).toHaveClass('button-secondary');
    expect(lightboxSave).not.toHaveClass('button-primary');

    const lightboxRoot = screen.getByTestId('acx-lightbox-name-face');
    const reviewSaves = screen
      .getAllByRole('button', { name: 'Save name' })
      .filter((button) => !lightboxRoot.contains(button));
    expect(reviewSaves).toHaveLength(1);
    expect(reviewSaves[0]).toHaveClass('button-secondary');
    expect(reviewSaves[0]).not.toHaveClass('acx-accent-primary-action');
  });
});
