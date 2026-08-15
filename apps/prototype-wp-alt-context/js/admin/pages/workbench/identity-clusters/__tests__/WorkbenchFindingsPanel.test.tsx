import React from 'react';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DATA_SOURCE } from '../../../../api/recognition/types';
import {
  buildWorkbenchFindings,
  NEXT_ACTION_KIND,
  NONE_REASON,
  useWorkbenchFindings,
  type WorkbenchFindingPreview,
  type WorkbenchFindingsViewModel,
} from '../useWorkbenchFindings';
import { FINDINGS_PREVIEW_SIZE_PX, WorkbenchFindingsPanel } from '../WorkbenchFindingsPanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

const { faceThumbnailSpy, avatarSpy, refetchAssignment, refetchMerge, refetchName, refetchTopUnlabeled } =
  vi.hoisted(() => {
    const refetchOk = (): Promise<{ isError: boolean }> => Promise.resolve({ isError: false });
    return {
      faceThumbnailSpy: vi.fn(),
      avatarSpy: vi.fn(),
      refetchAssignment: vi.fn(refetchOk),
      refetchMerge: vi.fn(refetchOk),
      refetchName: vi.fn(refetchOk),
      refetchTopUnlabeled: vi.fn(refetchOk),
    };
  });

// Radix Avatar's Image uses Image.onload which never fires in JSDOM.
vi.mock('@radix-ui/react-avatar', async () => {
  const ReactModule = await import('react');
  return {
    Root: ReactModule.forwardRef(function MockRoot({ children, ...props }: Record<string, unknown>, ref: unknown) {
      return ReactModule.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: ReactModule.forwardRef(function MockImage(props: Record<string, unknown>, ref: unknown) {
      return ReactModule.createElement('img', { ...props, ref } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: ReactModule.forwardRef(function MockFallback() {
      return null;
    }),
  };
});

vi.mock('../../../../../components/ui/FaceThumbnail', async () => {
  const ReactModule = await import('react');
  const actual =
    await vi.importActual<typeof import('../../../../../components/ui/FaceThumbnail')>(
      '../../../../../components/ui/FaceThumbnail',
    );
  return {
    FaceThumbnail: ReactModule.forwardRef(function MockFaceThumbnail(
      props: React.ComponentProps<typeof actual.FaceThumbnail>,
      ref: React.Ref<HTMLDivElement>,
    ) {
      faceThumbnailSpy(props);
      return ReactModule.createElement(actual.FaceThumbnail, { ...props, ref });
    }),
  };
});

vi.mock('../../../../../components/ui/avatar', async () => {
  const ReactModule = await import('react');
  const actual = await vi.importActual<typeof import('../../../../../components/ui/avatar')>(
    '../../../../../components/ui/avatar',
  );
  return {
    Avatar: (props: React.ComponentProps<typeof actual.Avatar>) => {
      avatarSpy(props);
      return ReactModule.createElement(actual.Avatar, props);
    },
  };
});

vi.mock('../useWorkbenchFindings', async () => {
  const actual = await vi.importActual<typeof import('../useWorkbenchFindings')>('../useWorkbenchFindings');
  return {
    ...actual,
    useWorkbenchFindings: vi.fn(),
  };
});

vi.mock('../useSuggestionReviewQueries', () => ({
  useSuggestionReviewQueries: vi.fn(() => ({
    assignmentQuery: { refetch: refetchAssignment },
    mergeQuery: { refetch: refetchMerge },
    nameQuery: { refetch: refetchName },
    topUnlabeledQuery: { refetch: refetchTopUnlabeled },
  })),
}));

const preview = (overrides: Partial<WorkbenchFindingPreview> & Pick<WorkbenchFindingPreview, 'key'>): WorkbenchFindingPreview => ({
  thumbUrl: null,
  mediaUrl: null,
  label: null,
  labelIsSuggested: false,
  bbox: null,
  ...overrides,
});

const makeViewModel = (overrides: Partial<WorkbenchFindingsViewModel> = {}): WorkbenchFindingsViewModel => ({
  counts: { assignments: 0, merges: 0, names: 0, unlabeledClusters: 0, total: 0 },
  previews: [],
  zeroEvidenceClusterCount: 0,
  topUnlabeledTruncated: false,
  hasFindings: false,
  isLoading: false,
  isError: false,
  isTopUnlabeledError: false,
  isAssignmentError: false,
  isUnavailable: false,
  isReadOnly: false,
  queueSettled: true,
  nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.EMPTY },
  queue: [],
  ...overrides,
});

describe('WorkbenchFindingsPanel', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    refetchAssignment.mockImplementation(() => Promise.resolve({ isError: false }));
    refetchMerge.mockImplementation(() => Promise.resolve({ isError: false }));
    refetchName.mockImplementation(() => Promise.resolve({ isError: false }));
    refetchTopUnlabeled.mockImplementation(() => Promise.resolve({ isError: false }));
  });

  it('renders counts, previews, and an enabled primary action for populated findings', async () => {
    const onTargetFindings = vi.fn();
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 2, merges: 1, names: 3, unlabeledClusters: 4, total: 10 },
        previews: [
          preview({
            key: 'assignment-s1',
            thumbUrl: 'http://example.test/face-1.jpg',
            label: 'Grace Hopper',
          }),
          preview({
            key: 'cluster-c1',
            thumbUrl: 'http://example.test/face-2.jpg',
          }),
        ],
        hasFindings: true,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c-high',
          label: 'Grace Hopper',
        },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={onTargetFindings} />);

    expect(screen.getByText('Recognition findings')).toBeInTheDocument();
    expect(screen.getByText('2 to review')).toBeInTheDocument();
    expect(screen.getByText('1 merge candidate')).toBeInTheDocument();
    expect(screen.getByText('3 suggested names')).toBeInTheDocument();
    expect(screen.getByText('4 unlabeled groups')).toBeInTheDocument();
    // L2V-04: pin real preview imgs (alt + src), not placeholder count alone.
    const previewImgs = screen.getAllByRole('img');
    expect(previewImgs).toHaveLength(2);
    expect(previewImgs[0]).toHaveAttribute('src', 'http://example.test/face-1.jpg');
    expect(previewImgs[0]).toHaveAttribute('alt', 'Grace Hopper');
    expect(previewImgs[0]).toHaveClass('acx-avatar__image');
    expect(previewImgs[1]).toHaveAttribute('src', 'http://example.test/face-2.jpg');
    expect(previewImgs[1]).toHaveAttribute('alt', 'Reference image');
    expect(previewImgs[1]).toHaveClass('acx-avatar__image');
    expect(avatarSpy).toHaveBeenCalled();
    expect(faceThumbnailSpy).not.toHaveBeenCalled();

    const primary = screen.getByRole('button', { name: /Review next/ });
    expect(primary).toBeEnabled();
    await userEvent.click(primary);
    expect(onTargetFindings).toHaveBeenCalledTimes(1);
  });

  it('routes cluster next-actions through onTargetFindings (queue owns cluster cards)', async () => {
    const onTargetFindings = vi.fn();
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 0, merges: 0, names: 0, unlabeledClusters: 1, total: 1 },
        hasFindings: true,
        nextAction: { kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'cluster-9' },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={onTargetFindings} />);

    await userEvent.click(screen.getByRole('button', { name: /Review next/ }));
    expect(onTargetFindings).toHaveBeenCalledTimes(1);
  });

  it('disables the primary action and explains population in the empty state', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(makeViewModel());

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(
      screen.getByText('No findings yet. Run a scan and new findings will appear here automatically.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Review next/ })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'View all findings' })).not.toBeInTheDocument();
  });

  // REV2-01 / TEST-15: an assignment-only outage keeps hasAnyData true, so the
  // hook's isError stays false and the panel used to render the all-clear over a
  // dead primary queue. Reverting the isAssignmentError branch in
  // WorkbenchFindingsPanel turns this red on the queryByText line.
  it('REV2-01: assignment-only outage shows an outage notice, not "No findings yet"', async () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({ isAssignmentError: true, isError: false, hasFindings: false }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(
      screen.queryByText('No findings yet. Run a scan and new findings will appear here automatically.'),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText('Face assignments unavailable — this is not an empty backlog.'),
    ).toBeInTheDocument();

    // The outage must be recoverable, and the control must sit outside the
    // live region that announces it (REV2-03 treatment).
    const retry = screen.getByRole('button', { name: 'Retry' });
    expect(retry.closest('[role="status"]')).toBeNull();
    await userEvent.click(retry);
    await waitFor(() => {
      expect(refetchAssignment).toHaveBeenCalledTimes(1);
      expect(refetchName).toHaveBeenCalledTimes(1);
    });
  });

  it('REV2-01: a genuine empty backlog still announces the all-clear', () => {
    // Pins the other side of the branch: without this, hiding the empty copy
    // unconditionally would satisfy the outage test above.
    vi.mocked(useWorkbenchFindings).mockReturnValue(makeViewModel({ isAssignmentError: false }));

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(
      screen.getByText('No findings yet. Run a scan and new findings will appear here automatically.'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('Face assignments unavailable — this is not an empty backlog.'),
    ).not.toBeInTheDocument();
  });

  it('disables the primary action when server totals are positive but no queue items loaded', () => {
    // Guards the nextAction-based gate: counts.total > 0 must not enable a no-op button.
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        hasFindings: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.EMPTY },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByRole('button', { name: /Review next/ })).toBeDisabled();
  });

  it('renders an explicit loading state', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isLoading: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.LOADING },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('Checking recognition findings…')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Review next/ })).not.toBeInTheDocument();
  });

  it('L3V-01: keeps #acx-workbench-findings-heading mounted in non-success states', () => {
    // ScanTabContent always aria-labelledby this id; early returns must not drop it.
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isLoading: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.LOADING },
      }),
    );

    const { container, rerender } = render(
      <WorkbenchFindingsPanel onTargetFindings={vi.fn()} />,
    );

    const loadingHeading = container.querySelector('#acx-workbench-findings-heading');
    expect(loadingHeading).toBeTruthy();
    expect(loadingHeading?.tagName).toBe('H3');
    expect(loadingHeading?.textContent).toBe('Recognition findings');

    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );
    rerender(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    expect(container.querySelector('#acx-workbench-findings-heading')).toBeTruthy();

    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isUnavailable: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.UNAVAILABLE },
      }),
    );
    rerender(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    expect(container.querySelector('#acx-workbench-findings-heading')).toBeTruthy();
  });

  it('renders an explicit error state', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('Could not load recognition findings.')).toBeInTheDocument();
  });

  // UI-03: top-unlabeled 500 must not launder into the confident empty state.
  // Fixture mirrors buildWorkbenchFindings: a zero-total top-unlabeled outage
  // is folded into isError, so isError:false here would be unproducible.
  it('UI-03: top-unlabeled error shows error affordance, not "No findings yet"', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        isTopUnlabeledError: true,
        isAssignmentError: false,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(
      screen.queryByText('No findings yet. Run a scan and new findings will appear here automatically.'),
    ).not.toBeInTheDocument();
    expect(screen.getByText('Could not load recognition findings.')).toBeInTheDocument();
  });

  // UI-04: aria-live must announce failure, not the drained/empty copy, when top-unlabeled errored.
  it('UI-04: aria-live announces error (not empty) when top-unlabeled failed', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        isTopUnlabeledError: true,
        isAssignmentError: false,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    const live = screen.getByRole('status');
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(live).toHaveTextContent('Could not load recognition findings.');
    expect(live).not.toHaveTextContent('No findings yet');
  });

  it('UI-04: aria-live announces empty only after a successful load with no findings', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(makeViewModel());

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    const live = screen.getByRole('status');
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(live).toHaveTextContent(
      'No findings yet. Run a scan and new findings will appear here automatically.',
    );
  });

  // UI-06: partial findings + top-unlabeled outage must not report "0 unlabeled groups".
  it('UI-06: unlabeled count is indeterminate when top-unlabeled query errored', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 2, merges: 0, names: 0, unlabeledClusters: 0, total: 2 },
        hasFindings: true,
        isTopUnlabeledError: true,
        isAssignmentError: false,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada',
        },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.queryByText('0 unlabeled groups')).not.toBeInTheDocument();
    expect(screen.queryByText('0 unlabeled group')).not.toBeInTheDocument();
    expect(screen.getByText('Unlabeled groups unavailable')).toBeInTheDocument();
    expect(screen.getByText('2 to review')).toBeInTheDocument();
  });

  it('renders an explicit unavailable state', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isUnavailable: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.UNAVAILABLE },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('Recognition findings are unavailable right now.')).toBeInTheDocument();
  });

  it('keeps findings visible but disables curation in read-only state', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 0, merges: 0, names: 0, unlabeledClusters: 2, total: 2 },
        hasFindings: true,
        isReadOnly: true,
        nextAction: { kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'cluster-2' },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('2 unlabeled groups')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Findings are visible while local sync catches up. Curation stays disabled until projected results are available locally.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Review next/ })).toBeDisabled();
  });

  it('shows a low-emphasis secondary action to view all findings for mixed queues', async () => {
    const onTargetFindings = vi.fn();
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 1, names: 0, unlabeledClusters: 0, total: 2 },
        hasFindings: true,
        nextAction: { kind: NEXT_ACTION_KIND.MERGE, suggestionId: 'm1' },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={onTargetFindings} />);

    const secondary = screen.getByRole('button', { name: 'View all findings' });
    await userEvent.click(secondary);
    expect(onTargetFindings).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  // HAI-01 / HITL-14: mediaUrl + bbox must CSS-crop via FaceThumbnail, not centre-crop via Avatar.
  it('renders a FaceThumbnail crop when a preview carries mediaUrl + bbox', () => {
    const mediaUrl = 'http://example.test/uploads/group-photo.jpg';
    const bbox = { x: 10, y: 20, width: 80, height: 90 };
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        previews: [
          preview({
            key: 'assignment-s1',
            thumbUrl: null,
            mediaUrl,
            label: 'Ada Lovelace',
            bbox,
          }),
        ],
        hasFindings: true,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada Lovelace',
        },
      }),
    );

    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    const image = screen.getByAltText('Ada Lovelace');
    expect(image.tagName).toBe('IMG');
    expect(image).toHaveAttribute('src', mediaUrl);
    expect(image.closest('.acx-face-thumbnail')).toBeInTheDocument();
    expect(container.querySelector('.acx-avatar')).toBeNull();
  });

  // FIX-2: rendered size must be pinned — lowering FINDINGS_PREVIEW_SIZE_PX must go red.
  it('renders FaceThumbnail crop at FINDINGS_PREVIEW_SIZE_PX (72)', () => {
    const mediaUrl = 'http://example.test/uploads/group-photo.jpg';
    const bbox = { x: 10, y: 20, width: 80, height: 90 };
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        previews: [
          preview({
            key: 'assignment-s1',
            mediaUrl,
            label: 'Ada Lovelace',
            bbox,
          }),
        ],
        hasFindings: true,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada Lovelace',
        },
      }),
    );

    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    const cropRoot = container.querySelector('.acx-face-thumbnail');
    expect(cropRoot).toBeInTheDocument();
    expect(cropRoot).toHaveStyle({
      width: `${FINDINGS_PREVIEW_SIZE_PX}px`,
      height: `${FINDINGS_PREVIEW_SIZE_PX}px`,
    });
    // Literal 72 pins the constant itself — lowering FINDINGS_PREVIEW_SIZE_PX must fail.
    expect(cropRoot).toHaveStyle({ width: '72px', height: '72px' });
    expect(FINDINGS_PREVIEW_SIZE_PX).toBe(72);
  });

  // Dedicated server face thumbs win over a croppable mediaUrl+bbox contest (TEST-15 vs HEAD).
  it('renders Avatar for a dedicated face-thumbs URL instead of FaceThumbnail', () => {
    const faceThumbUrl = 'http://example.test/wp-content/uploads/recognition/face-thumbs/rep-1.jpg';
    const mediaUrl = 'http://example.test/uploads/group-photo.jpg';
    const bbox = { x: 1, y: 2, width: 30, height: 40 };
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        previews: [
          preview({
            key: 'assignment-s1',
            thumbUrl: faceThumbUrl,
            mediaUrl,
            label: 'Grace Hopper',
            bbox,
          }),
        ],
        hasFindings: true,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Grace Hopper',
        },
      }),
    );

    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(faceThumbnailSpy).not.toHaveBeenCalled();
    expect(avatarSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        src: faceThumbUrl,
        sizePx: FINDINGS_PREVIEW_SIZE_PX,
      }),
    );
    expect(avatarSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        src: faceThumbUrl,
        sizePx: 72,
      }),
    );
    const image = screen.getByAltText('Grace Hopper');
    expect(image.getAttribute('src')).toBe(faceThumbUrl);
    expect(image.getAttribute('src')).not.toBe(mediaUrl);
    expect(image).toHaveClass('acx-avatar__image');
    expect(container.querySelector('.acx-face-thumbnail')).toBeNull();
  });

  // FIX-4: production WordPress attachment thumb must not short-circuit the crop branch.
  it('crops via FaceThumbnail when thumbUrl is a plain WP attachment thumb alongside mediaUrl + bbox', () => {
    const thumbUrl = 'http://example.test/uploads/2026/01/photo-150x150.jpg';
    const mediaUrl = 'http://example.test/uploads/2026/01/photo.jpg';
    const bbox = { x: 40, y: 50, width: 120, height: 140 };
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        previews: [
          preview({
            key: 'assignment-s1',
            thumbUrl,
            mediaUrl,
            label: 'Ada Lovelace',
            bbox,
          }),
        ],
        hasFindings: true,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada Lovelace',
        },
      }),
    );

    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    const crop = container.querySelector('.acx-face-thumbnail');
    expect(crop).toBeInTheDocument();
    const image = screen.getByAltText('Ada Lovelace');
    expect(image).toHaveAttribute('src', mediaUrl);
    expect(image.getAttribute('src')).not.toBe(thumbUrl);
    expect(faceThumbnailSpy).toHaveBeenCalledWith(
      expect.objectContaining({ mediaUrl, bbox, sizePx: FINDINGS_PREVIEW_SIZE_PX }),
    );
  });

  // A11Y-02: uncropped fallbacks must not claim "Detected face".
  it('uses honest alt text and an uncropped modifier when no face crop is available', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        previews: [
          preview({
            key: 'assignment-s1',
            mediaUrl: 'http://example.test/uploads/wide-shot.jpg',
          }),
        ],
        hasFindings: true,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: null,
        },
      }),
    );

    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByAltText('Reference image')).toBeInTheDocument();
    expect(screen.queryByAltText('Detected face')).not.toBeInTheDocument();
    expect(container.querySelector('.acx-findings-panel__preview--uncropped')).toBeInTheDocument();
  });

  // FIX-8 / A11Y-02 / HAI-01: four alt branches — confirmed+crop, suggested+crop, suggested+uncropped, none+crop.
  it('alt: confirmed label on a real crop uses the label alone', () => {
    const mediaUrl = 'http://example.test/uploads/group-photo.jpg';
    const bbox = { x: 10, y: 20, width: 80, height: 90 };
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        previews: [
          preview({
            key: 'assignment-s1',
            mediaUrl,
            label: 'Ada Lovelace',
            labelIsSuggested: false,
            bbox,
          }),
        ],
        hasFindings: true,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada Lovelace',
        },
      }),
    );

    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    const image = screen.getByAltText('Ada Lovelace');
    expect(image).toBeInTheDocument();
    expect(screen.queryByAltText(/possibly/)).not.toBeInTheDocument();
    expect(faceThumbnailSpy).toHaveBeenCalledWith(
      expect.objectContaining({ mediaUrl, bbox, sizePx: FINDINGS_PREVIEW_SIZE_PX }),
    );
    expect(image.closest('.acx-face-thumbnail')).toBeInTheDocument();
    expect(container.querySelector('.acx-avatar')).toBeNull();
  });

  it('alt: suggested label on a crop is hedged', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        previews: [
          preview({
            key: 'cluster-c1',
            mediaUrl: 'http://example.test/uploads/group-photo.jpg',
            label: 'Ada Lovelace',
            labelIsSuggested: true,
            bbox: { x: 10, y: 20, width: 80, height: 90 },
          }),
        ],
        hasFindings: true,
        nextAction: { kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'c1' },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByAltText('Face image, possibly Ada Lovelace')).toBeInTheDocument();
    expect(screen.queryByAltText('Ada Lovelace')).not.toBeInTheDocument();
  });

  it('alt: suggested label on an uncropped fallback is hedged', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 0, merges: 0, names: 0, unlabeledClusters: 1, total: 1 },
        previews: [
          preview({
            key: 'cluster-c1',
            mediaUrl: 'http://example.test/uploads/wide-shot.jpg',
            label: 'Ada Lovelace',
            labelIsSuggested: true,
            bbox: null,
          }),
        ],
        hasFindings: true,
        nextAction: { kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'c1' },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByAltText('Reference image, possibly Ada Lovelace')).toBeInTheDocument();
    expect(screen.queryByAltText('Ada Lovelace')).not.toBeInTheDocument();
  });

  it('alt: unlabeled crop uses Detected face', () => {
    const mediaUrl = 'http://example.test/uploads/group-photo.jpg';
    const bbox = { x: 10, y: 20, width: 80, height: 90 };
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        previews: [
          preview({
            key: 'assignment-s1',
            mediaUrl,
            label: null,
            labelIsSuggested: false,
            bbox,
          }),
        ],
        hasFindings: true,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: null,
        },
      }),
    );

    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    const image = screen.getByAltText('Detected face');
    expect(image).toBeInTheDocument();
    expect(faceThumbnailSpy).toHaveBeenCalledWith(
      expect.objectContaining({ mediaUrl, bbox, sizePx: FINDINGS_PREVIEW_SIZE_PX }),
    );
    expect(image.closest('.acx-face-thumbnail')).toBeInTheDocument();
    expect(container.querySelector('.acx-avatar')).toBeNull();
  });

  // FIX-4 / TEST-15: zero-extent sentinel must not enter FaceThumbnail (blank chip).
  it('renders Avatar for a zero-extent bbox instead of FaceThumbnail', () => {
    const mediaUrl = 'http://example.test/uploads/group-photo.jpg';
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        previews: [
          preview({
            key: 'assignment-s1',
            thumbUrl: null,
            mediaUrl,
            label: null,
            bbox: { x: 0, y: 0, width: 0, height: 0 },
          }),
        ],
        hasFindings: true,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: null,
        },
      }),
    );

    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(faceThumbnailSpy).not.toHaveBeenCalled();
    expect(avatarSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        src: mediaUrl,
        sizePx: FINDINGS_PREVIEW_SIZE_PX,
        alt: 'Reference image',
        className: 'acx-findings-panel__preview acx-findings-panel__preview--uncropped',
      }),
    );
    const image = screen.getByAltText('Reference image');
    expect(image.tagName).toBe('IMG');
    expect(image).toHaveAttribute('src', mediaUrl);
    expect(image).toHaveClass('acx-avatar__image');
    expect(container.querySelector('.acx-face-thumbnail')).toBeNull();
    expect(container.querySelector('.acx-findings-panel__preview--uncropped')).toBeInTheDocument();
  });

  // FIX-1 / A11Y-02 / HAI-01: merge cluster_a_label auto-placeholder must never reach alt text.
  it('alt: merge cluster_a_label placeholder from buildWorkbenchFindings is omitted', () => {
    const model = buildWorkbenchFindings(
      {
        reviewItems: [],
        assignmentTotal: 0,
        mergeSuggestions: [
          {
            id: 'merge-auto',
            cluster_a_id: 'cluster-a',
            cluster_b_id: 'cluster-b',
            similarity: 0.9,
            status: 'pending',
            cluster_a_label: 'cluster-7',
            cluster_a_representative_media_url: 'http://example.test/uploads/group-photo.jpg',
            cluster_a_representative_bbox: { x: 10, y: 20, width: 80, height: 90 },
          },
        ],
        mergeTotal: 1,
        nameSuggestions: [],
        nameTotal: 0,
        topUnlabeledClusters: [],
        topUnlabeledTotal: 0,
        topUnlabeledTruncated: false,
      },
      {
        assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        isLoading: false,
        isError: false,
        isTopUnlabeledError: false,
        isAssignmentError: false,
        queueSettled: true,
      },
    );

    expect(model.previews[0]).toMatchObject({
      label: null,
      labelIsSuggested: false,
    });

    vi.mocked(useWorkbenchFindings).mockReturnValue(model);

    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByAltText('Detected face')).toBeInTheDocument();
    expect(screen.queryByAltText(/cluster-7/)).not.toBeInTheDocument();
    expect(container.textContent).not.toContain('cluster-7');
  });

  // FIX-2 / A11Y-02 / HAI-01: top-unlabeled placeholder label must never reach alt text.
  it('alt: cluster placeholder label from buildWorkbenchFindings is omitted', () => {
    const model = buildWorkbenchFindings(
      {
        reviewItems: [],
        assignmentTotal: 0,
        mergeSuggestions: [],
        mergeTotal: 0,
        nameSuggestions: [],
        nameTotal: 0,
        topUnlabeledClusters: [
          {
            id: 'cluster-placeholder',
            tenant_id: 'test-tenant-id',
            label: 'cluster-7',
            is_labeled: false,
            is_auto_label: true,
            user_confirmed: false,
            suggested_label: null,
            identity_count: 3,
            representatives: [
              {
                id: 'rep-ph',
                media_id: 41,
                media_url: 'http://example.test/uploads/group-photo.jpg',
                bbox: { x: 10, y: 20, width: 80, height: 90 },
                is_pinned: false,
              },
            ],
          },
        ],
        topUnlabeledTotal: 1,
        topUnlabeledTruncated: false,
      },
      {
        assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        isLoading: false,
        isError: false,
        isTopUnlabeledError: false,
        isAssignmentError: false,
        queueSettled: true,
      },
    );

    expect(model.previews[0]).toMatchObject({
      label: null,
      labelIsSuggested: false,
    });

    vi.mocked(useWorkbenchFindings).mockReturnValue(model);

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByAltText('Detected face')).toBeInTheDocument();
    expect(screen.queryByAltText(/cluster-7/)).not.toBeInTheDocument();
  });

  it('alt: cluster suggested_label from buildWorkbenchFindings is hedged', () => {
    const model = buildWorkbenchFindings(
      {
        reviewItems: [],
        assignmentTotal: 0,
        mergeSuggestions: [],
        mergeTotal: 0,
        nameSuggestions: [],
        nameTotal: 0,
        topUnlabeledClusters: [
          {
            id: 'cluster-suggested',
            tenant_id: 'test-tenant-id',
            label: 'cluster-9',
            is_labeled: false,
            is_auto_label: true,
            user_confirmed: false,
            suggested_label: 'Ada Lovelace',
            identity_count: 2,
            representatives: [
              {
                id: 'rep-sug',
                media_id: 42,
                media_url: 'http://example.test/uploads/group-photo.jpg',
                bbox: { x: 10, y: 20, width: 80, height: 90 },
                is_pinned: false,
              },
            ],
          },
        ],
        topUnlabeledTotal: 1,
        topUnlabeledTruncated: false,
      },
      {
        assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        isLoading: false,
        isError: false,
        isTopUnlabeledError: false,
        isAssignmentError: false,
        queueSettled: true,
      },
    );

    expect(model.previews[0]).toMatchObject({
      label: 'Ada Lovelace',
      labelIsSuggested: true,
    });

    vi.mocked(useWorkbenchFindings).mockReturnValue(model);

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByAltText('Face image, possibly Ada Lovelace')).toBeInTheDocument();
    expect(screen.queryByAltText(/cluster-9/)).not.toBeInTheDocument();
  });

  // S3 / TEST-15: kills the dead <p> error with no Retry / no refetch.
  it('S3: error Retry fires assignment+merge+top-unlabeled refetch', async () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => {
      expect(refetchAssignment).toHaveBeenCalledTimes(1);
      expect(refetchMerge).toHaveBeenCalledTimes(1);
      // REV2-08: name suggestions feed counts.names and the queue, so a control
      // labelled "reload recognition findings" must refetch them too.
      expect(refetchName).toHaveBeenCalledTimes(1);
      expect(refetchTopUnlabeled).toHaveBeenCalledTimes(1);
    });
  });

  // E21-20-REV1-03 / TEST-15: chained .then() skips merge when assignment rejects.
  it('REV1-03: error Retry still refetches merge and top-unlabeled when assignment rejects', async () => {
    refetchAssignment.mockImplementationOnce(() => {
      const assignmentFailure = Promise.reject(new Error('assignment refetch failed'));
      void assignmentFailure.catch(() => undefined);
      return assignmentFailure;
    });

    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => {
      expect(refetchAssignment).toHaveBeenCalledTimes(1);
      expect(refetchMerge).toHaveBeenCalledTimes(1);
      // REV2-08: name suggestions feed counts.names and the queue, so a control
      // labelled "reload recognition findings" must refetch them too.
      expect(refetchName).toHaveBeenCalledTimes(1);
      expect(refetchTopUnlabeled).toHaveBeenCalledTimes(1);
    });
  });

  // S3 / TEST-15: kills hint-less unavailable copy that never names the setting.
  it('S3: unavailable state names the recognition-service setting', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isUnavailable: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.UNAVAILABLE },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('Recognition findings are unavailable right now.')).toBeInTheDocument();
    expect(screen.getByText(/Service API URL/)).toBeInTheDocument();
    expect(screen.getByText(/Recognition API Settings/)).toBeInTheDocument();
  });

  // S3 / TEST-15: kills copy-only unlabeled outage with no retry action.
  // REV1-03: every error-state Retry uses the shared Promise.all handler.
  it('S3: degraded unlabeled chip Retry refetches all findings queries', async () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 2, merges: 0, names: 0, unlabeledClusters: 0, total: 2 },
        hasFindings: true,
        isTopUnlabeledError: true,
        isAssignmentError: false,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada',
        },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('Unlabeled groups unavailable')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => {
      expect(refetchAssignment).toHaveBeenCalledTimes(1);
      expect(refetchMerge).toHaveBeenCalledTimes(1);
      // REV2-08: name suggestions feed counts.names and the queue, so a control
      // labelled "reload recognition findings" must refetch them too.
      expect(refetchName).toHaveBeenCalledTimes(1);
      expect(refetchTopUnlabeled).toHaveBeenCalledTimes(1);
    });
  });

  // S3 / TEST-15: kills Avatar src="" terminal branch.
  it('S3: data-missing chip uses role/name when no usable preview url', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        previews: [
          preview({
            key: 'assignment-s1',
            thumbUrl: null,
            mediaUrl: null,
            label: null,
            bbox: null,
          }),
        ],
        hasFindings: true,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: null,
        },
      }),
    );

    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByRole('img', { name: 'Representative image unavailable' })).toBeInTheDocument();
    expect(screen.getByText('No image')).toBeInTheDocument();
    expect(avatarSpy).not.toHaveBeenCalled();
    expect(container.querySelector('img[src=""]')).toBeNull();
  });

  // S2 / TEST-15: kills silent drop of zero-evidence clusters (no aggregate repair row).
  it('S2: aggregate repair row renders with the gated cluster count', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 1, total: 2 },
        hasFindings: true,
        zeroEvidenceClusterCount: 2,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada',
        },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('2 groups missing face data')).toBeInTheDocument();
    expect(screen.getByText('They are hidden from review until their faces sync.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Resync' })).toBeInTheDocument();
    expect(screen.getByText('1 unlabeled group')).toBeInTheDocument();
  });

  it('S2: Resync on the aggregate repair row refetches top-unlabeled', async () => {
    const model = buildWorkbenchFindings(
      {
        reviewItems: [],
        assignmentTotal: 0,
        mergeSuggestions: [],
        mergeTotal: 0,
        nameSuggestions: [],
        nameTotal: 0,
        topUnlabeledClusters: [
          {
            id: 'zero-a',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            user_confirmed: false,
            identity_count: 0,
            representatives: [{ id: 'rep-a', media_id: 1, is_pinned: false }],
          },
          {
            id: 'zero-b',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            user_confirmed: false,
            identity_count: 4,
            representatives: [],
          },
          {
            id: 'zero-c',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            user_confirmed: false,
            identity_count: 0,
            representatives: [],
          },
        ],
        topUnlabeledTotal: 3,
        topUnlabeledTruncated: false,
      },
      {
        assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        isLoading: false,
        isError: false,
        isTopUnlabeledError: false,
        isAssignmentError: false,
        queueSettled: true,
      },
    );

    vi.mocked(useWorkbenchFindings).mockReturnValue(model);
    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(
      screen.queryByText('No findings yet. Run a scan and new findings will appear here automatically.'),
    ).not.toBeInTheDocument();
    expect(screen.getByText('3 groups missing face data')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Resync' }));
    expect(refetchTopUnlabeled).toHaveBeenCalledTimes(1);
  });

  // E21-20-REV2-02 / TEST-15: drive a producible envelope (server total >=
  // loaded zeros). Assert the repair copy, not an unreachable 'repair' stamp.
  it('REV2-02: producible zero-evidence envelope shows repair copy on the data stamp', () => {
    const model = buildWorkbenchFindings(
      {
        reviewItems: [],
        assignmentTotal: 0,
        mergeSuggestions: [],
        mergeTotal: 0,
        nameSuggestions: [],
        nameTotal: 0,
        topUnlabeledClusters: [
          {
            id: 'zero-a',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            user_confirmed: false,
            identity_count: 0,
            representatives: [{ id: 'rep-a', media_id: 1, is_pinned: false }],
          },
          {
            id: 'zero-b',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            user_confirmed: false,
            identity_count: 2,
            representatives: [],
          },
          {
            id: 'zero-c',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            user_confirmed: false,
            identity_count: 0,
            representatives: [],
          },
        ],
        topUnlabeledTotal: 3,
        topUnlabeledTruncated: false,
      },
      {
        assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        isLoading: false,
        isError: false,
        isTopUnlabeledError: false,
        isAssignmentError: false,
        queueSettled: true,
      },
    );

    expect(model.hasFindings).toBe(true);
    expect(model.counts.total).toBe(3);
    expect(model.zeroEvidenceClusterCount).toBe(3);

    vi.mocked(useWorkbenchFindings).mockReturnValue(model);
    const { container } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('3 groups missing face data')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Resync' })).toBeInTheDocument();
    expect(container.querySelector('[data-findings-state]')).toHaveAttribute(
      'data-findings-state',
      'data',
    );
    expect(container.querySelector('[data-findings-state="empty"]')).toBeNull();
    expect(container.querySelector('[data-findings-state="repair"]')).toBeNull();
  });

  it('S2: counts and previews exclude gated zero-evidence clusters [TEST-15]', () => {
    const model = buildWorkbenchFindings(
      {
        reviewItems: [],
        assignmentTotal: 0,
        mergeSuggestions: [],
        mergeTotal: 0,
        nameSuggestions: [],
        nameTotal: 0,
        topUnlabeledClusters: [
          {
            id: 'zero-count',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            user_confirmed: false,
            identity_count: 0,
            representatives: [
              {
                id: 'rep-zero',
                media_id: 11,
                media_url: 'http://example.test/uploads/zero.jpg',
                bbox: { x: 1, y: 2, width: 10, height: 10 },
                is_pinned: false,
              },
            ],
          },
          {
            id: 'empty-reps',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            user_confirmed: false,
            identity_count: 5,
            representatives: [],
          },
          {
            id: 'reviewable',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            user_confirmed: false,
            identity_count: 4,
            representatives: [
              {
                id: 'rep-ok',
                media_id: 12,
                media_url: 'http://example.test/uploads/ok.jpg',
                bbox: { x: 10, y: 20, width: 80, height: 90 },
                is_pinned: false,
              },
            ],
          },
        ],
        topUnlabeledTotal: 3,
        topUnlabeledTruncated: false,
      },
      {
        assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        isLoading: false,
        isError: false,
        isTopUnlabeledError: false,
        isAssignmentError: false,
        queueSettled: true,
      },
    );

    expect(model.zeroEvidenceClusterCount).toBe(2);
    expect(model.counts.unlabeledClusters).toBe(3);
    expect(model.counts.total).toBe(3);
    expect(model.previews.map((preview) => preview.key)).toEqual(['cluster-reviewable']);
    expect(model.queue).toEqual([{ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'reviewable' }]);
    expect(model.hasFindings).toBe(true);

    vi.mocked(useWorkbenchFindings).mockReturnValue(model);
    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('3 unlabeled groups')).toBeInTheDocument();
    expect(screen.getByText('2 groups missing face data')).toBeInTheDocument();
    expect(screen.queryByText('1 unlabeled group')).not.toBeInTheDocument();
  });

  // E21-20-REV1-04 / TEST-15: repair copy lives in the counts status region;
  // Resync stays outside any live region and is described by the sentence.
  // REV2-03: the same contract applies to Retry — no interactive control may
  // sit inside any role=status (error Retry and unlabeled-outage Retry too).
  it('REV1-04: repair sentence shares the counts live region and Resync is described outside it', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 1, total: 2 },
        hasFindings: true,
        zeroEvidenceClusterCount: 2,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada',
        },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    const liveRegions = screen.getAllByRole('status');
    expect(liveRegions).toHaveLength(1);
    expect(liveRegions[0]).toHaveTextContent('2 groups missing face data');
    expect(liveRegions[0]).toHaveTextContent('1 to review');
    expect(within(liveRegions[0]).queryByRole('button', { name: 'Resync' })).not.toBeInTheDocument();
    for (const region of liveRegions) {
      expect(within(region).queryByRole('button')).not.toBeInTheDocument();
      expect(within(region).queryByRole('link')).not.toBeInTheDocument();
    }

    const resync = screen.getByRole('button', { name: 'Resync' });
    expect(resync.closest('[role="status"]')).toBeNull();
    expect(resync).toHaveAttribute('aria-describedby', 'acx-findings-panel-repair-copy');
    const described = document.getElementById('acx-findings-panel-repair-copy');
    expect(described).not.toBeNull();
    expect(described).toHaveTextContent('2 groups missing face data');
    expect(resync.getAttribute('aria-describedby')).toBe(described?.id);
  });

  // REV2-03 / TEST-15: error Retry used to sit inside the status region.
  // Moving the button back inside role=status fails the closest() assertion.
  it('REV2-03: error Retry sits outside the live region and is described by the error copy', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    for (const region of screen.getAllByRole('status')) {
      expect(within(region).queryByRole('button')).not.toBeInTheDocument();
      expect(within(region).queryByRole('link')).not.toBeInTheDocument();
    }

    const retry = screen.getByRole('button', { name: 'Retry' });
    expect(retry.closest('[role="status"]')).toBeNull();
    expect(retry).toHaveAttribute('aria-describedby', 'acx-findings-panel-error');
    const described = document.getElementById('acx-findings-panel-error');
    expect(described).not.toBeNull();
    expect(described).toHaveTextContent('Could not load recognition findings.');
  });

  // REV2-03 / TEST-15: unlabeled-outage chip Retry used to sit inside counts status.
  it('REV2-03: unlabeled-outage Retry sits outside the counts live region', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 2, merges: 0, names: 0, unlabeledClusters: 0, total: 2 },
        hasFindings: true,
        isTopUnlabeledError: true,
        isAssignmentError: false,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada',
        },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('Unlabeled groups unavailable')).toBeInTheDocument();
    for (const region of screen.getAllByRole('status')) {
      expect(within(region).queryByRole('button')).not.toBeInTheDocument();
      expect(within(region).queryByRole('link')).not.toBeInTheDocument();
    }

    const retry = screen.getByRole('button', { name: 'Retry' });
    expect(retry.closest('[role="status"]')).toBeNull();
    expect(retry).toHaveAttribute('aria-describedby', 'acx-findings-panel-unlabeled-outage');
    const described = document.getElementById('acx-findings-panel-unlabeled-outage');
    expect(described).not.toBeNull();
    expect(described).toHaveTextContent('Unlabeled groups unavailable');
  });

  // REV2-05 / TEST-15: isLoading stays false on an already-errored refetch, so
  // the live region must change from a local retrying flag. Restoring the
  // original single error sentence (or gating on isLoading) leaves this red.
  it('REV2-05: Retry announces in-progress then a distinct failure without using isLoading', async () => {
    let resolveAssignment: (value?: void) => void = () => undefined;
    const assignmentGate = new Promise<void>((resolve) => {
      resolveAssignment = resolve;
    });
    refetchAssignment.mockImplementation(() => assignmentGate.then(() => ({ isError: true })));

    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        isLoading: false,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    const retry = screen.getByRole('button', { name: 'Retry' });
    retry.focus();
    await userEvent.click(retry);

    expect(screen.getByText('Retrying recognition findings…')).toBeInTheDocument();
    expect(screen.queryByText('Could not load recognition findings.')).not.toBeInTheDocument();
    expect(retry).toHaveAttribute('aria-busy', 'true');
    expect(document.activeElement).toBe(retry);

    await act(async () => {
      resolveAssignment();
      await assignmentGate;
    });
    await waitFor(() => {
      expect(screen.getByText('Retry failed. Could not load recognition findings.')).toBeInTheDocument();
    });
    expect(screen.queryByText('Retrying recognition findings…')).not.toBeInTheDocument();
    expect(screen.queryByText('Could not load recognition findings.')).not.toBeInTheDocument();
    refetchAssignment.mockImplementation(() => Promise.resolve({ isError: false }));
  });

  it('REV2-05: successful retry moves focus to Review next when the error tree unmounts', async () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );

    const { rerender } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        hasFindings: true,
        isError: false,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada',
        },
      }),
    );
    rerender(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole('button', { name: /Review next/ }));
    });
  });

  it('REV2-05: successful retry with an empty backlog focuses the panel heading', async () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );

    const { rerender } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: false,
        hasFindings: false,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.EMPTY },
      }),
    );
    rerender(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    await waitFor(() => {
      expect(document.activeElement).toBe(
        screen.getByRole('heading', { name: 'Recognition findings' }),
      );
    });
  });

  // REV3-01 / REV4-01 / TEST-15: RQ v5 refetch() resolves on query error, so
  // retryFailed must come from results.some(r => r.isError). The pin must
  // observe the live-region copy WHILE the error view-model is still mounted —
  // leaving the error branch clears retryFailed via onErrorBranch and hides
  // a `const failed = true` mutation (REV4-01).
  it('REV3-01 / REV4-01: successful retry while error view-model stays mounted shows plain load copy, not Retry failed', async () => {
    const recovered = makeViewModel({
      counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
      hasFindings: true,
      isError: false,
      nextAction: {
        kind: NEXT_ACTION_KIND.ASSIGNMENT,
        suggestionId: 's1',
        clusterId: 'c1',
        label: 'Ada',
      },
    });
    let findings = makeViewModel({
      isError: true,
      nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
    });
    vi.mocked(useWorkbenchFindings).mockImplementation(() => findings);
    refetchAssignment.mockImplementation(() => Promise.resolve({ isError: false }));
    refetchMerge.mockImplementation(() => Promise.resolve({ isError: false }));
    refetchName.mockImplementation(() => Promise.resolve({ isError: false }));
    refetchTopUnlabeled.mockImplementation(() => Promise.resolve({ isError: false }));

    const { rerender } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    expect(screen.getByText('Could not load recognition findings.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => {
      expect(refetchAssignment).toHaveBeenCalled();
    });

    // REV4-01: still on the error branch. All settled results are isError:false,
    // so the live region must be the plain load sentence — not Retry failed.
    await waitFor(() => {
      expect(screen.queryByText('Retrying recognition findings…')).not.toBeInTheDocument();
      expect(screen.getByText('Could not load recognition findings.')).toBeInTheDocument();
    });
    expect(screen.queryByText('Retry failed. Could not load recognition findings.')).not.toBeInTheDocument();

    findings = recovered;
    rerender(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Review next/ })).toBeInTheDocument();

    findings = makeViewModel({
      isError: true,
      hasFindings: false,
      nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
    });
    rerender(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('Could not load recognition findings.')).toBeInTheDocument();
    expect(screen.queryByText('Retry failed. Could not load recognition findings.')).not.toBeInTheDocument();
  });

  // REV3-02 / TEST-15: degraded-chip Retry lives in the data branch, so
  // pendingRetryFocusRef must stay unarmed. A later hasFindings flip is not a
  // reason to jump focus to Review next.
  it('REV3-02: degraded-chip Retry does not move focus when hasFindings later becomes true', async () => {
    const degraded = makeViewModel({
      counts: { assignments: 2, merges: 0, names: 0, unlabeledClusters: 0, total: 2 },
      hasFindings: true,
      isTopUnlabeledError: true,
      isAssignmentError: false,
      nextAction: {
        kind: NEXT_ACTION_KIND.ASSIGNMENT,
        suggestionId: 's1',
        clusterId: 'c1',
        label: 'Ada',
      },
    });
    vi.mocked(useWorkbenchFindings).mockReturnValue(degraded);

    const { rerender } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    const retry = screen.getByRole('button', { name: 'Retry' });
    retry.focus();
    expect(document.activeElement).toBe(retry);
    await userEvent.click(retry);
    await waitFor(() => {
      expect(refetchAssignment).toHaveBeenCalled();
    });

    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        hasFindings: false,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );
    rerender(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 2, merges: 0, names: 0, unlabeledClusters: 1, total: 3 },
        hasFindings: true,
        isError: false,
        isTopUnlabeledError: false,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada',
        },
      }),
    );
    rerender(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(document.activeElement).not.toBe(screen.getByRole('button', { name: /Review next/ }));
    expect(document.activeElement).not.toBe(
      screen.getByRole('heading', { name: 'Recognition findings' }),
    );
  });

  // REV3-03 / TEST-15: degraded-chip and assignment-outage Retry must share
  // the error-branch busy contract (in-flight status + aria-busy), and the
  // control must stay outside its live region (REV2-03).
  it('REV3-03: degraded-chip Retry announces in-flight via the shared busy contract', async () => {
    let resolveAssignment!: (value: { isError: boolean }) => void;
    const assignmentGate = new Promise<{ isError: boolean }>((resolve) => {
      resolveAssignment = resolve;
    });
    refetchAssignment.mockImplementation(() => assignmentGate);

    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 2, merges: 0, names: 0, unlabeledClusters: 0, total: 2 },
        hasFindings: true,
        isTopUnlabeledError: true,
        isAssignmentError: false,
        nextAction: {
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: 's1',
          clusterId: 'c1',
          label: 'Ada',
        },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    const retry = screen.getByRole('button', { name: 'Retry' });
    await userEvent.click(retry);

    expect(screen.getByText('Retrying recognition findings…')).toBeInTheDocument();
    expect(retry).toHaveAttribute('aria-busy', 'true');
    expect(retry.closest('[role="status"]')).toBeNull();

    await act(async () => {
      resolveAssignment({ isError: false });
      await assignmentGate;
    });
  });

  it('REV3-03: assignment-outage Retry announces in-flight via the shared busy contract', async () => {
    let resolveAssignment!: (value: { isError: boolean }) => void;
    const assignmentGate = new Promise<{ isError: boolean }>((resolve) => {
      resolveAssignment = resolve;
    });
    refetchAssignment.mockImplementation(() => assignmentGate);

    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({ isAssignmentError: true, isError: false, hasFindings: false }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    const retry = screen.getByRole('button', { name: 'Retry' });
    await userEvent.click(retry);

    expect(screen.getByText('Retrying recognition findings…')).toBeInTheDocument();
    expect(retry).toHaveAttribute('aria-busy', 'true');
    expect(retry.closest('[role="status"]')).toBeNull();

    await act(async () => {
      resolveAssignment({ isError: false });
      await assignmentGate;
    });
  });

  // REV4-03 / TEST-15: assignment-outage Retry must not arm pendingRetryFocusRef
  // (REV3-02). On successful recovery the outage block unmounts with the
  // focused Retry inside it, so focus is restored in the settled .then —
  // Review next when enabled, else the panel heading — not via the deferred
  // [hasFindings, isError] effect.
  it('REV4-03: successful assignment-outage retry moves focus to Review next, not body', async () => {
    let resolveAssignment!: (value: { isError: boolean }) => void;
    const assignmentGate = new Promise<{ isError: boolean }>((resolve) => {
      resolveAssignment = resolve;
    });
    refetchAssignment.mockImplementation(() => assignmentGate);

    let findings = makeViewModel({ isAssignmentError: true, isError: false, hasFindings: false });
    vi.mocked(useWorkbenchFindings).mockImplementation(() => findings);

    const { rerender } = render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    const retry = screen.getByRole('button', { name: 'Retry' });
    retry.focus();
    expect(document.activeElement).toBe(retry);
    await userEvent.click(retry);

    findings = makeViewModel({
      counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
      hasFindings: true,
      isAssignmentError: false,
      isError: false,
      nextAction: {
        kind: NEXT_ACTION_KIND.ASSIGNMENT,
        suggestionId: 's1',
        clusterId: 'c1',
        label: 'Ada',
      },
    });
    rerender(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);
    expect(
      screen.queryByText('Face assignments unavailable — this is not an empty backlog.'),
    ).not.toBeInTheDocument();
    // REV3-02 must stay: outage Retry did not arm the deferred focus effect.
    expect(document.activeElement).not.toBe(screen.getByRole('button', { name: /Review next/ }));

    await act(async () => {
      resolveAssignment({ isError: false });
      await assignmentGate;
    });

    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole('button', { name: /Review next/ }));
    });
    expect(document.activeElement).not.toBe(document.body);
  });

  // REV2-04 / TEST-15: a truncated page must not say "3 groups" as if that is
  // the whole backlog. Dropping the qualifier (or ignoring topUnlabeledTruncated)
  // leaves this looking like the unqualified S2 copy.
  it('REV2-04: truncated top-unlabeled page qualifies the gated-cluster count', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 0, merges: 0, names: 0, unlabeledClusters: 42, total: 42 },
        hasFindings: true,
        zeroEvidenceClusterCount: 3,
        topUnlabeledTruncated: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.EMPTY },
      }),
    );

    render(<WorkbenchFindingsPanel onTargetFindings={vi.fn()} />);

    expect(screen.getByText('At least 3 groups on this page missing face data')).toBeInTheDocument();
    expect(screen.queryByText('3 groups missing face data')).not.toBeInTheDocument();
    expect(screen.getByText('42 unlabeled groups')).toBeInTheDocument();
  });
});
