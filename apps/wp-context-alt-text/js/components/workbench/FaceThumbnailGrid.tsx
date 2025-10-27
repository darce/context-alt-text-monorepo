import React from "react";

import { FaceGrid } from "@/components/workbench/FaceGrid";
import type { ClusterFaceDetail } from "@/types/face-clustering";
import "./FaceThumbnailGrid.scss";

export interface FaceThumbnailGridProps {
    faces: ClusterFaceDetail[];
    selectedFaceIds: string[];
    onToggleFace: (faceId: string) => void;
}

export const FaceThumbnailGrid = ({
    faces,
    selectedFaceIds,
    onToggleFace,
}: FaceThumbnailGridProps): React.JSX.Element => {
    return (
        <div className="cat-face-thumbnail-grid">
            <FaceGrid
                faces={faces}
                selectedFaceIds={selectedFaceIds}
                onToggleFace={(faceId) => onToggleFace(faceId)}
                selectionAnchorIndex={null}
            />
        </div>
    );
};
