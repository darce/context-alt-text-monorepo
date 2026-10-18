import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AdvancedDrawer } from '../AdvancedDrawer';
import { CLUSTERING_DISCLOSURE_SUMMARY } from '../confirmTabCopy';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, _plural: string, count: number) => (count === 1 ? single : _plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

const navStub = {
  isAdvancedOpen: true,
  setAdvancedOpen: vi.fn(),
};

vi.mock('../WorkbenchNavContext', () => ({
  useWorkbenchNav: () => navStub,
}));

vi.mock('../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));

vi.mock('../../../hooks/useRemoteActionGate', () => ({
  useRemoteActionGate: () => ({
    disabled: false,
    title: undefined,
    'aria-disabled': undefined,
  }),
}));

vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: {
      isScanning: false,
      statusText: undefined,
      etaSeconds: null,
      isSynced: false,
    },
    status: {
      clusterProgress: null,
      clusterMessage: null,
    },
    history: {
      jobId: null,
      jobHistory: [],
      jobStatuses: {},
      historySource: 'unavailable',
    },
    cluster: vi.fn(),
    handleSelectJobFromHistory: vi.fn(),
    clearHistory: vi.fn(),
  }),
}));

describe('AdvancedDrawer', () => {
  it('opens onto recovery tools with the clustering disclosure closed', () => {
    const { container } = render(<AdvancedDrawer />);

    expect(screen.getByRole('region', { name: 'Advanced: jobs & recovery' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cluster the latest job results' })).toBeTruthy();

    const details = container.querySelector<HTMLDetailsElement>('details.acx-workbench-help-card');
    expect(details).not.toBeNull();
    expect(details?.open).toBe(false);
    expect(screen.getByText(CLUSTERING_DISCLOSURE_SUMMARY)).toBeTruthy();
  });

  it('lets the operator expand the clustering disclosure on demand', async () => {
    const { container } = render(<AdvancedDrawer />);
    const details = container.querySelector<HTMLDetailsElement>('details.acx-workbench-help-card');

    await userEvent.click(screen.getByText(CLUSTERING_DISCLOSURE_SUMMARY));
    expect(details?.open).toBe(true);
  });
});
