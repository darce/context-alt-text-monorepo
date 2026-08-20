import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { MediaIdentitiesResponse } from '../../admin/api/recognition/types/identity';
import * as recognitionApi from '../../admin/api/recognition/identityQueriesApi';
import {
  AttachmentFacesApp,
  ATTACHMENT_FACES_QUERY_OPTIONS,
} from '../AttachmentFacesApp';
import { ATTACHMENT_EDIT_COPY } from '../copy';
import { mountAttachmentEdit } from '../main';
import { resetConfigCache } from '../../admin/api/config';

vi.mock('../../admin/api/recognition/identityQueriesApi', () => ({
  fetchMediaIdentities: vi.fn(),
}));

const fetchMock = vi.mocked(recognitionApi.fetchMediaIdentities);

const defaultProps = {
  attachmentId: 42,
  imageUrl: 'https://example.test/photo.jpg',
  imageWidth: 1000,
  imageHeight: 800,
  workbenchUrl: 'https://example.test/wp-admin/admin.php?page=alt-context-workbench',
};

function createTestClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        ...ATTACHMENT_FACES_QUERY_OPTIONS,
      },
    },
  });
}

function renderApp(ui: ReactNode, client = createTestClient()) {
  return {
    client,
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
  };
}

function curatedUncuratedFixture(): MediaIdentitiesResponse {
  return {
    data_source: 'local_projection',
    identities_by_media: {
      '42': [
        {
          identity_id: 'curated-1',
          media_id: 42,
          similarity: null,
          confidence: 0.95,
          bbox: { x: 10, y: 10, width: 40, height: 40 },
          cluster_id: 'cluster-curated',
          cluster_label: 'Sam Rivera',
          is_auto_label: false,
        },
        {
          identity_id: 'auto-1',
          media_id: 42,
          similarity: null,
          confidence: 0.8,
          bbox: { x: 200, y: 50, width: 40, height: 40 },
          cluster_id: 'cluster-xyz',
          cluster_label: 'cluster-xyz',
          is_auto_label: true,
        },
        {
          identity_id: 'uncurated-1',
          media_id: 42,
          similarity: null,
          confidence: 0.7,
          bbox: { x: 50, y: 200, width: 40, height: 40 },
          cluster_id: null,
          cluster_label: null,
          is_auto_label: true,
        },
      ],
    },
  };
}

/** backend_proxy envelope — local mappers hardcode clustering_pending false. */
function clusteringPendingBackendProxyFixture(): MediaIdentitiesResponse {
  return {
    data_source: 'backend_proxy',
    identities_by_media: {
      '42': [
        {
          identity_id: 'pending-1',
          media_id: 42,
          similarity: null,
          confidence: 0.9,
          clustering_pending: true,
          bbox: { x: 20, y: 30, width: 50, height: 50 },
          cluster_id: null,
          cluster_label: null,
          is_auto_label: false,
        },
      ],
    },
  };
}

describe('ATTACHMENT_FACES_QUERY_OPTIONS one-shot contract', () => {
  it('pins retry/focus/reconnect/staleTime and omits refetchInterval', () => {
    expect(ATTACHMENT_FACES_QUERY_OPTIONS.retry).toBe(false);
    expect(ATTACHMENT_FACES_QUERY_OPTIONS.refetchOnWindowFocus).toBe(false);
    expect(ATTACHMENT_FACES_QUERY_OPTIONS.refetchOnReconnect).toBe(false);
    expect(ATTACHMENT_FACES_QUERY_OPTIONS.staleTime).toBe(Infinity);
    expect('refetchInterval' in ATTACHMENT_FACES_QUERY_OPTIONS).toBe(false);
  });
});

describe('AttachmentFacesApp five designed states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetConfigCache();
  });

  afterEach(() => {
    resetConfigCache();
  });

  it('shows loading status while the query is pending', async () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    expect(screen.getByRole('status')).toHaveTextContent(ATTACHMENT_EDIT_COPY.loadingFaces);
    expect(screen.getByTestId('acx-attachment-faces-app')).toHaveAttribute('data-state', 'loading');
  });

  it('renders curated name chip and treats auto-label as uncurated [AIPX-07]', async () => {
    fetchMock.mockResolvedValue(curatedUncuratedFixture());
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Sam Rivera' })).toBeInTheDocument();
    });

    expect(screen.queryByRole('button', { name: 'cluster-xyz' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unnamed face 1 of 2' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unnamed face 2 of 2' })).toBeInTheDocument();
    expect(screen.getByTestId('acx-attachment-faces-app')).toHaveAttribute('data-state', 'faces');
  });

  it('empty map + local_projection shows No faces detected (not degraded)', async () => {
    fetchMock.mockResolvedValue({
      data_source: 'local_projection',
      identities_by_media: { '42': [] },
    });
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(ATTACHMENT_EDIT_COPY.noFacesDetected);
    });
    expect(screen.getByTestId('acx-attachment-faces-app')).toHaveAttribute('data-state', 'empty');
    expect(screen.queryByText(ATTACHMENT_EDIT_COPY.faceDataUnavailable)).not.toBeInTheDocument();
  });

  it('empty map + unavailable shows Face data unavailable (branches on data_source) [TEST-15]', async () => {
    fetchMock.mockResolvedValue({
      data_source: 'unavailable',
      identities_by_media: {},
    });
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(ATTACHMENT_EDIT_COPY.faceDataUnavailable);
    });
    expect(screen.getByTestId('acx-attachment-faces-app')).toHaveAttribute('data-state', 'degraded');
    expect(screen.queryByText(ATTACHMENT_EDIT_COPY.noFacesDetected)).not.toBeInTheDocument();
  });

  it('empty map + endpoint_error is degraded, not empty', async () => {
    fetchMock.mockResolvedValue({
      data_source: 'endpoint_error',
      identities_by_media: { '42': [] },
    });
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText(ATTACHMENT_EDIT_COPY.faceDataUnavailable)).toBeInTheDocument();
    });
    expect(screen.getByTestId('acx-attachment-faces-app')).toHaveAttribute('data-state', 'degraded');
  });

  it('query-error (rejected fetch) renders Face data unavailable with no retry [RLSE-04]', async () => {
    fetchMock.mockRejectedValue(new Error('403 Forbidden'));
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(ATTACHMENT_EDIT_COPY.faceDataUnavailable);
    });
    expect(screen.getByTestId('acx-attachment-faces-app')).toHaveAttribute('data-state', 'query-error');
    // One attempt only (retry: false).
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('AuthExpiredError renders session-expired copy, not faceDataUnavailable [TEST-15]', async () => {
    const { AuthExpiredError } = await import('../../admin/utils/http');
    fetchMock.mockRejectedValue(
      new AuthExpiredError({ endpoint: '/media-identities', status: 403 }),
    );
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(ATTACHMENT_EDIT_COPY.sessionExpired);
    });
    expect(screen.queryByText(ATTACHMENT_EDIT_COPY.faceDataUnavailable)).not.toBeInTheDocument();
    expect(screen.getByTestId('acx-attachment-faces-app')).toHaveAttribute('data-state', 'session-expired');
    expect(screen.getByRole('button', { name: ATTACHMENT_EDIT_COPY.reloadPage })).toBeInTheDocument();
  });

  it('generic query error still shows faceDataUnavailable, not session-expired [TEST-15]', async () => {
    fetchMock.mockRejectedValue(new Error('network down'));
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(ATTACHMENT_EDIT_COPY.faceDataUnavailable);
    });
    expect(screen.queryByText(ATTACHMENT_EDIT_COPY.sessionExpired)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: ATTACHMENT_EDIT_COPY.reloadPage })).not.toBeInTheDocument();
  });

  it('issues exactly one fetch per mount; focus + timers do not refetch', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock.mockResolvedValue(curatedUncuratedFixture());
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Sam Rivera' })).toBeInTheDocument();
    });

    await act(async () => {
      window.dispatchEvent(new Event('focus'));
      window.dispatchEvent(new Event('online'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('clustering_pending under backend_proxy shows reload hint as uncurated', async () => {
    fetchMock.mockResolvedValue(clusteringPendingBackendProxyFixture());
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText(ATTACHMENT_EDIT_COPY.stillClustering)).toBeInTheDocument();
    });
    // No curated name chip; face is uncurated marker.
    expect(screen.getByRole('button', { name: 'Unnamed face 1 of 1' })).toBeInTheDocument();
    expect(screen.getByTestId('acx-attachment-faces-app')).toHaveAttribute('data-state', 'faces');
  });

  // jsdom does not load/compile SCSS or resolve CSS custom properties at runtime, so this
  // cannot assert computed "rendered style". It is a structural SCSS graph assertion only:
  // attachment-edit.scss @use's shared tokens and paints curated chips with token vars.
  it('asserts structural scss token graph for curated chip background [UXP5-BR-02]', async () => {
    fetchMock.mockResolvedValue(curatedUncuratedFixture());
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Sam Rivera' })).toBeInTheDocument();
    });

    const chip = screen.getByRole('button', { name: 'Sam Rivera' });
    expect(chip.className).toContain('acx-face-overlay__chip--curated');

    const { readFileSync } = await import('node:fs');
    const { join } = await import('node:path');
    const scssPath = join(__dirname, '..', 'attachment-edit.scss');
    const overlayScssPath = join(
      __dirname,
      '..',
      '..',
      'admin',
      'styles',
      'components',
      '_face-overlay.scss',
    );
    const scss = readFileSync(scssPath, 'utf8');
    const overlayScss = readFileSync(overlayScssPath, 'utf8');
    expect(scss).toMatch(/@use\s+['"]\.\.\/admin\/styles\/tokens\/colors['"]/);
    expect(scss).toMatch(/@use\s+['"]\.\.\/admin\/styles\/components\/face-overlay['"]/);
    expect(overlayScss).toMatch(/&__chip--curated\s*\{[^}]*background-color:\s*var\(--acx-color-success-bg\)/);
  });
});

describe('mountAttachmentEdit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetConfigCache();
    delete window.AltContextAttachmentEdit;
    delete window.AltContextAdmin;
    document.body.innerHTML = '';
  });

  afterEach(() => {
    resetConfigCache();
    delete window.AltContextAttachmentEdit;
    document.body.innerHTML = '';
  });

  it('is a no-op when the container div is absent', () => {
    window.AltContextAttachmentEdit = {
      nonce: 'n',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      attachmentId: 1,
      imageUrl: '',
      imageWidth: 0,
      imageHeight: 0,
      workbenchUrl: '',
      endpoints: { recognitionMediaIdentities: 'https://example.test/mi' },
    };
    expect(mountAttachmentEdit()).toBe(false);
    expect(window.AltContextAdmin).toBeUndefined();
  });

  it('is a no-op mount when attachmentId is zero (container stays hidden) [UXP5-BR-01]', () => {
    document.body.innerHTML =
      '<div id="acx-attachment-faces" data-attachment-id="0" hidden></div>';
    window.AltContextAttachmentEdit = {
      nonce: 'n',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      attachmentId: 0,
      imageUrl: 'https://example.test/img.jpg',
      imageWidth: 100,
      imageHeight: 80,
      workbenchUrl: '',
      endpoints: { recognitionMediaIdentities: 'https://example.test/mi' },
    };

    expect(mountAttachmentEdit()).toBe(false);
    const container = document.getElementById('acx-attachment-faces');
    expect(container?.hasAttribute('hidden')).toBe(true);
    expect(container?.querySelector('[data-testid="acx-attachment-faces-app"]')).toBeNull();
    expect(container?.querySelector('.acx-attachment-faces__skeleton')).toBeNull();
    expect(window.AltContextAdmin).toBeUndefined();
  });

  it('removes hidden after successful mount and registers config without AltContextAdmin', async () => {
    fetchMock.mockResolvedValue({
      data_source: 'local_projection',
      identities_by_media: { '7': [] },
    });

    document.body.innerHTML =
      '<div id="acx-attachment-faces" data-attachment-id="7" hidden></div>';
    window.AltContextAttachmentEdit = {
      nonce: 'mount-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      attachmentId: 7,
      imageUrl: 'https://example.test/img.jpg',
      imageWidth: 100,
      imageHeight: 80,
      workbenchUrl: 'https://example.test/workbench',
      endpoints: {
        recognitionMediaIdentities: 'https://example.test/wp-json/acx/v1/recognition/media-identities',
      },
    };

    await act(async () => {
      expect(mountAttachmentEdit()).toBe(true);
    });

    const container = document.getElementById('acx-attachment-faces');
    expect(container?.hasAttribute('hidden')).toBe(false);
    expect(window.AltContextAdmin).toBeUndefined();

    await waitFor(() => {
      expect(screen.getByTestId('acx-attachment-faces-app')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith([7]);
    });
  });
});
