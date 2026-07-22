import React from 'react';
import { WorkbenchNavProvider } from './WorkbenchNavContext';
import { WorkbenchMediaProvider } from './WorkbenchMediaContext';
import { JobPipelineProvider } from './JobPipelineContext';
import { ClusterPanelProvider } from './ClusterPanelContext';
import { MergeSurvivorProvider } from './identity-clusters/MergeSurvivorContext';

export { TAB_IDS, ADVANCED_PARAM, ADVANCED_OPEN_VALUE } from './WorkbenchNavContext';
export type { WorkbenchTab, WorkbenchOverlay } from './WorkbenchNavContext';

/** Composition only. Nav must wrap JobPipeline: the pipeline's history selection opens the advanced drawer via nav. */
export const WorkbenchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <WorkbenchNavProvider>
    <WorkbenchMediaProvider>
      <JobPipelineProvider>
        <ClusterPanelProvider>
          <MergeSurvivorProvider>{children}</MergeSurvivorProvider>
        </ClusterPanelProvider>
      </JobPipelineProvider>
    </WorkbenchMediaProvider>
  </WorkbenchNavProvider>
);
