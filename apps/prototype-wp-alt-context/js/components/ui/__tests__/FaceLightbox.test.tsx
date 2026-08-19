import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { FaceLightbox } from '../FaceLightbox';
import { ReviewCardLightbox } from '../../../admin/pages/workbench/identity-clusters/ReviewCardLightbox';
import type { BoundingBox } from '../../../admin/api/recognition/types/identity';
import type { FaceOverlayIdentity } from '../FaceOverlayLayer';
import * as identityQueriesApi from '../../../admin/api/recognition/identityQueriesApi';
import { DATA_SOURCE } from '../../../admin/api/recognition/types/dataSource';

vi.mock('../../../admin/api/recognition/identityQueriesApi', () => ({
  fetchMediaIdentities: vi.fn(),
}));

const fetchMediaIdentities = vi.mocked(identityQueriesApi.fetchMediaIdentities);

const bbox: BoundingBox = { x: 10, y: 20, width: 40, height: 50 };
const mediaUrl = 'https://example.com/face-source.jpg';

const overlayIdentities: FaceOverlayIdentity[] = [
  {
    identity_id: 'reviewed',
    bbox: { x: 10, y: 20, width: 40, height: 50 },
    cluster_label: null,
    is_auto_label: true,
  },
  {
    identity_id: 'other',
    bbox: { x: 120, y: 30, width: 30, height: 30 },
    cluster_label: 'Alex',
    is_auto_label: false,
  },
];

const createClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

const renderLightbox = (ui: React.ReactElement, client = createClient()) =>
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);

describe('FaceLightbox', () => {
  let resizeObserverCallback: ResizeObserverCallback | null = null;

  beforeEach(() => {
    resizeObserverCallback = null;
    fetchMediaIdentities.mockReset();
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(cb: ResizeObserverCallback) {
          resizeObserverCallback = cb;
        }
        observe(): void {
          if (resizeObserverCallback) {
            resizeObserverCallback([], this);
          }
        }
        unobserve(): void {
          return undefined;
        }
        disconnect(): void {
          return undefined;
        }
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('opens with dialog accessible name and closes via Close', async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    const { rerender } = renderLightbox(
      <FaceLightbox
        open
        onOpenChange={onOpenChange}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Alice face"
      />,
    );

    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);

    rerender(
      <QueryClientProvider client={createClient()}>
        <FaceLightbox
          open={false}
          onOpenChange={onOpenChange}
          mediaUrl={mediaUrl}
          bbox={bbox}
          label="Alice face"
        />
      </QueryClientProvider>,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders bbox overlay rect after image load', async () => {
    renderLightbox(<FaceLightbox open onOpenChange={vi.fn()} mediaUrl={mediaUrl} bbox={bbox} label="Face" />);

    const frame = document.querySelector('.acx-review-card-lightbox__frame');
    expect(frame).toBeInstanceOf(HTMLElement);
    Object.defineProperty(frame, 'clientWidth', { configurable: true, value: 400 });
    Object.defineProperty(frame, 'clientHeight', { configurable: true, value: 300 });
    if (resizeObserverCallback) {
      resizeObserverCallback([], {} as ResizeObserver);
    }

    const img = screen.getByRole('img', { name: 'Face' });
    Object.defineProperty(img, 'naturalWidth', { configurable: true, value: 200 });
    Object.defineProperty(img, 'naturalHeight', { configurable: true, value: 150 });
    fireEvent.load(img);

    await waitFor(() => {
      expect(document.querySelector('.acx-review-card-lightbox__bbox')).toBeInTheDocument();
    });
  });

  const loadFramedImage = (alt = 'Face'): void => {
    const frame = document.querySelector('.acx-review-card-lightbox__frame');
    expect(frame).toBeInstanceOf(HTMLElement);
    Object.defineProperty(frame, 'clientWidth', { configurable: true, value: 400 });
    Object.defineProperty(frame, 'clientHeight', { configurable: true, value: 300 });
    if (resizeObserverCallback) {
      resizeObserverCallback([], {} as ResizeObserver);
    }
    const img = screen.getByRole('img', { name: alt });
    Object.defineProperty(img, 'naturalWidth', { configurable: true, value: 200 });
    Object.defineProperty(img, 'naturalHeight', { configurable: true, value: 150 });
    fireEvent.load(img);
  };

  it('renders FaceOverlayLayer for every identity and a ? chip on the reviewed face', async () => {
    renderLightbox(
      <FaceLightbox
        open
        onOpenChange={vi.fn()}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Face"
        identities={overlayIdentities}
        activeFaceId="reviewed"
      />,
    );

    loadFramedImage();

    await waitFor(() => {
      expect(screen.getByTestId('acx-face-overlay-layer')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Face under review' })).toHaveTextContent('?');
    expect(screen.getByRole('button', { name: 'Alex' })).toBeInTheDocument();
    expect(document.querySelector('.acx-review-card-lightbox__bbox')).not.toBeInTheDocument();
    expect(fetchMediaIdentities).not.toHaveBeenCalled();
  });

  it('falls back to the single bbox when identities is empty', async () => {
    renderLightbox(
      <FaceLightbox
        open
        onOpenChange={vi.fn()}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Face"
        identities={[]}
        activeFaceId="reviewed"
      />,
    );

    loadFramedImage();

    await waitFor(() => {
      expect(document.querySelector('.acx-review-card-lightbox__bbox')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('acx-face-overlay-layer')).not.toBeInTheDocument();
  });

  it('does not fetch media identities while closed even when mediaId is positive', () => {
    renderLightbox(
      <FaceLightbox
        open={false}
        onOpenChange={vi.fn()}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Face"
        mediaId={42}
        activeFaceId="reviewed"
      />,
    );

    expect(fetchMediaIdentities).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('does not fetch when mediaId is missing or not positive', () => {
    renderLightbox(
      <FaceLightbox open onOpenChange={vi.fn()} mediaUrl={mediaUrl} bbox={bbox} label="Face" mediaId={0} />,
    );
    expect(fetchMediaIdentities).not.toHaveBeenCalled();
  });

  it('fetches media identities only while open with a positive mediaId', async () => {
    fetchMediaIdentities.mockResolvedValue({
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
      identities_by_media: {
        '42': [
          {
            identity_id: 'reviewed',
            media_id: 42,
            similarity: null,
            confidence: 0.9,
            bbox: { x: 10, y: 20, width: 40, height: 50 },
            cluster_id: null,
            cluster_label: null,
            is_auto_label: true,
          },
          {
            identity_id: 'other',
            media_id: 42,
            similarity: null,
            confidence: 0.8,
            bbox: { x: 120, y: 30, width: 30, height: 30 },
            cluster_id: 'c-alex',
            cluster_label: 'Alex',
            is_auto_label: false,
          },
        ],
      },
    });

    renderLightbox(
      <FaceLightbox
        open
        onOpenChange={vi.fn()}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Face"
        mediaId={42}
        activeFaceId="reviewed"
      />,
    );

    loadFramedImage();

    await waitFor(() => {
      expect(fetchMediaIdentities).toHaveBeenCalledWith([42]);
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Face under review' })).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Alex' })).toBeInTheDocument();
  });

  it('keeps the photo and single-face highlight when the identities fetch fails', async () => {
    fetchMediaIdentities.mockRejectedValue(new Error('timeout'));

    renderLightbox(
      <FaceLightbox
        open
        onOpenChange={vi.fn()}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Face"
        mediaId={42}
        activeFaceId="reviewed"
      />,
    );

    loadFramedImage();

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Could not load other faces.');
    });
    expect(screen.getByRole('img', { name: 'Face' })).toBeInTheDocument();
    expect(document.querySelector('.acx-review-card-lightbox__bbox')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeInTheDocument();
  });

  it('invokes onReviewFaceActivate when the ? chip is activated', async () => {
    const user = userEvent.setup();
    const onReviewFaceActivate = vi.fn();
    renderLightbox(
      <FaceLightbox
        open
        onOpenChange={vi.fn()}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Face"
        identities={overlayIdentities}
        activeFaceId="reviewed"
        onReviewFaceActivate={onReviewFaceActivate}
      />,
    );

    loadFramedImage();
    await user.click(await screen.findByRole('button', { name: 'Face under review' }));
    expect(onReviewFaceActivate).toHaveBeenCalledWith('reviewed');
  });

  it('renders reviewNaming inside the open dialog', async () => {
    renderLightbox(
      <FaceLightbox
        open
        onOpenChange={vi.fn()}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Face"
        reviewNaming={<div>Lightbox naming surface</div>}
      />,
    );

    expect(screen.getByRole('dialog')).toContainElement(screen.getByText('Lightbox naming surface'));
  });

  it('announces loading while identities are in flight and still shows the photo', async () => {

    renderLightbox(
      <FaceLightbox
        open
        onOpenChange={vi.fn()}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Face"
        mediaId={42}
        activeFaceId="reviewed"
      />,
    );

    loadFramedImage();

    expect(screen.getByRole('img', { name: 'Face' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Loading faces…');
  });
});

describe('ReviewCardLightbox shim', () => {
  it('renders FaceLightbox via shim import path', () => {
    renderLightbox(
      <ReviewCardLightbox
        open
        onOpenChange={vi.fn()}
        mediaUrl={mediaUrl}
        bbox={bbox}
        label="Shim face"
      />,
    );

    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();
    expect(document.querySelector('.acx-review-card-lightbox')).toBeInTheDocument();
  });
});
