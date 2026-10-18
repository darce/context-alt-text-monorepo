/**
 * post.php attachment faces app: one-shot media-identities fetch + five designed states.
 */

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertCircle, CircleHelp, Loader2 } from 'lucide-react';

import { queryKeys } from '../admin/api/queryKeys';
import { fetchMediaIdentities } from '../admin/api/recognition/identityQueriesApi';
import { DATA_SOURCE, type DataSource } from '../admin/api/recognition/types/dataSource';
import type { DetectedIdentity } from '../admin/api/recognition/types/identity';
import { FaceOverlayLayer } from '../components/ui/FaceOverlayLayer';
import { isAuthExpiredError } from '../admin/utils/userFacingError';
import { ATTACHMENT_EDIT_COPY } from './copy';
import { UncuratedFaceList } from './UncuratedFaceList';

export interface AttachmentFacesAppProps {
  attachmentId: number;
  imageUrl: string;
  imageWidth: number;
  imageHeight: number;
  workbenchUrl: string;
}

/** One-shot contract pinned by UXP-5 plan — no polling, no bare-false refetchInterval. */
export const ATTACHMENT_FACES_QUERY_OPTIONS = {
  retry: false as const,
  refetchOnWindowFocus: false as const,
  refetchOnReconnect: false as const,
  staleTime: Infinity,
};

const isDegradedDataSource = (dataSource: DataSource | undefined): boolean => {
  return dataSource === DATA_SOURCE.ENDPOINT_ERROR || dataSource === DATA_SOURCE.UNAVAILABLE;
};

const hasClusteringPending = (identities: DetectedIdentity[]): boolean => {
  return identities.some((identity) => identity.clustering_pending === true);
};

export const AttachmentFacesApp: React.FC<AttachmentFacesAppProps> = ({
  attachmentId,
  imageUrl,
  imageWidth,
  imageHeight,
  workbenchUrl,
}) => {
  const [highlightedFaceId, setHighlightedFaceId] = React.useState<string | null>(null);

  const { data, isPending, isError, isFetching, error } = useQuery({
    queryKey: queryKeys.media.identitiesByIds([attachmentId]),
    queryFn: () => fetchMediaIdentities([attachmentId]),
    enabled: attachmentId > 0,
    ...ATTACHMENT_FACES_QUERY_OPTIONS,
  });

  const handleActivate = React.useCallback(
    () => {
      if (!workbenchUrl) {
        return;
      }
      // Curated chip activation follows the workbench deep link (plain admin URL).
      window.location.assign(workbenchUrl);
    },
    [workbenchUrl],
  );

  if (isPending || (isFetching && !data && !isError)) {
    return (
      <div className="acx-attachment-faces" data-testid="acx-attachment-faces-app" data-state="loading">
        <div className="acx-attachment-faces__status" role="status" aria-live="polite">
          <Loader2 className="acx-attachment-faces__status-icon" size={16} aria-hidden="true" />
          <span>{ATTACHMENT_EDIT_COPY.loadingFaces}</span>
        </div>
        <div className="acx-attachment-faces__skeleton" aria-hidden="true" />
      </div>
    );
  }

  if (isError) {
    // FEBT1-LB-03: tag check, not `instanceof`. The boundary now guarantees a
    // tagged error, and a structural check also holds for an AuthExpiredError
    // that crossed a serialisation seam (React Query cache hydration, a worker
    // postMessage) where the prototype does not survive. Repo idiom:
    // userFacingError.ts:10.
    const sessionExpired = isAuthExpiredError(error);
    return (
      <div
        className="acx-attachment-faces"
        data-testid="acx-attachment-faces-app"
        data-state={sessionExpired ? 'session-expired' : 'query-error'}
      >
        <div className="acx-attachment-faces__status acx-attachment-faces__status--error" role="status" aria-live="polite">
          <AlertCircle className="acx-attachment-faces__status-icon" size={16} aria-hidden="true" />
          <span>
            {sessionExpired ? ATTACHMENT_EDIT_COPY.sessionExpired : ATTACHMENT_EDIT_COPY.faceDataUnavailable}
          </span>
          {sessionExpired ? (
            <button
              type="button"
              className="acx-attachment-faces__reload"
              onClick={() => window.location.reload()}
            >
              {ATTACHMENT_EDIT_COPY.reloadPage}
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  const dataSource = data?.data_source;
  if (isDegradedDataSource(dataSource)) {
    return (
      <div className="acx-attachment-faces" data-testid="acx-attachment-faces-app" data-state="degraded">
        <div className="acx-attachment-faces__status acx-attachment-faces__status--error" role="status" aria-live="polite">
          <AlertCircle className="acx-attachment-faces__status-icon" size={16} aria-hidden="true" />
          <span>{ATTACHMENT_EDIT_COPY.faceDataUnavailable}</span>
        </div>
      </div>
    );
  }

  const identities = data?.identities_by_media?.[String(attachmentId)] ?? [];
  if (identities.length === 0) {
    return (
      <div className="acx-attachment-faces" data-testid="acx-attachment-faces-app" data-state="empty">
        <div className="acx-attachment-faces__status" role="status" aria-live="polite">
          <CircleHelp className="acx-attachment-faces__status-icon" size={16} aria-hidden="true" />
          <span>{ATTACHMENT_EDIT_COPY.noFacesDetected}</span>
        </div>
      </div>
    );
  }

  const clusteringNote = hasClusteringPending(identities);
  const naturalSize = { width: imageWidth, height: imageHeight };

  return (
    <div className="acx-attachment-faces" data-testid="acx-attachment-faces-app" data-state="faces">
      {clusteringNote ? (
        <div className="acx-attachment-faces__status acx-attachment-faces__status--pending" role="status" aria-live="polite">
          <Loader2 className="acx-attachment-faces__status-icon" size={16} aria-hidden="true" />
          <span>{ATTACHMENT_EDIT_COPY.stillClustering}</span>
        </div>
      ) : null}
      {/* Plan default pending owner: self-contained figure (duplicate of core preview). */}
      <figure className="acx-attachment-faces__figure">
        <div className="acx-attachment-faces__image-wrap">
          {imageUrl ? (
            <img
              className="acx-attachment-faces__image"
              src={imageUrl}
              alt=""
              width={imageWidth > 0 ? imageWidth : undefined}
              height={imageHeight > 0 ? imageHeight : undefined}
              decoding="async"
            />
          ) : null}
          <FaceOverlayLayer
            identities={identities}
            naturalSize={naturalSize}
            onActivate={handleActivate}
            highlightedFaceId={highlightedFaceId}
            onHighlightChange={setHighlightedFaceId}
          />
        </div>
      </figure>
      <UncuratedFaceList
        identities={identities}
        mediaUrl={imageUrl}
        workbenchUrl={workbenchUrl}
        highlightedFaceId={highlightedFaceId}
        onHighlightChange={setHighlightedFaceId}
      />
    </div>
  );
};

AttachmentFacesApp.displayName = 'AttachmentFacesApp';
