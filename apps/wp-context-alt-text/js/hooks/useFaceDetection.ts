/**
 * Face Detection Hook
 *
 * React hook for managing MediaPipe face detection lifecycle.
 * Handles model loading, detection execution, and cleanup.
 *
 * @package ContextAltText
 * @since 1.0.0
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
    loadFaceDetector,
    unloadFaceDetector,
    detectFaces,
    isDetectorLoaded,
    type FaceDetection,
} from "../utils/mediaPipeLoader";
import type { FaceDetector } from "@mediapipe/tasks-vision";

/**
 * Face detection state
 */
export type DetectionState = "idle" | "loading" | "detecting" | "success" | "error";

/**
 * Face detection hook return type
 */
export interface UseFaceDetectionResult {
    /** Current detection state */
    state: DetectionState;
    /** Detected faces (null until first successful detection) */
    detections: FaceDetection[] | null;
    /** Error message if state is 'error' */
    error: string | null;
    /** Whether detector is loaded and ready */
    isReady: boolean;
    /** Load the detector model (call once on mount or mode activation) */
    loadDetector: () => Promise<void>;
    /** Run face detection on an image element */
    detect: (image: HTMLImageElement) => Promise<FaceDetection[]>;
    /** Unload detector and free memory */
    unload: () => void;
    /** Reset state to idle */
    reset: () => void;
}

/**
 * Hook for face detection with MediaPipe
 *
 * Usage pattern:
 * 1. Call loadDetector() when entering Interactive mode
 * 2. Call detect(imageElement) for each image
 * 3. Call unload() when exiting Interactive mode
 *
 * @param options - Configuration options
 * @param options.autoLoad - Automatically load detector on mount (default: false)
 * @param options.onDetectionComplete - Callback when detection completes
 * @param options.onError - Callback when error occurs
 * @returns Detection state and control functions
 *
 * @example
 * ```typescript
 * const { state, detections, detect, loadDetector } = useFaceDetection();
 *
 * useEffect(() => {
 *   void loadDetector();
 * }, []);
 *
 * const handleImageLoad = async (img: HTMLImageElement) => {
 *   const faces = await detect(img);
 *   console.log(`Found ${faces.length} faces`);
 * };
 * ```
 */
export const useFaceDetection = (options?: {
    autoLoad?: boolean;
    onDetectionComplete?: (detections: FaceDetection[]) => void;
    onError?: (error: Error) => void;
}): UseFaceDetectionResult => {
    const { autoLoad = false, onDetectionComplete, onError } = options ?? {};

    const [state, setState] = useState<DetectionState>("idle");
    const [detections, setDetections] = useState<FaceDetection[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [isReady, setIsReady] = useState(false);

    const detectorRef = useRef<FaceDetector | null>(null);
    const isMountedRef = useRef(true);

    /**
     * Load MediaPipe detector
     */
    const loadDetector = useCallback(async () => {
        if (!isMountedRef.current) {
            return;
        }

        // Already loaded
        if (isDetectorLoaded() && detectorRef.current !== null) {
            setIsReady(true);
            setState("idle");
            return;
        }

        setState("loading");
        setError(null);

        try {
            const detector = await loadFaceDetector();

            if (isMountedRef.current) {
                detectorRef.current = detector;
                setIsReady(true);
                setState("idle");
            }
        } catch (err) {
            if (isMountedRef.current) {
                const errorMessage = err instanceof Error ? err.message : "Failed to load detector";
                setError(errorMessage);
                setState("error");
                setIsReady(false);

                if (onError !== undefined) {
                    onError(err instanceof Error ? err : new Error("Failed to load detector"));
                }
            }
        }
    }, [onError]);

    /**
     * Run face detection on image
     */
    const detect = useCallback(
        async (image: HTMLImageElement): Promise<FaceDetection[]> => {
            if (!isMountedRef.current) {
                return [];
            }

            // Ensure detector is loaded
            if (detectorRef.current === null) {
                throw new Error("Detector not loaded. Call loadDetector() first.");
            }

            setState("detecting");
            setError(null);

            try {
                // Run synchronous detection, wrapped in Promise for consistency
                const results = await Promise.resolve(detectFaces(detectorRef.current, image));

                if (isMountedRef.current) {
                    setDetections(results);
                    setState("success");

                    if (onDetectionComplete !== undefined) {
                        onDetectionComplete(results);
                    }
                }

                return results;
            } catch (err) {
                if (isMountedRef.current) {
                    const errorMessage = err instanceof Error ? err.message : "Face detection failed";
                    setError(errorMessage);
                    setState("error");

                    if (onError !== undefined) {
                        onError(err instanceof Error ? err : new Error("Face detection failed"));
                    }
                }

                return [];
            }
        },
        [onDetectionComplete, onError],
    );

    /**
     * Unload detector and free resources
     */
    const unload = useCallback(() => {
        unloadFaceDetector();
        detectorRef.current = null;
        setIsReady(false);
        setState("idle");
        setDetections(null);
        setError(null);
    }, []);

    /**
     * Reset state without unloading detector
     */
    const reset = useCallback(() => {
        setState("idle");
        setDetections(null);
        setError(null);
    }, []);

    /**
     * Auto-load on mount if requested and setup cleanup
     */
    useEffect(() => {
        isMountedRef.current = true;

        if (autoLoad) {
            void loadDetector();
        }

        return () => {
            isMountedRef.current = false;
            // Don't unload detector on unmount - it's cached globally
            // Only unload when explicitly requested (e.g., mode switch)
        };
    }, [autoLoad, loadDetector]);

    return {
        state,
        detections,
        error,
        isReady,
        loadDetector,
        detect,
        unload,
        reset,
    };
};
