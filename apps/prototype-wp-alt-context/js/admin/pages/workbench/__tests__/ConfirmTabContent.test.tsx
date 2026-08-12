import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import {
  CLUSTERING_DISCLOSURE_BODY,
  CLUSTERING_DISCLOSURE_SUMMARY,
} from '../confirmTabCopy';
import { ConfirmTabContent } from '../ConfirmTabContent';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, _plural: string, count: number) => (count === 1 ? single : _plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
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

const jobPipelineStub = {
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
    jobId: null as string | null,
    jobHistory: [] as string[],
    jobStatuses: {} as Record<string, string>,
    historySource: 'unavailable' as const,
  },
  cluster: vi.fn(),
  handleSelectJobFromHistory: vi.fn(),
  clearHistory: vi.fn(),
};

vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => jobPipelineStub,
}));

describe('ConfirmTabContent', () => {
  it('keeps the clustering explainer closed by default and recovery tools first', () => {
    const { container } = render(<ConfirmTabContent />);

    const details = container.querySelector<HTMLDetailsElement>('details.acx-workbench-help-card');
    expect(details).not.toBeNull();
    expect(details?.open).toBe(false);
    expect(screen.getByText(CLUSTERING_DISCLOSURE_SUMMARY)).toBeTruthy();

    // Recovery tools remain reachable with the disclosure closed (tools-first).
    expect(screen.getByRole('button', { name: 'Cluster the latest job results' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open roster' })).toBeTruthy();
  });

  it('reveals disclosure body without embeddings only after the summary is toggled', async () => {
    const { container } = render(<ConfirmTabContent />);
    const details = container.querySelector<HTMLDetailsElement>('details.acx-workbench-help-card');
    expect(details?.open).toBe(false);

    await userEvent.click(screen.getByText(CLUSTERING_DISCLOSURE_SUMMARY));
    expect(details?.open).toBe(true);
    expect(screen.getByText(CLUSTERING_DISCLOSURE_BODY)).toBeTruthy();
    // Spec: confirm tab surface (disclosure + ConfirmPanel intro) drops "embeddings".
    expect(CLUSTERING_DISCLOSURE_BODY.toLowerCase()).not.toContain('embeddings');
    expect(details?.textContent?.toLowerCase()).not.toContain('embeddings');
    expect(container.textContent?.toLowerCase()).not.toContain('embeddings');
  });

  it('keeps the disclosure summary keyboard-focusable (UXP4-BRV-03)', () => {
    render(<ConfirmTabContent />);
    const summary = screen.getByText(CLUSTERING_DISCLOSURE_SUMMARY);
    expect(summary.tagName).toBe('SUMMARY');
    summary.focus();
    expect(document.activeElement).toBe(summary);
  });
});
