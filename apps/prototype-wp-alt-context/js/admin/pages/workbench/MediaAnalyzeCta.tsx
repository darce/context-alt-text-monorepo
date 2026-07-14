import { __, _n, sprintf } from '@wordpress/i18n';

import { isClusteringActive } from './Panels';
import { useJobPipeline } from './JobPipelineContext';
import { useWorkbenchMediaContext } from './WorkbenchMediaContext';

export const MediaAnalyzeCta = (): React.JSX.Element => {
  const { scanRun, scan } = useJobPipeline();
  const { selectedMedia } = useWorkbenchMediaContext().selection;
  const selectedCount = selectedMedia.length;

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
        disabled={scanRun.isScanning || selectedCount === 0}
      >
        {scanRun.isScanning
          ? isClusteringActive(scanRun.progress?.phase)
            ? __('Clustering identities…', 'alt-context')
            : __('Scanning media…', 'alt-context')
          : __('Analyze selected media', 'alt-context')}
      </button>
    </div>
  );
};
