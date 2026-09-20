import React, { useEffect, useState } from 'react';
import { __ } from '@wordpress/i18n';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getEndpoint } from '../../api/config';
import { queryKeys } from '../../api/queryKeys';
import {
  acceptMergeSuggestion,
  fetchPendingMergeSuggestions,
  rejectMergeSuggestion,
  type BoundingBox,
  type PendingMergeSuggestion,
} from '../../api/recognition';
import { Avatar } from '../../../components/ui/avatar';
import { FaceThumbnail } from '../../../components/ui/FaceThumbnail';

export const SAME_PERSON_PROMPT_SESSION_KEY = 'acx.samePersonPrompt.consumed';

const SESSION_CONSUMED_VALUE = '1';

let samePersonPromptConsumedInMemory = false;

const canFetchMergeSuggestions = (): boolean => {
  try {
    getEndpoint('recognitionMergeSuggestions');
    return true;
  } catch {
    return false;
  }
};

const readSamePersonPromptConsumed = (): boolean => {
  if (samePersonPromptConsumedInMemory) {
    return true;
  }
  try {
    if (typeof window === 'undefined' || !window.sessionStorage) {
      return false;
    }
    const stored = window.sessionStorage.getItem(SAME_PERSON_PROMPT_SESSION_KEY) === SESSION_CONSUMED_VALUE;
    if (stored) {
      samePersonPromptConsumedInMemory = true;
    }
    return stored;
  } catch {
    return false;
  }
};

const writeSamePersonPromptConsumed = (): void => {
  samePersonPromptConsumedInMemory = true;
  try {
    if (typeof window === 'undefined' || !window.sessionStorage) {
      return;
    }
    window.sessionStorage.setItem(SAME_PERSON_PROMPT_SESSION_KEY, SESSION_CONSUMED_VALUE);
  } catch {
    // sessionStorage may be blocked; in-memory hide still applies
  }
};

export const resetSamePersonPromptSessionForTests = (): void => {
  samePersonPromptConsumedInMemory = false;
};

const isReservedClusterLabel = (label: string): boolean => {
  const normalized = label.trim().toLowerCase();
  return normalized.startsWith('cluster-') || normalized.startsWith('cluster_');
};

const unnamedPersonName = (sideIndex: 0 | 1): string =>
  sideIndex === 0 ? __('First person', 'alt-context') : __('Second person', 'alt-context');

const displayPersonName = (label: string | null | undefined, sideIndex: 0 | 1): string => {
  if (label == null) {
    return unnamedPersonName(sideIndex);
  }
  const trimmed = label.trim();
  if (trimmed === '' || isReservedClusterLabel(trimmed)) {
    return unnamedPersonName(sideIndex);
  }
  return trimmed;
};

const mediaAdminEditHref = (mediaId: number | null | undefined): string | null => {
  if (typeof mediaId !== 'number' || !Number.isInteger(mediaId) || mediaId <= 0) {
    return null;
  }
  const params = new URLSearchParams({ post: String(mediaId), action: 'edit' });
  return `post.php?${params.toString()}`;
};

const FaceSide = ({
  name,
  mediaUrl,
  bbox,
  thumbUrl,
  photoHref,
}: {
  name: string;
  mediaUrl: string | null | undefined;
  bbox: BoundingBox | null | undefined;
  thumbUrl: string | null | undefined;
  photoHref: string | null;
}): React.JSX.Element => {
  const hasCrop = typeof mediaUrl === 'string' && mediaUrl.length > 0 && bbox != null;
  const croppedThumb = typeof thumbUrl === 'string' && thumbUrl.length > 0 ? thumbUrl : undefined;
  return (
    <div className="acx-suggestion-card__face">
      {hasCrop ? (
        <FaceThumbnail mediaUrl={mediaUrl} bbox={bbox} size="md" alt={name} className="acx-suggestion-card__thumb" />
      ) : (
        <Avatar
          size="md"
          className="acx-suggestion-card__thumb"
          src={croppedThumb}
          alt={name}
          missingLabel={name}
          hideMissingLabel
        />
      )}
      <span className="acx-suggestion-card__face-label">{name}</span>
      {photoHref !== null ? (
        <a className="acx-suggestion-card__view-photo" href={photoHref} target="_blank" rel="noopener noreferrer">
          {__('View photo', 'alt-context')}
        </a>
      ) : null}
    </div>
  );
};

export const SamePersonPrompt = (): React.JSX.Element | null => {
  const queryClient = useQueryClient();
  const [sessionConsumed, setSessionConsumed] = useState(readSamePersonPromptConsumed);
  const pendingQuery = useQuery({
    queryKey: queryKeys.suggestions.mergePending(),
    queryFn: () => fetchPendingMergeSuggestions(10, 0),
    enabled: !sessionConsumed && canFetchMergeSuggestions(),
    retry: false,
  });
  const consumePrompt = (): void => {
    writeSamePersonPromptConsumed();
    setSessionConsumed(true);
  };
  const acceptMutation = useMutation({
    mutationFn: acceptMergeSuggestion,
    onSuccess: async () => {
      consumePrompt();
      await queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
    },
  });
  const rejectMutation = useMutation({
    mutationFn: rejectMergeSuggestion,
    onSuccess: async () => {
      consumePrompt();
      await queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
    },
  });

  const suggestion: PendingMergeSuggestion | null = pendingQuery.data?.suggestions[0] ?? null;
  const suggestionId = suggestion?.id ?? null;

  useEffect(() => {
    if (sessionConsumed || suggestionId === null) {
      return;
    }
    writeSamePersonPromptConsumed();
  }, [sessionConsumed, suggestionId]);

  if (sessionConsumed || suggestion === null) {
    return null;
  }

  const busy = acceptMutation.isPending || rejectMutation.isPending;
  const error = acceptMutation.error ?? rejectMutation.error;
  const nameA = displayPersonName(suggestion.cluster_a_label, 0);
  const nameB = displayPersonName(suggestion.cluster_b_label, 1);
  const titleId = 'acx-same-person-prompt-title';

  return (
    <section
      className="acx-suggestion-card acx-suggestion-card--merge"
      data-testid="acx-same-person-prompt"
      aria-labelledby={titleId}
      aria-busy={busy || undefined}
    >
      <div className="acx-suggestion-card__faces">
        <FaceSide
          name={nameA}
          mediaUrl={suggestion.cluster_a_representative_media_url}
          bbox={suggestion.cluster_a_representative_bbox}
          thumbUrl={suggestion.cluster_a_representative_thumb_url}
          photoHref={mediaAdminEditHref(suggestion.cluster_a_representative_media_id)}
        />
        <FaceSide
          name={nameB}
          mediaUrl={suggestion.cluster_b_representative_media_url}
          bbox={suggestion.cluster_b_representative_bbox}
          thumbUrl={suggestion.cluster_b_representative_thumb_url}
          photoHref={mediaAdminEditHref(suggestion.cluster_b_representative_media_id)}
        />
      </div>
      <div className="acx-suggestion-card__content">
        <h2 id={titleId} className="acx-suggestion-card__question">
          {__('Same or different person?', 'alt-context')}
        </h2>
      </div>
      {error ? (
        <p role="alert">{error instanceof Error ? error.message : __('Unable to save this choice.', 'alt-context')}</p>
      ) : null}
      <div className="acx-suggestion-card__actions">
        <button
          type="button"
          className="acx-button acx-button--primary"
          onClick={() => {
            acceptMutation.mutate(suggestion.id);
          }}
          disabled={busy}
          aria-describedby={titleId}
        >
          {__('Yes', 'alt-context')}
        </button>
        <button
          type="button"
          className="acx-button acx-button--secondary"
          onClick={() => {
            rejectMutation.mutate(suggestion.id);
          }}
          disabled={busy}
          aria-describedby={titleId}
        >
          {__('No', 'alt-context')}
        </button>
        <button type="button" className="acx-button" onClick={consumePrompt} disabled={busy} aria-describedby={titleId}>
          {__('Skip', 'alt-context')}
        </button>
      </div>
    </section>
  );
};
