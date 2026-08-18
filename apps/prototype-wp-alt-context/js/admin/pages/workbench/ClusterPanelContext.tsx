import React, { createContext, useContext, useMemo, useReducer } from 'react';
import { useSearchParams } from 'react-router-dom';

import { APP_LINK_PARAMS, APP_LINK_VALUES } from '../../navigation/appLinks';

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

/** UXW2-4: `panel=review&cluster=<id>` is the review panel's deep-link state (NAV-11). */
const readReviewFromParams = (searchParams: URLSearchParams): ClusterPanelState => {
  const clusterId = searchParams.get(APP_LINK_PARAMS.cluster);
  if (searchParams.get(APP_LINK_PARAMS.panel) === APP_LINK_VALUES.panelReview && clusterId) {
    return { mode: 'review', clusterId };
  }
  return { mode: 'none', clusterId: null };
};

export const ClusterPanelProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [clusterPanel, dispatch] = useReducer(clusterPanelReducer, searchParams, readReviewFromParams);
  const stateRef = React.useRef(clusterPanel);
  stateRef.current = clusterPanel;

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

  // State → URL: one setSearchParams write per transition, touching only the
  // panel/cluster keys (UXW2-4; rq= and friends keep their own owners).
  // Close decides from `next` + the functional `prev` snapshot so a same-tick
  // open then retire-close cannot leave panel=review in the hash.
  const dispatchClusterPanel = React.useCallback<React.Dispatch<ClusterPanelAction>>(
    (action) => {
      const next = clusterPanelReducer(stateRef.current, action);
      stateRef.current = next;
      dispatch(action);
      if (next.mode === 'review' && next.clusterId) {
        const clusterId = next.clusterId;
        setSearchParams((prev) => {
          if (
            prev.get(APP_LINK_PARAMS.panel) === APP_LINK_VALUES.panelReview &&
            prev.get(APP_LINK_PARAMS.cluster) === clusterId
          ) {
            return prev;
          }
          const params = new URLSearchParams(prev);
          params.set(APP_LINK_PARAMS.panel, APP_LINK_VALUES.panelReview);
          params.set(APP_LINK_PARAMS.cluster, clusterId);
          return params;
        });
      } else {
        setSearchParams(
          (prev) => {
            if (prev.get(APP_LINK_PARAMS.panel) !== APP_LINK_VALUES.panelReview) {
              if (!prev.has(APP_LINK_PARAMS.cluster)) {
                return prev;
              }
              const params = new URLSearchParams(prev);
              params.delete(APP_LINK_PARAMS.cluster);
              return params;
            }
            const params = new URLSearchParams(prev);
            params.delete(APP_LINK_PARAMS.panel);
            params.delete(APP_LINK_PARAMS.cluster);
            return params;
          },
          { replace: true },
        );
      }
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
