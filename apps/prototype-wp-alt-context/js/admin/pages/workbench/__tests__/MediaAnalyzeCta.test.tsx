import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MediaAnalyzeCta } from '../MediaAnalyzeCta';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, _plural: string, count: number) => (count === 1 ? single : _plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

const scan = vi.fn();

let workbenchContext = {
  selectedMedia: [] as { id: number }[],
  isScanRunning: false,
  scanProgress: null as { phase?: string | null } | null,
  clusterProgress: null as { phase?: string | null } | null,
  currentPhase: 'idle',
  scan,
};

vi.mock('../WorkbenchContext', () => ({
  useWorkbenchContext: () => workbenchContext,
}));

describe('MediaAnalyzeCta', () => {
  beforeEach(() => {
    scan.mockClear();
    workbenchContext = {
      selectedMedia: [],
      isScanRunning: false,
      scanProgress: null,
      clusterProgress: null,
      currentPhase: 'idle',
      scan,
    };
  });

  it('renders zero-selection prompt and disabled button', () => {
    render(<MediaAnalyzeCta />);

    expect(screen.getByText('Select media items from the queue to analyze them.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Analyze selected media' })).toBeDisabled();
  });

  it('renders item count and scans selected media when selection is non-zero', async () => {
    workbenchContext = {
      ...workbenchContext,
      selectedMedia: [{ id: 11 }, { id: 12 }, { id: 13 }],
    };

    render(<MediaAnalyzeCta />);

    expect(screen.getByText('Ready to analyze 3 media items.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Analyze selected media' }));
    expect(scan).toHaveBeenCalledWith([11, 12, 13]);
  });

  it('shows scanning label and disables button while scanning', () => {
    workbenchContext = {
      ...workbenchContext,
      selectedMedia: [{ id: 11 }],
      isScanRunning: true,
    };

    render(<MediaAnalyzeCta />);

    expect(screen.getByRole('button', { name: 'Scanning media…' })).toBeDisabled();
  });

  it('shows clustering label when the active progress phase is clustering', () => {
    workbenchContext = {
      ...workbenchContext,
      selectedMedia: [{ id: 11 }],
      isScanRunning: true,
      currentPhase: 'clustering',
      clusterProgress: { phase: 'clustering' },
    };

    render(<MediaAnalyzeCta />);

    expect(screen.getByRole('button', { name: 'Clustering identities…' })).toBeDisabled();
  });
});
