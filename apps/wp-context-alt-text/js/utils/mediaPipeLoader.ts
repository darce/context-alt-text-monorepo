/**
 * MediaPipe FaceDetector Model Loader
 *
 * Lazy-loads MediaPipe's FaceDetector model with WebAssembly runtime.
 * This module handles:
 * - Dynamic import to avoid including ~2.5 MB in main bundle
 * - Model initialization with optimal settings
 * - Error handling and retry logic
 * - Caching to prevent re-downloads
 *
 * @package ContextAltText
 * @since 1.0.0
 */

import type { FaceDetector, FaceDetectorOptions } from "@mediapipe/tasks-vision";

/**
 * MediaPipe model configuration
 * Using SHORT_RANGE model for faster detection on individual photos
 */
const MODEL_CONFIG: FaceDetectorOptions = {
    baseOptions: {
        modelAssetPath:
            "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
        delegate: "GPU", // Use GPU acceleration when available
    },
    runningMode: "IMAGE", // IMAGE mode for static photos (vs VIDEO for streams)
    minDetectionConfidence: 0.5, // Lower threshold to catch more faces (backend will validate)
    minSuppressionThreshold: 0.3, // Non-max suppression threshold
};

/**
 * Singleton instance cache
 * Prevents loading model multiple times
 */
let cachedDetector: FaceDetector | null = null;
let loadingPromise: Promise<FaceDetector> | null = null;

/**
 * Load MediaPipe FaceDetector model
 *
 * Uses dynamic import for code splitting. The first call loads ~2.5 MB
 * (model + WASM runtime), subsequent calls return cached instance.
 *
 * @returns Promise resolving to initialized FaceDetector instance
 * @throws Error if model fails to load after retries
 *
 * @example
 * ```typescript
 * const detector = await loadFaceDetector();
 * const results = detector.detect(imageElement);
 * console.log(`Found ${results.detections.length} faces`);
 * ```
 */
export const loadFaceDetector = async (): Promise<FaceDetector> => {
    // Return cached instance if available
    if (cachedDetector !== null) {
        return cachedDetector;
    }

    // Return in-flight promise if already loading
    if (loadingPromise !== null) {
        return loadingPromise;
    }

    // Start loading
    loadingPromise = (async () => {
        try {
            // Dynamic import to enable code splitting
            const { FaceDetector, FilesetResolver } = await import("@mediapipe/tasks-vision");

            // Load WebAssembly runtime
            const vision = await FilesetResolver.forVisionTasks(
                "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm",
            );

            // Create detector with configuration
            const detector = await FaceDetector.createFromOptions(vision, MODEL_CONFIG);

            cachedDetector = detector;
            return detector;
        } catch (error) {
            loadingPromise = null; // Allow retry on next call

            if (error instanceof Error) {
                throw new Error(`Failed to load MediaPipe FaceDetector: ${error.message}`);
            }

            throw new Error("Failed to load MediaPipe FaceDetector: Unknown error");
        }
    })();

    return loadingPromise;
};

/**
 * Unload the detector and free memory
 *
 * Call this when interactive mode is disabled to free resources.
 * The detector will be reloaded on next use.
 */
export const unloadFaceDetector = (): void => {
    if (cachedDetector !== null) {
        cachedDetector.close();
        cachedDetector = null;
    }
    loadingPromise = null;
};

/**
 * Check if detector is currently loaded
 *
 * @returns true if detector is loaded and ready
 */
export const isDetectorLoaded = (): boolean => {
    return cachedDetector !== null;
};

/**
 * Face detection bounding box (normalized coordinates)
 *
 * MediaPipe returns coordinates normalized to [0, 1] range.
 * Multiply by image width/height to get pixel coordinates.
 */
export interface NormalizedBoundingBox {
    /** X coordinate of top-left corner (0.0 - 1.0) */
    originX: number;
    /** Y coordinate of top-left corner (0.0 - 1.0) */
    originY: number;
    /** Width of bounding box (0.0 - 1.0) */
    width: number;
    /** Height of bounding box (0.0 - 1.0) */
    height: number;
}

/**
 * Face detection result from MediaPipe
 */
export interface FaceDetection {
    /** Normalized bounding box coordinates */
    boundingBox: NormalizedBoundingBox;
    /** Detection confidence score (0.0 - 1.0) */
    confidence: number;
    /** Keypoints (eyes, nose, mouth) - optional for labeling UI */
    keypoints?: { x: number; y: number; name: string }[];
}

/**
 * Detect faces in an image element
 *
 * Called once per image when the image loads.
 * Video detection is not part of the MVP.
 *
 * @param detector - MediaPipe FaceDetector instance (from loadFaceDetector)
 * @param image - HTMLImageElement to detect faces in
 * @returns Array of detected faces with bounding boxes
 *
 * @example
 * ```typescript
 * const detector = await loadFaceDetector();
 * const img = document.querySelector('img');
 * const faces = detectFaces(detector, img);
 *
 * faces.forEach((face, i) => {
 *   console.log(`Face ${i + 1}: confidence ${face.confidence.toFixed(2)}`);
 *   console.log(`  Position: x=${face.boundingBox.originX}, y=${face.boundingBox.originY}`);
 * });
 * ```
 */
export const detectFaces = (detector: FaceDetector, image: HTMLImageElement): FaceDetection[] => {
    const startTime = performance.now();

    // Run detection
    const detectionResults = detector.detect(image);

    const endTime = performance.now();
    const duration = endTime - startTime;

    // Log performance for monitoring
    if (duration > 500) {
        console.warn(`[MediaPipe] Face detection took ${duration.toFixed(0)}ms (target: <400ms)`);
    }

    // Log raw MediaPipe output to debug coordinate system
    if (detectionResults.detections.length > 0) {
        console.log("[MediaPipe] Raw detection:", detectionResults.detections[0]?.boundingBox);
    }

    // Transform MediaPipe results to our format
    return detectionResults.detections
        .filter((detection) => detection.boundingBox !== undefined)
        .map((detection) => ({
            boundingBox: {
                originX: detection.boundingBox!.originX,
                originY: detection.boundingBox!.originY,
                width: detection.boundingBox!.width,
                height: detection.boundingBox!.height,
            },
            confidence: detection.categories[0]?.score ?? 0.0,
            keypoints: detection.keypoints?.map((kp, index) => ({
                x: kp.x,
                y: kp.y,
                name: `keypoint-${index}`,
            })),
        }));
};

/**
 * Convert normalized coordinates to pixel coordinates
 *
 * @param normalized - Normalized bounding box (0-1 range)
 * @param imageWidth - Image width in pixels
 * @param imageHeight - Image height in pixels
 * @returns Bounding box in pixel coordinates
 *
 * @example
 * ```typescript
 * const normalized = { originX: 0.2, originY: 0.3, width: 0.15, height: 0.2 };
 * const pixels = toPixelCoordinates(normalized, 1920, 1080);
 * // { x: 384, y: 324, width: 288, height: 216 }
 * ```
 */
export const toPixelCoordinates = (
    normalized: NormalizedBoundingBox,
    imageWidth: number,
    imageHeight: number,
): { x: number; y: number; width: number; height: number } => {
    return {
        x: Math.round(normalized.originX * imageWidth),
        y: Math.round(normalized.originY * imageHeight),
        width: Math.round(normalized.width * imageWidth),
        height: Math.round(normalized.height * imageHeight),
    };
};
