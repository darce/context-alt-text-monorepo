import React, { useMemo, useState } from 'react';
import type { ChangeEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { __, _n, sprintf } from '@wordpress/i18n';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';

type AltContextAdminConfig = {
	nonce: string;
	endpoints: {
		workbenchMedia: string;
	};
};

declare global {
	interface Window {
		AltContextAdmin?: AltContextAdminConfig;
	}
}

type WorkbenchMediaItem = {
	id: number;
	title: string;
	altText: string | null;
	status: 'missing' | 'complete';
	thumbnailUrl: string | null;
	mimeType: string;
	editUrl: string;
	tags: string[];
};

type WorkbenchMediaResponse = {
  items: WorkbenchMediaItem[];
  total: number;
  totalPages: number;
};

type FetchWorkbenchMediaParams = {
	page: number;
	perPage: number;
	search?: string;
};

const MEDIA_PAGE_SIZE = 10;
const TAB_IDS = {
	scan: 'scan',
	batch: 'batch',
	confirm: 'confirm',
} as const;
type WorkbenchTab = (typeof TAB_IDS)[keyof typeof TAB_IDS];

export const WorkbenchPage = (): React.JSX.Element => {
	const sections = useMemo(
		() => [
			{
				id: TAB_IDS.scan,
				label: __('Scan', 'alt-context'),
				title: __('Scan Media Queue', 'alt-context'),
				body: __(
					'Scan your library for images that still need descriptive metadata, filtering by status or search term.',
					'alt-context'
				),
				checklist: [
					__('Use search to filter by keyword or attachment ID.', 'alt-context'),
					__('Toggle “Missing Alt Text” to focus on gaps.', 'alt-context'),
					__('Batch-select up to 100 items per run.', 'alt-context'),
				],
			},
			{
				id: TAB_IDS.batch,
				label: __('Batch', 'alt-context'),
				title: __('Batch Operations', 'alt-context'),
				body: __(
					'Group the selected media, run recognition jobs, and prep face scans before publishing.',
					'alt-context'
				),
				checklist: [
					__('Trigger recognition runs or schedule background jobs.', 'alt-context'),
					__('Preview generated descriptions and confidence scores.', 'alt-context'),
					__('Edit copy inline before committing the change.', 'alt-context'),
				],
			},
			{
				id: TAB_IDS.confirm,
				label: __('Confirm', 'alt-context'),
				title: __('Confirm & Publish', 'alt-context'),
				body: __(
					'Compare before/after states, spot-check compliance, and push updates to WordPress media.',
					'alt-context'
				),
				checklist: [
					__('Highlight regressions or items needing manual follow-up.', 'alt-context'),
					__('Export audit logs for stakeholders.', 'alt-context'),
					__('Publish confirmed captions directly to the Media Library.', 'alt-context'),
				],
			},
		],
		[]
	);

	const [activeSection, setActiveSection] = useState<WorkbenchTab>(TAB_IDS.scan);
	const [searchQuery, setSearchQuery] = useState('');
	const [currentPage, setCurrentPage] = useState(1);
	const [selection, setSelection] = useState<Record<string, boolean>>({});
	const [selectedDetails, setSelectedDetails] = useState<Record<string, WorkbenchMediaItem>>({});

	const normalizedSearch = searchQuery.trim();

	const mediaQuery = useWorkbenchMedia({
		page: currentPage,
		perPage: MEDIA_PAGE_SIZE,
		search: normalizedSearch,
		enabled: activeSection === TAB_IDS.scan,
	});

	const mediaItems = mediaQuery.data?.items ?? [];
	const totalPages = mediaQuery.data?.totalPages ?? 1;
	const totalCount = mediaQuery.data?.total ?? 0;

	const allPageRowsChecked =
		mediaItems.length > 0 && mediaItems.every((item) => selection[item.id.toString()] === true);

	const selectedMedia = useMemo(
		() =>
			Object.entries(selection)
				.filter(([, isChecked]) => isChecked)
				.map(([key]) => selectedDetails[key])
				.filter((item): item is WorkbenchMediaItem => Boolean(item)),
		[selection, selectedDetails]
	);

	const statusMessage = useMemo(() => {
		if (mediaQuery.isFetching) {
			return __('Updating media queue…', 'alt-context');
		}

		if (mediaQuery.isError) {
			return __('Unable to load media. Please try again.', 'alt-context');
		}

		if (totalCount === 0) {
			return normalizedSearch
				? sprintf(__('No media found for “%s”.', 'alt-context'), normalizedSearch)
				: __('No media items match the current filters.', 'alt-context');
		}

		return sprintf(
			_n('Showing %d media item.', 'Showing %d media items.', totalCount, 'alt-context'),
			totalCount
		);
	}, [mediaQuery.isError, mediaQuery.isFetching, normalizedSearch, totalCount]);

	const handleSearchChange = (event: ChangeEvent<HTMLInputElement>): void => {
		setSearchQuery(event.target.value);
		setCurrentPage(1);
	};

	const handleToggleAll = (items: WorkbenchMediaItem[], checked: boolean): void => {
		setSelection((prev) => {
			const next = { ...prev };
			const nextDetails = { ...selectedDetails };

			items.forEach((item) => {
				const key = item.id.toString();
				if (checked) {
					next[key] = true;
					nextDetails[key] = item;
				} else {
					delete next[key];
					delete nextDetails[key];
				}
			});

			setSelectedDetails(nextDetails);
			return next;
		});
	};

	const handleRowToggle = (item: WorkbenchMediaItem, checked: boolean): void => {
		const key = item.id.toString();

		setSelection((prev) => {
			const next = { ...prev };
			if (checked) {
				next[key] = true;
			} else {
				delete next[key];
			}
			return next;
		});

		setSelectedDetails((prev) => {
			const next = { ...prev };
			if (checked) {
				next[key] = item;
			} else {
				delete next[key];
			}
			return next;
		});
	};

  return (
    <section className="acx-workbench" aria-labelledby="acx-workbench-title">
      <Tabs
        value={activeSection}
        onValueChange={(value) => setActiveSection(value as WorkbenchTab)}
        className="acx-workbench__tabs"
      >
        <TabsList className="acx-workbench__tabs-list" aria-label={__('Workbench steps', 'alt-context')}>
          {sections.map((section) => (
            <TabsTrigger
              key={section.id}
              value={section.id}
              className="acx-workbench__tabs-trigger"
              aria-label={section.title}
            >
              {section.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <div className="acx-workbench__panels">
          <TabsContent
            value={TAB_IDS.scan}
            className="acx-workbench__panel"
            aria-live="polite"
            aria-labelledby="acx-workbench-section-scan"
          >
            <h2 id="acx-workbench-section-scan">{sections[0].title}</h2>
            <p>{sections[0].body}</p>
            <MediaSelection
              items={mediaItems}
              isLoading={mediaQuery.isFetching && mediaQuery.isPreviousData}
              isError={mediaQuery.isError}
              onRetry={mediaQuery.isError ? () => mediaQuery.refetch() : undefined}
              statusMessage={statusMessage}
              searchQuery={searchQuery}
              onSearchChange={handleSearchChange}
              selection={selection}
              onToggleRow={handleRowToggle}
              onToggleAll={(checked) => handleToggleAll(mediaItems, checked)}
              currentPage={currentPage}
              totalPages={totalPages}
              onPageChange={setCurrentPage}
              areAllPageRowsChecked={allPageRowsChecked}
            />
          </TabsContent>

          <TabsContent
            value={TAB_IDS.batch}
            className="acx-workbench__panel"
            aria-live="polite"
            aria-labelledby="acx-workbench-section-batch"
          >
            <h2 id="acx-workbench-section-batch">{sections[1].title}</h2>
            <p>{sections[1].body}</p>
            <BatchPanel
              items={selectedMedia}
              onScanFaces={() => {
                // eslint-disable-next-line no-console
                console.info('Trigger face scan for media IDs:', selectedMedia.map((item) => item.id));
              }}
            />
          </TabsContent>

          <TabsContent
            value={TAB_IDS.confirm}
            className="acx-workbench__panel"
            aria-live="polite"
            aria-labelledby="acx-workbench-section-confirm"
          >
            <h2 id="acx-workbench-section-confirm">{sections[2].title}</h2>
            <p>{sections[2].body}</p>
            <ul className="acx-workbench__checklist">
              {sections[2].checklist.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </TabsContent>
        </div>
      </Tabs>
    </section>
  );
};

type MediaSelectionProps = {
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

const MediaSelection = ({
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
}: MediaSelectionProps): React.JSX.Element => {
	return (
		<div className="acx-media-selection">
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
						<th scope="col">{__('Alt text', 'alt-context')}</th>
						<th scope="col">{__('Tags', 'alt-context')}</th>
					</tr>
				</thead>
				<tbody>
					{isLoading ? (
						<tr>
							<td colSpan={4}>{__('Loading media…', 'alt-context')}</td>
						</tr>
					) : items.length === 0 ? (
						<tr>
							<td colSpan={4}>{__('No media matches your search.', 'alt-context')}</td>
						</tr>
					) : (
						items.map((item) => {
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
									<td>
										{item.thumbnailUrl ? (
											<img
												src={item.thumbnailUrl}
												alt={item.altText ?? item.title}
												width={48}
												height={48}
												className="acx-media-selection__thumb"
												loading="lazy"
											/>
										) : (
											<span className="acx-media-selection__thumb acx-media-selection__thumb--placeholder" />
										)}
									</td>
									<td>
										<p className="acx-media-selection__media-title">{item.title}</p>
										<p className="acx-media-selection__media-alt">
											{item.altText ?? __('No alt text yet', 'alt-context')}
										</p>
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
						})
					)}
				</tbody>
			</table>

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
		</div>
	);
};

const BatchPanel = ({
	items,
	onScanFaces,
}: {
	items: WorkbenchMediaItem[];
	onScanFaces: () => void;
}): React.JSX.Element => {
	if (items.length === 0) {
		return (
			<div className="acx-apply-panel">
				<p>{__('Select at least one media item in the previous step to continue.', 'alt-context')}</p>
			</div>
		);
	}

	return (
		<div className="acx-apply-panel">
			<p>
				{sprintf(
					_n('You have %d media item ready for analysis.', 'You have %d media items ready for analysis.', items.length, 'alt-context'),
					items.length
				)}
			</p>
			<ul className="acx-apply-panel__list">
				{items.map((item) => (
					<li key={item.id}>
						<strong>{item.title}</strong> — {item.altText ?? __('No alt text yet', 'alt-context')}
					</li>
				))}
			</ul>
			<button type="button" className="acx-apply-panel__scan" onClick={onScanFaces}>
				{__('Scan selected media for faces', 'alt-context')}
			</button>
		</div>
	);
};

const useWorkbenchMedia = ({
	page,
	perPage,
	search,
	enabled,
}: {
	page: number;
	perPage: number;
	search?: string;
	enabled: boolean;
}) =>
	useQuery<WorkbenchMediaResponse>({
		queryKey: ['workbench-media', { page, perPage, search }],
		queryFn: () => fetchWorkbenchMedia({ page, perPage, search }),
		keepPreviousData: true,
		enabled,
	});

const fetchWorkbenchMedia = async ({
	page,
	perPage,
	search,
}: FetchWorkbenchMediaParams): Promise<WorkbenchMediaResponse> => {
	const config = window.AltContextAdmin;
	if (!config?.endpoints?.workbenchMedia) {
		throw new Error('Workbench media endpoint is not available.');
	}

	const requestUrl = new URL(config.endpoints.workbenchMedia, window.location.origin);
	requestUrl.searchParams.set('page', String(page));
	requestUrl.searchParams.set('per_page', String(perPage));
	requestUrl.searchParams.set('status', 'missing');

	if (search) {
		requestUrl.searchParams.set('search', search);
	}

	const response = await fetch(requestUrl.toString(), {
		headers: {
			'X-WP-Nonce': config.nonce,
			Accept: 'application/json',
		},
		credentials: 'same-origin',
	});

	if (!response.ok) {
		throw new Error(`Request failed with status ${response.status}`);
	}

	return response.json();
};
