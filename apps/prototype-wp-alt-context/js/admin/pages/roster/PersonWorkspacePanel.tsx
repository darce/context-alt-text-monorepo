import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { __, _n, sprintf } from '@wordpress/i18n';
import { getConfig, getEndpoint } from '../../api/config';
import { listRosterEntries, type RosterEntry } from '../../api/rosterApi';
import type { RosterEntryInstance } from '../../api/generated/roster-entry';
import { queryKeys } from '../../api/queryKeys';
import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { formatTimestamp } from '../../utils/formatTimestamp';
import { Combobox } from '../../../components/ui/combobox';
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
const PERSON_MEDIA_PAGE_SIZE = 50;
const ALSO_WITH_PERSON_LIMIT = 5;
const PERSON_MEDIA_LOAD_ERROR_COPY = __('Could not load this person\'s photos.', 'alt-context');
const COVER_UPDATED_COPY = __('Cover photo updated.', 'alt-context');
const COVER_RESTORED_COPY = __('Cover photo restored.', 'alt-context');
const ALSO_WITH_LABEL = __('Also with…', 'alt-context');

interface LightboxSelection {
  mediaUrl: string;
  bbox: BoundingBox;
  label: string;
}

interface PersonMediaItem {
  identity_id: string;
  media_id: number;
  media_url: string | null;
  bbox: RosterEntryInstance['bbox'];
  similarity: number | null;
  cluster_id: string;
}

interface PersonMediaPage {
  media: PersonMediaItem[];
  limit: number;
  offset: number;
  total: number;
  truncated: boolean;
}

interface CoverPin {
  clusterId: string;
  identityId: string;
}

interface CoverToast {
  clusterId: string;
  identityId: string;
  previousIdentityId: string | null;
}

interface CoverPending extends CoverToast {
  kind: 'set' | 'undo';
}

interface AlsoWithPerson {
  id: number;
  name: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const isBoundingBox = (value: unknown): value is BoundingBox =>
  isRecord(value) &&
  typeof value.x === 'number' &&
  typeof value.y === 'number' &&
  typeof value.width === 'number' &&
  typeof value.height === 'number';

const parsePersonMediaItem = (value: unknown): PersonMediaItem => {
  if (!isRecord(value)) {
    throw new Error('Person media item is missing or malformed.');
  }
  if (typeof value.identity_id !== 'string' || typeof value.cluster_id !== 'string') {
    throw new Error('Person media item is missing identity or cluster.');
  }
  if (typeof value.media_id !== 'number') {
    throw new Error('Person media item is missing media_id.');
  }
  if (value.media_url !== null && typeof value.media_url !== 'string') {
    throw new Error('Person media item has a malformed media_url.');
  }
  if (value.bbox !== null && !isBoundingBox(value.bbox)) {
    throw new Error('Person media item has a malformed bbox.');
  }
  if (value.similarity !== null && typeof value.similarity !== 'number') {
    throw new Error('Person media item has a malformed similarity.');
  }
  return {
    identity_id: value.identity_id,
    media_id: value.media_id,
    media_url: value.media_url,
    bbox: value.bbox,
    similarity: value.similarity,
    cluster_id: value.cluster_id,
  };
};

const parsePersonMediaPage = (payload: unknown): PersonMediaPage => {
  if (!isRecord(payload) || !Array.isArray(payload.media)) {
    throw new Error('Person media response is missing or malformed.');
  }
  if (
    typeof payload.limit !== 'number' ||
    typeof payload.offset !== 'number' ||
    typeof payload.total !== 'number' ||
    typeof payload.truncated !== 'boolean'
  ) {
    throw new Error('Person media response is missing pagination metadata.');
  }
  return {
    media: payload.media.map(parsePersonMediaItem),
    limit: payload.limit,
    offset: payload.offset,
    total: payload.total,
    truncated: payload.truncated,
  };
};

const listPersonMedia = async (
  personId: number,
  params: { limit: number; offset: number; withPersonIds?: readonly number[] },
  signal?: AbortSignal,
): Promise<PersonMediaPage> => {
  const requestUrl = new URL(
    `${stripTrailingSlash(getEndpoint('rosterPersons'))}/${personId}/media`,
    window.location.origin,
  );
  requestUrl.searchParams.set('limit', String(params.limit));
  requestUrl.searchParams.set('offset', String(params.offset));
  (params.withPersonIds ?? []).forEach((id) => {
    requestUrl.searchParams.append('with_person_ids[]', String(id));
  });
  const payload = await fetchRequiredApi<unknown>(requestUrl.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal,
  });
  return parsePersonMediaPage(payload);
};

const canQueryPersonMedia = (personId: number): boolean => {
  if (!Number.isInteger(personId) || personId < 1) {
    return false;
  }
  try {
    getEndpoint('rosterPersons');
    return true;
  } catch {
    return false;
  }
};

const canQueryRosterEntries = (): boolean => {
  try {
    getEndpoint('rosterEntries');
    return true;
  } catch {
    return false;
  }
};

const formatAlsoWithNames = (names: readonly string[]): string => {
  if (names.length === 0) {
    return '';
  }
  if (names.length === 1) {
    return names[0] ?? '';
  }
  const head = names.slice(0, -1).join(', ');
  const last = names[names.length - 1] ?? '';
  return sprintf(__('%s and %s', 'alt-context'), head, last);
};

const previousRepresentativeId = (entry: RosterEntry, clusterId: string): string | null => {
  const cluster = entry.clusters.find((candidate) => candidate.cluster_id === clusterId);
  const identityId = cluster?.representative_identity?.identity_id;
  return typeof identityId === 'string' && identityId.length > 0 ? identityId : null;
};

const isPinnedCover = (
  optimistic: CoverPin | null,
  clusterId: string,
  identityId: string,
  entry: RosterEntry,
): boolean => {
  if (optimistic) {
    return optimistic.clusterId === clusterId && optimistic.identityId === identityId;
  }
  return entry.clusters.some(
    (cluster) =>
      cluster.cluster_id === clusterId && cluster.representative_identity?.identity_id === identityId,
  );
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
  const [photoOffset, setPhotoOffset] = React.useState(0);
  const [alsoWithPeople, setAlsoWithPeople] = React.useState<AlsoWithPerson[]>([]);
  const [coverUi, setCoverUi] = React.useState<{ optimistic: CoverPin | null; toast: CoverToast | null }>({
    optimistic: null,
    toast: null,
  });
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
  const pendingCoverRef = React.useRef<CoverPending | null>(null);
  const seenCoverPinRef = React.useRef(false);
  const mediaEnabled = canQueryPersonMedia(entry.id);
  const rosterEnabled = canQueryRosterEntries();
  const withPersonIds = React.useMemo(
    () => alsoWithPeople.map((person) => person.id),
    [alsoWithPeople],
  );
  const rosterQuery = useQuery({
    queryKey: queryKeys.roster.entries(),
    queryFn: () => listRosterEntries(),
    enabled: rosterEnabled,
  });
  const personMediaQuery = useQuery({
    queryKey: [...queryKeys.roster.entries(), 'media', entry.id, { limit: PERSON_MEDIA_PAGE_SIZE, offset: photoOffset, withPersonIds }],
    queryFn: ({ signal }) =>
      listPersonMedia(entry.id, { limit: PERSON_MEDIA_PAGE_SIZE, offset: photoOffset, withPersonIds }, signal),
    enabled: mediaEnabled,
  });
  const alsoWithOptions = React.useMemo(() => {
    const selectedIds = new Set(withPersonIds);
    return (rosterQuery.data ?? [])
      .filter(
        (person) =>
          Number.isInteger(person.id) &&
          person.id >= 1 &&
          person.id !== entry.id &&
          !selectedIds.has(person.id) &&
          person.name.trim().length > 0,
      )
      .map((person) => ({ value: String(person.id), label: person.name }));
  }, [entry.id, rosterQuery.data, withPersonIds]);
  const alsoWithAtLimit = alsoWithPeople.length >= ALSO_WITH_PERSON_LIMIT;

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
    setPhotoOffset(0);
    setAlsoWithPeople([]);
    setCoverUi({ optimistic: null, toast: null });
    pendingCoverRef.current = null;
    seenCoverPinRef.current = false;
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
  const selectedIsCover = Boolean(
    selectedFace &&
      isPinnedCover(coverUi.optimistic, selectedFace.clusterId, selectedFace.identityId, entry),
  );
  const canUseAsCover = Boolean(selectedFace?.clusterId && selectedFace.identityId && !selectedIsCover && !isPinning);

  const useAsCover = React.useCallback(
    (clusterId: string, identityId: string, kind: CoverPending['kind'] = 'set') => {
      if (!clusterId || !identityId || isPinning) {
        return;
      }
      const previousIdentityId =
        kind === 'undo'
          ? identityId === coverUi.toast?.identityId
            ? coverUi.toast.previousIdentityId
            : previousRepresentativeId(entry, clusterId)
          : previousRepresentativeId(entry, clusterId);
      const nextOptimistic: CoverPin | null =
        kind === 'undo' && !previousIdentityId ? null : { clusterId, identityId };
      pendingCoverRef.current = { kind, clusterId, identityId, previousIdentityId };
      setCoverUi({ optimistic: nextOptimistic, toast: kind === 'set' ? null : coverUi.toast });
      pin(clusterId, identityId, true);
      seenCoverPinRef.current = true;
    },
    [coverUi.toast, entry, isPinning, pin],
  );

  const undoCover = React.useCallback(() => {
    const toast = coverUi.toast;
    if (!toast || isPinning) {
      return;
    }
    if (toast.previousIdentityId) {
      useAsCover(toast.clusterId, toast.previousIdentityId, 'undo');
      return;
    }
    pendingCoverRef.current = {
      kind: 'undo',
      clusterId: toast.clusterId,
      identityId: toast.identityId,
      previousIdentityId: null,
    };
    setCoverUi({ optimistic: null, toast });
    pin(toast.clusterId, toast.identityId, false);
    seenCoverPinRef.current = true;
  }, [coverUi.toast, isPinning, pin, useAsCover]);

  React.useEffect(() => {
    if (isPinning) {
      seenCoverPinRef.current = true;
      return;
    }
    const pending = pendingCoverRef.current;
    if (!pending) {
      seenCoverPinRef.current = false;
      return;
    }
    if (!seenCoverPinRef.current) {
      return;
    }
    seenCoverPinRef.current = false;
    pendingCoverRef.current = null;
    if (pinError) {
      setCoverUi({ optimistic: null, toast: null });
      return;
    }
    if (pending.kind === 'undo') {
      setCoverUi({
        optimistic: pending.previousIdentityId
          ? { clusterId: pending.clusterId, identityId: pending.identityId }
          : null,
        toast: null,
      });
      announce(COVER_RESTORED_COPY);
      return;
    }
    setCoverUi({
      optimistic: { clusterId: pending.clusterId, identityId: pending.identityId },
      toast: {
        clusterId: pending.clusterId,
        identityId: pending.identityId,
        previousIdentityId: pending.previousIdentityId,
      },
    });
    announce(COVER_UPDATED_COPY);
  }, [announce, isPinning, pinError]);

  const addAlsoWithPerson = React.useCallback(
    (personId: number, name: string) => {
      if (!Number.isInteger(personId) || personId < 1 || personId === entry.id || name.trim().length === 0) {
        return;
      }
      setAlsoWithPeople((current) => {
        if (current.length >= ALSO_WITH_PERSON_LIMIT || current.some((person) => person.id === personId)) {
          return current;
        }
        return [...current, { id: personId, name }];
      });
      setPhotoOffset(0);
    },
    [entry.id],
  );

  const removeAlsoWithPerson = React.useCallback((personId: number) => {
    setAlsoWithPeople((current) => current.filter((person) => person.id !== personId));
    setPhotoOffset(0);
  }, []);

  const photoPage = personMediaQuery.data ?? null;
  const alsoWithEmptyCopy =
    alsoWithPeople.length > 0
      ? sprintf(
          __('No photos of %s also with %s.', 'alt-context'),
          entry.name,
          formatAlsoWithNames(alsoWithPeople.map((person) => person.name)),
        )
      : __('No photos of this person yet.', 'alt-context');

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
            ) : null}
            <button
              type="button"
              className="acx-button acx-button--primary"
              disabled={!selectedFace || !canPin || isPinning}
              onClick={() => {
                if (!selectedFace) {
                  return;
                }
                pin(selectedFace.clusterId, selectedFace.identityId, true);
              }}
            >
              {__('Set as representative', 'alt-context')}
            </button>
            <button
              type="button"
              className="acx-button acx-button--secondary"
              disabled={!canUseAsCover}
              onClick={() => {
                if (!selectedFace) {
                  return;
                }
                useAsCover(selectedFace.clusterId, selectedFace.identityId);
              }}
            >
              {selectedIsCover ? __('Already the cover', 'alt-context') : __('Use as cover', 'alt-context')}
            </button>
            {coverUi.toast ? (
              <div
                className="acx-roster__person-workspace-live"
                role="status"
                data-testid="acx-person-cover-toast"
                aria-live="polite"
                aria-label={__('Cover photo status', 'alt-context')}
              >
                <p>{COVER_UPDATED_COPY}</p>
                <button type="button" className="acx-button" onClick={undoCover}>
                  {__('Undo', 'alt-context')}
                </button>
              </div>
            ) : null}
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

      <section
        aria-labelledby="acx-person-workspace-photos"
        data-testid="acx-person-photo-grid"
        role="region"
        aria-label={__('Photos', 'alt-context')}
      >
        <h4 id="acx-person-workspace-photos">{__('Photos', 'alt-context')}</h4>
        <div role="search" aria-label={ALSO_WITH_LABEL}>
          <Combobox
            options={alsoWithOptions}
            onSelect={(value) => {
              const selected = alsoWithOptions.find((option) => option.value === value);
              if (!selected) {
                return;
              }
              addAlsoWithPerson(Number(selected.value), selected.label);
            }}
            placeholder={ALSO_WITH_LABEL}
            searchPlaceholder={__('Search people', 'alt-context')}
            emptyText={__('No named people found.', 'alt-context')}
            ariaLabel={ALSO_WITH_LABEL}
            disabled={!rosterEnabled || alsoWithAtLimit}
            isLoading={rosterEnabled && rosterQuery.isLoading}
          />
          {alsoWithPeople.length > 0 ? (
            <ul aria-label={__('Also with people', 'alt-context')}>
              {alsoWithPeople.map((person) => (
                <li key={person.id}>
                  <span>{person.name}</span>
                  <button
                    type="button"
                    className="acx-button"
                    aria-label={sprintf(__('Remove %s', 'alt-context'), person.name)}
                    onClick={() => {
                      removeAlsoWithPerson(person.id);
                    }}
                  >
                    {__('Remove', 'alt-context')}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        {!mediaEnabled ? (
          <p>{__('Photos will appear after the next refresh.', 'alt-context')}</p>
        ) : personMediaQuery.isLoading ? (
          <p role="status">{__('Loading photos…', 'alt-context')}</p>
        ) : personMediaQuery.isError ? (
          <UserFacingErrorNotice error={personMediaQuery.error} fallback={PERSON_MEDIA_LOAD_ERROR_COPY} />
        ) : photoPage && photoPage.media.length === 0 ? (
          <p>{alsoWithEmptyCopy}</p>
        ) : photoPage ? (
          <>
            <ul>
              {photoPage.media.map((item) => {
                const itemIsCover = isPinnedCover(
                  coverUi.optimistic,
                  item.cluster_id,
                  item.identity_id,
                  entry,
                );
                const photoAlt = sprintf(__('Photo from media %d', 'alt-context'), item.media_id);
                const coverLabel = itemIsCover
                  ? sprintf(__('Media %d is already the cover', 'alt-context'), item.media_id)
                  : sprintf(__('Use media %d as cover', 'alt-context'), item.media_id);
                const canCoverItem =
                  item.cluster_id.length > 0 && item.identity_id.length > 0 && !itemIsCover && !isPinning;
                return (
                  <li key={`${item.cluster_id}-${item.identity_id}-${item.media_id}`}>
                    {renderEvidenceMedia({
                      mediaUrl: item.media_url,
                      bbox: item.bbox,
                      alt: photoAlt,
                      onOpenLightbox: setLightbox,
                    })}
                    <p>{sprintf(__('Media %d', 'alt-context'), item.media_id)}</p>
                    {itemIsCover ? <p>{__('Current cover', 'alt-context')}</p> : null}
                    <button
                      type="button"
                      className="acx-button"
                      disabled={!canCoverItem}
                      aria-label={coverLabel}
                      onClick={() => {
                        useAsCover(item.cluster_id, item.identity_id);
                      }}
                    >
                      {itemIsCover ? __('Already the cover', 'alt-context') : __('Use as cover', 'alt-context')}
                    </button>
                  </li>
                );
              })}
            </ul>
            <p>
              {photoPage.total > 0
                ? sprintf(
                    __('%d–%d of %d photos', 'alt-context'),
                    photoPage.offset + 1,
                    photoPage.offset + photoPage.media.length,
                    photoPage.total,
                  )
                : null}
            </p>
            <button
              type="button"
              className="acx-button"
              disabled={photoPage.offset <= 0 || isPinning}
              onClick={() => {
                setPhotoOffset(Math.max(0, photoPage.offset - photoPage.limit));
              }}
            >
              {__('Previous photos', 'alt-context')}
            </button>
            <button
              type="button"
              className="acx-button"
              disabled={!photoPage.truncated || isPinning}
              onClick={() => {
                setPhotoOffset(photoPage.offset + photoPage.limit);
              }}
            >
              {__('Next photos', 'alt-context')}
            </button>
          </>
        ) : (
          <p>{__('Photos will appear after the next refresh.', 'alt-context')}</p>
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
