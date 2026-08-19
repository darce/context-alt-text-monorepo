import React, { createContext, useContext, useMemo, useReducer } from 'react';
import { useSearchParams } from 'react-router-dom';

import { APP_LINK_PARAMS, APP_LINK_VALUES, toWorkbench } from '../../navigation/appLinks';

type ClusterPanelMode = 'none' | 'label' | 'review';

export interface ClusterPanelState {
  mode: ClusterPanelMode;
  clusterId: string | null;
}

export type ClusterPanelAction =
  | { type: 'open_label'; clusterId: string }
  | { type: 'open_review'; clusterId: string }
  | { type: 'close' };

const clusterPanelReducer = (state: ClusterPanelState, action: ClusterPanelAction): ClusterPanelState => {
  switch (action.type) {
    case 'open_label':
      return { mode: 'label', clusterId: action.clusterId };
    case 'open_review':
      return { mode: 'review', clusterId: action.clusterId };
    case 'close':
      return { mode: 'none', clusterId: null };
    default:
      return state;
  }
};

export interface ClusterPanelContextValue {
  clusterPanel: ClusterPanelState;
  dispatchClusterPanel: React.Dispatch<ClusterPanelAction>;
}

const ClusterPanelContext = createContext<ClusterPanelContextValue | null>(null);

/** Legal `panel` values: `review` | `conflicts` | `dead-letter` (see WorkbenchNavContext). */
const OVERLAY_PANEL_VALUES = new Set(['conflicts', 'dead-letter']);

/** UXW2-4: `panel=review&cluster=<id>` is the review panel's deep-link state (NAV-11). */
export const readReviewFromParams = (searchParams: URLSearchParams): ClusterPanelState => {
  const clusterId = searchParams.get(APP_LINK_PARAMS.cluster);
  if (searchParams.get(APP_LINK_PARAMS.panel) === APP_LINK_VALUES.panelReview && clusterId) {
    return { mode: 'review', clusterId };
  }
  return { mode: 'none', clusterId: null };
};

/** Patch panel/cluster onto the current search using the appLinks builder (one emit owner). */
export const applyReviewPanelToSearchParams = (
  prev: URLSearchParams,
  next: ClusterPanelState,
  restoreOverlay: string | null,
): URLSearchParams => {
  const params = new URLSearchParams(prev);
  if (next.mode === 'review' && next.clusterId) {
    const built = new URLSearchParams(
      toWorkbench({
        panel: APP_LINK_VALUES.panelReview,
        cluster: next.clusterId,
      }).split('?')[1] ?? '',
    );
    const panel = built.get(APP_LINK_PARAMS.panel);
    const cluster = built.get(APP_LINK_PARAMS.cluster);
    if (panel) {
      params.set(APP_LINK_PARAMS.panel, panel);
    }
    if (cluster) {
      params.set(APP_LINK_PARAMS.cluster, cluster);
    }
    return params;
  }
  params.delete(APP_LINK_PARAMS.cluster);
  if (restoreOverlay && OVERLAY_PANEL_VALUES.has(restoreOverlay)) {
    params.set(APP_LINK_PARAMS.panel, restoreOverlay);
  } else if (params.get(APP_LINK_PARAMS.panel) === APP_LINK_VALUES.panelReview) {
    params.delete(APP_LINK_PARAMS.panel);
  }
  return params;
};

export const ClusterPanelProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [clusterPanel, dispatch] = useReducer(clusterPanelReducer, searchParams, readReviewFromParams);
  const stateRef = React.useRef(clusterPanel);
  stateRef.current = clusterPanel;
  const previousOverlayRef = React.useRef<string | null>(null);

  // URL → state: back/forward navigation and external writers. Reload is covered
  // by the reducer initializer; our own writes echo back here as no-ops because
  // the reducer has already applied the same transition.
  React.useEffect(() => {
    const fromUrl = readReviewFromParams(searchParams);
    const current = stateRef.current;
    if (fromUrl.mode === 'review' && fromUrl.clusterId) {
      if (current.mode !== 'review' || current.clusterId !== fromUrl.clusterId) {
        dispatch({ type: 'open_review', clusterId: fromUrl.clusterId });
      }
    } else if (current.mode === 'review') {
      dispatch({ type: 'close' });
    }
  }, [searchParams]);

  // State → URL: one reducer over stateRef, one navigate per tick (close last).
  // RR7's functional updater is the closure snapshot, not a chained prev — we
  // encode `next` rather than no-op on a stale prev. History contract: both
  // open and close use {replace:true} so panel is URL state, not a stack frame.
  // Back after close therefore cannot reopen the panel.
  const dispatchClusterPanel = React.useCallback<React.Dispatch<ClusterPanelAction>>(
    (action) => {
      const next = clusterPanelReducer(stateRef.current, action);
      stateRef.current = next;
      dispatch(action);
      setSearchParams(
        (prev) => {
          if (next.mode === 'review' && next.clusterId) {
            const currentPanel = prev.get(APP_LINK_PARAMS.panel);
            if (currentPanel && OVERLAY_PANEL_VALUES.has(currentPanel)) {
              previousOverlayRef.current = currentPanel;
            }
            return applyReviewPanelToSearchParams(prev, next, null);
          }
          const restore = previousOverlayRef.current;
          previousOverlayRef.current = null;
          return applyReviewPanelToSearchParams(prev, next, restore);
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const value = useMemo<ClusterPanelContextValue>(
    () => ({ clusterPanel, dispatchClusterPanel }),
    [clusterPanel, dispatchClusterPanel],
  );

  return <ClusterPanelContext.Provider value={value}>{children}</ClusterPanelContext.Provider>;
};

export const useClusterPanel = (): ClusterPanelContextValue => {
  const context = useContext(ClusterPanelContext);
  if (!context) {
    throw new Error('useClusterPanel must be used within a ClusterPanelProvider');
  }
  return context;
};
