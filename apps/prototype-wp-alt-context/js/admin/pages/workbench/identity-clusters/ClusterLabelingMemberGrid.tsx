/**
 * Member-face grid for ClusterLabelingPanel (extracted for FEBT1G-M-14).
 *
 * Owns member loading, reading-order positioning, the show-all expansion affordance and
 * its AT announcement. The panel keeps naming; this file keeps faces.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import { Avatar } from '../../../../components/ui/avatar';
import { isCroppableBbox } from '../../../../components/ui/faceGeometry';
import { unavailableImageName } from '../../../../components/ui/faceThumbDisplay';
import { isDedicatedFaceThumbUrl } from '../../../../components/ui/isDedicatedFaceThumbUrl';
import { EmptyState, EmptyStateVariant } from '../../../components/ui/EmptyState';
import { useShowAllClusterMembers } from './useShowAllClusterMembers';

interface ClusterLabelingMemberGridProps {
  readonly clusterId: string;
  readonly onClose: () => void;
}

type ClusterMember = ReturnType<typeof useShowAllClusterMembers>['members'][number];

/**
 * Reading order within a media item: left-to-right by bbox x, with positionless faces
 * kept last and ties resolved by original index (stable).
 */
const buildMemberPositions = (members: readonly ClusterMember[]): number[] => {
  const positions: number[] = [];
  const memberIndexesByMedia = new Map<number, number[]>();

  members.forEach((member, memberIndex) => {
    const mediaMemberIndexes = memberIndexesByMedia.get(member.media_id) ?? [];
    mediaMemberIndexes.push(memberIndex);
    memberIndexesByMedia.set(member.media_id, mediaMemberIndexes);
  });

  memberIndexesByMedia.forEach((memberIndexes) => {
    memberIndexes
      .sort((leftIndex, rightIndex) => {
        const leftX = members[leftIndex]?.bbox?.x;
        const rightX = members[rightIndex]?.bbox?.x;
        const leftHasPosition = Number.isFinite(leftX);
        const rightHasPosition = Number.isFinite(rightX);

        if (
          leftHasPosition &&
          rightHasPosition &&
          typeof leftX === 'number' &&
          typeof rightX === 'number' &&
          leftX !== rightX
        ) {
          return leftX - rightX;
        }
        if (leftHasPosition !== rightHasPosition) {
          return leftHasPosition ? -1 : 1;
        }
        return leftIndex - rightIndex;
      })
      .forEach((memberIndex, positionIndex) => {
        positions[memberIndex] = positionIndex + 1;
      });
  });

  return positions;
};

const MemberFace = ({ member, alt }: { member: ClusterMember; alt: string }): React.JSX.Element => {
  if (member.thumb_url && isDedicatedFaceThumbUrl(member.thumb_url)) {
    return <Avatar src={member.thumb_url} size="lg" alt={alt} />;
  }
  if (member.media_url && isCroppableBbox(member.bbox)) {
    return <FaceThumbnail mediaUrl={member.media_url} bbox={member.bbox} size="lg" alt={alt} />;
  }
  if (member.thumb_url) {
    return <Avatar src={member.thumb_url} size="lg" alt={alt} />;
  }
  return (
    <div className="acx-cluster-labeling-panel__face-unavailable" role="img" aria-label={unavailableImageName(alt)}>
      <span className="acx-cluster-labeling-panel__face-unavailable-label">{__('No image', 'alt-context')}</span>
    </div>
  );
};

export const ClusterLabelingMemberGrid = ({
  clusterId,
  onClose,
}: ClusterLabelingMemberGridProps): React.JSX.Element => {
  const { members, isLoading, isError, truncated, total, isFullyLoaded, isExpanding, expandError, showAll, refetch } =
    useShowAllClusterMembers(clusterId);
  const [showAllAnnouncement, setShowAllAnnouncement] = useState<string | null>(null);
  const memberGridRef = useRef<HTMLDivElement | null>(null);
  const wasExpandingRef = useRef(false);

  const memberPositions = useMemo(() => buildMemberPositions(members), [members]);

  // AT affordance: when expansion completes the show-all button unmounts, so announce
  // completion and move focus to the member grid before it drops.
  useEffect(() => {
    if (wasExpandingRef.current && !isExpanding && isFullyLoaded && !expandError) {
      setShowAllAnnouncement(
        sprintf(
          /* translators: %d: total member count */
          __('All %d members shown', 'alt-context'),
          total,
        ),
      );
      memberGridRef.current?.focus();
    }
    wasExpandingRef.current = isExpanding;
  }, [isExpanding, isFullyLoaded, expandError, total]);

  const handleShowAll = () => {
    void showAll();
  };

  return (
    <>
      <div className="acx-cluster-labeling-panel__grid" ref={memberGridRef} tabIndex={-1}>
        {isLoading ? (
          <p>{__('Loading faces...', 'alt-context')}</p>
        ) : isError ? (
          <div className="acx-cluster-labeling-panel__error" role="alert" data-testid="acx-cluster-members-error">
            <p>{__('Unable to load these faces.', 'alt-context')}</p>
            <button type="button" className="button" onClick={() => refetch()}>
              {__('Retry', 'alt-context')}
            </button>
          </div>
        ) : members.length > 0 ? (
          members.map((member, memberIndex) => (
            <div key={member.identity_id} className="acx-cluster-labeling-panel__face">
              <MemberFace
                member={member}
                alt={sprintf(
                  __('Face %1$d in media %2$d', 'alt-context'),
                  memberPositions[memberIndex] ?? memberIndex + 1,
                  member.media_id,
                )}
              />
            </div>
          ))
        ) : (
          <EmptyState
            variant={EmptyStateVariant.EMPTY}
            heading={__('No faces available to name', 'alt-context')}
            body={__('Return to the review suggestions and choose another face group.', 'alt-context')}
            action={{ label: __('Back to review suggestions', 'alt-context'), onClick: onClose }}
            headingLevel={3}
          />
        )}
      </div>
      <p className="acx-cluster-members-show-all__announce" role="status" aria-live="polite">
        {showAllAnnouncement}
      </p>
      {truncated && !isFullyLoaded ? (
        <div className="acx-cluster-members-show-all">
          <button
            type="button"
            className="button acx-cluster-members-show-all__button"
            onClick={handleShowAll}
            disabled={isExpanding}
            data-truncated={truncated ? 'true' : 'false'}
            data-total={total}
          >
            {isExpanding
              ? __('Loading all members…', 'alt-context')
              : sprintf(
                  /* translators: %d: total member count */
                  __('Show all (%d)', 'alt-context'),
                  total,
                )}
          </button>
          {expandError ? (
            <p className="acx-cluster-members-show-all__error" role="alert">
              {expandError}
            </p>
          ) : null}
        </div>
      ) : null}
    </>
  );
};
