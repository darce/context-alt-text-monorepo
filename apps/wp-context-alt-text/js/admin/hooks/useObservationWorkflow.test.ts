/* eslint-disable @typescript-eslint/no-unsafe-assignment */
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-unsafe-argument */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useObservationWorkflow } from "./useObservationWorkflow";
import type {
    AdminConfig,
    RosterEntry,
    RecognitionObservationRecord,
    RecognitionObservationAttachment,
} from "@/admin/types";
import type { UseRecognitionObservationsResult } from "./useRecognitionObservations";
import * as useRecognitionObservationsModule from "./useRecognitionObservations";
import * as noticesModule from "@/admin/notices";

// Mock the dependencies
vi.mock("./useRecognitionObservations");
vi.mock("@/admin/notices");

// Helper to create a mock UseRecognitionObservationsResult
const createMockObservationsResult = (
    overrides?: Partial<UseRecognitionObservationsResult>,
): UseRecognitionObservationsResult => ({
    query: {
        data: undefined,
        error: null,
        isFetching: false,
        isLoading: false,
        refetch: vi.fn(),
    } as any,
    hasEndpoint: true,
    canUpdateObservation: true,
    updateObservation: vi.fn(),
    isUpdating: false,
    retryRecognition: vi.fn(),
    isRetrying: false,
    ...overrides,
});

describe("useObservationWorkflow", () => {
    const mockConfig: AdminConfig = {
        endpoints: {
            rosterEntries: "/wp-json/cat/v1/roster",
            recognitionObservations: "/wp-json/cat/v1/observations",
        },
        featureFlags: {},
        settings: {
            recognition: {
                canManage: true,
            },
        },
    };

    const mockEntries: RosterEntry[] = [
        {
            remoteId: "entry-1",
            label: "John Doe",
            type: "person",
            status: "SYNCED",
            updatedAt: "2025-10-18T00:00:00Z",
            metadata: {},
            referenceImages: [],
            avatarUrl: null,
            avatarId: null,
            referenceImageCount: 0,
        },
        {
            remoteId: "entry-2",
            label: "Acme Corp",
            type: "brand",
            status: "SYNCED",
            updatedAt: "2025-10-18T00:00:00Z",
            metadata: {},
            referenceImages: [],
            avatarUrl: null,
            avatarId: null,
            referenceImageCount: 0,
        },
    ];

    const mockUpdateEntry = vi.fn();
    const mockRefetch = vi.fn();

    const mockObservationRecord: RecognitionObservationRecord = {
        observationId: "obs-123",
        label: "John Doe",
        entityType: "person",
        confidence: 0.95,
        status: "needs_review",
        candidates: [],
        roster: null,
        area: 0.25,
        boundingBox: [100, 100, 200, 200],
        source: null,
        match: {
            isMatch: false,
            similarity: 0.95,
            confidence: 0.95,
            threshold: 0.85,
        },
    };

    const mockAttachment: RecognitionObservationAttachment = {
        attachmentId: 456,
        jobId: "job-123",
        updatedAt: Date.now(),
        status: "needs_review",
        summary: {
            total: 1,
            matched: 0,
            needs_review: 1,
        },
        observations: [mockObservationRecord],
        context: {
            imageUrl: "https://example.com/image.jpg",
        },
        confidenceScore: 0.95,
        sourceRemoteId: null,
    };

    const mockObservationData = {
        items: [mockAttachment],
        summary: {
            attachments: 1,
            observations: { total: 1, matched: 0, needs_review: 1 },
        },
    };

    beforeEach(() => {
        vi.clearAllMocks();

        // Mock useRecognitionObservations
        vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
            createMockObservationsResult({
                query: {
                    data: mockObservationData,
                    error: null,
                    isFetching: false,
                    isLoading: false,
                    refetch: mockRefetch,
                } as any,
            }),
        );

        mockUpdateEntry.mockResolvedValue(undefined);
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    describe("initialization", () => {
        it("initializes with observation data", () => {
            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            expect(result.current.observationItems).toEqual([mockAttachment]);
            expect(result.current.observationSummary).toEqual(mockObservationData.summary);
            expect(result.current.observationsError).toBeNull();
            expect(result.current.observationsLoading).toBe(false);
            expect(result.current.hasObservationEndpoint).toBe(true);
        });

        it("uses default summary when no data available", () => {
            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: undefined,
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            expect(result.current.observationItems).toEqual([]);
            expect(result.current.observationSummary).toEqual({
                attachments: 0,
                observations: { total: 0, matched: 0, needs_review: 0 },
            });
        });

        it("exposes error state", () => {
            const mockError = new Error("Failed to fetch observations");
            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: undefined,
                        error: mockError,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            expect(result.current.observationsError).toBe(mockError);
        });

        it("exposes loading state", () => {
            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: undefined,
                        error: null,
                        isFetching: true,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            expect(result.current.observationsLoading).toBe(true);
        });

        it("exposes endpoint availability", () => {
            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: mockObservationData,
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                    hasEndpoint: false,
                }),
            );

            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            expect(result.current.hasObservationEndpoint).toBe(false);
        });
    });

    describe("observation index", () => {
        it("builds index from observation items", () => {
            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            const index = result.current.observationIndex;
            expect(index.size).toBe(1);
            expect(index.has("obs-123")).toBe(true);

            const entry = index.get("obs-123");
            expect(entry).toBeDefined();
            expect(entry?.record).toBe(mockObservationRecord);
            expect(entry?.attachment).toBe(mockAttachment);
        });

        it("handles multiple observations across attachments", () => {
            const obs1: RecognitionObservationRecord = {
                observationId: "obs-1",
                label: "Person A",
                entityType: "person",
                confidence: 0.9,
                status: "needs_review",
                candidates: [],
                roster: null,
                area: 0.2,
                boundingBox: [50, 50, 150, 150],
                source: null,
                match: {
                    isMatch: false,
                    similarity: 0.9,
                    confidence: 0.9,
                    threshold: 0.85,
                },
            };

            const obs2: RecognitionObservationRecord = {
                observationId: "obs-2",
                label: "Person B",
                entityType: "person",
                confidence: 0.85,
                status: "needs_review",
                candidates: [],
                roster: null,
                area: 0.15,
                boundingBox: [200, 200, 300, 300],
                source: null,
                match: {
                    isMatch: false,
                    similarity: 0.85,
                    confidence: 0.85,
                    threshold: 0.85,
                },
            };

            const attachment1: RecognitionObservationAttachment = {
                attachmentId: 100,
                jobId: "job-1",
                updatedAt: Date.now(),
                status: "needs_review",
                summary: { total: 1, matched: 0, needs_review: 1 },
                observations: [obs1],
                context: {},
                confidenceScore: 0.9,
                sourceRemoteId: null,
            };

            const attachment2: RecognitionObservationAttachment = {
                attachmentId: 200,
                jobId: "job-2",
                updatedAt: Date.now(),
                status: "needs_review",
                summary: { total: 1, matched: 0, needs_review: 1 },
                observations: [obs2],
                context: {},
                confidenceScore: 0.85,
                sourceRemoteId: null,
            };

            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: {
                            items: [attachment1, attachment2],
                            summary: mockObservationData.summary,
                        } as any,
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            const index = result.current.observationIndex;
            expect(index.size).toBe(2);
            expect(index.has("obs-1")).toBe(true);
            expect(index.has("obs-2")).toBe(true);
            expect(index.get("obs-1")?.attachment.attachmentId).toBe(100);
            expect(index.get("obs-2")?.attachment.attachmentId).toBe(200);
        });

        it("skips invalid attachments", () => {
            const invalidAttachments = [
                null,
                { attachmentId: 1, observations: null },
                { attachmentId: 2, observations: "invalid" },
                { attachmentId: 3, observations: [null] },
                { attachmentId: 4, observations: [{ invalid: true }] },
            ];

            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: {
                            items: invalidAttachments as any,
                            summary: mockObservationData.summary,
                        } as any,
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            expect(result.current.observationIndex.size).toBe(0);
        });
    });

    describe("handleAssignToRoster", () => {
        it("successfully assigns observation to roster entry", async () => {
            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            await act(async () => {
                await result.current.handleAssignToRoster(mockObservationRecord, mockAttachment, "entry-1");
            });

            expect(mockUpdateEntry).toHaveBeenCalledWith({
                remoteId: "entry-1",
                label: "John Doe",
                type: "person",
                resolveObservation: {
                    attachmentId: 456,
                    observationId: "obs-123",
                    status: "matched",
                    label: "John Doe",
                    entityType: "person",
                },
            });

            expect(noticesModule.dispatchNotice).toHaveBeenCalledWith("success", expect.stringContaining("John Doe"), {
                id: "cat-roster-observation-assign-success",
            });

            expect(mockRefetch).toHaveBeenCalled();
        });

        it("handles missing observation ID", async () => {
            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            const invalidRecord = { ...mockObservationRecord, observationId: undefined };

            await act(async () => {
                await result.current.handleAssignToRoster(invalidRecord as any, mockAttachment, "entry-1");
            });

            expect(mockUpdateEntry).not.toHaveBeenCalled();
            expect(noticesModule.notifyError).toHaveBeenCalledWith(
                expect.stringContaining("Unable to resolve observation details"),
                { id: "cat-roster-observation-assign-error" },
            );
        });

        it("handles missing attachment ID", async () => {
            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            const invalidAttachment = { ...mockAttachment, attachmentId: undefined };

            await act(async () => {
                await result.current.handleAssignToRoster(mockObservationRecord, invalidAttachment as any, "entry-1");
            });

            expect(mockUpdateEntry).not.toHaveBeenCalled();
            expect(noticesModule.notifyError).toHaveBeenCalledWith(
                expect.stringContaining("Unable to resolve observation details"),
                { id: "cat-roster-observation-assign-error" },
            );
        });

        it("handles missing roster entry", async () => {
            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            await act(async () => {
                await result.current.handleAssignToRoster(mockObservationRecord, mockAttachment, "non-existent");
            });

            expect(mockUpdateEntry).not.toHaveBeenCalled();
            expect(noticesModule.notifyError).toHaveBeenCalledWith(
                expect.stringContaining("Select a roster entry with a remote ID"),
                { id: "cat-roster-observation-assign-error" },
            );
        });

        it("handles update errors", async () => {
            mockUpdateEntry.mockRejectedValueOnce(new Error("Update failed"));

            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            await act(async () => {
                await result.current.handleAssignToRoster(mockObservationRecord, mockAttachment, "entry-1");
            });

            expect(noticesModule.notifyError).toHaveBeenCalledWith("Update failed", {
                id: "cat-roster-observation-assign-error",
            });
        });

        it("does not refetch if endpoint not available", async () => {
            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: mockObservationData,
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                    hasEndpoint: false,
                }),
            );

            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            await act(async () => {
                await result.current.handleAssignToRoster(mockObservationRecord, mockAttachment, "entry-1");
            });

            expect(mockUpdateEntry).toHaveBeenCalled();
            expect(mockRefetch).not.toHaveBeenCalled();
        });

        it("uses fallback values when entry/record fields are missing", async () => {
            const recordWithoutLabel: RecognitionObservationRecord = {
                ...mockObservationRecord,
                label: "", // Empty string instead of null
            };

            const entryWithoutType = {
                ...mockEntries[0],
                type: "", // Empty string for missing type
            };

            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: [entryWithoutType as RosterEntry, ...mockEntries.slice(1)],
                    updateEntry: mockUpdateEntry,
                }),
            );

            await act(async () => {
                await result.current.handleAssignToRoster(recordWithoutLabel, mockAttachment, "entry-1");
            });

            expect(mockUpdateEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    resolveObservation: expect.objectContaining({
                        label: "John Doe", // From entry
                        entityType: "", // Entry type is empty
                    }),
                }),
            );
        });
    });

    describe("refetchObservations", () => {
        it("exposes refetch function", () => {
            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            expect(result.current.refetchObservations).toBe(mockRefetch);
        });

        it("can refetch observations", async () => {
            const { result } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            await act(async () => {
                await result.current.refetchObservations();
            });

            expect(mockRefetch).toHaveBeenCalled();
        });
    });

    describe("memoization", () => {
        it("memoizes observation items", () => {
            const { result, rerender } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            const initialItems = result.current.observationItems;
            rerender();
            const nextItems = result.current.observationItems;

            expect(initialItems).toBe(nextItems); // Same reference
        });

        it("memoizes observation index", () => {
            const { result, rerender } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            const initialIndex = result.current.observationIndex;
            rerender();
            const nextIndex = result.current.observationIndex;

            expect(initialIndex).toBe(nextIndex); // Same reference
        });

        it("rebuilds index when items change", () => {
            const { result, rerender } = renderHook(
                (props) =>
                    useObservationWorkflow({
                        config: props.config,
                        entries: props.entries,
                        updateEntry: props.updateEntry,
                    }),
                {
                    initialProps: {
                        config: mockConfig,
                        entries: mockEntries,
                        updateEntry: mockUpdateEntry,
                    },
                },
            );

            const initialIndex = result.current.observationIndex;

            // Change observation data
            const newObservation: RecognitionObservationRecord = {
                observationId: "obs-new",
                label: "New Person",
                entityType: "person",
                confidence: 0.8,
                status: "needs_review",
                candidates: [],
                roster: null,
                area: 0.18,
                boundingBox: [10, 10, 100, 100],
                source: null,
                match: {
                    isMatch: false,
                    similarity: 0.8,
                    confidence: 0.8,
                    threshold: 0.85,
                },
            };

            const newAttachment: RecognitionObservationAttachment = {
                attachmentId: 999,
                jobId: "job-999",
                updatedAt: Date.now(),
                status: "needs_review",
                summary: { total: 1, matched: 0, needs_review: 1 },
                observations: [newObservation],
                context: {},
                confidenceScore: 0.8,
                sourceRemoteId: null,
            };

            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: {
                            items: [newAttachment],
                            summary: mockObservationData.summary,
                        } as any,
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            rerender({
                config: mockConfig,
                entries: mockEntries,
                updateEntry: mockUpdateEntry,
            });

            const nextIndex = result.current.observationIndex;

            expect(initialIndex).not.toBe(nextIndex); // Different reference
            expect(nextIndex.has("obs-new")).toBe(true);
            expect(nextIndex.has("obs-123")).toBe(false);
        });
    });
});
