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
let offline = false;

let scanRun = {
  isScanning: false,
  progress: null as { phase?: string | null } | null,
};

let selectedMedia: { id: number }[] = [];

vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({ scanRun, scan }),
}));

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({
    selection: { selectedMedia },
  }),
}));

vi.mock('../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => offline,
}));

describe('MediaAnalyzeCta', () => {
  beforeEach(() => {
    scan.mockClear();
    offline = false;
    scanRun = {
      isScanning: false,
      progress: null,
    };
    selectedMedia = [];
  });

  it('renders zero-selection prompt and disabled button', () => {
    render(<MediaAnalyzeCta />);

    expect(screen.getByText('Select media items from the queue to analyze them.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Analyze selected media' })).toBeDisabled();
  });

  it('renders item count and scans selected media when selection is non-zero', async () => {
    selectedMedia = [{ id: 11 }, { id: 12 }, { id: 13 }];

    render(<MediaAnalyzeCta />);

    expect(screen.getByText('Ready to analyze 3 media items.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Analyze selected media' }));
    expect(scan).toHaveBeenCalledWith([11, 12, 13]);
  });

  it('shows scanning label and disables button while scanning', () => {
    selectedMedia = [{ id: 11 }];
    scanRun = {
      ...scanRun,
      isScanning: true,
    };

    render(<MediaAnalyzeCta />);

    expect(screen.getByRole('button', { name: 'Scanning media…' })).toBeDisabled();
  });

  it('shows clustering label when the active progress phase is clustering', () => {
    selectedMedia = [{ id: 11 }];
    scanRun = {
      ...scanRun,
      isScanning: true,
      progress: { phase: 'clustering' },
    };

    render(<MediaAnalyzeCta />);

    expect(screen.getByRole('button', { name: 'Clustering identities…' })).toBeDisabled();
  });

  it('disables analyze with offline reason when breaker is open', async () => {
    offline = true;
    selectedMedia = [{ id: 11 }];
    render(<MediaAnalyzeCta />);

    const button = screen.getByRole('button', { name: 'Analyze selected media' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Unavailable while the recognition service is offline');
    expect(button).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(button);
    expect(scan).not.toHaveBeenCalled();
  });

  it('enables analyze when online with selection', () => {
    selectedMedia = [{ id: 11 }];
    render(<MediaAnalyzeCta />);

    const button = screen.getByRole('button', { name: 'Analyze selected media' });
    expect(button).not.toBeDisabled();
    expect(button).not.toHaveAttribute('title');
  });
});
