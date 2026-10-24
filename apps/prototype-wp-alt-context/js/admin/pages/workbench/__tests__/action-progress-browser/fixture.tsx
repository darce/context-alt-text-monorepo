// Offline acceptance: real components, styles, providers, stores and queries.
// Only HTTP data is replaced by the Playwright runner; no UI/hook aliases.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { registerConfig, type ApiConfig } from '../../../../api/config';
import { MediaSelection } from '../../MediaSelection';
import { ActivityStatusStrip } from '../../ActivityStatusStrip';
import { WorkbenchMediaProvider } from '../../WorkbenchMediaContext';
import { WorkbenchNavProvider } from '../../WorkbenchNavContext';
import { JobPipelineProvider, useJobPipeline } from '../../JobPipelineContext';
import '../../../../styles/main.scss';

// The runner owns transport identities (tenant, endpoints) so the served config and
// every mocked producer payload come from one contract-checked source.
const configNode = document.getElementById('acx-fixture-config');
if (configNode?.textContent == null) {
  throw new Error('Offline fixture config is missing.');
}
registerConfig(JSON.parse(configNode.textContent) as ApiConfig);
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

// A WB_CONTROL consumer binds the library's remaining height on an ancestor.
const availableHeight = new URLSearchParams(location.search).get('available');
const hostStyle = (
  availableHeight === null ? undefined : { '--acx-media-selection-available-height': availableHeight }
) as React.CSSProperties | undefined;

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={client}>
    <MemoryRouter initialEntries={['/workbench']}>
      <WorkbenchNavProvider>
        <JobPipelineProvider>
          <WorkbenchMediaProvider>
            <main className="acx-admin acx-workbench" style={hostStyle}>
              <h1>Media library fixture</h1>
              <Library />
            </main>
          </WorkbenchMediaProvider>
        </JobPipelineProvider>
      </WorkbenchNavProvider>
    </MemoryRouter>
  </QueryClientProvider>,
);
