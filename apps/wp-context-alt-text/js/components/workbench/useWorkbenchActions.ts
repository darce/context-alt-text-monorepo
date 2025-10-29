import React from "react";

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

    return {
        handleToggleSelection,
        clearSelection,
        handleGenerateAltText,
        handleRegenerateAltText,
        handleMarkReviewed,
    };
};
