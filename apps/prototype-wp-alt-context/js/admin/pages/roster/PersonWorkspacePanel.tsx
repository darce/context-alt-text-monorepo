import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';
import type { RosterEntryInstance } from '../../api/generated/roster-entry';
import { formatTimestamp } from '../../utils/formatTimestamp';
import { FaceLightbox } from '../../../components/ui/FaceLightbox';
import { FaceThumbnail } from '../../../components/ui/FaceThumbnail';
import { isCroppableBbox } from '../../../components/ui/faceGeometry';
import type { BoundingBox } from '../../api/recognition/types/identity';
import { UserFacingErrorNotice } from '../../components/ui/UserFacingErrorNotice';
import { useAriaAnnounce } from './hooks/useAriaAnnounce';
import { PIN_REPRESENTATIVE_ERROR_COPY, usePinRepresentative } from './hooks/usePinRepresentative';
import { useRosterFaceCursor } from './hooks/useRosterFaceCursor';
import { useRosterFaceRoute } from './hooks/useRosterFaceRoute';
import { rosterFaceDomId } from './faceDomId';
import { PersonFaceFilmstrip } from './PersonFaceFilmstrip';
import { PersonFaceMetadataPanel } from './PersonFaceMetadataPanel';
import { PersonFacePreview } from './PersonFacePreview';
import { collectPersonFaces } from './personFaces';
import { getSelectedFaceMetadataLines } from './similarityCopy';

const QUEUE_SECTIONS = [
  {
    id: 'singleton-proposals',
    label: __('Singleton proposals', 'alt-context'),
    queuedAction: __('Open singleton proposals queue', 'alt-context'),
    emptyMessage: __('Singleton proposals will appear after the next refresh.', 'alt-context'),
  },
  {
    id: 'hard-examples',
    label: __('Hard examples', 'alt-context'),
    queuedAction: __('Open hard examples queue', 'alt-context'),
    emptyMessage: __('Hard examples will appear after the next refresh.', 'alt-context'),
  },
  {
    id: 'needs-confirmation-after-merge',
    label: __('Needs confirmation after merge', 'alt-context'),
    queuedAction: __('Open needs confirmation after merge queue', 'alt-context'),
    emptyMessage: __('Confirmation requests will appear after the next refresh.', 'alt-context'),
  },
] as const;

const EVIDENCE_IMAGE_SIZE = 96;

interface LightboxSelection {
  mediaUrl: string;
  bbox: BoundingBox;
  label: string;
}

const renderEvidenceMedia = ({
  mediaUrl,
  bbox,
  alt,
  onOpenLightbox,
}: {
  mediaUrl: string | null | undefined;
  bbox: RosterEntryInstance['bbox'];
  alt: string;
  onOpenLightbox: (selection: LightboxSelection) => void;
}): React.JSX.Element => {
  if (typeof mediaUrl === 'string' && mediaUrl.length > 0 && isCroppableBbox(bbox)) {
    return (
      <button
        type="button"
        aria-label={alt}
        onClick={() => onOpenLightbox({ mediaUrl, bbox, label: alt })}
      >
        <FaceThumbnail
          mediaUrl={mediaUrl}
          bbox={bbox}
          sizePx={EVIDENCE_IMAGE_SIZE}
          shape="square"
          alt={alt}
          loading="lazy"
        />
      </button>
    );
  }

  if (typeof mediaUrl === 'string' && mediaUrl.length > 0) {
    return (
      <img
        src={mediaUrl}
        alt={alt}
        width={EVIDENCE_IMAGE_SIZE}
        height={EVIDENCE_IMAGE_SIZE}
        loading="lazy"
      />
    );
  }

  return (
    <div role="img" aria-label={alt}>
      {__('No image', 'alt-context')}
    </div>
  );
};

interface PersonWorkspacePanelProps {
  entry: RosterEntry;
  onOpenQueue: (personUuid: string, queueId: string) => void;
}

export const PersonWorkspacePanel = ({ entry, onOpenQueue }: PersonWorkspacePanelProps): React.JSX.Element => {
  const queueMemberships = new Set(entry.queue_memberships);
  const personUuid = typeof entry.person_uuid === 'string' && entry.person_uuid.length > 0 ? entry.person_uuid : null;
  const entryIdentity = `${entry.id}:${typeof entry.person_uuid === 'string' ? entry.person_uuid : ''}`;
  const [lightbox, setLightbox] = React.useState<LightboxSelection | null>(null);
  const faces = React.useMemo(() => collectPersonFaces(entry), [entry]);
  const visibleIds = React.useMemo(() => faces.map((face) => face.faceId), [faces]);
  const { requestedFaceId, writeFace } = useRosterFaceRoute();
  const { selectedId, select } = useRosterFaceCursor(visibleIds, requestedFaceId);
  const selectedFace = faces.find((face) => face.faceId === selectedId) ?? null;
  const { pin, isPinning, pinError } = usePinRepresentative();
  const { message, seq, announce } = useAriaAnnounce();
  const railRefs = React.useRef(new Map<string, HTMLDivElement>());
  const railCallbackRefs = React.useRef(new Map<string, (node: HTMLDivElement | null) => void>());
  const scrollLeftByRailRef = React.useRef(new Map<string, number>());
  const previousSelectedIdRef = React.useRef<string | null>(selectedId);

  const bindRailRef = React.useCallback((clusterId: string) => {
    const existing = railCallbackRefs.current.get(clusterId);
    if (existing) {
      return existing;
    }
    const callback = (node: HTMLDivElement | null): void => {
      if (node) {
        railRefs.current.set(clusterId, node);
        node.scrollLeft = scrollLeftByRailRef.current.get(clusterId) ?? 0;
        return;
      }
      const current = railRefs.current.get(clusterId);
      if (current) {
        scrollLeftByRailRef.current.set(clusterId, current.scrollLeft);
      }
      railRefs.current.delete(clusterId);
    };
    railCallbackRefs.current.set(clusterId, callback);
    return callback;
  }, []);

  React.useEffect(() => {
    setLightbox(null);
  }, [entryIdentity]);

  React.useEffect(() => {
    if (requestedFaceId === selectedId) {
      return;
    }
    writeFace(selectedId, personUuid);
  }, [personUuid, requestedFaceId, selectedId, writeFace]);

  React.useEffect(() => {
    if (!pinError) {
      return;
    }
    announce(PIN_REPRESENTATIVE_ERROR_COPY);
  }, [announce, pinError]);

  React.useLayoutEffect(() => {
    const rails = railRefs.current;
    const saved = scrollLeftByRailRef.current;
    rails.forEach((rail, clusterId) => {
      rail.scrollLeft = saved.get(clusterId) ?? 0;
    });
    return () => {
      rails.forEach((rail, clusterId) => {
        saved.set(clusterId, rail.scrollLeft);
      });
    };
  });

  React.useEffect(() => {
    const previousId = previousSelectedIdRef.current;
    previousSelectedIdRef.current = selectedId;
    if (!previousId || previousId === selectedId || visibleIds.includes(previousId)) {
      return;
    }

    const active = document.activeElement;
    const focusLostToBody = active === document.body || active === document.documentElement || active === null;
    const activeInRemovedOption = Boolean(
      active instanceof HTMLElement && active.id === rosterFaceDomId(previousId),
    );
    if (!focusLostToBody && !activeInRemovedOption) {
      return;
    }

    const survivingOption = selectedId ? document.getElementById(rosterFaceDomId(selectedId)) : null;
    const survivingRail = survivingOption?.closest<HTMLElement>('[role="listbox"]');
    survivingRail?.focus();
  }, [selectedId, visibleIds]);

  const selectFace = React.useCallback(
    (faceId: string, railFaceIds: readonly string[]) => {
      select(faceId);
      writeFace(faceId, personUuid);
      const nextIndex = railFaceIds.indexOf(faceId);
      if (nextIndex >= 0) {
        announce(
          sprintf(__('Selected face %d of %d', 'alt-context'), nextIndex + 1, railFaceIds.length),
        );
      }
    },
    [announce, personUuid, select, writeFace],
  );

  const canPin = Boolean(selectedFace && !selectedFace.isRepresentative && selectedFace.clusterId);

  return (
    <section
      className="acx-roster__person-workspace"
      role="region"
      aria-label={sprintf(__('Person workspace: %s', 'alt-context'), entry.name)}
    >
      <header className="acx-roster__person-workspace-header">
        <h3>{entry.name}</h3>
        {entry.projection_status !== 'failed' ? (
          <p className="acx-roster__person-workspace-meta">
            {sprintf(__('%d face groups assigned', 'alt-context'), entry.cluster_count)}
          </p>
        ) : null}
        <p className="acx-roster__person-workspace-meta">
          {sprintf(__('Data status: %s', 'alt-context'), entry.projection_status)}
        </p>
        <p className="acx-roster__person-workspace-meta">
          {sprintf(__('Last refreshed: %s', 'alt-context'), formatTimestamp(entry.projection_refreshed_at))}
        </p>
        <p className="acx-roster__person-workspace-meta">
          {sprintf(__('Record version: %d', 'alt-context'), entry.source_version)}
        </p>
      </header>

      <div className="acx-roster__person-workspace-summary">
        <section aria-labelledby="acx-person-workspace-clusters" data-testid="acx-zone-z-person-identities">
          <h4 id="acx-person-workspace-clusters">{__('Face group detail', 'alt-context')}</h4>
          {entry.projection_status === 'failed' ? (
            <p role="alert">{__('Unable to load linked faces.', 'alt-context')}</p>
          ) : entry.projection_status === 'refreshing' ? (
            <p role="status">{__('Refreshing linked faces…', 'alt-context')}</p>
          ) : entry.projection_status === 'stale' ? (
            <p role="status">{__('Linked faces may be out of date.', 'alt-context')}</p>
          ) : (
            <p>
              {entry.cluster_count === 0
                ? __('No face groups are assigned to this person yet.', 'alt-context')
                : sprintf(
                    _n(
                      '%d face group is currently assigned to this person.',
                      '%d face groups are currently assigned to this person.',
                      entry.cluster_count,
                      'alt-context',
                    ),
                    entry.cluster_count,
                  )}
            </p>
          )}
        </section>

        <section aria-labelledby="acx-person-workspace-evidence">
          <h4 id="acx-person-workspace-evidence">{__('Person evidence', 'alt-context')}</h4>
          {entry.tags.length === 0 ? (
            <p>{__('No person tags recorded yet.', 'alt-context')}</p>
          ) : (
            <ul>
              {entry.tags.map((tag) => (
                <li key={tag}>{tag}</li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section aria-label={__('Face evidence', 'alt-context')} role="region">
        <h4>{__('Face evidence', 'alt-context')}</h4>
        <div className="acx-roster__person-workspace-scrubber">
          <PersonFacePreview face={selectedFace} onOpenLightbox={setLightbox} />
          <PersonFaceMetadataPanel face={selectedFace} />
          <div className="acx-roster__person-workspace-actions" data-testid="acx-zone-z-person-actions">
            {isPinning ? <p>{__('Saving representative…', 'alt-context')}</p> : null}
            {!selectedFace ? (
              <p>{__('Select a face to choose a representative.', 'alt-context')}</p>
            ) : (
              <button
                type="button"
                className="acx-button acx-button--primary"
                disabled={!canPin || isPinning}
                onClick={() => {
                  pin(selectedFace.clusterId, selectedFace.identityId, true);
                }}
              >
                {__('Set as representative', 'alt-context')}
              </button>
            )}
            {pinError ? (
              <UserFacingErrorNotice error={pinError} fallback={PIN_REPRESENTATIVE_ERROR_COPY} />
            ) : null}
          </div>
          <div
            className="acx-roster__person-workspace-live"
            role="status"
            aria-live="polite"
            aria-label={__('Face selection announcements', 'alt-context')}
          >
            {message ? `${message}${seq % 2 === 1 ? '\u200b' : ''}` : null}
          </div>
        </div>
        {entry.clusters.length > 0 ? (
          <div>
            {entry.clusters.map((cluster, index) => {
              const clusterLabel = sprintf(__('Face group %d', 'alt-context'), index + 1);
              const representativeAlt = sprintf(
                __('Representative face for face group %d', 'alt-context'),
                index + 1,
              );
              const clusterFaces = faces.filter((face) => face.clusterIndex === index);
              return (
                <section key={cluster.cluster_id} role="region" aria-label={clusterLabel}>
                  <h5>{clusterLabel}</h5>
                  <p>{sprintf(__('%d faces', 'alt-context'), cluster.instances.length)}</p>
                  {cluster.representative_identity?.media_url ? (
                    renderEvidenceMedia({
                      mediaUrl: cluster.representative_identity.media_url,
                      bbox: cluster.representative_identity.bbox,
                      alt: representativeAlt,
                      onOpenLightbox: setLightbox,
                    })
                  ) : (
                    <p>{__('Representative face unavailable until the next refresh.', 'alt-context')}</p>
                  )}
                  {getSelectedFaceMetadataLines(cluster.representative_identity).map((line) => (
                    <p key={`${cluster.cluster_id}-representative-${line}`}>{line}</p>
                  ))}
                  {clusterFaces.length > 0 ? (
                    <PersonFaceFilmstrip
                      faces={clusterFaces}
                      selectedId={selectedId}
                      onSelect={selectFace}
                      railRef={bindRailRef(cluster.cluster_id)}
                      clusterOrdinal={index + 1}
                    />
                  ) : null}
                  <div>
                    {cluster.instances.map((instance) => (
                      <div key={`${cluster.cluster_id}-${instance.identity_id}-${instance.media_id}`}>
                        {getSelectedFaceMetadataLines(instance).map((line) => (
                          <div key={`${cluster.cluster_id}-${instance.identity_id}-${instance.media_id}-${line}`}>
                            {line}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        ) : (
          <p>{__('Face evidence will appear after the next refresh.', 'alt-context')}</p>
        )}
      </section>

      <section aria-labelledby="acx-person-workspace-queues-title">
        <h4 id="acx-person-workspace-queues-title">{__('Review queues', 'alt-context')}</h4>
        <div>
          {QUEUE_SECTIONS.map((queueSection) => {
            const isQueued = queueMemberships.has(queueSection.id);
            return (
              <section
                key={queueSection.id}
                role="region"
                aria-label={sprintf(__('%s queue', 'alt-context'), queueSection.label)}
              >
                <h5>{queueSection.label}</h5>
                <p>
                  {isQueued
                    ? __('Queued for review in this workspace.', 'alt-context')
                    : __('No queued items for this person yet.', 'alt-context')}
                </p>
                {isQueued && personUuid ? (
                  <button
                    type="button"
                    className="acx-link-button"
                    onClick={() => onOpenQueue(personUuid, queueSection.id)}
                  >
                    {queueSection.queuedAction}
                  </button>
                ) : isQueued ? (
                  <>
                    <button type="button" className="acx-link-button" disabled>
                      {queueSection.queuedAction}
                    </button>
                    <p>{__('Person identifier unavailable until the next refresh.', 'alt-context')}</p>
                  </>
                ) : (
                  <p>{queueSection.emptyMessage}</p>
                )}
              </section>
            );
          })}
        </div>
      </section>

      {lightbox ? (
        <FaceLightbox
          open
          onOpenChange={(open) => {
            if (!open) {
              setLightbox(null);
            }
          }}
          mediaUrl={lightbox.mediaUrl}
          bbox={lightbox.bbox}
          label={lightbox.label}
        />
      ) : null}
    </section>
  );
};
