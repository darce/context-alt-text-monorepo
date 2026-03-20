import React from 'react';

import type { ConflictResolutionChoice } from '../../../api/recognition';

interface PendingResolution {
  conflictId: number;
  choice: ConflictResolutionChoice;
}

interface ConflictInboxState {
  offset: number;
  selectedConflictIds: number[];
  expandedConflictId: number | null;
  pendingResolution: PendingResolution | null;
  pendingBatchResolution: ConflictResolutionChoice | null;
  showSyncNow: boolean;
  resolutionError: string | null;
}

type ConflictInboxAction =
  | { type: 'setOffset'; offset: number }
  | { type: 'setSelectedConflictIds'; ids: number[] }
  | { type: 'toggleSelectedConflictId'; id: number }
  | { type: 'setExpandedConflictId'; id: number | null }
  | { type: 'toggleExpandedConflictId'; id: number }
  | { type: 'setPendingResolution'; value: PendingResolution | null }
  | { type: 'setPendingBatchResolution'; value: ConflictResolutionChoice | null }
  | { type: 'setShowSyncNow'; value: boolean }
  | { type: 'setResolutionError'; value: string | null }
  | { type: 'clearTransientState' };

const INITIAL_STATE: ConflictInboxState = {
  offset: 0,
  selectedConflictIds: [],
  expandedConflictId: null,
  pendingResolution: null,
  pendingBatchResolution: null,
  showSyncNow: false,
  resolutionError: null,
};

const reducer = (state: ConflictInboxState, action: ConflictInboxAction): ConflictInboxState => {
  switch (action.type) {
    case 'setOffset':
      return { ...state, offset: action.offset };
    case 'setSelectedConflictIds':
      return { ...state, selectedConflictIds: action.ids };
    case 'toggleSelectedConflictId':
      return {
        ...state,
        selectedConflictIds: state.selectedConflictIds.includes(action.id)
          ? state.selectedConflictIds.filter((id) => id !== action.id)
          : [...state.selectedConflictIds, action.id],
      };
    case 'setExpandedConflictId':
      return { ...state, expandedConflictId: action.id };
    case 'toggleExpandedConflictId':
      return {
        ...state,
        expandedConflictId: state.expandedConflictId === action.id ? null : action.id,
      };
    case 'setPendingResolution':
      return { ...state, pendingResolution: action.value };
    case 'setPendingBatchResolution':
      return { ...state, pendingBatchResolution: action.value };
    case 'setShowSyncNow':
      return { ...state, showSyncNow: action.value };
    case 'setResolutionError':
      return { ...state, resolutionError: action.value };
    case 'clearTransientState':
      return {
        ...state,
        pendingResolution: null,
        pendingBatchResolution: null,
        resolutionError: null,
      };
    default:
      return state;
  }
};

export const useConflictInboxState = (): [ConflictInboxState, React.Dispatch<ConflictInboxAction>] =>
  React.useReducer(reducer, INITIAL_STATE);
