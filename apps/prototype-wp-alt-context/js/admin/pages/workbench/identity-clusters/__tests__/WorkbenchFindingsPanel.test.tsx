import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
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

const { faceThumbnailSpy, avatarSpy } = vi.hoisted(() => ({
  faceThumbnailSpy: vi.fn(),
  avatarSpy: vi.fn(),
}));

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
  hasFindings: false,
  isLoading: false,
  isError: false,
  isTopUnlabeledError: false,
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
    expect(previewImgs[0]).toHaveClass('acx-durable-face-thumb__uncropped');
    expect(previewImgs[1]).toHaveAttribute('src', 'http://example.test/face-2.jpg');
    expect(previewImgs[1]).toHaveAttribute('alt', 'Reference image');
    expect(previewImgs[1]).toHaveClass('acx-durable-face-thumb__uncropped');
    expect(avatarSpy).not.toHaveBeenCalled();
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
    expect(avatarSpy).not.toHaveBeenCalled();
    const image = screen.getByAltText('Reference image');
    expect(image.tagName).toBe('IMG');
    expect(image).toHaveAttribute('src', mediaUrl);
    expect(image).toHaveClass('acx-durable-face-thumb__uncropped');
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
      },
      {
        assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        isLoading: false,
        isError: false,
        isTopUnlabeledError: false,
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
      },
      {
        assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        isLoading: false,
        isError: false,
        isTopUnlabeledError: false,
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
      },
      {
        assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
        isLoading: false,
        isError: false,
        isTopUnlabeledError: false,
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
});
