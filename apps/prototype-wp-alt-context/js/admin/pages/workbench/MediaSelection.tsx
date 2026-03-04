import { ChangeEvent } from 'react';
import * as Select from '@radix-ui/react-select';
import { Check, ChevronDown } from 'lucide-react';
import { __, sprintf } from '@wordpress/i18n';
import type { WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';
import type { WorkbenchMediaStatus } from '../../api/workbenchMediaApi';
import { IdentityClusterList } from './identity-clusters';
import { mediaEditUrl } from './Panels';

import { Checkbox } from '../../../components/ui/checkbox';
import { useWorkbenchContext } from './WorkbenchContext';

export const MediaSelection = (): React.JSX.Element => {
  const {
    mediaQuery,
    statusMessage,
    searchQuery,
    handleSearchChange: onSearchChange,
    statusFilter,
    handleStatusChange: onStatusFilterChange,
    selection,
    toggleRow,
    toggleAll,
    currentPage,
    perPage,
    setPerPage: onPerPageChange,
    setCurrentPage: onPageChange,
  } = useWorkbenchContext();

  const mediaData = mediaQuery.data;
  const items = mediaQuery.itemsWithIdentities ?? mediaData?.items ?? [];
  const isLoading = mediaQuery.isPending && items.length === 0;
  const isError = mediaQuery.isError;
  const onRetry = () => void mediaQuery.refetch();
  const totalPages = mediaData?.totalPages ?? 1;
  const areAllPageRowsChecked = items.length > 0 && items.every((item: WorkbenchMediaItem) => selection[item.id.toString()]);
  const identityQuery = mediaQuery.identitiesQuery;

  const onToggleAll = (checked: boolean) => toggleAll(items, checked);
  const onToggleRow = (item: WorkbenchMediaItem, checked: boolean) => toggleRow(item, checked);
  const identityStatusMessage = identityQuery.isLoading
    ? __('Loading identity data…', 'alt-context')
    : identityQuery.isError
      ? __('Unable to load identity data.', 'alt-context')
      : null;

  return (
    <>
      <div className="acx-media-selection">
        <MediaSelectionToolbar
          searchQuery={searchQuery}
          onSearchChange={onSearchChange}
          statusFilter={statusFilter}
          onStatusFilterChange={onStatusFilterChange}
          statusMessage={statusMessage}
          isError={isError}
          onRetry={onRetry}
        />

        <table className="acx-media-selection__table">
          <thead>
            <tr>
              <th scope="col">
                <Checkbox
                  ariaLabel={__('Select all items on this page', 'alt-context')}
                  checked={areAllPageRowsChecked}
                  onCheckedChange={(checked: boolean) => onToggleAll(checked)}
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

        <MediaSelectionPagination
          currentPage={currentPage}
          totalPages={totalPages}
          perPage={perPage}
          onPerPageChange={onPerPageChange}
          onPageChange={onPageChange}
        />
      </div>
      {identityStatusMessage && (
        <div className="acx-identity-status">
          <span>{identityStatusMessage}</span>
          {identityQuery.isError && (
            <button type="button" className="acx-identity-status__retry" onClick={() => void identityQuery.refetch()}>
              {__('Retry', 'alt-context')}
            </button>
          )}
        </div>
      )}
    </>
  );
};

interface MediaSelectionToolbarProps {
  searchQuery: string;
  onSearchChange: (event: ChangeEvent<HTMLInputElement>) => void;
  statusFilter: WorkbenchMediaStatus;
  onStatusFilterChange: (status: WorkbenchMediaStatus) => void;
  statusMessage: string;
  isError: boolean;
  onRetry?: () => void;
}

const MediaSelectionToolbar = ({
  searchQuery,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
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
    <div className="acx-media-selection__status-filter">
      <span id="acx-media-status-label">{__('Status', 'alt-context')}</span>
      <Select.Root value={statusFilter} onValueChange={(value) => onStatusFilterChange(value as WorkbenchMediaStatus)}>
        <Select.Trigger
          className="acx-media-selection__status-filter-trigger"
          aria-labelledby="acx-media-status-label"
        >
          <Select.Value />
          <Select.Icon className="acx-media-selection__status-filter-icon">
            <ChevronDown aria-hidden="true" size={16} />
          </Select.Icon>
        </Select.Trigger>
        <Select.Portal>
          <Select.Content className="acx-media-selection__status-filter-content" position="popper" sideOffset={6}>
            <Select.Viewport className="acx-media-selection__status-filter-viewport">
              <Select.Item value="all" className="acx-media-selection__status-filter-item">
                <Select.ItemText>{__('All media', 'alt-context')}</Select.ItemText>
                <Select.ItemIndicator className="acx-media-selection__status-filter-indicator">
                  <Check aria-hidden="true" size={14} />
                </Select.ItemIndicator>
              </Select.Item>
              <Select.Item value="missing" className="acx-media-selection__status-filter-item">
                <Select.ItemText>{__('Missing alt text', 'alt-context')}</Select.ItemText>
                <Select.ItemIndicator className="acx-media-selection__status-filter-indicator">
                  <Check aria-hidden="true" size={14} />
                </Select.ItemIndicator>
              </Select.Item>
            </Select.Viewport>
          </Select.Content>
        </Select.Portal>
      </Select.Root>
    </div>

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

interface MediaSelectionPaginationProps {
  currentPage: number;
  totalPages: number;
  perPage: number;
  onPerPageChange: (perPage: number) => void;
  onPageChange: (page: number) => void;
}

const MEDIA_PAGE_SIZES = [10, 50, 100] as const;

const MediaSelectionPagination = ({
  currentPage,
  totalPages,
  perPage,
  onPerPageChange,
  onPageChange,
}: MediaSelectionPaginationProps) => {
  const boundedTotalPages = Math.max(1, totalPages);
  const boundedCurrentPage = Math.min(Math.max(1, currentPage), boundedTotalPages);

  const handlePerPageChange = (value: string) => {
    const selected = Number(value);
    if (!Number.isFinite(selected)) {
      return;
    }
    onPerPageChange(selected);
  };

  return (
    <div
      className="acx-media-selection__pagination"
      role="navigation"
      aria-label={__('Media pagination', 'alt-context')}
    >
      <button
        type="button"
        onClick={() => onPageChange(Math.max(1, boundedCurrentPage - 1))}
        disabled={boundedCurrentPage <= 1}
      >
        {__('Previous', 'alt-context')}
      </button>
      <span>
        {__('Page', 'alt-context')} {boundedCurrentPage} {__('of', 'alt-context')} {boundedTotalPages}
      </span>
      <button
        type="button"
        onClick={() => onPageChange(Math.min(boundedTotalPages, boundedCurrentPage + 1))}
        disabled={boundedCurrentPage >= boundedTotalPages}
      >
        {__('Next', 'alt-context')}
      </button>
      <div className="acx-media-selection__page-size">
        <span id="acx-media-page-size-label">{__('Images per page', 'alt-context')}</span>
        <Select.Root value={String(perPage)} onValueChange={handlePerPageChange}>
          <Select.Trigger
            className="acx-media-selection__page-size-trigger"
            aria-labelledby="acx-media-page-size-label"
          >
            <Select.Value />
            <Select.Icon className="acx-media-selection__page-size-icon">
              <ChevronDown aria-hidden="true" size={16} />
            </Select.Icon>
          </Select.Trigger>
          <Select.Portal>
            <Select.Content className="acx-media-selection__page-size-content" position="popper" sideOffset={6}>
              <Select.Viewport className="acx-media-selection__page-size-viewport">
                {MEDIA_PAGE_SIZES.map((size) => (
                  <Select.Item key={size} value={String(size)} className="acx-media-selection__page-size-item">
                    <Select.ItemText>{size}</Select.ItemText>
                    <Select.ItemIndicator className="acx-media-selection__page-size-indicator">
                      <Check aria-hidden="true" size={14} />
                    </Select.ItemIndicator>
                  </Select.Item>
                ))}
              </Select.Viewport>
            </Select.Content>
          </Select.Portal>
        </Select.Root>
      </div>
    </div>
  );
};

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
  if (isLoading && items.length === 0) {
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

  return items.map((item, index) => {
    const key = item.id.toString();
    const eagerLoad = index < 8;
    const thumbDimensions = item.thumbnailDimensions;
    return (
      <tr key={key}>
        <td>
          <Checkbox
            ariaLabel={sprintf(__('Select media item %s', 'alt-context'), item.title)}
            checked={selection[key] ?? false}
            onCheckedChange={(checked: boolean) => onToggleRow(item, checked)}
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
            <p className="acx-media-selection__media-alt">{item.altText ?? __('No alt text yet', 'alt-context')}</p>
          </a>
          <IdentityClusterList identities={item.identities ?? []} />
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
