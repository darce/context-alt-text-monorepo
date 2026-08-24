import { useCallback, useRef, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';
import type { DataSource } from '../../api/recognition/types';
import { Checkbox } from '../../../components/ui/checkbox';
import { decodeHtmlEntities } from '../../utils/decodeHtmlEntities';
import { IdentityClusterList } from './identity-clusters';
import { MediaAltInlineEditor } from './MediaAltInlineEditor';
import { MediaAltSuggest } from './MediaAltSuggest';
import { mediaEditUrl } from './Panels';
import { EmptyState, EmptyStateVariant } from '../../components/ui/EmptyState';

/** Who may hold the row's polite region or commit lock. */
export type RowPoliteOwner = 'editor' | 'suggest';

/**
 * Row commit-lock primitives [S2c-4b-ii BR-01]. Exported so a third simulated
 * claimant can exercise compare-and-set without driving the full UI — the defect
 * (unconditional begin) is unreachable through the two real surfaces that already
 * refuse when peerCommitPending is true.
 *
 * Claim result is decided on a ref so beginCommit can return synchronously.
 * React may defer useState updaters; a side-effect flag inside setState is not
 * a reliable "did I win?" signal. State still drives peerCommitPending paint.
 */
export const useRowCommitLock = (): {
  commitOwner: RowPoliteOwner | null;
  beginCommit: (owner: RowPoliteOwner) => boolean;
  endCommit: (owner: RowPoliteOwner) => void;
} => {
  const [commitOwner, setCommitOwner] = useState<RowPoliteOwner | null>(null);
  const commitOwnerRef = useRef<RowPoliteOwner | null>(null);

  // Compare-and-set: claim only when free. Returns whether this caller won.
  // Exclusivity lives here — not in each caller's peerCommitPending guard.
  const beginCommit = useCallback((owner: RowPoliteOwner): boolean => {
    if (commitOwnerRef.current !== null) {
      return false;
    }
    commitOwnerRef.current = owner;
    setCommitOwner(owner);
    return true;
  }, []);

  // Compare-and-clear: only the holding owner releases the lock.
  const endCommit = useCallback((owner: RowPoliteOwner): void => {
    if (commitOwnerRef.current !== owner) {
      return;
    }
    commitOwnerRef.current = null;
    setCommitOwner(null);
  }, []);

  return { commitOwner, beginCommit, endCommit };
};

interface MediaSelectionTableBodyProps {
  items: WorkbenchMediaItem[];
  isLoading: boolean;
  detailIsLoading: boolean;
  onToggleRow: (item: WorkbenchMediaItem, checked: boolean) => void;
  selection: Record<string, boolean>;
  identitiesDataSource?: DataSource;
  onRetryIdentities?: () => void;
  onClearSearch: () => void;
}

export const MediaSelectionTableBody = ({
  items,
  isLoading,
  detailIsLoading,
  onToggleRow,
  selection,
  identitiesDataSource,
  onRetryIdentities,
  onClearSearch,
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
        <td colSpan={4}>
          <EmptyState
            variant={EmptyStateVariant.EMPTY}
            heading={__('No media matches your search.', 'alt-context')}
            body={__('Clear the search to return to the media library.', 'alt-context')}
            action={{ label: __('Clear search', 'alt-context'), onClick: onClearSearch }}
            headingLevel={3}
          />
        </td>
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

  // One correction in flight per row (S2c-4b-i / S2c-4b-ii). Owner-tagged like
  // the polite region: begin is exclusive compare-and-set, end is
  // compare-and-clear so a late sibling settle cannot clear another owner's lock.
  const { commitOwner, beginCommit, endCommit } = useRowCommitLock();

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

  const editorAnnounce = useCallback((message: string): void => announcePolite('editor', message), [announcePolite]);
  const editorClear = useCallback((): void => clearPolite('editor'), [clearPolite]);
  const suggestAnnounce = useCallback((message: string): void => announcePolite('suggest', message), [announcePolite]);
  const suggestClear = useCallback((): void => clearPolite('suggest'), [clearPolite]);
  // beginCommit returns whether the claim won — surfaces must not write on false.
  const editorCommitStart = useCallback((): boolean => beginCommit('editor'), [beginCommit]);
  const editorCommitEnd = useCallback((): void => endCommit('editor'), [endCommit]);
  const suggestCommitStart = useCallback((): boolean => beginCommit('suggest'), [beginCommit]);
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
        <a
          href={mediaEditUrl(item.id)}
          aria-label={sprintf(__('Edit %s', 'alt-context'), item.title)}
        >
          {item.thumbnailUrl ? (
            <img
              src={item.thumbnailUrl}
              srcSet={item.thumbnailSrcset ?? undefined}
              sizes={item.thumbnailSizes ?? undefined}
              alt={
                // Prefer real alt over a leftover decorative marker (same
                // precedence as DescriptionCandidateService: has_alt_text wins).
                // Empty alt only when decorative AND altText is null. [WBUX-5-R1-01][A11Y-02]
                item.altText != null
                  ? decodeHtmlEntities(item.altText)
                  : item.isDecorative
                    ? ''
                    : item.title
              }
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
          title={item.title}
          isDecorative={item.isDecorative === true}
          onPoliteAnnounce={editorAnnounce}
          onPoliteClear={editorClear}
          peerCommitPending={commitOwner === 'suggest'}
          onCommitStart={editorCommitStart}
          onCommitEnd={editorCommitEnd}
        />
        <MediaAltSuggest
          mediaId={item.id}
          committedAlt={item.altText ?? null}
          title={item.title}
          isDecorative={item.isDecorative === true}
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
                  {sprintf(__('%1$d × %2$d px', 'alt-context'), item.dimensions.width ?? 0, item.dimensions.height ?? 0)}
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
