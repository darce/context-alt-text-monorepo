/**
 * Shared media+bbox lightbox primitive (promoted from ReviewCardLightbox).
 * Shows source media full-size with the face bbox rect highlighted.
 * Optional identities overlay boxes every detected face; the reviewed face
 * carries a "?" chip. Dialog only (Esc/close); no routing, no new endpoint.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { __ } from '@wordpress/i18n';

import { queryKeys } from '../../admin/api/queryKeys';
import { fetchMediaIdentities } from '../../admin/api/recognition/identityQueriesApi';
import { DATA_SOURCE } from '../../admin/api/recognition/types/dataSource';
import type { BoundingBox, DetectedIdentity } from '../../admin/api/recognition/types/identity';
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from './dialog';
import {
  containFit,
  isCompleteFiniteBbox,
  isPositiveMediaId,
  type NaturalSize,
} from './faceGeometry';
import { FaceOverlayLayer, type FaceOverlayIdentity } from './FaceOverlayLayer';

/** One-shot contract — same shape as AttachmentFacesApp; never bare-false refetchInterval. */
const LIGHTBOX_IDENTITIES_QUERY_OPTIONS = {
  retry: false as const,
  refetchOnWindowFocus: false as const,
  refetchOnReconnect: false as const,
  staleTime: Infinity,
};

export const FACE_LIGHTBOX_COPY = {
  LOADING: __('Loading faces…', 'alt-context'),
  LOAD_FAILED: __('Could not load other faces.', 'alt-context'),
} as const;

export interface FaceLightboxProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mediaUrl: string;
  bbox: BoundingBox;
  label?: string;
  identities?: FaceOverlayIdentity[];
  activeFaceId?: string | null;
  mediaId?: number;
  onReviewFaceActivate?: (faceId: string) => void;
  reviewNaming?: React.ReactNode;
}

/** @deprecated Prefer FaceLightboxProps; kept for ReviewCardLightbox shim consumers. */
export type ReviewCardLightboxProps = FaceLightboxProps;

const toOverlayIdentity = (identity: DetectedIdentity): FaceOverlayIdentity => ({
  identity_id: identity.identity_id,
  bbox: identity.bbox,
  cluster_label: identity.cluster_label,
  is_auto_label: identity.is_auto_label,
});

const isDegradedDataSource = (dataSource: string | undefined): boolean =>
  dataSource === DATA_SOURCE.ENDPOINT_ERROR || dataSource === DATA_SOURCE.UNAVAILABLE;

export const FaceLightbox = ({
  open,
  onOpenChange,
  mediaUrl,
  bbox,
  label,
  identities,
  activeFaceId = null,
  mediaId,
  onReviewFaceActivate,
  reviewNaming,
}: FaceLightboxProps): React.JSX.Element => {
  const frameRef = React.useRef<HTMLDivElement>(null);
  const [naturalSize, setNaturalSize] = React.useState<NaturalSize | null>(null);
  const [frameSize, setFrameSize] = React.useState<NaturalSize | null>(null);

  const identitiesFromProp =
    identities != null && identities.length > 0 ? identities : null;
  const fetchId = isPositiveMediaId(mediaId) ? mediaId : null;
  const shouldFetch = open && fetchId != null && identitiesFromProp == null;

  const identitiesQuery = useQuery({
    queryKey: queryKeys.media.identitiesByIds(fetchId != null ? [fetchId] : []),
    queryFn: () => {
      if (fetchId == null) {
        throw new Error('lightbox media-identities query ran without a positive media id');
      }
      return fetchMediaIdentities([fetchId]);
    },
    enabled: shouldFetch,
    ...LIGHTBOX_IDENTITIES_QUERY_OPTIONS,
  });

  React.useEffect(() => {
    if (!open) {
      setNaturalSize(null);
      setFrameSize(null);
    }
  }, [open, mediaUrl]);

  React.useEffect(() => {
    if (!open || !frameRef.current) {
      return;
    }
    const el = frameRef.current;
    const update = (): void => {
      setFrameSize({ width: el.clientWidth, height: el.clientHeight });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [open, naturalSize]);

  const handleLoad = (event: React.SyntheticEvent<HTMLImageElement>): void => {
    const img = event.currentTarget;
    setNaturalSize({ width: img.naturalWidth, height: img.naturalHeight });
  };

  const fetchedIdentities = React.useMemo(() => {
    if (identitiesFromProp) {
      return identitiesFromProp;
    }
    if (fetchId == null || !identitiesQuery.data) {
      return null;
    }
    const rows = identitiesQuery.data.identities_by_media?.[String(fetchId)] ?? [];
    return rows.map(toOverlayIdentity);
  }, [identitiesFromProp, fetchId, identitiesQuery.data]);

  const fetchFailed =
    shouldFetch &&
    (identitiesQuery.isError || isDegradedDataSource(identitiesQuery.data?.data_source));
  const fetchLoading =
    shouldFetch &&
    !fetchFailed &&
    (identitiesQuery.isPending || (identitiesQuery.isFetching && !identitiesQuery.data));
  const overlayIdentities =
    !fetchFailed && fetchedIdentities != null && fetchedIdentities.length > 0
      ? fetchedIdentities
      : null;

  const fit = naturalSize && frameSize ? containFit(naturalSize, frameSize) : null;

  let highlightStyle: React.CSSProperties | undefined;
  if (!overlayIdentities && fit && isCompleteFiniteBbox(bbox)) {
    highlightStyle = {
      left: fit.offsetX + bbox.x * fit.scale,
      top: fit.offsetY + bbox.y * fit.scale,
      width: bbox.width * fit.scale,
      height: bbox.height * fit.scale,
    };
  }

  const overlayStyle: React.CSSProperties | undefined = fit
    ? {
        left: fit.offsetX,
        top: fit.offsetY,
        width: fit.displayWidth,
        height: fit.displayHeight,
      }
    : undefined;

  const title = label
    ? __('Original media with face highlight', 'alt-context')
    : __('Original media', 'alt-context');

  const statusMessage = fetchLoading
    ? FACE_LIGHTBOX_COPY.LOADING
    : fetchFailed
      ? FACE_LIGHTBOX_COPY.LOAD_FAILED
      : null;

  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogContent className="acx-review-card-lightbox" aria-describedby="acx-review-card-lightbox-desc">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription id="acx-review-card-lightbox-desc">
            {label
              ? __('Face region is outlined on the source photo.', 'alt-context')
              : __('Source photo for this review card.', 'alt-context')}
          </DialogDescription>
          {statusMessage ? (
            <p className="acx-review-card-lightbox__status" role="status" aria-live="polite">
              {statusMessage}
            </p>
          ) : null}
          <div ref={frameRef} className="acx-review-card-lightbox__frame">
            <img
              src={mediaUrl}
              alt={label ?? __('Original media', 'alt-context')}
              className="acx-review-card-lightbox__image"
              onLoad={handleLoad}
            />
            {overlayIdentities && overlayStyle && naturalSize ? (
              <div className="acx-review-card-lightbox__overlay" style={overlayStyle}>
                <FaceOverlayLayer
                  identities={overlayIdentities}
                  naturalSize={naturalSize}
                  highlightedFaceId={activeFaceId}
                  reviewFaceId={activeFaceId}
                  onReviewActivate={onReviewFaceActivate}
                />
              </div>
            ) : null}
            {highlightStyle ? (
              <span
                className="acx-review-card-lightbox__bbox"
                style={highlightStyle}
                aria-hidden="true"
              />
            ) : null}
          </div>
          {reviewNaming}
          <div className="acx-dialog__actions">
            <button
              type="button"
              className="acx-button acx-button--secondary"
              onClick={() => onOpenChange(false)}
            >
              {__('Close', 'alt-context')}
            </button>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
};
