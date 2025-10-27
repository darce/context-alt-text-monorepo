import { http, HttpResponse } from "msw";

/**
 * MSW handler for the recognition scan endpoint.
 */
export const recognitionScanHandler = http.post(
    "https://example.com/wp-json/cat/v1/recognition/scan",
    async ({ request }) => {
        const body = await request.json();
        const attachmentIds: number[] = Array.isArray(body?.attachment_ids) ? body.attachment_ids : [];

        return HttpResponse.json({
            job_id: "scan-mock-job",
            queued_count: attachmentIds.length,
            priority: body?.priority ?? "normal",
        });
    },
);

/**
 * MSW handler for the unknown clusters listing endpoint.
 */
export const unknownClustersHandler = http.get("/wp-json/cat/v1/clusters", () =>
    HttpResponse.json({
        clusters: [
            {
                id: "cluster-alpha",
                face_count: 3,
                sample_face: {
                    attachment_id: 123,
                    thumbnail_url: "http://example.test/uploads/cat-face-crops/123-alpha.jpg",
                    bbox: { x: 12, y: 18, width: 120, height: 140 },
                },
                suggestion: {
                    roster_id: "person-123",
                    display_name: "Ellyn",
                    confidence: 0.91,
                    reason: "High cosine similarity",
                },
                created_at: "2025-01-01T12:00:00Z",
                updated_at: "2025-01-02T18:00:00Z",
            },
        ],
        total: 1,
        page: 1,
        per_page: 20,
    }),
);

export const clusterSuggestionsHandler = http.get("/wp-json/cat/v1/clusters/:clusterId/suggestions", ({ params }) => {
    const clusterId = typeof params.clusterId === "string" ? params.clusterId : "cluster-alpha";

    return HttpResponse.json({
        cluster_id: clusterId,
        suggestions: [
            {
                cluster_id: clusterId,
                roster_id: "person-123",
                display_name: "Ellyn",
                confidence: 0.94,
                confidence_level: "high",
                match_count: 3,
                face_ids: ["face-1", "face-2", "face-3"],
                reason: "3 faces matched (best 94%, avg 91%)",
            },
            {
                cluster_id: clusterId,
                roster_id: "person-999",
                display_name: "Daniel",
                confidence: 0.82,
                confidence_level: "medium",
                match_count: 1,
                face_ids: ["face-2"],
                reason: "Best match at 82% similarity",
            },
        ],
    });
});
