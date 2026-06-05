import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  NEXT_ACTION_KIND,
  NONE_REASON,
  useWorkbenchFindings,
  type WorkbenchFindingsViewModel,
} from '../useWorkbenchFindings';
import { WorkbenchFindingsPanel } from '../WorkbenchFindingsPanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (text: string) => text,
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

vi.mock('../useWorkbenchFindings', async () => {
  const actual = await vi.importActual<typeof import('../useWorkbenchFindings')>('../useWorkbenchFindings');
  return {
    ...actual,
    useWorkbenchFindings: vi.fn(),
  };
});

const makeViewModel = (overrides: Partial<WorkbenchFindingsViewModel> = {}): WorkbenchFindingsViewModel => ({
  counts: { assignments: 0, merges: 0, names: 0, unlabeledClusters: 0, total: 0 },
  previews: [],
  hasFindings: false,
  isLoading: false,
  isError: false,
  isUnavailable: false,
  isReadOnly: false,
  nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.EMPTY },
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
          { key: 'assignment-s1', thumbUrl: 'http://example.test/face-1.jpg', mediaUrl: null, label: 'Grace Hopper' },
          { key: 'cluster-c1', thumbUrl: 'http://example.test/face-2.jpg', mediaUrl: null, label: null },
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

    render(<WorkbenchFindingsPanel onLabel={vi.fn()} onTargetFindings={onTargetFindings} />);

    expect(screen.getByText('Recognition findings')).toBeInTheDocument();
    expect(screen.getByText('2 to review')).toBeInTheDocument();
    expect(screen.getByText('1 merge candidates')).toBeInTheDocument();
    expect(screen.getByText('3 suggested names')).toBeInTheDocument();
    expect(screen.getByText('4 unlabeled groups')).toBeInTheDocument();
    expect(screen.getAllByRole('img')).toHaveLength(2);

    const primary = screen.getByRole('button', { name: /Review next/ });
    expect(primary).toBeEnabled();
    await userEvent.click(primary);
    expect(onTargetFindings).toHaveBeenCalledTimes(1);
  });

  it('opens the label drawer when the next action targets an unlabeled cluster', async () => {
    const onLabel = vi.fn();
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        counts: { assignments: 0, merges: 0, names: 0, unlabeledClusters: 1, total: 1 },
        hasFindings: true,
        nextAction: { kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'cluster-9' },
      }),
    );

    render(<WorkbenchFindingsPanel onLabel={onLabel} onTargetFindings={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: /Review next/ }));
    expect(onLabel).toHaveBeenCalledWith('cluster-9');
  });

  it('disables the primary action and explains population in the empty state', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(makeViewModel());

    render(<WorkbenchFindingsPanel onLabel={vi.fn()} onTargetFindings={vi.fn()} />);

    expect(
      screen.getByText('No findings yet. Run a scan and new findings will appear here automatically.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Review next/ })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'View all findings' })).not.toBeInTheDocument();
  });

  it('renders an explicit loading state', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isLoading: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.LOADING },
      }),
    );

    render(<WorkbenchFindingsPanel onLabel={vi.fn()} onTargetFindings={vi.fn()} />);

    expect(screen.getByText('Checking recognition findings…')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Review next/ })).not.toBeInTheDocument();
  });

  it('renders an explicit error state', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isError: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR },
      }),
    );

    render(<WorkbenchFindingsPanel onLabel={vi.fn()} onTargetFindings={vi.fn()} />);

    expect(screen.getByText('Could not load recognition findings.')).toBeInTheDocument();
  });

  it('renders an explicit unavailable state', () => {
    vi.mocked(useWorkbenchFindings).mockReturnValue(
      makeViewModel({
        isUnavailable: true,
        nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.UNAVAILABLE },
      }),
    );

    render(<WorkbenchFindingsPanel onLabel={vi.fn()} onTargetFindings={vi.fn()} />);

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

    render(<WorkbenchFindingsPanel onLabel={vi.fn()} onTargetFindings={vi.fn()} />);

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

    render(<WorkbenchFindingsPanel onLabel={vi.fn()} onTargetFindings={onTargetFindings} />);

    const secondary = screen.getByRole('button', { name: 'View all findings' });
    await userEvent.click(secondary);
    expect(onTargetFindings).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
