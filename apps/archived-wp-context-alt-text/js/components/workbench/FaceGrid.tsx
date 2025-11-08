import React from "react";
import { __, sprintf } from "@wordpress/i18n";

import type { ClusterFaceDetail } from "@/types/face-clustering";
import "./FaceGrid.scss";

export interface FaceGridRangeSelection {
    faceIds: string[];
    startIndex: number;
    endIndex: number;
}

export interface FaceGridProps {
    faces: ClusterFaceDetail[];
    selectedFaceIds: string[];
    onToggleFace: (faceId: string, options?: { index: number }) => void;
    onRangeSelect?: (range: FaceGridRangeSelection) => void;
    onSelectAll?: () => void;
    selectionAnchorIndex?: number | null;
    onDragStart?: (faceId: string, index: number, event: React.DragEvent<HTMLButtonElement>) => void;
    onDragEnd?: (event: React.DragEvent<HTMLButtonElement>) => void;
    onDeleteFace?: (faceId: string) => void;
    onViewOriginal?: (attachmentId: number) => void;
}

export const FaceGrid = ({
    faces,
    selectedFaceIds,
    onToggleFace,
    onRangeSelect,
    onSelectAll,
    selectionAnchorIndex = null,
    onDragStart,
    onDragEnd,
    onDeleteFace,
    onViewOriginal,
}: FaceGridProps): React.JSX.Element => {
    const buttonRefs = React.useRef<(HTMLButtonElement | null)[]>([]);
    const defaultFocusIndex = React.useMemo(() => {
        if (faces.length === 0) {
            return -1;
        }

        const firstSelectedIndex = faces.findIndex((face) => selectedFaceIds.includes(face.id));
        return firstSelectedIndex >= 0 ? firstSelectedIndex : 0;
    }, [faces, selectedFaceIds]);

    const [activeIndex, setActiveIndex] = React.useState<number>(defaultFocusIndex);

    React.useEffect(() => {
        buttonRefs.current.length = faces.length;

        setActiveIndex((previousIndex) => {
            if (faces.length === 0) {
                return -1;
            }

            if (previousIndex === -1) {
                return defaultFocusIndex;
            }

            if (previousIndex >= faces.length) {
                return faces.length - 1;
            }

            return previousIndex;
        });
    }, [faces, defaultFocusIndex]);

    const moveFocus = React.useCallback(
        (nextIndex: number) => {
            if (nextIndex < 0 || nextIndex >= faces.length) {
                return;
            }

            setActiveIndex(nextIndex);

            const nextButton = buttonRefs.current[nextIndex];
            if (nextButton) {
                nextButton.focus({ preventScroll: true });
            }
        },
        [faces.length],
    );

    const resolveAnchorIndex = React.useCallback(
        (fallbackIndex: number) => {
            if (
                typeof selectionAnchorIndex === "number" &&
                selectionAnchorIndex >= 0 &&
                selectionAnchorIndex < faces.length
            ) {
                return selectionAnchorIndex;
            }

            if (activeIndex >= 0 && activeIndex < faces.length) {
                return activeIndex;
            }

            const firstSelectedIndex = faces.findIndex((face) => selectedFaceIds.includes(face.id));
            if (firstSelectedIndex >= 0) {
                return firstSelectedIndex;
            }

            return Math.max(0, Math.min(fallbackIndex, faces.length - 1));
        },
        [activeIndex, faces, selectedFaceIds, selectionAnchorIndex],
    );

    const createRangeSelection = React.useCallback(
        (targetIndex: number): FaceGridRangeSelection => {
            const anchorIndex = resolveAnchorIndex(targetIndex);
            const startIndex = Math.min(anchorIndex, targetIndex);
            const endIndex = Math.max(anchorIndex, targetIndex);
            const faceIds = faces.slice(startIndex, endIndex + 1).map((face) => face.id);

            return {
                faceIds,
                startIndex: anchorIndex,
                endIndex: targetIndex,
            };
        },
        [faces, resolveAnchorIndex],
    );

    const handleKeyDown = React.useCallback(
        (event: React.KeyboardEvent<HTMLButtonElement>, index: number, faceId: string) => {
            if ((event.key === "a" || event.key === "A") && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                onSelectAll?.();
                return;
            }

            const handleRangeShortcut = (targetIndex: number) => {
                if (!onRangeSelect) {
                    return;
                }

                const range = createRangeSelection(targetIndex);
                onRangeSelect(range);
            };

            switch (event.key) {
                case "ArrowRight":
                case "ArrowDown": {
                    event.preventDefault();
                    const nextIndex = Math.min(faces.length - 1, index + 1);
                    moveFocus(nextIndex);
                    if (event.shiftKey) {
                        handleRangeShortcut(nextIndex);
                    }
                    break;
                }
                case "ArrowLeft":
                case "ArrowUp": {
                    event.preventDefault();
                    const nextIndex = Math.max(0, index - 1);
                    moveFocus(nextIndex);
                    if (event.shiftKey) {
                        handleRangeShortcut(nextIndex);
                    }
                    break;
                }
                case "Home":
                    event.preventDefault();
                    moveFocus(0);
                    if (event.shiftKey) {
                        handleRangeShortcut(0);
                    }
                    break;
                case "End": {
                    event.preventDefault();
                    const lastIndex = faces.length - 1;
                    moveFocus(lastIndex);
                    if (event.shiftKey) {
                        handleRangeShortcut(lastIndex);
                    }
                    break;
                }
                case " ":
                case "Spacebar":
                case "Enter":
                    event.preventDefault();
                    onToggleFace(faceId, { index });
                    break;
                default:
                    break;
            }
        },
        [createRangeSelection, faces.length, moveFocus, onRangeSelect, onSelectAll, onToggleFace],
    );

    const handleViewOriginal = React.useCallback(
        (event: React.MouseEvent, attachmentId: number) => {
            event.stopPropagation();
            event.preventDefault();
            onViewOriginal?.(attachmentId);
        },
        [onViewOriginal],
    );

    const handleDelete = React.useCallback(
        (event: React.MouseEvent, faceId: string) => {
            event.stopPropagation();
            event.preventDefault();
            onDeleteFace?.(faceId);
        },
        [onDeleteFace],
    );

    const handleDoubleClick = React.useCallback(
        (attachmentId: number) => {
            onViewOriginal?.(attachmentId);
        },
        [onViewOriginal],
    );

    return (
        <ul className="cat-face-grid">
            {faces.map((face, index) => {
                const faceLabel = sprintf(
                    /* translators: %d: face index */
                    __("Face %d preview", "context-alt-text"),
                    index + 1,
                );
                const isSelected = selectedFaceIds.includes(face.id);

                return (
                    <li key={face.id} className="cat-face-grid__item">
                        <button
                            type="button"
                            className="cat-face-grid__button"
                            aria-label={faceLabel}
                            aria-pressed={isSelected ? "true" : "false"}
                            data-selected={isSelected || undefined}
                            tabIndex={index === activeIndex ? 0 : -1}
                            onKeyDown={(event) => handleKeyDown(event, index, face.id)}
                            ref={(element) => {
                                buttonRefs.current[index] = element;
                            }}
                            draggable={Boolean(onDragStart)}
                            onDragStart={
                                onDragStart
                                    ? (event) => {
                                          onDragStart(face.id, index, event);
                                      }
                                    : undefined
                            }
                            onDragEnd={onDragEnd}
                            onClick={(event) => {
                                if (event.shiftKey && onRangeSelect) {
                                    event.preventDefault();
                                    const range = createRangeSelection(index);
                                    onRangeSelect(range);
                                    return;
                                }

                                onToggleFace(face.id, { index });
                            }}
                            onDoubleClick={() => onViewOriginal && handleDoubleClick(face.attachmentId)}
                            title={
                                onViewOriginal
                                    ? __("Double-click to view original image", "context-alt-text")
                                    : undefined
                            }
                        >
                            {face.thumbnailUrl ? (
                                <img src={face.thumbnailUrl} alt={faceLabel} className="cat-face-grid__image" />
                            ) : (
                                <div className="cat-face-grid__placeholder" role="presentation">
                                    <span aria-hidden="true" className="cat-face-grid__placeholder-icon">
                                        ?
                                    </span>
                                    <span className="screen-reader-text">
                                        {__("No thumbnail available for this face", "context-alt-text")}
                                    </span>
                                </div>
                            )}
                            {(onDeleteFace || onViewOriginal) && (
                                <div className="cat-face-grid__actions">
                                    {onViewOriginal && (
                                        <button
                                            type="button"
                                            className="cat-face-grid__action"
                                            onClick={(e) => handleViewOriginal(e, face.attachmentId)}
                                            aria-label={__("View original image", "context-alt-text")}
                                            title={__("View original image", "context-alt-text")}
                                        >
                                            <svg
                                                width="16"
                                                height="16"
                                                viewBox="0 0 16 16"
                                                fill="none"
                                                xmlns="http://www.w3.org/2000/svg"
                                                aria-hidden="true"
                                            >
                                                <path
                                                    d="M14 9v5H2V9H0v5a2 2 0 002 2h12a2 2 0 002-2V9h-2z"
                                                    fill="currentColor"
                                                />
                                                <path
                                                    d="M8 11L3.5 6.5 5 5l2 2V0h2v7l2-2 1.5 1.5L8 11z"
                                                    fill="currentColor"
                                                />
                                            </svg>
                                        </button>
                                    )}
                                    {onDeleteFace && (
                                        <button
                                            type="button"
                                            className="cat-face-grid__action cat-face-grid__action--delete"
                                            onClick={(e) => handleDelete(e, face.id)}
                                            aria-label={__("Delete this face", "context-alt-text")}
                                            title={__("Delete this face", "context-alt-text")}
                                        >
                                            <svg
                                                width="16"
                                                height="16"
                                                viewBox="0 0 16 16"
                                                fill="none"
                                                xmlns="http://www.w3.org/2000/svg"
                                                aria-hidden="true"
                                            >
                                                <path
                                                    d="M14 3h-3.27L9.31 1.13A2.5 2.5 0 007.38 0H5.62a2.5 2.5 0 00-1.93 1.13L2.27 3H2a1 1 0 000 2h.09L3 14.5A1.5 1.5 0 004.5 16h7a1.5 1.5 0 001.5-1.5L13.91 5H14a1 1 0 000-2zM5.62 2h1.76c.24 0 .47.11.62.3l.77 1.7H4.23l.77-1.7a.75.75 0 01.62-.3zM11.5 14h-7l-.84-9h8.68l-.84 9z"
                                                    fill="currentColor"
                                                />
                                            </svg>
                                        </button>
                                    )}
                                </div>
                            )}
                        </button>
                    </li>
                );
            })}
        </ul>
    );
};
