import { useQuery } from '@tanstack/react-query';

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

type Params = {
	page: number;
	perPage: number;
	search?: string;
	enabled: boolean;
};

export const useWorkbenchMedia = ({ page, perPage, search, enabled }: Params) =>
	useQuery<WorkbenchMediaResponse, Error>({
		queryKey: ['workbench-media', { page, perPage, search }],
		queryFn: () => fetchWorkbenchMedia({ page, perPage, search }),
		placeholderData: (previousData) => previousData,
		enabled,
	});

type FetchParams = {
	page: number;
	perPage: number;
	search?: string;
};

const fetchWorkbenchMedia = async ({
	page,
	perPage,
	search,
}: FetchParams): Promise<WorkbenchMediaResponse> => {
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

export type { WorkbenchMediaItem, WorkbenchMediaResponse };
