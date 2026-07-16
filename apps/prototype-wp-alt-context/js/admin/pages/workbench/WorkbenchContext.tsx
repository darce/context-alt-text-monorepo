import React from 'react';
import { WorkbenchNavProvider } from './WorkbenchNavContext';
import { WorkbenchMediaProvider } from './WorkbenchMediaContext';
import { JobPipelineProvider } from './JobPipelineContext';
import { ClusterPanelProvider } from './ClusterPanelContext';

export { TAB_IDS, LEGACY_CONFIRM_TAB, ADVANCED_PARAM, ADVANCED_OPEN_VALUE } from './WorkbenchNavContext';
export type { WorkbenchTab, WorkbenchOverlay } from './WorkbenchNavContext';

/** Composition only. Nav must wrap JobPipeline: the pipeline's history selection opens the advanced drawer via nav. */
export const WorkbenchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <WorkbenchNavProvider>
    <WorkbenchMediaProvider>
      <JobPipelineProvider>
        <ClusterPanelProvider>{children}</ClusterPanelProvider>
      </JobPipelineProvider>
    </WorkbenchMediaProvider>
  </WorkbenchNavProvider>
);
