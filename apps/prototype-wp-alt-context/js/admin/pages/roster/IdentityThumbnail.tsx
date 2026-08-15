import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { MediaMeta } from '../../api/mediaApi';
import { cropFaceFromImage } from '../../../components/ui/cropFaceFromImage';
import { isDedicatedFaceThumbUrl } from '../../../components/ui/isDedicatedFaceThumbUrl';

/**
 * Structural minimum IdentityThumbnail actually reads.
 * ClusterIdentity satisfies this (extra fields are fine).
 * RosterEntryInstance is adapted at the call site to this shape — we do not
 * fabricate a ClusterIdentity [rg-015].
 */
export interface ThumbnailIdentity {
  media_id: number;
  identity_id?: string;
  thumb_url?: string | null;
  /** Durable WP attachment URL used to crop after scan-time blobs expire. */
  attachment_url?: string | null;
  /** Full-media URL when no dedicated thumb_url (RosterEntryInstance path). */
  media_url?: string | null;
  /** Pixel-space face bbox. Null/absent → no canvas crop. */
  bbox?: { x: number; y: number; width: number; height: number } | null;
}

export interface IdentityThumbnailProps {
  identity: ThumbnailIdentity;
  mediaMeta?: MediaMeta;
  size?: number;
  onClick?: () => void;
  /**
   * Override alt text. Pass "" when the thumbnail is decorative beside a name
   * label already present in the row [A11Y-21].
   */
  alt?: string;
}

const PADDING_RATIO = 0.15;

interface OwnedCrop {
  ownerId: string;
  src: string;
}

/** Face/media key for a crop so a previous person's data: URL cannot paint on a swap. */
export const thumbnailCropOwnerId = (identity: ThumbnailIdentity): string => {
  const bbox = identity.bbox;
  const bboxKey =
    bbox != null ? `${bbox.x},${bbox.y},${bbox.width},${bbox.height}` : 'none';
  if (identity.identity_id != null) {
    // Assigned identities still need a bbox signature: an unusable-bbox frame
    // stores the full scene under this key, and a later usable bbox on the
    // same identity must not reuse that crop for one paint [E21-19-REV1-05].
    return `${identity.identity_id}:${bboxKey}`;
  }
  if (bbox != null) {
    return `media:${identity.media_id}:${bboxKey}`;
  }
  return `media:${identity.media_id}`;
};

/** Positive finite area required — zero-area is schema-legal but cannot crop [S8-BR-01]. */
const isUsableBbox = (
  bbox: ThumbnailIdentity['bbox'],
): bbox is { x: number; y: number; width: number; height: number } =>
  bbox != null &&
  Number.isFinite(bbox.x) &&
  Number.isFinite(bbox.y) &&
  Number.isFinite(bbox.width) &&
  Number.isFinite(bbox.height) &&
  bbox.width > 0 &&
  bbox.height > 0;

export const IdentityThumbnail = ({
  identity,
  mediaMeta,
  size = 96,
  onClick,
  alt,
}: IdentityThumbnailProps): React.JSX.Element => {
  const [cropped, setCropped] = React.useState<OwnedCrop | null>(null);
  const [isIntersecting, setIsIntersecting] = React.useState(false);
  const [thumbFailed, setThumbFailed] = React.useState(false);
  const [fallbackFailed, setFallbackFailed] = React.useState(false);
  const hostRef = React.useRef<HTMLSpanElement | null>(null);
  const sourceUrl = mediaMeta?.url ?? identity.attachment_url ?? identity.media_url ?? null;
  const cropOwnerId = thumbnailCropOwnerId(identity);
  const dedicatedThumbUrl = isDedicatedFaceThumbUrl(identity.thumb_url) ? (identity.thumb_url ?? null) : null;
  const effectiveThumbUrl = thumbFailed ? null : dedicatedThumbUrl;

  React.useEffect(() => {
    setThumbFailed(false);
  }, [identity.thumb_url]);

  React.useEffect(() => {
    setFallbackFailed(false);
  }, [sourceUrl, cropOwnerId]);

  // Canvas crop path only (no usable thumb_url). Dedicated blob errors fall
  // through here via thumbFailed so attachment_url + bbox can still paint.
  const needsCanvasCrop = !effectiveThumbUrl && Boolean(sourceUrl) && isUsableBbox(identity.bbox);

  React.useEffect(() => {
    if (!needsCanvasCrop) {
      setIsIntersecting(false);
      return;
    }

    const host = hostRef.current;
    if (!host) {
      return;
    }

    if (typeof IntersectionObserver === 'undefined') {
      setIsIntersecting(true);
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setIsIntersecting(true);
        observer.disconnect();
      }
    });
    observer.observe(host);
    return () => {
      observer.disconnect();
    };
  }, [needsCanvasCrop]);

  React.useEffect(() => {
    if (effectiveThumbUrl) {
      setCropped(null);
      return;
    }
    if (!sourceUrl) {
      setCropped(null);
      return;
    }
    if (!isUsableBbox(identity.bbox)) {
      setCropped({ ownerId: cropOwnerId, src: sourceUrl });
      return;
    }
    // Defer full-res Image construction until the thumb is on-screen.
    if (!isIntersecting) {
      setCropped(null);
      return;
    }

    // [S6-BR-01] Drop any previous data: crop immediately when source/bbox
    // changes so the old face cannot remain painted under new data attributes
    // while the replacement Image loads.
    setCropped(null);

    let cancelled = false;
    const bbox = identity.bbox;
    const ownerId = cropOwnerId;
    const img = new Image();
    img.crossOrigin = 'anonymous';

    const draw = () => {
      if (cancelled) {
        return;
      }

      const dataUrl = cropFaceFromImage({
        image: img,
        bbox,
        size,
        originalWidth: mediaMeta?.width,
        originalHeight: mediaMeta?.height,
        paddingRatio: PADDING_RATIO,
      });
      if (!dataUrl) {
        setCropped({ ownerId, src: sourceUrl });
        return;
      }
      setCropped({ ownerId, src: dataUrl });
    };

    // Assign handlers before src so load/error cannot race past the bindings.
    img.onload = draw;
    img.onerror = () => {
      if (!cancelled) {
        setCropped({ ownerId, src: sourceUrl });
      }
    };
    img.src = sourceUrl;

    return () => {
      cancelled = true;
    };
  }, [
    cropOwnerId,
    effectiveThumbUrl,
    identity.bbox,
    identity.media_url,
    isIntersecting,
    mediaMeta?.height,
    mediaMeta?.url,
    mediaMeta?.width,
    size,
    sourceUrl,
  ]);

  // While canvas crop is required and not yet ready, keep a sized placeholder
  // — both pre-intersection and during the post-intersect crop window — so
  // rows never paint/fetch the full uncropped scene [S6-BR-02] [PERC-02].
  // Ignore a previous identity's crop on this render — effect cleanup is
  // post-paint and would leak one frame [WBUX-5-R2-S3-BR-01].
  const croppedSrc = cropped !== null && cropped.ownerId === cropOwnerId ? cropped.src : null;
  const fallbackSrc = needsCanvasCrop ? croppedSrc : sourceUrl;
  const resolvedSrc = effectiveThumbUrl ?? (fallbackFailed ? null : fallbackSrc);
  const resolvedAlt = alt ?? sprintf(__('Identity from media %d', 'alt-context'), identity.media_id);
  const imageFailedLabel = __('Image failed to load', 'alt-context');

  if (!resolvedSrc) {
    // Sized via the size prop (inline, no CSS file) so rows with/without faces
    // share height [PERC-02]. data-face-missing distinguishes "no face on file"
    // from a real photo an operator does not recognise — only when there is
    // genuinely no media; pending crop reuses the same box without the missing
    // flag so layout stays stable while the crop waits.
    //
    // Pending crop [A11Y-02]: when resolvedAlt is non-empty the placeholder is
    // the sole content of wrapping links (e.g. ClusterDrawerPanel), so it must
    // expose role=img + aria-label. Decorative alt="" stays aria-hidden.
    // Genuinely-missing media keeps aria-hidden + data-face-missing unchanged.
    //
    // When onClick is provided *and* the placeholder is a named pending-crop
    // (sole content of a wrapping control contract), use a native <button> so
    // it honours the same click/keyboard path as the resolved <img> [S3-BR-04]
    // [A11Y-11] [A11Y-12]. Decorative alt="" and genuinely-missing media must
    // NOT be buttons: an aria-hidden control that still fires onClick violates
    // keyboard operability and name/role/value [WBUX-5-D-03] [A11Y-04].
    const pendingCrop = needsCanvasCrop && !croppedSrc && !fallbackFailed;
    const namedPending = pendingCrop && resolvedAlt !== '';
    const claimedThenFailed = Boolean(dedicatedThumbUrl) && thumbFailed && !pendingCrop;
    const loudError = (claimedThenFailed || fallbackFailed) && resolvedAlt !== '';
    const boxStyle: React.CSSProperties = {
      width: size,
      height: size,
      display: 'inline-block',
      verticalAlign: 'middle',
      flexShrink: 0,
    };
    if (loudError) {
      return (
        <span ref={hostRef} style={{ display: 'inline-block', verticalAlign: 'middle', flexShrink: 0 }}>
          <div
            className="acx-cluster-card__face--placeholder"
            role="img"
            aria-label={imageFailedLabel}
            data-face-error="true"
            style={boxStyle}
          >
            {imageFailedLabel}
          </div>
        </span>
      );
    }
    if (onClick && namedPending) {
      return (
        <span ref={hostRef} style={{ display: 'inline-block', verticalAlign: 'middle', flexShrink: 0 }}>
          <button
            type="button"
            className="acx-cluster-card__face--placeholder"
            onClick={onClick}
            aria-label={resolvedAlt}
            data-face-pending="true"
            style={{
              ...boxStyle,
              border: 'none',
              padding: 0,
              margin: 0,
              background: 'transparent',
              cursor: 'pointer',
            }}
          />
        </span>
      );
    }
    // Non-interactive placeholder: decorative, genuinely-missing, or pending
    // crop without onClick. Same markup either way — never a hidden button.
    return (
      <span ref={hostRef} style={{ display: 'inline-block', verticalAlign: 'middle', flexShrink: 0 }}>
        <div
          className="acx-cluster-card__face--placeholder"
          role={namedPending ? 'img' : undefined}
          aria-label={namedPending ? resolvedAlt : undefined}
          aria-hidden={namedPending ? undefined : 'true'}
          data-face-missing={pendingCrop ? undefined : 'true'}
          data-face-pending={pendingCrop ? 'true' : undefined}
          style={boxStyle}
        />
      </span>
    );
  }

  return (
    <span ref={hostRef} style={{ display: 'inline-block', verticalAlign: 'middle', flexShrink: 0 }}>
      <img
        src={resolvedSrc}
        alt={resolvedAlt}
        width={size}
        height={size}
        className="acx-cluster-card__thumb"
        data-identity-id={identity.identity_id}
        data-media-id={identity.media_id}
        onClick={onClick}
        onError={() => {
          if (effectiveThumbUrl) {
            setThumbFailed(true);
            return;
          }
          setFallbackFailed(true);
        }}
        loading="lazy"
      />
    </span>
  );
};
