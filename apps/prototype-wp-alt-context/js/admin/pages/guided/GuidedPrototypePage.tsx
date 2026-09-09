import React, { useContext } from 'react';

import { getGuidedLiveMediaId } from '../../api/config';
import { ErrorBoundary } from '../../../components/ErrorBoundary';
import { guidedCopy } from '../../guidedPrototype/copy';
import { RecordedWalkthrough, RecordedWalkthroughLiveSlot } from '../../guidedPrototype/RecordedWalkthrough';
import { GuidedLiveDescriptionPanel } from './GuidedLiveDescriptionPanel';

const AdminLivePanel = (): React.JSX.Element => {
  const setLiveWaiting = useContext(RecordedWalkthroughLiveSlot);

  return (
    <ErrorBoundary
      fallback={
        <p className="acx-guided-live__fallback" role="alert">
          {guidedCopy('live.failed')}
        </p>
      }
    >
      <GuidedLiveDescriptionPanel mediaId={getGuidedLiveMediaId()} onWaitingChange={setLiveWaiting ?? undefined} />
    </ErrorBoundary>
  );
};

export const GuidedPrototypePage = (): React.JSX.Element => (
  <RecordedWalkthrough scope="admin" livePanel={<AdminLivePanel />} />
);

GuidedPrototypePage.displayName = 'GuidedPrototypePage';
AdminLivePanel.displayName = 'AdminLivePanel';
