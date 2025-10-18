import React from "react";
import type { useRecognitionJob } from "@/admin/hooks/useRecognitionJob";
import { emitDashboardEvent } from "@/admin/analytics";

/** Recognition job hook return type */
type UseRecognitionJobResult = ReturnType<typeof useRecognitionJob>;

/**
 * Action handlers for workbench operations
 *
 * @interface WorkbenchActions
 */
export interface WorkbenchActions {
    /** Toggle selection state for a media item */
    handleToggleSelection: (id: string) => void;
    /** Clear all selections */
    clearSelection: () => void;
    /** Generate alt text for selected items */
    handleGenerateAltText: () => void;
    /** Regenerate alt text for selected items */
    handleRegenerateAltText: () => void;
    /** Mark selected items as reviewed */
    handleMarkReviewed: () => void;
    /** Trigger recognition job for selected items */
    handleTriggerRecognition: () => void;
    /** Retry last failed recognition job */
    handleRetryRecognition: () => void;
}

/**
 * Props for useWorkbenchActions hook
 *
 * @interface UseWorkbenchActionsProps
 */
export interface UseWorkbenchActionsProps {
    /** Currently selected media item IDs */
    selectedList: string[];
    /** Set function for updating selected IDs */
    setSelectedIds: React.Dispatch<React.SetStateAction<Set<string>>>;
    /** Recognition job hook result */
    recognition: UseRecognitionJobResult;
    /** Reference to last attempted IDs for retry functionality */
    lastAttemptedIdsRef: React.MutableRefObject<string[]>;
    /** Reference to request error event signature for deduplication */
    requestErrorEventRef: React.MutableRefObject<string | null>;
    /** Reference to job error event signature for deduplication */
    jobErrorEventRef: React.MutableRefObject<string | null>;
    /** Reference to completed job event signature for deduplication */
    completedJobEventRef: React.MutableRefObject<string | null>;
    /** Optional callback when alt text generation is requested */
    onGenerateAltText?: (ids: string[]) => void;
    /** Optional callback when alt text regeneration is requested */
    onRegenerateAltText?: (ids: string[]) => void;
    /** Optional callback when items are marked as reviewed */
    onMarkReviewed?: (ids: string[]) => void;
}

/**
 * Custom hook for managing workbench action handlers
 *
 * Extracts all action-related useCallback handlers from WorkbenchApp component
 * to reduce component complexity and improve separation of concerns.
 *
 * @param {UseWorkbenchActionsProps} props - Action handler dependencies
 * @returns {WorkbenchActions} Object containing all action handler functions
 *
 * @example
 * ```tsx
 * const actions = useWorkbenchActions({
 *   selectedList,
 *   setSelectedIds,
 *   recognition,
 *   lastAttemptedIdsRef,
 *   requestErrorEventRef,
 *   jobErrorEventRef,
 *   completedJobEventRef,
 *   onGenerateAltText,
 *   onRegenerateAltText,
 *   onMarkReviewed,
 * });
 *
 * // Use actions
 * actions.handleToggleSelection('media-123');
 * actions.handleTriggerRecognition();
 * ```
 */
export const useWorkbenchActions = ({
    selectedList,
    setSelectedIds,
    recognition,
    lastAttemptedIdsRef,
    requestErrorEventRef,
    jobErrorEventRef,
    completedJobEventRef,
    onGenerateAltText,
    onRegenerateAltText,
    onMarkReviewed,
}: UseWorkbenchActionsProps): WorkbenchActions => {
    /**
     * Toggle selection state for a media item
     * Adds item to selection if not selected, removes if already selected
     */
    const handleToggleSelection = React.useCallback(
        (id: string) => {
            setSelectedIds((prev) => {
                const next = new Set(prev);
                if (next.has(id)) {
                    next.delete(id);
                } else {
                    next.add(id);
                }
                return next;
            });
        },
        [setSelectedIds],
    );

    /**
     * Clear all selected items
     */
    const clearSelection = React.useCallback(() => setSelectedIds(new Set()), [setSelectedIds]);

    /**
     * Generate alt text for currently selected items
     * Calls optional onGenerateAltText callback with selected IDs
     */
    const handleGenerateAltText = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onGenerateAltText?.(selectedList);
    }, [onGenerateAltText, selectedList]);

    /**
     * Regenerate alt text for currently selected items
     * Calls optional onRegenerateAltText callback with selected IDs
     */
    const handleRegenerateAltText = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onRegenerateAltText?.(selectedList);
    }, [onRegenerateAltText, selectedList]);

    /**
     * Mark currently selected items as reviewed
     * Calls optional onMarkReviewed callback with selected IDs
     */
    const handleMarkReviewed = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onMarkReviewed?.(selectedList);
    }, [onMarkReviewed, selectedList]);

    /**
     * Trigger recognition job for currently selected items
     * Emits analytics event and resets error tracking refs
     */
    const handleTriggerRecognition = React.useCallback(() => {
        if (selectedList.length === 0 || !recognition.canSubmit) {
            return;
        }
        const selectionSnapshot = [...selectedList];
        lastAttemptedIdsRef.current = selectionSnapshot;

        // Reset error tracking to allow new error notifications
        requestErrorEventRef.current = null;
        jobErrorEventRef.current = null;
        completedJobEventRef.current = null;

        emitDashboardEvent("cat_workbench_recognition_triggered", {
            selection: selectionSnapshot,
            count: selectionSnapshot.length,
        });

        void recognition.triggerRecognition(selectionSnapshot).catch(() => {
            // Errors are surfaced via the hook state; no additional handling needed here.
        });
    }, [recognition, selectedList, lastAttemptedIdsRef, requestErrorEventRef, jobErrorEventRef, completedJobEventRef]);

    /**
     * Retry last failed recognition job
     * Uses lastAttemptedIdsRef to retry same selection that previously failed
     */
    const handleRetryRecognition = React.useCallback(() => {
        const retryIds = lastAttemptedIdsRef.current;

        if (retryIds.length === 0 || !recognition.canSubmit) {
            return;
        }

        // Reset error tracking to allow new error notifications
        requestErrorEventRef.current = null;
        jobErrorEventRef.current = null;

        emitDashboardEvent("cat_workbench_recognition_triggered", {
            selection: retryIds,
            count: retryIds.length,
            retry: true,
        });

        void recognition.triggerRecognition(retryIds).catch(() => {
            // Errors are surfaced via the hook state; no additional handling needed here.
        });
    }, [recognition, lastAttemptedIdsRef, requestErrorEventRef, jobErrorEventRef]);

    return {
        handleToggleSelection,
        clearSelection,
        handleGenerateAltText,
        handleRegenerateAltText,
        handleMarkReviewed,
        handleTriggerRecognition,
        handleRetryRecognition,
    };
};
