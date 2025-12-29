/**
 * Hook for managing cluster edit state with useReducer.
 *
 * Centralizes all edit-related state: editing mode, label input, errors, and merge tracking.
 */

import React from 'react';

import type { MergeClusterResponse } from '../../../api/recognition';
import type { ClusterEditAction, ClusterEditState } from './types';

const initialState: ClusterEditState = {
  isEditing: false,
  labelInput: '',
  error: null,
  lastMerge: null,
};

const clusterEditReducer = (state: ClusterEditState, action: ClusterEditAction): ClusterEditState => {
  switch (action.type) {
    case 'START_EDIT':
      return {
        ...state,
        isEditing: true,
        labelInput: action.initialLabel,
        error: null,
        lastMerge: null,
      };

    case 'CANCEL_EDIT':
      return {
        ...state,
        isEditing: false,
        error: null,
      };

    case 'SET_LABEL':
      return {
        ...state,
        labelInput: action.label,
        error: null,
      };

    case 'SET_ERROR':
      return {
        ...state,
        error: action.error,
      };

    case 'CLEAR_ERROR':
      return {
        ...state,
        error: null,
      };

    case 'SAVE_SUCCESS':
      return {
        ...state,
        isEditing: false,
        error: null,
        lastMerge: null,
      };

    case 'MERGE_SUCCESS':
      return {
        ...state,
        isEditing: false,
        error: null,
        lastMerge: action.mergeResult,
      };

    case 'REVERT_SUCCESS':
      return {
        ...state,
        lastMerge: null,
        error: null,
      };

    default:
      return state;
  }
};

interface UseClusterEditStateOptions {
  /** Initial label to show when editing starts */
  derivedLabel: string | null;
}

interface UseClusterEditStateReturn {
  state: ClusterEditState;
  dispatch: React.Dispatch<ClusterEditAction>;
  /** Convenience: start editing with the derived label */
  startEditing: () => void;
  /** Convenience: cancel editing */
  cancelEditing: () => void;
  /** Convenience: update the label input */
  setLabel: (label: string) => void;
  /** Convenience: set an error message */
  setError: (error: string) => void;
  /** Convenience: handle successful save */
  onSaveSuccess: () => void;
  /** Convenience: handle successful merge */
  onMergeSuccess: (result: MergeClusterResponse) => void;
  /** Convenience: handle successful revert */
  onRevertSuccess: () => void;
}

/**
 * Hook for managing cluster edit state.
 *
 * Uses useReducer internally for predictable state transitions.
 * Syncs with derived label changes from parent.
 */
export const useClusterEditState = ({ derivedLabel }: UseClusterEditStateOptions): UseClusterEditStateReturn => {
  const [state, dispatch] = React.useReducer(clusterEditReducer, {
    ...initialState,
    labelInput: derivedLabel ?? '',
  });

  // Sync label input when derived label changes (e.g., after external update)
  React.useLayoutEffect(() => {
    if (state.isEditing) {
      return;
    }
    const nextLabel = derivedLabel ?? '';
    if (state.labelInput === nextLabel) {
      return;
    }
    dispatch({ type: 'SET_LABEL', label: nextLabel });
  }, [derivedLabel, state.isEditing, state.labelInput]);

  const startEditing = React.useCallback(() => {
    dispatch({ type: 'START_EDIT', initialLabel: derivedLabel ?? '' });
  }, [derivedLabel]);

  const cancelEditing = React.useCallback(() => {
    dispatch({ type: 'CANCEL_EDIT' });
  }, []);

  const setLabel = React.useCallback((label: string) => {
    dispatch({ type: 'SET_LABEL', label });
  }, []);

  const setError = React.useCallback((error: string) => {
    dispatch({ type: 'SET_ERROR', error });
  }, []);

  const onSaveSuccess = React.useCallback(() => {
    dispatch({ type: 'SAVE_SUCCESS' });
  }, []);

  const onMergeSuccess = React.useCallback((result: MergeClusterResponse) => {
    dispatch({ type: 'MERGE_SUCCESS', mergeResult: result });
  }, []);

  const onRevertSuccess = React.useCallback(() => {
    dispatch({ type: 'REVERT_SUCCESS' });
  }, []);

  return {
    state,
    dispatch,
    startEditing,
    cancelEditing,
    setLabel,
    setError,
    onSaveSuccess,
    onMergeSuccess,
    onRevertSuccess,
  };
};
