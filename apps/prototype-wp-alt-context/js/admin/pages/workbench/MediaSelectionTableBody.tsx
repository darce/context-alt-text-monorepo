import { useCallback, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';
import type { DataSource } from '../../api/recognition/types';
import { Checkbox } from '../../../components/ui/checkbox';
import { decodeHtmlEntities } from '../../utils/decodeHtmlEntities';
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

/** Who last wrote the row's polite live region — used for compare-and-clear. */
type RowPoliteOwner = 'editor' | 'suggest';

interface RowPoliteState {
  owner: RowPoliteOwner | null;
  message: string;
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

  // One persistent polite region per row (S2c-4a). Announce is last-writer-wins;
  // clear is compare-and-clear so a sibling's blur-retirement cannot wipe a
  // message it does not own (same principle as DescriptionHistoryPage's
  // per-row correctionErrors map [RLSE-05]).
  const [polite, setPolite] = useState<RowPoliteState>({ owner: null, message: '' });

  // One correction in flight per row (S2c-4b-i). Owner-tagged like the polite
  // region: begin is exclusive, end is compare-and-clear so a late sibling
  // settle cannot clear another owner's lock.
  const [commitOwner, setCommitOwner] = useState<RowPoliteOwner | null>(null);

  const announcePolite = useCallback((owner: RowPoliteOwner, message: string): void => {
    setPolite({ owner, message });
  }, []);

  const clearPolite = useCallback((owner: RowPoliteOwner): void => {
    setPolite((current) => {
      if (current.owner !== owner) {
        return current;
      }
      return { owner: null, message: '' };
    });
  }, []);

  const beginCommit = useCallback((owner: RowPoliteOwner): void => {
    setCommitOwner(owner);
  }, []);

  const endCommit = useCallback((owner: RowPoliteOwner): void => {
    setCommitOwner((current) => (current === owner ? null : current));
  }, []);

  const editorAnnounce = useCallback((message: string): void => announcePolite('editor', message), [announcePolite]);
  const editorClear = useCallback((): void => clearPolite('editor'), [clearPolite]);
  const suggestAnnounce = useCallback((message: string): void => announcePolite('suggest', message), [announcePolite]);
  const suggestClear = useCallback((): void => clearPolite('suggest'), [clearPolite]);
  const editorCommitStart = useCallback((): void => beginCommit('editor'), [beginCommit]);
  const editorCommitEnd = useCallback((): void => endCommit('editor'), [endCommit]);
  const suggestCommitStart = useCallback((): void => beginCommit('suggest'), [beginCommit]);
  const suggestCommitEnd = useCallback((): void => endCommit('suggest'), [endCommit]);

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
              alt={item.altText != null ? decodeHtmlEntities(item.altText) : item.title}
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
        {/*
          Row-owned polite region [S2c-4a / A11Y-08 / BR-32]. Always mounted in a
          stable position, empty while quiet. Editor and Suggest announce through
          props — no context provider for a two-consumer one-level hop.
        */}
        <div
          role="status"
          aria-live="polite"
          className="screen-reader-text"
          data-testid="media-selection-row-status"
        >
          {polite.message}
        </div>
        <MediaAltInlineEditor
          mediaId={item.id}
          altText={item.altText ?? null}
          onPoliteAnnounce={editorAnnounce}
          onPoliteClear={editorClear}
          peerCommitPending={commitOwner === 'suggest'}
          onCommitStart={editorCommitStart}
          onCommitEnd={editorCommitEnd}
        />
        <MediaAltSuggest
          mediaId={item.id}
          committedAlt={item.altText ?? null}
          onPoliteAnnounce={suggestAnnounce}
          onPoliteClear={suggestClear}
          peerCommitPending={commitOwner === 'editor'}
          onCommitStart={suggestCommitStart}
          onCommitEnd={suggestCommitEnd}
        />
        {/* detail-meta is metadata loading, not an operator result — not a live region. */}
        <div className="acx-media-selection__detail-meta">
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
