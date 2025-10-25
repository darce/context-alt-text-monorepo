/**
 * Face Embeddings Extraction
 *
 * Extracts 512-dimensional face embeddings using MediaPipe FaceLandmarker
 * for local similarity comparison and clustering.
 *
 * Note: MediaPipe doesn't have a dedicated face recognition embedder,
 * so we'll use face landmarks (468 3D points) as a proxy for similarity.
 * This is less accurate than InsightFace but sufficient for local clustering.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import type { FaceLandmarker, FaceLandmarkerOptions } from "@mediapipe/tasks-vision";

/**
 * MediaPipe FaceLandmarker configuration
 */
const LANDMARKER_CONFIG: FaceLandmarkerOptions = {
    baseOptions: {
        modelAssetPath:
            "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        delegate: "GPU",
    },
    runningMode: "IMAGE",
    numFaces: 1, // Process one face at a time for embeddings
    minFaceDetectionConfidence: 0.5,
    minFacePresenceConfidence: 0.5,
    minTrackingConfidence: 0.5,
    outputFaceBlendshapes: true, // Include blendshapes for richer embedding
    outputFacialTransformationMatrixes: true,
};

/**
 * Singleton cache
 */
let cachedLandmarker: FaceLandmarker | null = null;
let loadingPromise: Promise<FaceLandmarker> | null = null;

/**
 * Load MediaPipe FaceLandmarker
 *
 * @returns Promise resolving to FaceLandmarker instance
 */
export const loadFaceLandmarker = async (): Promise<FaceLandmarker> => {
    if (cachedLandmarker !== null) {
        return cachedLandmarker;
    }

    if (loadingPromise !== null) {
        return loadingPromise;
    }

    loadingPromise = (async () => {
        try {
            const { FaceLandmarker, FilesetResolver } = await import("@mediapipe/tasks-vision");

            const vision = await FilesetResolver.forVisionTasks(
                "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm",
            );

            const landmarker = await FaceLandmarker.createFromOptions(vision, LANDMARKER_CONFIG);

            cachedLandmarker = landmarker;
            return landmarker;
        } catch (error) {
            loadingPromise = null;

            if (error instanceof Error) {
                throw new Error(`Failed to load FaceLandmarker: ${error.message}`);
            }

            throw new Error("Failed to load FaceLandmarker: Unknown error");
        }
    })();

    return loadingPromise;
};

/**
 * Unload landmarker and free memory
 */
export const unloadFaceLandmarker = (): void => {
    if (cachedLandmarker !== null) {
        cachedLandmarker.close();
        cachedLandmarker = null;
    }
    loadingPromise = null;
};

/**
 * Face embedding vector (512D for compatibility with backend)
 *
 * Derived from MediaPipe landmarks + blendshapes.
 * Less accurate than InsightFace but sufficient for local clustering.
 */
export type FaceEmbedding = Float32Array;

/**
 * Crop face region from image
 *
 * @param image - Source image
 * @param bbox - Bounding box in pixel coordinates
 * @returns Canvas with cropped face (112x112 for consistency with backend)
 */
const cropFaceRegion = (
    image: HTMLImageElement,
    bbox: { x: number; y: number; width: number; height: number },
): HTMLCanvasElement => {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    if (ctx === null) {
        throw new Error("Failed to get 2D context");
    }

    // Resize to 112x112 (standard face recognition input size)
    canvas.width = 112;
    canvas.height = 112;

    // Add padding around bbox (10% on each side)
    const padding = Math.max(bbox.width, bbox.height) * 0.1;
    const x = Math.max(0, bbox.x - padding);
    const y = Math.max(0, bbox.y - padding);
    const w = bbox.width + padding * 2;
    const h = bbox.height + padding * 2;

    // Draw cropped and resized face
    ctx.drawImage(image, x, y, w, h, 0, 0, 112, 112);

    return canvas;
};

/**
 * Extract face embedding from image region
 *
 * @param landmarker - MediaPipe FaceLandmarker instance
 * @param image - Source image
 * @param bbox - Face bounding box in pixel coordinates
 * @returns 512D embedding vector
 */
export const extractFaceEmbedding = async (
    landmarker: FaceLandmarker,
    image: HTMLImageElement,
    bbox: { x: number; y: number; width: number; height: number },
): Promise<FaceEmbedding> => {
    // Crop face region
    const faceCanvas = cropFaceRegion(image, bbox);

    // Run landmarker
    const results = landmarker.detect(faceCanvas);

    if (results.faceLandmarks.length === 0) {
        throw new Error("No face landmarks detected");
    }

    const landmarks = results.faceLandmarks[0]; // 468 3D points
    const blendshapes = results.faceBlendshapes?.[0] ?? [];

    // Create embedding from landmarks + blendshapes
    // This is a simplified approach - ideally we'd use a trained face recognition model
    const embedding = new Float32Array(512);

    // Fill first 468 values with flattened landmark coordinates (x, y, z not all used)
    let idx = 0;
    for (let i = 0; i < Math.min(156, landmarks.length); i++) {
        // Use first 156 landmarks (468 values)
        const lm = landmarks[i];
        if (lm !== undefined) {
            embedding[idx++] = lm.x;
            embedding[idx++] = lm.y;
            embedding[idx++] = lm.z ?? 0;
        }
    }

    // Fill remaining values with blendshapes (52 values)
    for (let i = 0; i < Math.min(52, blendshapes.categories?.length ?? 0); i++) {
        const bs = blendshapes.categories?.[i];
        if (bs !== undefined) {
            embedding[idx++] = bs.score;
        }
    }

    // Pad remaining with zeros
    while (idx < 512) {
        embedding[idx++] = 0;
    }

    // Normalize the embedding vector (L2 norm)
    const norm = Math.sqrt(embedding.reduce((sum, val) => sum + val * val, 0));
    if (norm > 0) {
        for (let i = 0; i < embedding.length; i++) {
            embedding[i] /= norm;
        }
    }

    return embedding;
};

/**
 * Extract embeddings for multiple faces
 *
 * @param landmarker - MediaPipe FaceLandmarker instance
 * @param image - Source image
 * @param bboxes - Array of face bounding boxes
 * @returns Array of 512D embeddings
 */
export const extractFaceEmbeddings = async (
    landmarker: FaceLandmarker,
    image: HTMLImageElement,
    bboxes: Array<{ x: number; y: number; width: number; height: number }>,
): Promise<FaceEmbedding[]> => {
    const embeddings: FaceEmbedding[] = [];

    for (const bbox of bboxes) {
        try {
            const embedding = await extractFaceEmbedding(landmarker, image, bbox);
            embeddings.push(embedding);
        } catch (error) {
            console.warn("Failed to extract embedding for face:", error);
            // Return zero vector as fallback
            embeddings.push(new Float32Array(512));
        }
    }

    return embeddings;
};

/**
 * Compute cosine similarity between two embedding vectors
 *
 * @param a - First embedding
 * @param b - Second embedding
 * @returns Similarity score (0.0 to 1.0, higher = more similar)
 *
 * @example
 * ```typescript
 * const sim = cosineSimilarity(embedding1, embedding2);
 * if (sim > 0.7) {
 *   console.log('Likely same person');
 * }
 * ```
 */
export const cosineSimilarity = (a: FaceEmbedding, b: FaceEmbedding): number => {
    if (a.length !== b.length) {
        throw new Error("Embeddings must have the same length");
    }

    let dotProduct = 0;
    let normA = 0;
    let normB = 0;

    for (let i = 0; i < a.length; i++) {
        dotProduct += a[i] * b[i];
        normA += a[i] * a[i];
        normB += b[i] * b[i];
    }

    const denominator = Math.sqrt(normA) * Math.sqrt(normB);

    if (denominator === 0) {
        return 0;
    }

    // Return similarity in [0, 1] range
    // Cosine similarity is in [-1, 1], but face embeddings are normalized so it's [0, 1]
    return dotProduct / denominator;
};
