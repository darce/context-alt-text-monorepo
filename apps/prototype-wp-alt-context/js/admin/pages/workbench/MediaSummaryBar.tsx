import { __, _n, sprintf } from '@wordpress/i18n';

import { useWorkbenchContext } from './WorkbenchContext';

interface MediaSummaryBarProps {
  onExpand: () => void;
}

const statusLabels = {
  all: __('All media', 'alt-context'),
  missing: __('Missing alt text', 'alt-context'),
} as const;

export const MediaSummaryBar = ({ onExpand }: MediaSummaryBarProps): React.JSX.Element => {
  const { mediaQuery, selectedMedia, statusFilter } = useWorkbenchContext();
  const total = mediaQuery.data?.total ?? mediaQuery.itemsWithIdentities?.length ?? 0;
  const selectedCount = selectedMedia.length;

  return (
    <div className="acx-media-selection acx-media-selection--collapsed">
      <div className="acx-media-selection__summary" role="region" aria-label={__('Media table summary', 'alt-context')}>
        <div className="acx-media-selection__summary-main">
          <span>{sprintf(_n('%d media item', '%d media items', total, 'alt-context'), total)}</span>
          <span>{sprintf(_n('%d selected', '%d selected', selectedCount, 'alt-context'), selectedCount)}</span>
          <span>{statusLabels[statusFilter]}</span>
        </div>
        <button
          type="button"
          className="acx-button acx-button--secondary acx-button--small"
          aria-expanded="false"
          onClick={onExpand}
        >
          {__('Show media table', 'alt-context')}
        </button>
      </div>
    </div>
  );
};
