// Offline acceptance: real components, styles, providers, stores and queries.
// Only HTTP data is replaced by the Playwright runner; no UI/hook aliases.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { registerConfig } from '../../../../api/config';
import { MediaSelection } from '../../MediaSelection';
import { ActivityStatusStrip } from '../../ActivityStatusStrip';
import { WorkbenchMediaProvider } from '../../WorkbenchMediaContext';
import { WorkbenchNavProvider } from '../../WorkbenchNavContext';
import { JobPipelineProvider, useJobPipeline } from '../../JobPipelineContext';
import '../../../../styles/main.scss';

const endpointNames = [
  'settings',
  'workbenchMedia',
  'workbenchMediaDetail',
  'recognitionMediaIdentities',
  'recognitionDescribeRuns',
  'recognitionDescribeHistory',
  'recognitionGpuStatus',
  'recognitionSyncHealth',
  'recognitionSyncStatus',
  'recognitionBatchRuns',
  'recognitionJobs',
  'recognitionClusters',
  'recognitionSyncTrigger',
];
registerConfig({
  nonce: 'offline-fixture',
  ajaxUrl: '/fixture-api/ajax',
  tenant_id: 'action-progress-fixture',
  endpoints: Object.fromEntries(
    endpointNames.map((name) => [name, `https://action-progress-fixture.invalid/fixture-api/${name}`]),
  ),
});
const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
Object.assign(window, { actionProgressHarness: { refetch: () => client.refetchQueries({ type: 'active' }) } });

const Library = () => {
  const pipeline = useJobPipeline();
  const props = {
    reviewActive: new URLSearchParams(location.search).get('review') === '1',
    // Composition seam: the existing status is moved once, never copied.
    activityStatus: (
      <ActivityStatusStrip
        scan={{
          isScanning: pipeline.scanRun.isScanning,
          progress: pipeline.scanRun.progress,
          jobId: pipeline.scanRun.jobId,
          cancelScan: () => pipeline.cancelScan(pipeline.history.activeJobIds),
        }}
      />
    ),
  };
  return <MediaSelection {...props} />;
};

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={client}>
    <MemoryRouter initialEntries={['/workbench']}>
      <WorkbenchNavProvider>
        <JobPipelineProvider>
          <WorkbenchMediaProvider>
            <main className="acx-admin acx-workbench">
              <h1>Media library fixture</h1>
              <Library />
            </main>
          </WorkbenchMediaProvider>
        </JobPipelineProvider>
      </WorkbenchNavProvider>
    </MemoryRouter>
  </QueryClientProvider>,
);
