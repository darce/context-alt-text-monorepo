import { __, _n, sprintf } from '@wordpress/i18n';

import { useRemoteActionGate } from '../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../hooks/useSyncOffline';
import { isClusteringActive } from './Panels';
import { useJobPipeline } from './JobPipelineContext';
import { useWorkbenchMediaContext } from './WorkbenchMediaContext';

/** aria-describedby target for the §7 offline reason. */
const ANALYZE_OFFLINE_REASON_ID = 'acx-analyze-offline-reason';

interface MediaAnalyzeCtaProps {
  /**
   * §7 accent ownership: when this CTA is the footer's single accent primary it
   * renders with the accent token role and carries the accent-primary marker;
   * otherwise it steps down to the neutral/ghost secondary variant (no accent).
   * Defaults to primary (the standalone/select state).
   */
  accentPrimary?: boolean;
}

export const MediaAnalyzeCta = ({ accentPrimary = true }: MediaAnalyzeCtaProps = {}): React.JSX.Element => {
  const { scanRun, scan } = useJobPipeline();
  const { selectedMedia } = useWorkbenchMediaContext().selection;
  const selectedCount = selectedMedia.length;
  // Co-located hook + button — gate directly (RES-15, RES-03).
  const offline = useSyncOffline();
  const remoteGate = useRemoteActionGate(offline);

  const handleScanFaces = (): void => {
    if (offline) {
      return;
    }
    const mediaIds = selectedMedia.map((item) => item.id);
    if (mediaIds.length === 0) {
      return;
    }
    scan(mediaIds);
  };

  // §7 offline row: aria-disabled (still focusable, reason reachable) — NEVER HTML
  // `disabled`, which drops the control from tab order + AT perception. The reason
  // is associated via aria-describedby; the offline transition itself is announced
  // through the sync-status live region (SyncStatusIndicator).
  const buttonClassName = accentPrimary
    ? 'acx-apply-panel__scan'
    : 'acx-apply-panel__scan acx-apply-panel__scan--secondary';

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
        className={buttonClassName}
        onClick={handleScanFaces}
        // BR-74: offline never HTML-disables — that drops the button from tab order,
        // stranding the aria-describedby reason on an unfocusable control. Offline is
        // gated by aria-disabled + the onClick guard only; the reason stays reachable.
        // Zero-selection/scanning still HTML-disable when online.
        disabled={!offline && (scanRun.isScanning || selectedCount === 0)}
        aria-disabled={remoteGate['aria-disabled']}
        aria-describedby={offline ? ANALYZE_OFFLINE_REASON_ID : undefined}
        title={remoteGate.title}
        {...(accentPrimary ? { 'data-acx-accent-primary': true } : {})}
      >
        {scanRun.isScanning
          ? isClusteringActive(scanRun.progress?.phase)
            ? __('Clustering identities…', 'alt-context')
            : __('Scanning media…', 'alt-context')
          : __('Analyze selected media', 'alt-context')}
      </button>
      {offline && remoteGate.title ? (
        <span id={ANALYZE_OFFLINE_REASON_ID} className="screen-reader-text">
          {remoteGate.title}
        </span>
      ) : null}
    </div>
  );
};
