import { useCallback, useState } from 'react';

export type ClusterDragPayload = { faceId: string; fromClusterId: string } | null;

export const useClusterDragDrop = () => {
	const [dragPayload, setDragPayload] = useState<ClusterDragPayload>(null);
	const [dropTarget, setDropTarget] = useState<string | 'discard' | null>(null);

	const handleFaceDragStart = useCallback((clusterId: string, faceId: string) => {
		setDragPayload({ fromClusterId: clusterId, faceId });
	}, []);

	const handleFaceDragEnd = useCallback(() => {
		setDragPayload(null);
		setDropTarget(null);
	}, []);

	const handleDropTargetChange = useCallback((target: string | 'discard' | null) => {
		setDropTarget(target);
	}, []);

	const reset = useCallback(() => {
		handleFaceDragEnd();
	}, [handleFaceDragEnd]);

	return {
		dragPayload,
		dropTarget,
		isDragging: Boolean(dragPayload),
		handleFaceDragStart,
		handleFaceDragEnd,
		handleDropTargetChange,
		resetDragState: reset,
	};
};
