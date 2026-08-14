import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';
import type { RosterEntryInstance } from '../../api/generated/roster-entry';
import { formatTimestamp } from '../../utils/formatTimestamp';
import { FaceLightbox } from '../../../components/ui/FaceLightbox';
import { FaceThumbnail } from '../../../components/ui/FaceThumbnail';
import { isCroppableBbox } from '../../../components/ui/faceGeometry';
import type { BoundingBox } from '../../api/recognition/types/identity';

const QUEUE_SECTIONS = [
  {
    id: 'singleton-proposals',
    label: __('Singleton proposals', 'alt-context'),
    queuedAction: __('Open singleton proposals queue', 'alt-context'),
    emptyMessage: __('Singleton proposals will appear after the next projection refresh.', 'alt-context'),
  },
  {
    id: 'hard-examples',
    label: __('Hard examples', 'alt-context'),
    queuedAction: __('Open hard examples queue', 'alt-context'),
    emptyMessage: __('Hard examples will appear after the next projection refresh.', 'alt-context'),
  },
  {
    id: 'needs-confirmation-after-merge',
    label: __('Needs confirmation after merge', 'alt-context'),
    queuedAction: __('Open needs confirmation after merge queue', 'alt-context'),
    emptyMessage: __('Confirmation requests will appear after the next projection refresh.', 'alt-context'),
  },
] as const;

const EVIDENCE_IMAGE_SIZE = 96;

interface EvidenceMetadata {
  similarity: number | null;
  similarity_threshold?: number | null;
}

interface LightboxSelection {
  mediaUrl: string;
  bbox: BoundingBox;
  label: string;
}

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

const formatEvidencePercent = (value: number, fractionDigits = 0): string =>
  `${(value * 100).toFixed(fractionDigits)}%`;

const getEvidenceMetadataLines = (evidence: EvidenceMetadata | null | undefined): string[] => {
  if (!evidence) {
    return [];
  }

  const lines: string[] = [];

  if (isFiniteNumber(evidence.similarity)) {
    lines.push(`${formatEvidencePercent(evidence.similarity)} ${__('similarity', 'alt-context')}`);
  } else {
    lines.push(__('Similarity pending next projection refresh.', 'alt-context'));
  }

  const thresholdParts: string[] = [];
  if (isFiniteNumber(evidence.similarity_threshold)) {
    thresholdParts.push(`${__('Threshold', 'alt-context')} ${formatEvidencePercent(evidence.similarity_threshold, 1)}`);
  }
  if (thresholdParts.length > 0) {
    lines.push(thresholdParts.join(' · '));
  }

  return lines;
};

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

  React.useEffect(() => {
    setLightbox(null);
  }, [entryIdentity]);

  return (
    <section
      className="acx-roster__person-workspace"
      role="region"
      aria-label={sprintf(__('Person workspace: %s', 'alt-context'), entry.name)}
    >
      <header className="acx-roster__person-workspace-header">
        <h3>{entry.name}</h3>
        <p className="acx-roster__person-workspace-meta">
          {sprintf(__('%d clusters assigned', 'alt-context'), entry.cluster_count)}
        </p>
        <p className="acx-roster__person-workspace-meta">
          {sprintf(__('Projection status: %s', 'alt-context'), entry.projection_status)}
        </p>
        <p className="acx-roster__person-workspace-meta">
          {sprintf(__('Projection refreshed: %s', 'alt-context'), formatTimestamp(entry.projection_refreshed_at))}
        </p>
        <p className="acx-roster__person-workspace-meta">
          {sprintf(__('Source version: %d', 'alt-context'), entry.source_version)}
        </p>
      </header>

      <div className="acx-roster__person-workspace-summary">
        <section aria-labelledby="acx-person-workspace-clusters">
          <h4 id="acx-person-workspace-clusters">{__('Grouped cluster detail', 'alt-context')}</h4>
          <p>
            {entry.cluster_count === 0
              ? __('No curated clusters are grouped under this person yet.', 'alt-context')
              : sprintf(
                  _n(
                    '%d curated cluster is currently grouped under this person.',
                    '%d curated clusters are currently grouped under this person.',
                    entry.cluster_count,
                    'alt-context',
                  ),
                  entry.cluster_count,
                )}
          </p>
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

      <section aria-label={__('Assigned cluster evidence', 'alt-context')} role="region">
        <h4>{__('Assigned cluster evidence', 'alt-context')}</h4>
        {entry.clusters.length > 0 ? (
          <div>
            {entry.clusters.map((cluster, index) => {
              const clusterLabel = sprintf(__('Cluster %d', 'alt-context'), index + 1);
              const representativeAlt = sprintf(
                __('Representative face for Cluster %d', 'alt-context'),
                index + 1,
              );
              return (
                <section key={cluster.cluster_id} role="region" aria-label={clusterLabel}>
                  <h5>{clusterLabel}</h5>
                  <p>{sprintf(__('%d projected instances', 'alt-context'), cluster.instances.length)}</p>
                  {cluster.representative_identity?.media_url ? (
                    renderEvidenceMedia({
                      mediaUrl: cluster.representative_identity.media_url,
                      bbox: cluster.representative_identity.bbox,
                      alt: representativeAlt,
                      onOpenLightbox: setLightbox,
                    })
                  ) : (
                    <p>{__('Representative face unavailable until the next projection refresh.', 'alt-context')}</p>
                  )}
                  {getEvidenceMetadataLines(cluster.representative_identity).map((line) => (
                    <p key={`${cluster.cluster_id}-representative-${line}`}>{line}</p>
                  ))}
                  <div>
                    {cluster.instances.map((instance) => {
                      const instanceAlt = sprintf(
                        __('Instance %d for Cluster %d', 'alt-context'),
                        instance.media_id,
                        index + 1,
                      );
                      return (
                        <figure key={`${cluster.cluster_id}-${instance.identity_id}-${instance.media_id}`}>
                          {renderEvidenceMedia({
                            mediaUrl: instance.media_url,
                            bbox: instance.bbox,
                            alt: instanceAlt,
                            onOpenLightbox: setLightbox,
                          })}
                          <figcaption>{sprintf(__('Media %d', 'alt-context'), instance.media_id)}</figcaption>
                          {getEvidenceMetadataLines(instance).map((line) => (
                            <div key={`${cluster.cluster_id}-${instance.identity_id}-${instance.media_id}-${line}`}>
                              {line}
                            </div>
                          ))}
                        </figure>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        ) : (
          <p>{__('Assigned cluster evidence will appear after the next projection refresh.', 'alt-context')}</p>
        )}
      </section>

      <section aria-labelledby="acx-person-workspace-queues-title">
        <h4 id="acx-person-workspace-queues-title">{__('Curriculum review queues', 'alt-context')}</h4>
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
                    <p>{__('Person identifier unavailable until the next projection refresh.', 'alt-context')}</p>
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
