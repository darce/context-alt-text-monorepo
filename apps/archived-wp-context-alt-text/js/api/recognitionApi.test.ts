/**
 * Recognition API Tests
 *
 * Tests for typed API wrappers using Mock Service Worker (MSW).
 */

import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/admin/testing/mswServer";
import { identifyFaces, submitLabel, bulkConfirm } from "./recognitionApi";
import type { IdentifyRequest, IdentifyResponse } from "@/types/people-labeling";

// Match the identify endpoint - MSW will handle any origin
const IDENTIFY_ENDPOINT = "/wp-json/cat/v1/recognition/identify";

describe("recognitionApi", () => {
    describe("identifyFaces", () => {
        it("should successfully identify faces", async () => {
            const request: IdentifyRequest = {
                attachmentId: 123,
                faces: [
                    {
                        bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
                        faceId: "face-1",
                    },
                ],
            };

            const mockResponse: IdentifyResponse = {
                faces: [
                    {
                        faceId: "face-1",
                        clusterId: "cluster-abc123-0",
                        suggestions: [
                            { rosterId: "person-1", display: "Ana Rodriguez", score: 0.95 },
                            { rosterId: "person-2", display: "Carlos Santos", score: 0.87 },
                        ],
                    },
                ],
            };

            server.use(
                http.post(IDENTIFY_ENDPOINT, () => {
                    return HttpResponse.json(mockResponse);
                }),
            );

            const response = await identifyFaces(request);

            expect(response).toEqual(mockResponse);
            expect(response.faces).toHaveLength(1);
            expect(response.faces[0].faceId).toBe("face-1");
            expect(response.faces[0].suggestions).toHaveLength(2);
        });

        it("should handle multiple faces", async () => {
            const request: IdentifyRequest = {
                attachmentId: 456,
                faces: [
                    { bbox: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 }, faceId: "face-1" },
                    { bbox: { x: 0.5, y: 0.5, width: 0.3, height: 0.3 }, faceId: "face-2" },
                ],
            };

            const mockResponse: IdentifyResponse = {
                faces: [
                    {
                        faceId: "face-1",
                        clusterId: "cluster-1",
                        suggestions: [{ rosterId: "person-1", display: "Alice", score: 0.9 }],
                    },
                    {
                        faceId: "face-2",
                        clusterId: "cluster-2",
                        suggestions: [{ rosterId: "person-2", display: "Bob", score: 0.85 }],
                    },
                ],
            };

            server.use(http.post(IDENTIFY_ENDPOINT, () => HttpResponse.json(mockResponse)));

            const response = await identifyFaces(request);

            expect(response.faces).toHaveLength(2);
            expect(response.faces[0].faceId).toBe("face-1");
            expect(response.faces[1].faceId).toBe("face-2");
        });

        it("should handle network errors", async () => {
            const request: IdentifyRequest = {
                attachmentId: 789,
                faces: [{ bbox: { x: 0, y: 0, width: 1, height: 1 } }],
            };

            server.use(http.post(IDENTIFY_ENDPOINT, () => HttpResponse.error()));

            await expect(identifyFaces(request)).rejects.toThrow();
        });

        it("should handle 400 Bad Request", async () => {
            const request: IdentifyRequest = {
                attachmentId: 999,
                faces: [],
            };

            server.use(
                http.post(IDENTIFY_ENDPOINT, () => HttpResponse.json({ message: "Invalid request" }, { status: 400 })),
            );

            await expect(identifyFaces(request)).rejects.toThrow("Invalid request");
        });

        it("should handle 503 Service Unavailable", async () => {
            const request: IdentifyRequest = {
                attachmentId: 111,
                faces: [{ bbox: { x: 0, y: 0, width: 1, height: 1 } }],
            };

            server.use(
                http.post(IDENTIFY_ENDPOINT, () =>
                    HttpResponse.json({ message: "Recognition service unavailable" }, { status: 503 }),
                ),
            );

            await expect(identifyFaces(request)).rejects.toThrow("Recognition service unavailable");
        });

        it("should handle 401 Unauthorized permission error", async () => {
            const request: IdentifyRequest = {
                attachmentId: 123,
                faces: [{ bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } }],
            };

            server.use(
                http.post(IDENTIFY_ENDPOINT, () =>
                    HttpResponse.json(
                        {
                            code: "rest_forbidden",
                            message: "You do not have permission to identify faces.",
                            data: { status: 401 },
                        },
                        { status: 401 },
                    ),
                ),
            );

            await expect(identifyFaces(request)).rejects.toThrow("You do not have permission to identify faces.");
        });
    });

    describe("submitLabel", () => {
        it("should submit label for single face", async () => {
            const request: IdentifyRequest = {
                attachmentId: 123,
                faces: [
                    {
                        bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
                        faceId: "face-1",
                        label: { rosterId: "person-1" },
                    },
                ],
            };

            const mockResponse: IdentifyResponse = {
                faces: [
                    {
                        faceId: "face-1",
                        observationId: 456,
                        suggestions: [],
                    },
                ],
            };

            server.use(http.post(IDENTIFY_ENDPOINT, () => HttpResponse.json(mockResponse)));

            const response = await submitLabel(request);

            expect(response.faces[0].observationId).toBe(456);
        });

        it("should handle new person creation", async () => {
            const request: IdentifyRequest = {
                attachmentId: 789,
                faces: [
                    {
                        bbox: { x: 0.5, y: 0.5, width: 0.2, height: 0.2 },
                        faceId: "face-2",
                        label: { newName: "Maria Silva" },
                    },
                ],
            };

            const mockResponse: IdentifyResponse = {
                faces: [
                    {
                        faceId: "face-2",
                        observationId: 789,
                        suggestions: [],
                    },
                ],
            };

            server.use(http.post(IDENTIFY_ENDPOINT, () => HttpResponse.json(mockResponse)));

            const response = await submitLabel(request);

            expect(response.faces[0].observationId).toBe(789);
        });
    });

    describe("bulkConfirm", () => {
        it("should confirm multiple faces", async () => {
            const request: IdentifyRequest = {
                attachmentId: 123,
                faces: [
                    {
                        bbox: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 },
                        faceId: "face-1",
                        label: { rosterId: "person-1" },
                    },
                    {
                        bbox: { x: 0.5, y: 0.5, width: 0.3, height: 0.3 },
                        faceId: "face-2",
                        label: { rosterId: "person-1" },
                    },
                    {
                        bbox: { x: 0.2, y: 0.8, width: 0.2, height: 0.2 },
                        faceId: "face-3",
                        label: { rosterId: "person-1" },
                    },
                ],
            };

            const mockResponse: IdentifyResponse = {
                faces: [
                    { faceId: "face-1", observationId: 101, suggestions: [] },
                    { faceId: "face-2", observationId: 102, suggestions: [] },
                    { faceId: "face-3", observationId: 103, suggestions: [] },
                ],
            };

            server.use(http.post(IDENTIFY_ENDPOINT, () => HttpResponse.json(mockResponse)));

            const response = await bulkConfirm(request);

            expect(response.faces).toHaveLength(3);
            expect(response.faces[0].observationId).toBe(101);
            expect(response.faces[1].observationId).toBe(102);
            expect(response.faces[2].observationId).toBe(103);
        });
    });
});
