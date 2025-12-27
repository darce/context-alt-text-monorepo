# Implementation Plan: Top Clusters Curation UI

**Related Task**: `dynamic_suggestion_updates_implementation_plan.md` §6.3
**Date**: 2025-12-24
**Status**: 📋 Planned

---

## 1. Overview

The current `CurateTopClustersPrompt` component is a passive guidance prompt that shows users which clusters to label. This plan extends it into a **fully interactive curation panel** that allows:

1. **Wholesale cluster labeling** — Label multiple top clusters without navigating pages
2. **Identity removal** — Remove incorrectly clustered faces directly from the panel
3. **Suggestion confirm/reject** — Surface pending suggestions with clear Yes/No buttons

---

## 2. Problem Statement

### Current State

| Component | Current Behavior | Gap |
|-----------|-----------------|-----|
| `CurateTopClustersPrompt` | Read-only list of top unlabeled clusters | No inline editing or actions |
| `InlineSuggestionPrompt` | Shows "Is this X?" with Yes/No buttons | Only appears for identities with suggestions |
| `SuggestionReviewPanel` | Lists pending suggestions with actions | Not prominently surfaced in main workflow |

### User Feedback

> "I want to label the biggest clusters wholesale at the top of the page without navigating to each page individually. This high-level cluster labeling feature must be able to remove incorrectly clustered identities."

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F1 | Display top N unlabeled clusters in an expandable panel | Must |
| F2 | Allow inline label editing for each cluster | Must |
| F3 | Show cluster member thumbnails when expanded | Must |
| F4 | Allow removal of incorrectly clustered identities | Must |
| F5 | Show pending suggestions with confirm/reject buttons | Must |
| F6 | Persist across page navigation (panel state) | Should |
| F7 | Batch operations (label multiple, dismiss multiple) | Could |

### 3.2 Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NF1 | Panel loads in < 500ms | Must |
| NF2 | Actions provide immediate visual feedback | Must |
| NF3 | Accessible keyboard navigation | Must |
| NF4 | Mobile-responsive layout | Should |

---

## 4. Proposed Design

### 4.1 Component Hierarchy

```
TopClustersCurationPanel (new)
├── PanelHeader
│   ├── Title: "Quick Cluster Curation"
│   ├── Badge: "{n} clusters need labels"
│   └── CollapseButton
├── ClusterCurationCard[] (per top cluster)
│   ├── ClusterPreview (thumbnail + count)
│   ├── InlineLabelEditor
│   │   ├── TextInput (autofocus)
│   │   ├── SuggestionDropdown
│   │   └── SaveButton
│   ├── MemberGallery (expandable)
│   │   ├── MemberThumbnail[]
│   │   └── RemoveButton (per member)
│   └── ActionBar
│       ├── ExpandToggle
│       └── SkipButton
└── SuggestionPromptSection
    ├── SuggestionCard[] (pending suggestions)
    │   ├── IdentityThumbnail
    │   ├── "Is this {label}?" text
    │   ├── SimilarityBadge ("{n}%")
    │   ├── ConfirmButton (✓ Yes)
    │   └── RejectButton (✗ No)
    └── ViewAllLink
```

### 4.2 Wireframe

```
┌─────────────────────────────────────────────────────────────┐
│ 🏷️ Quick Cluster Curation                      [3 clusters] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────┐  ┌────────────────────────────┐  ┌──────┐         │
│  │ 👤  │  │ Enter name...              │  │ Save │  [▼]    │
│  │ x12 │  └────────────────────────────┘  └──────┘         │
│  └─────┘  Suggested: John Smith (89%), Jane Doe (72%)      │
│                                                             │
│  ┌─────┐  ┌────────────────────────────┐  ┌──────┐         │
│  │ 👤  │  │ Enter name...              │  │ Save │  [▼]    │
│  │ x8  │  └────────────────────────────┘  └──────┘         │
│  └─────┘                                                    │
│                                                             │
│  ┌─────┐  ┌────────────────────────────┐  ┌──────┐         │
│  │ 👤  │  │ Enter name...              │  │ Save │  [▼]    │
│  │ x5  │  └────────────────────────────┘  └──────┘         │
│  └─────┘                                                    │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ 💡 Pending Suggestions (2)                                  │
│                                                             │
│  ┌─────┐  Is this John Smith?    87%   [✓ Yes] [✗ No]     │
│  │ 👤  │                                                    │
│  └─────┘                                                    │
│                                                             │
│  ┌─────┐  Is this Jane Doe?      73%   [✓ Yes] [✗ No]     │
│  │ 👤  │                                                    │
│  └─────┘                                                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 Expanded Cluster View (with member removal)

```
┌─────────────────────────────────────────────────────────────┐
│  ┌─────┐  ┌────────────────────────────┐  ┌──────┐         │
│  │ 👤  │  │ John Smith                 │  │ Save │  [▲]    │
│  │ x12 │  └────────────────────────────┘  └──────┘         │
│  └─────┘                                                    │
│                                                             │
│  Members (12):                                              │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │
│  │ 👤  │ │ 👤  │ │ 👤  │ │ 👤  │ │ 👤  │ │ 👤  │          │
│  │  ✗  │ │  ✗  │ │  ✗  │ │  ✗  │ │  ✗  │ │  ✗  │          │
│  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘          │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │
│  │ 👤  │ │ 👤  │ │ 👤  │ │ 👤  │ │ 👤  │ │ 👤  │          │
│  │  ✗  │ │  ✗  │ │  ✗  │ │  ✗  │ │  ✗  │ │  ✗  │          │
│  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘          │
│                                                             │
│  [Remove selected (0)]                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Technical Implementation

### 5.1 Backend Changes

#### 5.1.1 Enhanced `/clusters/top-unlabeled` Response

**Current Response**:
```json
{
  "id": "uuid",
  "label": "cluster-abc123",
  "identity_count": 12,
  "is_labeled": false
}
```

**Enhanced Response** (add `members` and `suggestions`):
```json
{
  "id": "uuid",
  "label": "cluster-abc123",
  "identity_count": 12,
  "is_labeled": false,
  "representative": {
    "identity_id": "uuid",
    "thumbnail_url": "/media/123/face-crop.jpg",
    "bounds": { "x": 100, "y": 50, "width": 80, "height": 100 }
  },
  "members": [
    {
      "identity_id": "uuid",
      "media_id": 123,
      "thumbnail_url": "/media/123/face-crop.jpg",
      "bounds": { "x": 100, "y": 50, "width": 80, "height": 100 }
    }
  ],
  "top_suggestions": [
    {
      "cluster_id": "uuid",
      "label": "John Smith",
      "similarity": 0.89
    }
  ]
}
```

**File**: `recognition/interface_adapters/http/routers/clusters.py`

```python
class TopUnlabeledClusterResponse(BaseModel):
    """Enhanced response for top unlabeled clusters with members and suggestions."""
    
    id: str
    label: str | None
    identity_count: int
    is_labeled: bool
    representative: RepresentativeResponse | None
    members: list[ClusterMemberResponse]  # First N members
    top_suggestions: list[ClusterSuggestionResponse]  # Top 3 label suggestions


@router.get("/clusters/top-unlabeled/detailed", response_model=list[TopUnlabeledClusterResponse])
async def get_top_unlabeled_clusters_detailed(
    limit: int = Query(default=5, ge=1, le=10),
    members_limit: int = Query(default=12, ge=1, le=24),
    tenant_id: str = Depends(get_tenant_id),
    session=Depends(get_session),
) -> list[TopUnlabeledClusterResponse]:
    """Get top unlabeled clusters with member details for inline curation."""
    ...
```

#### 5.1.2 Batch Remove Identities Endpoint

**File**: `recognition/interface_adapters/http/routers/clusters.py`

```python
class BatchRemoveIdentitiesRequest(BaseModel):
    """Request to remove multiple identities from a cluster."""
    
    cluster_id: str
    identity_ids: list[str]
    reason: str = "wrong_person"  # For logging


class BatchRemoveIdentitiesResponse(BaseModel):
    """Response after batch identity removal."""
    
    removed_count: int
    cluster_id: str
    new_identity_count: int


@router.post("/clusters/{cluster_id}/remove-identities", response_model=BatchRemoveIdentitiesResponse)
async def batch_remove_identities(
    cluster_id: str,
    request: BatchRemoveIdentitiesRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> BatchRemoveIdentitiesResponse:
    """Remove multiple identities from a cluster (wrong person correction)."""
    ...
```

### 5.2 Frontend Changes

#### 5.2.1 New Components

| Component | Purpose | File |
|-----------|---------|------|
| `TopClustersCurationPanel` | Main container panel | `TopClustersCurationPanel.tsx` |
| `ClusterCurationCard` | Individual cluster with inline editing | `ClusterCurationCard.tsx` |
| `MemberGallery` | Expandable member grid with removal | `MemberGallery.tsx` |
| `MemberThumbnail` | Single member with remove button | `MemberThumbnail.tsx` |
| `SuggestionPromptList` | List of pending suggestions | `SuggestionPromptList.tsx` |

#### 5.2.2 New Hooks

| Hook | Purpose | File |
|------|---------|------|
| `useTopUnlabeledClusters` | Fetch detailed top clusters | `useTopUnlabeledClusters.ts` |
| `useBatchRemoveIdentities` | Mutation for batch removal | `useBatchRemoveIdentities.ts` |
| `usePendingSuggestions` | Fetch suggestions with actions | `usePendingSuggestions.ts` |

#### 5.2.3 Component Implementation

**File**: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersCurationPanel.tsx`

```tsx
/**
 * Interactive panel for curating top unlabeled clusters.
 * 
 * Provides wholesale cluster labeling without page navigation,
 * with ability to remove incorrectly clustered identities.
 */

import React, { useState } from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import { useQuery } from '@tanstack/react-query';

import { ClusterCurationCard } from './ClusterCurationCard';
import { SuggestionPromptList } from './SuggestionPromptList';
import type { TopUnlabeledCluster } from '../../../api/recognition/types';

interface TopClustersCurationPanelProps {
  /** Tenant ID for API scoping */
  tenantId: string;
  /** Maximum clusters to show */
  limit?: number;
  /** Whether panel is initially collapsed */
  defaultCollapsed?: boolean;
}

export const TopClustersCurationPanel = ({
  tenantId,
  limit = 5,
  defaultCollapsed = false,
}: TopClustersCurationPanelProps): React.JSX.Element | null => {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const [expandedClusterId, setExpandedClusterId] = useState<string | null>(null);

  const { data: clusters, isLoading } = useQuery<TopUnlabeledCluster[]>({
    queryKey: ['clusters', 'top-unlabeled', 'detailed', tenantId, limit],
    queryFn: async () => {
      // Fetch from /clusters/top-unlabeled/detailed
      throw new Error('TODO: Implement API call');
    },
    staleTime: 30000,
  });

  if (isLoading || !clusters || clusters.length === 0) {
    return null;
  }

  return (
    <div className="acx-top-clusters-panel">
      <button
        type="button"
        className="acx-top-clusters-panel__header"
        onClick={() => setIsCollapsed(!isCollapsed)}
        aria-expanded={!isCollapsed}
      >
        <span className="acx-top-clusters-panel__title">
          {__('Quick Cluster Curation', 'alt-context')}
        </span>
        <span className="acx-top-clusters-panel__badge">
          {sprintf(
            _n('%d cluster', '%d clusters', clusters.length, 'alt-context'),
            clusters.length
          )}
        </span>
        <span className="acx-top-clusters-panel__toggle">
          {isCollapsed ? '▼' : '▲'}
        </span>
      </button>

      {!isCollapsed && (
        <div className="acx-top-clusters-panel__content">
          <div className="acx-top-clusters-panel__clusters">
            {clusters.map((cluster) => (
              <ClusterCurationCard
                key={cluster.id}
                cluster={cluster}
                isExpanded={expandedClusterId === cluster.id}
                onToggleExpand={() => 
                  setExpandedClusterId(
                    expandedClusterId === cluster.id ? null : cluster.id
                  )
                }
              />
            ))}
          </div>

          <SuggestionPromptList tenantId={tenantId} limit={5} />
        </div>
      )}
    </div>
  );
};
```

**File**: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterCurationCard.tsx`

```tsx
/**
 * Card for curating a single cluster with inline editing and member management.
 */

import React, { useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { ClusterPreview } from './ClusterPreview';
import { MemberGallery } from './MemberGallery';
import type { TopUnlabeledCluster } from '../../../api/recognition/types';

interface ClusterCurationCardProps {
  cluster: TopUnlabeledCluster;
  isExpanded: boolean;
  onToggleExpand: () => void;
}

export const ClusterCurationCard = ({
  cluster,
  isExpanded,
  onToggleExpand,
}: ClusterCurationCardProps): React.JSX.Element => {
  const [labelInput, setLabelInput] = useState('');
  const [selectedMembers, setSelectedMembers] = useState<Set<string>>(new Set());
  const queryClient = useQueryClient();

  // Label update mutation
  const labelMutation = useMutation({
    mutationKey: ['update-cluster-label', cluster.id],
    mutationFn: async (label: string) => {
      // PATCH /clusters/{id}
      throw new Error('TODO: Implement');
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['clusters'] });
    },
  });

  // Batch remove mutation
  const removeMutation = useMutation({
    mutationKey: ['remove-identities', cluster.id],
    mutationFn: async (identityIds: string[]) => {
      // POST /clusters/{id}/remove-identities
      throw new Error('TODO: Implement');
    },
    onSuccess: () => {
      setSelectedMembers(new Set());
      void queryClient.invalidateQueries({ queryKey: ['clusters'] });
    },
  });

  const handleSave = () => {
    if (labelInput.trim()) {
      labelMutation.mutate(labelInput.trim());
    }
  };

  const handleRemoveSelected = () => {
    if (selectedMembers.size > 0) {
      removeMutation.mutate(Array.from(selectedMembers));
    }
  };

  const handleMemberToggle = (identityId: string) => {
    setSelectedMembers((prev) => {
      const next = new Set(prev);
      if (next.has(identityId)) {
        next.delete(identityId);
      } else {
        next.add(identityId);
      }
      return next;
    });
  };

  return (
    <div className="acx-cluster-curation-card">
      <div className="acx-cluster-curation-card__main">
        <ClusterPreview
          representative={cluster.representative}
          memberCount={cluster.identity_count}
        />

        <div className="acx-cluster-curation-card__edit">
          <input
            type="text"
            value={labelInput}
            onChange={(e) => setLabelInput(e.target.value)}
            placeholder={__('Enter name...', 'alt-context')}
            className="acx-cluster-curation-card__input"
            onKeyDown={(e) => e.key === 'Enter' && handleSave()}
          />

          <button
            type="button"
            className="button button-primary"
            onClick={handleSave}
            disabled={!labelInput.trim() || labelMutation.isPending}
          >
            {labelMutation.isPending ? __('Saving...', 'alt-context') : __('Save', 'alt-context')}
          </button>
        </div>

        <button
          type="button"
          className="acx-cluster-curation-card__expand"
          onClick={onToggleExpand}
          aria-expanded={isExpanded}
          aria-label={isExpanded ? __('Collapse', 'alt-context') : __('Expand', 'alt-context')}
        >
          {isExpanded ? '▲' : '▼'}
        </button>
      </div>

      {/* Suggestions row */}
      {cluster.top_suggestions.length > 0 && (
        <div className="acx-cluster-curation-card__suggestions">
          <span className="acx-cluster-curation-card__suggestions-label">
            {__('Suggested:', 'alt-context')}
          </span>
          {cluster.top_suggestions.map((s) => (
            <button
              key={s.cluster_id}
              type="button"
              className="acx-cluster-curation-card__suggestion-chip"
              onClick={() => setLabelInput(s.label)}
            >
              {s.label} ({Math.round(s.similarity * 100)}%)
            </button>
          ))}
        </div>
      )}

      {/* Expanded member gallery */}
      {isExpanded && (
        <MemberGallery
          members={cluster.members}
          selectedIds={selectedMembers}
          onToggle={handleMemberToggle}
          onRemoveSelected={handleRemoveSelected}
          isRemoving={removeMutation.isPending}
        />
      )}
    </div>
  );
};
```

**File**: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/MemberGallery.tsx`

```tsx
/**
 * Expandable gallery of cluster members with selection for removal.
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ClusterMember } from '../../../api/recognition/types';

interface MemberGalleryProps {
  members: ClusterMember[];
  selectedIds: Set<string>;
  onToggle: (identityId: string) => void;
  onRemoveSelected: () => void;
  isRemoving: boolean;
}

export const MemberGallery = ({
  members,
  selectedIds,
  onToggle,
  onRemoveSelected,
  isRemoving,
}: MemberGalleryProps): React.JSX.Element => {
  return (
    <div className="acx-member-gallery">
      <div className="acx-member-gallery__header">
        <span>
          {sprintf(__('Members (%d):', 'alt-context'), members.length)}
        </span>
        {selectedIds.size > 0 && (
          <button
            type="button"
            className="button button-link-delete"
            onClick={onRemoveSelected}
            disabled={isRemoving}
          >
            {isRemoving
              ? __('Removing...', 'alt-context')
              : sprintf(__('Remove selected (%d)', 'alt-context'), selectedIds.size)}
          </button>
        )}
      </div>

      <div className="acx-member-gallery__grid">
        {members.map((member) => (
          <button
            key={member.identity_id}
            type="button"
            className={`acx-member-gallery__item ${
              selectedIds.has(member.identity_id) ? 'acx-member-gallery__item--selected' : ''
            }`}
            onClick={() => onToggle(member.identity_id)}
            aria-pressed={selectedIds.has(member.identity_id)}
            aria-label={
              selectedIds.has(member.identity_id)
                ? __('Deselect for removal', 'alt-context')
                : __('Select for removal', 'alt-context')
            }
          >
            <img
              src={member.thumbnail_url}
              alt=""
              className="acx-member-gallery__thumbnail"
            />
            {selectedIds.has(member.identity_id) && (
              <span className="acx-member-gallery__remove-indicator">✗</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
};
```

**File**: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionPromptList.tsx`

```tsx
/**
 * List of pending suggestions with confirm/reject buttons.
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  fetchPendingSuggestions,
  acceptSuggestion,
  rejectSuggestion,
  type PendingSuggestion,
} from '../../../api/recognition';

interface SuggestionPromptListProps {
  tenantId: string;
  limit?: number;
}

export const SuggestionPromptList = ({
  tenantId,
  limit = 5,
}: SuggestionPromptListProps): React.JSX.Element | null => {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ['pending-suggestions', tenantId, limit],
    queryFn: () => fetchPendingSuggestions(limit, 0),
    staleTime: 30000,
  });

  const acceptMutation = useMutation({
    mutationFn: acceptSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['pending-suggestions'] });
      void queryClient.invalidateQueries({ queryKey: ['clusters'] });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: rejectSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['pending-suggestions'] });
    },
  });

  const suggestions = data?.suggestions ?? [];
  const totalCount = data?.total ?? 0;

  if (isLoading || suggestions.length === 0) {
    return null;
  }

  const isPending = acceptMutation.isPending || rejectMutation.isPending;

  return (
    <div className="acx-suggestion-prompt-list">
      <h4 className="acx-suggestion-prompt-list__title">
        💡 {__('Pending Suggestions', 'alt-context')}
        <span className="acx-suggestion-prompt-list__count">({totalCount})</span>
      </h4>

      <div className="acx-suggestion-prompt-list__items">
        {suggestions.map((suggestion) => (
          <div key={suggestion.id} className="acx-suggestion-prompt-item">
            <img
              src={suggestion.identity_thumbnail_url}
              alt=""
              className="acx-suggestion-prompt-item__thumbnail"
            />
            <div className="acx-suggestion-prompt-item__content">
              <span className="acx-suggestion-prompt-item__question">
                {__('Is this', 'alt-context')}{' '}
                <strong>{suggestion.cluster_label ?? __('Unknown', 'alt-context')}</strong>?
              </span>
              <span className="acx-suggestion-prompt-item__similarity">
                {Math.round(suggestion.representative_similarity * 100)}%
              </span>
            </div>
            <div className="acx-suggestion-prompt-item__actions">
              <button
                type="button"
                className="button button-primary button-small"
                onClick={() => acceptMutation.mutate(suggestion.id)}
                disabled={isPending}
                aria-label={__('Yes, confirm suggestion', 'alt-context')}
              >
                ✓ {__('Yes', 'alt-context')}
              </button>
              <button
                type="button"
                className="button button-small"
                onClick={() => rejectMutation.mutate(suggestion.id)}
                disabled={isPending}
                aria-label={__('No, reject suggestion', 'alt-context')}
              >
                ✗ {__('No', 'alt-context')}
              </button>
            </div>
          </div>
        ))}
      </div>

      {totalCount > suggestions.length && (
        <a href="#suggestions" className="acx-suggestion-prompt-list__view-all">
          {sprintf(__('View all %d suggestions', 'alt-context'), totalCount)}
        </a>
      )}
    </div>
  );
};
```

### 5.3 Styles

**File**: `apps/prototype-wp-alt-context/src/scss/admin/_top-clusters-panel.scss`

```scss
/**
 * Top Clusters Curation Panel styles.
 */

.acx-top-clusters-panel {
  background: #fff;
  border: 1px solid #c3c4c7;
  border-radius: 4px;
  margin-bottom: 20px;

  &__header {
    display: flex;
    align-items: center;
    width: 100%;
    padding: 12px 16px;
    background: #f6f7f7;
    border: none;
    border-bottom: 1px solid #c3c4c7;
    cursor: pointer;
    text-align: left;

    &:hover {
      background: #f0f0f1;
    }
  }

  &__title {
    flex: 1;
    font-size: 14px;
    font-weight: 600;
  }

  &__badge {
    margin: 0 12px;
    padding: 2px 8px;
    background: var(--wp-admin-theme-color, #007cba);
    color: #fff;
    border-radius: 10px;
    font-size: 12px;
  }

  &__toggle {
    font-size: 12px;
    color: #50575e;
  }

  &__content {
    padding: 16px;
  }

  &__clusters {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
}

.acx-cluster-curation-card {
  border: 1px solid #ddd;
  border-radius: 4px;
  padding: 12px;

  &__main {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  &__edit {
    flex: 1;
    display: flex;
    gap: 8px;
  }

  &__input {
    flex: 1;
    padding: 6px 10px;
    border: 1px solid #8c8f94;
    border-radius: 4px;
  }

  &__expand {
    padding: 6px 10px;
    background: none;
    border: 1px solid #ddd;
    border-radius: 4px;
    cursor: pointer;

    &:hover {
      background: #f0f0f1;
    }
  }

  &__suggestions {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid #eee;
    font-size: 13px;
    color: #50575e;
  }

  &__suggestions-label {
    margin-right: 8px;
  }

  &__suggestion-chip {
    display: inline-block;
    margin: 0 4px 4px 0;
    padding: 2px 8px;
    background: #f0f0f1;
    border: 1px solid #ddd;
    border-radius: 12px;
    font-size: 12px;
    cursor: pointer;

    &:hover {
      background: #e0e0e0;
    }
  }
}

.acx-member-gallery {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #ddd;

  &__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    font-size: 13px;
  }

  &__grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(60px, 1fr));
    gap: 8px;
  }

  &__item {
    position: relative;
    aspect-ratio: 1;
    padding: 0;
    border: 2px solid transparent;
    border-radius: 4px;
    cursor: pointer;
    overflow: hidden;

    &:hover {
      border-color: #007cba;
    }

    &--selected {
      border-color: #d63638;

      .acx-member-gallery__remove-indicator {
        display: flex;
      }
    }
  }

  &__thumbnail {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  &__remove-indicator {
    display: none;
    position: absolute;
    inset: 0;
    align-items: center;
    justify-content: center;
    background: rgba(214, 54, 56, 0.7);
    color: #fff;
    font-size: 24px;
    font-weight: bold;
  }
}

.acx-suggestion-prompt-list {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #ddd;

  &__title {
    margin: 0 0 12px;
    font-size: 14px;
    font-weight: 600;
  }

  &__count {
    font-weight: normal;
    color: #50575e;
  }

  &__items {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  &__view-all {
    display: block;
    margin-top: 12px;
    text-align: center;
    font-size: 13px;
  }
}

.acx-suggestion-prompt-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px;
  background: #f9f9f9;
  border: 1px solid #eee;
  border-radius: 4px;

  &__thumbnail {
    width: 48px;
    height: 48px;
    border-radius: 4px;
    object-fit: cover;
  }

  &__content {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  &__question {
    font-size: 14px;
  }

  &__similarity {
    padding: 2px 6px;
    background: #e7f5e7;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    color: #1e7e1e;
  }

  &__actions {
    display: flex;
    gap: 6px;
  }
}
```

---

## 6. API Types

**File**: `apps/prototype-wp-alt-context/js/admin/api/recognition/types/cluster.ts`

```typescript
/** Cluster member for gallery display */
export interface ClusterMember {
  identity_id: string;
  media_id: number;
  thumbnail_url: string;
  bounds?: { x: number; y: number; width: number; height: number };
}

/** Label suggestion for a cluster */
export interface ClusterLabelSuggestion {
  cluster_id: string;
  label: string;
  similarity: number;
}

/** Enhanced response for top unlabeled clusters */
export interface TopUnlabeledCluster {
  id: string;
  label: string | null;
  identity_count: number;
  is_labeled: boolean;
  representative: RepresentativeBounds | null;
  members: ClusterMember[];
  top_suggestions: ClusterLabelSuggestion[];
}

/** Request to batch remove identities */
export interface BatchRemoveIdentitiesRequest {
  cluster_id: string;
  identity_ids: string[];
  reason?: string;
}

/** Response from batch remove */
export interface BatchRemoveIdentitiesResponse {
  removed_count: number;
  cluster_id: string;
  new_identity_count: number;
}
```

---

## 7. Implementation Checklist

### Phase 1: Backend

- [ ] Create `TopUnlabeledClusterResponse` schema with members and suggestions
- [ ] Implement `/clusters/top-unlabeled/detailed` endpoint
- [ ] Create `BatchRemoveIdentitiesRequest/Response` schemas
- [ ] Implement `/clusters/{id}/remove-identities` endpoint
- [ ] Add integration tests for new endpoints

### Phase 2: Frontend Components

- [ ] Create `TopClustersCurationPanel` component
- [ ] Create `ClusterCurationCard` component
- [ ] Create `MemberGallery` component
- [ ] Create `SuggestionPromptList` component
- [ ] Add SCSS styles for all components

### Phase 3: Frontend Integration

- [ ] Add `useTopUnlabeledClusters` hook
- [ ] Add `useBatchRemoveIdentities` hook
- [ ] Update `IdentityClusterList` to include `TopClustersCurationPanel`
- [ ] Add Vitest tests for components

### Phase 4: Polish

- [ ] Keyboard navigation support
- [ ] Loading states and skeletons
- [ ] Error handling and toasts
- [ ] Mobile responsive adjustments
- [ ] Storybook stories for components

---

## 8. Files Summary

| File | Type | Description |
|------|------|-------------|
| `clusters.py` | Modify | Add detailed top-unlabeled and batch-remove endpoints |
| `TopClustersCurationPanel.tsx` | New | Main curation panel component |
| `ClusterCurationCard.tsx` | New | Individual cluster card with editing |
| `MemberGallery.tsx` | New | Expandable member grid with removal |
| `SuggestionPromptList.tsx` | New | Pending suggestions with Yes/No buttons |
| `_top-clusters-panel.scss` | New | Styles for all new components |
| `types/cluster.ts` | Modify | Add new TypeScript interfaces |

---

## 9. Open Questions

1. **Batch labeling**: Should we support labeling multiple clusters at once with the same name?
2. **Removed identities**: Where do removed identities go? New singleton clusters or outlier pool?
3. **Suggestions source**: Should suggestions come from the identity or from cluster similarity matching?
4. **Panel position**: Top of page (always visible) or sticky sidebar?
