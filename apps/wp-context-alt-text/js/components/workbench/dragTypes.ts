export const FACE_DRAG_MIME_TYPE = "application/x-cat-face-drag";

export interface FaceDragPayload {
    clusterId: string;
    faceIds: string[];
}

export const setFaceDragData = (dataTransfer: DataTransfer, payload: FaceDragPayload): void => {
    try {
        dataTransfer.setData(FACE_DRAG_MIME_TYPE, JSON.stringify(payload));
    } catch (error) {
        // Fallback for environments that do not support custom MIME types
    }

    try {
        dataTransfer.setData("text/plain", payload.faceIds.join(","));
    } catch (error) {
        // Ignore text/plain failures as well
    }
};

export const getFaceDragData = (dataTransfer: DataTransfer): FaceDragPayload | null => {
    let raw = "";

    try {
        raw = dataTransfer.getData(FACE_DRAG_MIME_TYPE);
    } catch (error) {
        raw = "";
    }

    if (!raw || raw.trim() === "") {
        return null;
    }

    try {
        const parsed = JSON.parse(raw) as Partial<FaceDragPayload>;

        if (
            !parsed ||
            typeof parsed.clusterId !== "string" ||
            !Array.isArray(parsed.faceIds) ||
            parsed.faceIds.some((value) => typeof value !== "string")
        ) {
            return null;
        }

        return {
            clusterId: parsed.clusterId,
            faceIds: parsed.faceIds,
        };
    } catch (error) {
        return null;
    }
};

export const hasFaceDragData = (dataTransfer: DataTransfer): boolean => {
    try {
        const types = Array.from(dataTransfer.types ?? []);
        if (types.includes(FACE_DRAG_MIME_TYPE)) {
            return true;
        }
    } catch (error) {
        // Ignore
    }

    const payload = getFaceDragData(dataTransfer);
    return payload !== null;
};
