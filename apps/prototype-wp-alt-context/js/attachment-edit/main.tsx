/**
 * Attachment-edit entry for post.php: register minimal config, mount faces app.
 * Reveal contract: container ships `hidden`; remove after successful render.
 */

import * as React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { registerConfig, type AttachmentEditLocalizedConfig } from '../admin/api/config';
import { AttachmentFacesApp } from './AttachmentFacesApp';
import './attachment-edit.scss';

function toPositiveInt(value: number | string | undefined): number {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : 0;
}

function createAttachmentEditQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        staleTime: Infinity,
        // no refetchInterval — one-shot only (UXP-NET-1: never bare-false)
      },
    },
  });
}

/**
 * Mount into #acx-attachment-faces when present. No-op when the container is
 * absent (media modal / non-attachment safety).
 */
export function mountAttachmentEdit(
  doc: Document = document,
  payload: AttachmentEditLocalizedConfig | undefined = window.AltContextAttachmentEdit,
): boolean {
  const container = doc.getElementById('acx-attachment-faces');
  if (!container) {
    return false;
  }

  if (!payload?.nonce || !payload.ajaxUrl || !payload.endpoints) {
    return false;
  }

  // Zero / missing attachmentId: leave container hidden — never mount a permanent skeleton.
  const attachmentId = toPositiveInt(payload.attachmentId);
  if (attachmentId === 0) {
    return false;
  }

  registerConfig({
    nonce: payload.nonce,
    ajaxUrl: payload.ajaxUrl,
    endpoints: payload.endpoints,
  });

  const imageWidth = toPositiveInt(payload.imageWidth);
  const imageHeight = toPositiveInt(payload.imageHeight);
  const imageUrl = typeof payload.imageUrl === 'string' ? payload.imageUrl : '';
  const workbenchUrl = typeof payload.workbenchUrl === 'string' ? payload.workbenchUrl : '';

  const queryClient = createAttachmentEditQueryClient();
  const root = createRoot(container);
  root.render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <AttachmentFacesApp
          attachmentId={attachmentId}
          imageUrl={imageUrl}
          imageWidth={imageWidth}
          imageHeight={imageHeight}
          workbenchUrl={workbenchUrl}
        />
      </QueryClientProvider>
    </React.StrictMode>,
  );

  container.removeAttribute('hidden');
  return true;
}

// Auto-mount when the bundle loads on post.php.
mountAttachmentEdit();
