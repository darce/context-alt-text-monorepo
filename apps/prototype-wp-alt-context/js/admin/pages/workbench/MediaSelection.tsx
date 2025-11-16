import { ChangeEvent } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';
import { mediaEditUrl } from './Panels';

type Props = {
  items: WorkbenchMediaItem[];
  isLoading: boolean;
  isError: boolean;
  onRetry?: () => void;
  statusMessage: string;
  searchQuery: string;
  onSearchChange: (event: ChangeEvent<HTMLInputElement>) => void;
  selection: Record<string, boolean>;
  onToggleRow: (item: WorkbenchMediaItem, checked: boolean) => void;
  onToggleAll: (checked: boolean) => void;
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  areAllPageRowsChecked: boolean;
};

export const MediaSelection = ({
  items,
  isLoading,
  isError,
  onRetry,
  statusMessage,
  searchQuery,
  onSearchChange,
  selection,
  onToggleRow,
  onToggleAll,
  currentPage,
  totalPages,
  onPageChange,
  areAllPageRowsChecked,
}: Props): React.JSX.Element => (
  <div className="acx-media-selection">
    <MediaSelectionToolbar
      searchQuery={searchQuery}
      onSearchChange={onSearchChange}
      statusMessage={statusMessage}
      isError={isError}
      onRetry={onRetry}
    />

    <table className="acx-media-selection__table">
      <thead>
        <tr>
          <th scope="col">
            <input
              type="checkbox"
              aria-label={__('Select all items on this page', 'alt-context')}
              checked={areAllPageRowsChecked}
              onChange={(event) => onToggleAll(event.target.checked)}
              disabled={items.length === 0}
            />
          </th>
          <th scope="col">{__('Preview', 'alt-context')}</th>
          <th scope="col">{__('Details', 'alt-context')}</th>
          <th scope="col">{__('Tags', 'alt-context')}</th>
        </tr>
      </thead>
      <tbody>{renderRows({ items, isLoading, onToggleRow, selection })}</tbody>
    </table>

    <MediaSelectionPagination currentPage={currentPage} totalPages={totalPages} onPageChange={onPageChange} />
  </div>
);

type MediaSelectionToolbarProps = {
  searchQuery: string;
  onSearchChange: (event: ChangeEvent<HTMLInputElement>) => void;
  statusMessage: string;
  isError: boolean;
  onRetry?: () => void;
};

const MediaSelectionToolbar = ({
  searchQuery,
  onSearchChange,
  statusMessage,
  isError,
  onRetry,
}: MediaSelectionToolbarProps) => (
  <div className="acx-media-selection__toolbar">
    <label htmlFor="acx-media-search" className="acx-media-selection__search-label">
      {__('Search media', 'alt-context')}
    </label>
    <input
      id="acx-media-search"
      className="acx-media-selection__search"
      type="search"
      placeholder={__('Filter by alt text or tag…', 'alt-context')}
      value={searchQuery}
      onChange={onSearchChange}
    />

    <div className="acx-media-selection__toolbar-actions">
      <span className="acx-media-selection__status">{statusMessage}</span>
      {isError && onRetry && (
        <button type="button" className="acx-media-selection__retry" onClick={onRetry}>
          {__('Retry', 'alt-context')}
        </button>
      )}
    </div>
  </div>
);

type MediaSelectionPaginationProps = {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
};

const MediaSelectionPagination = ({ currentPage, totalPages, onPageChange }: MediaSelectionPaginationProps) => (
  <div className="acx-media-selection__pagination" role="navigation" aria-label={__('Media pagination', 'alt-context')}>
    <button type="button" onClick={() => onPageChange(Math.max(1, currentPage - 1))} disabled={currentPage === 1}>
      {__('Previous', 'alt-context')}
    </button>
    <span>
      {__('Page', 'alt-context')} {currentPage} {__('of', 'alt-context')} {totalPages}
    </span>
    <button
      type="button"
      onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
      disabled={currentPage === totalPages}
    >
      {__('Next', 'alt-context')}
    </button>
  </div>
);

const renderRows = ({
  items,
  isLoading,
  onToggleRow,
  selection,
}: {
  items: WorkbenchMediaItem[];
  isLoading: boolean;
  onToggleRow: (item: WorkbenchMediaItem, checked: boolean) => void;
  selection: Record<string, boolean>;
}) => {
  if (isLoading) {
    return (
      <tr>
        <td colSpan={4}>{__('Loading media…', 'alt-context')}</td>
      </tr>
    );
  }

  if (items.length === 0) {
    return (
      <tr>
        <td colSpan={4}>{__('No media matches your search.', 'alt-context')}</td>
      </tr>
    );
  }

  return items.map((item) => {
    const key = item.id.toString();
    return (
      <tr key={key}>
        <td>
          <input
            type="checkbox"
            aria-label={sprintf(__('Select media item %s', 'alt-context'), item.title)}
            checked={selection[key] ?? false}
            onChange={(event) => onToggleRow(item, event.target.checked)}
          />
        </td>
        <td className="acx-media-selection__thumb-cell">
          <a href={mediaEditUrl(item.id)}>
            {item.thumbnailUrl ? (
              <img
                src={item.thumbnailUrl}
                alt={item.altText ?? item.title}
                className="acx-media-selection__thumb acx-media-selection__thumb--thumb"
                loading="lazy"
              />
            ) : (
              <span className="acx-media-selection__thumb acx-media-selection__thumb--placeholder" />
            )}
          </a>
        </td>
        <td className="acx-media-selection__details">
          <a href={mediaEditUrl(item.id)} className="acx-media-selection__link">
            <p className="acx-media-selection__media-title">{item.title}</p>
            <p className="acx-media-selection__media-alt">{item.altText ?? __('No alt text yet', 'alt-context')}</p>
          </a>
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
  });
};
