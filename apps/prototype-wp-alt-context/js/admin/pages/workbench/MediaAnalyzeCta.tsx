import { __, _n, sprintf } from '@wordpress/i18n';

import { useWorkbenchContext } from './WorkbenchContext';

const isClusteringActive = (phase?: string | null): boolean => phase === 'clustering' || phase === 'retrying';

export const MediaAnalyzeCta = (): React.JSX.Element => {
  const { selectedMedia, isScanRunning, currentPhase, scanProgress, clusterProgress, scan } = useWorkbenchContext();
  const selectedCount = selectedMedia.length;
  const activeProgress =
    (currentPhase === 'clustering' || currentPhase === 'projecting') && clusterProgress ? clusterProgress : scanProgress;

  const handleScanFaces = (): void => {
    const mediaIds = selectedMedia.map((item) => item.id);
    if (mediaIds.length === 0) {
      return;
    }
    scan(mediaIds);
  };

  return (
    <div className="acx-media-selection__analyze">
      <p className="acx-media-selection__analyze-copy">
        {selectedCount === 0
          ? __('Select media items from the queue to analyze them.', 'alt-context')
          : sprintf(
              _n('Ready to analyze %d media item.', 'Ready to analyze %d media items.', selectedCount, 'alt-context'),
              selectedCount,
            )}
      </p>
      <button
        type="button"
        className="acx-apply-panel__scan"
        onClick={handleScanFaces}
        disabled={isScanRunning || selectedCount === 0}
      >
        {isScanRunning
          ? isClusteringActive(activeProgress?.phase)
            ? __('Clustering identities…', 'alt-context')
            : __('Scanning media…', 'alt-context')
          : __('Analyze selected media', 'alt-context')}
      </button>
    </div>
  );
};
