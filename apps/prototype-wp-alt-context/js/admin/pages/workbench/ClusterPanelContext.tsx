import React, { createContext, useContext, useMemo, useReducer } from 'react';

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

export const ClusterPanelProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [clusterPanel, dispatchClusterPanel] = useReducer(clusterPanelReducer, {
    mode: 'none',
    clusterId: null,
  });

  const value = useMemo<ClusterPanelContextValue>(() => ({ clusterPanel, dispatchClusterPanel }), [clusterPanel]);

  return <ClusterPanelContext.Provider value={value}>{children}</ClusterPanelContext.Provider>;
};

export const useClusterPanel = (): ClusterPanelContextValue => {
  const context = useContext(ClusterPanelContext);
  if (!context) {
    throw new Error('useClusterPanel must be used within a ClusterPanelProvider');
  }
  return context;
};
