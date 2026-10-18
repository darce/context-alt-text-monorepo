/**
 * Attachment-edit entry for post.php: register minimal config, mount faces app.
 * Reveal contract: container ships `hidden`; remove after successful render.
 */

import * as React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { registerConfig, type AttachmentEditLocalizedConfig } from '../admin/api/config';
import { createLogger, withRequestId } from '../admin/utils/logger';
import { AttachmentFacesApp } from './AttachmentFacesApp';
import './attachment-edit.scss';

const bootstrapLog = createLogger('attachment-edit.bootstrap');

/** Localized keys `registerConfig` cannot work without. */
const REQUIRED_CONFIG_KEYS = ['nonce', 'ajaxUrl', 'endpoints'] as const;

const toPositiveInt = (value: number | string | undefined): number => {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : 0;
};

const createAttachmentEditQueryClient = (): QueryClient => {
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
};

/**
 * Mount into #acx-attachment-faces when present. No-op when the container is
 * absent (media modal / non-attachment safety).
 */
export const mountAttachmentEdit = (
  doc: Document = document,
  payload: AttachmentEditLocalizedConfig | undefined = window.AltContextAttachmentEdit,
): boolean => {
  // One correlated record per bootstrap attempt, minted before the first branch so
  // every exit below is attributable to the same unit of work (OBS-02/OBS-03).
  const log = withRequestId(bootstrapLog);

  const container = doc.getElementById('acx-attachment-faces');
  if (!container) {
    // Designed no-op, not a failure: the media modal and every non-attachment screen
    // load this bundle without the container (RLSE-04). It is still recorded — a branch
    // that returns in total silence is indistinguishable from "the bundle never ran"
    // (OBS-08). `debug` not `warn`: this fires on every media-modal open, and paging on
    // routine business would train operators past the real warnings below (OBS-04).
    // `defaultMinLevel` filters debug out in PROD, so this costs production nothing.
    log.debug('Attachment-edit faces panel not mounted: no container on this screen');
    return false;
  }

  // Past this point PHP rendered the container, so it decided this surface should
  // show faces. Anything that stops the mount now is a broken localized payload and
  // the user sees an empty box with no explanation — make it observable (RLSE-05).

  const missingConfigKeys = REQUIRED_CONFIG_KEYS.filter((key) => !payload?.[key]);
  if (!payload || missingConfigKeys.length > 0) {
    log.warn('Attachment-edit faces panel not mounted: incomplete localized config', {
      missingConfigKeys,
    });
    return false;
  }

  // Zero / missing attachmentId: leave container hidden — never mount a permanent skeleton.
  const attachmentId = toPositiveInt(payload.attachmentId);
  if (attachmentId === 0) {
    log.warn('Attachment-edit faces panel not mounted: attachmentId is not a positive integer', {
      attachmentIdType: typeof payload.attachmentId,
    });
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
};

// Auto-mount when the bundle loads on post.php.
mountAttachmentEdit();
