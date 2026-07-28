import { __, sprintf } from '@wordpress/i18n';

import type { WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';
import type { DataSource } from '../../api/recognition/types';
import { Checkbox } from '../../../components/ui/checkbox';
import { IdentityClusterList } from './identity-clusters';
import { MediaAltInlineEditor } from './MediaAltInlineEditor';
import { MediaAltSuggest } from './MediaAltSuggest';
import { mediaEditUrl } from './Panels';

interface MediaSelectionTableBodyProps {
  items: WorkbenchMediaItem[];
  isLoading: boolean;
  detailIsLoading: boolean;
  onToggleRow: (item: WorkbenchMediaItem, checked: boolean) => void;
  selection: Record<string, boolean>;
  identitiesDataSource?: DataSource;
  onRetryIdentities?: () => void;
}

export const MediaSelectionTableBody = ({
  items,
  isLoading,
  detailIsLoading,
  onToggleRow,
  selection,
  identitiesDataSource,
  onRetryIdentities,
}: MediaSelectionTableBodyProps): React.JSX.Element => {
  if (isLoading && items.length === 0) {
    return (
      <>
        {Array.from({ length: 5 }, (_, index) => (
          <MediaSelectionSkeletonRow key={`skeleton-${index}`} />
        ))}
      </>
    );
  }

  if (items.length === 0) {
    return (
      <tr>
        <td colSpan={4}>{__('No media matches your search.', 'alt-context')}</td>
      </tr>
    );
  }

  return (
    <>
      {items.map((item, index) => (
        <MediaSelectionRow
          key={item.id}
          item={item}
          eagerLoad={index < 8}
          detailIsLoading={detailIsLoading}
          onToggleRow={onToggleRow}
          checked={selection[item.id.toString()] ?? false}
          identitiesDataSource={identitiesDataSource}
          onRetryIdentities={onRetryIdentities}
        />
      ))}
    </>
  );
};

interface MediaSelectionRowProps {
  item: WorkbenchMediaItem;
  eagerLoad: boolean;
  detailIsLoading: boolean;
  onToggleRow: (item: WorkbenchMediaItem, checked: boolean) => void;
  checked: boolean;
  identitiesDataSource?: DataSource;
  onRetryIdentities?: () => void;
}

const MediaSelectionRow = ({
  item,
  eagerLoad,
  detailIsLoading,
  onToggleRow,
  checked,
  identitiesDataSource,
  onRetryIdentities,
}: MediaSelectionRowProps): React.JSX.Element => {
  const thumbDimensions = item.thumbnailDimensions;
  const detailReady = [item.mimeType, item.updatedAt, item.dimensions].some((value) => value != null && value !== '');

  return (
    <tr>
      <td>
        <Checkbox
          ariaLabel={sprintf(__('Select media item %s', 'alt-context'), item.title)}
          checked={checked}
          onCheckedChange={(nextChecked: boolean) => onToggleRow(item, nextChecked)}
        />
      </td>
      <td className="acx-media-selection__thumb-cell">
        <a href={mediaEditUrl(item.id)}>
          {item.thumbnailUrl ? (
            <img
              src={item.thumbnailUrl}
              srcSet={item.thumbnailSrcset ?? undefined}
              sizes={item.thumbnailSizes ?? undefined}
              alt={item.altText ?? item.title}
              className="acx-media-selection__thumb acx-media-selection__thumb--thumb"
              loading={eagerLoad ? 'eager' : 'lazy'}
              fetchPriority={eagerLoad ? 'high' : 'auto'}
              decoding="async"
              width={thumbDimensions?.width ?? undefined}
              height={thumbDimensions?.height ?? undefined}
            />
          ) : (
            <span className="acx-media-selection__thumb acx-media-selection__thumb--placeholder" />
          )}
        </a>
      </td>
      <td className="acx-media-selection__details">
        <a href={mediaEditUrl(item.id)} className="acx-media-selection__link">
          <p className="acx-media-selection__media-title">
            {item.title}
            <span className="acx-media-selection__media-id"> (#{item.id})</span>
          </p>
        </a>
        <MediaAltInlineEditor mediaId={item.id} altText={item.altText ?? null} />
        <MediaAltSuggest mediaId={item.id} />
        <div className="acx-media-selection__detail-meta" aria-live="polite">
          {detailReady ? (
            <>
              {item.mimeType ? <span className="acx-media-selection__detail-chip">{item.mimeType}</span> : null}
              {item.dimensions ? (
                <span className="acx-media-selection__detail-chip">
                  {sprintf(__('%d × %d px', 'alt-context'), item.dimensions.width ?? 0, item.dimensions.height ?? 0)}
                </span>
              ) : null}
            </>
          ) : detailIsLoading ? (
            <>
              <span className="acx-media-selection__detail-chip acx-media-selection__detail-chip--skeleton" />
              <span className="acx-media-selection__detail-chip acx-media-selection__detail-chip--skeleton" />
            </>
          ) : (
            <span className="acx-media-selection__detail-chip acx-media-selection__detail-chip--muted">
              {__('Details unavailable', 'alt-context')}
            </span>
          )}
        </div>
        <IdentityClusterList
          identities={item.identities ?? []}
          dataSource={identitiesDataSource}
          onRetry={onRetryIdentities}
        />
      </td>
      <td>
        {item.tags.length === 0 ? (
          <span className="acx-media-selection__tag acx-media-selection__tag--empty">
            {__('No tags', 'alt-context')}
          </span>
        ) : (
          <ul className="acx-media-selection__tags">
            {item.tags.map((tag) => (
              <li key={`${item.id}-${tag}`}>{tag}</li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
};

const MediaSelectionSkeletonRow = (): React.JSX.Element => (
  <tr className="acx-media-selection__skeleton-row" aria-hidden="true">
    <td>
      <span className="acx-media-selection__skeleton acx-media-selection__skeleton--checkbox" />
    </td>
    <td className="acx-media-selection__thumb-cell">
      <span className="acx-media-selection__thumb acx-media-selection__thumb--skeleton" />
    </td>
    <td>
      <div className="acx-media-selection__skeleton-stack">
        <span className="acx-media-selection__skeleton acx-media-selection__skeleton--title" />
        <span className="acx-media-selection__skeleton acx-media-selection__skeleton--text" />
        <div className="acx-media-selection__detail-meta">
          <span className="acx-media-selection__detail-chip acx-media-selection__detail-chip--skeleton" />
          <span className="acx-media-selection__detail-chip acx-media-selection__detail-chip--skeleton" />
        </div>
      </div>
    </td>
    <td>
      <span className="acx-media-selection__skeleton acx-media-selection__skeleton--tag" />
    </td>
  </tr>
);