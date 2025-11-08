/**
 * RosterEditor component
 *
 * Form for creating and editing roster entries, with support for observation resolution.
 */

import React from "react";
import { __ } from "@wordpress/i18n";

import type { RosterEntry, RecognitionObservationRecord, RecognitionObservationAttachment } from "@/admin/types";
import type { RosterFormValues } from "@/admin/hooks/useRoster";
import { StatusBadge } from "./StatusBadge";
import { AvatarPicker } from "./AvatarPicker";
import { Form, FormField, FormLabel, FormControl, FormMessage, FormSubmit } from "@/components/ui/form";
import {
    getTopCandidate,
    getRosterConfidenceValue,
    getDetectionConfidenceValue,
    formatPercentage,
} from "@/admin/utils/rosterHelpers";

// ==================== Types ====================

interface ObservationPromptState {
    observationId: string;
    attachmentId: number | null;
    source: string | null;
    remoteId?: string | null;
    label?: string | null;
}

// ==================== Types ====================

interface RosterEditorDraft {
    label?: string;
    type?: string;
    avatarUrl?: string | null;
    avatarId?: number | null;
}

interface RosterEditorProps {
    entry: RosterEntry | null;
    draftValues: RosterEditorDraft | null;
    observationPrompt: ObservationPromptState | null;
    observationDetails?: { record: RecognitionObservationRecord; attachment: RecognitionObservationAttachment } | null;
    onSubmit: (values: RosterFormValues) => Promise<void>;
    submitting: boolean;
}

// ==================== Component ====================

export const RosterEditor = ({
    entry,
    draftValues,
    observationPrompt,
    observationDetails = null,
    onSubmit,
    submitting,
}: RosterEditorProps): React.JSX.Element => {
    const observationRecord = observationDetails?.record ?? null;
    const observationAttachment = observationDetails?.attachment ?? null;

    const initialLabel = entry?.label ?? draftValues?.label ?? observationRecord?.label ?? "";
    const initialType = entry?.type ?? draftValues?.type ?? observationRecord?.entityType ?? "";
    const initialAvatarUrl =
        entry?.avatarUrl ?? draftValues?.avatarUrl ?? observationAttachment?.context?.imageUrl ?? "";
    const initialAvatarId = entry?.avatarId ?? draftValues?.avatarId ?? null;

    const [label, setLabel] = React.useState<string>(initialLabel);
    const [type, setType] = React.useState<string>(initialType);
    const [avatarUrl, setAvatarUrl] = React.useState<string>(initialAvatarUrl);
    const [avatarId, setAvatarId] = React.useState<number | null>(initialAvatarId);
    const topCandidate = observationRecord ? getTopCandidate(observationRecord) : null;

    React.useEffect(() => {
        const nextLabel = entry?.label ?? draftValues?.label ?? observationRecord?.label ?? "";
        const nextType = entry?.type ?? draftValues?.type ?? observationRecord?.entityType ?? "";
        const nextAvatarUrl =
            entry?.avatarUrl ?? draftValues?.avatarUrl ?? observationAttachment?.context?.imageUrl ?? "";
        const nextAvatarId = entry?.avatarId ?? draftValues?.avatarId ?? null;

        setLabel(nextLabel);
        setType(nextType);
        setAvatarUrl(nextAvatarUrl);
        setAvatarId(nextAvatarId);
    }, [
        entry?.remoteId,
        entry?.label,
        entry?.type,
        entry?.avatarUrl,
        entry?.avatarId,
        draftValues?.label,
        draftValues?.type,
        draftValues?.avatarUrl,
        draftValues?.avatarId,
        observationRecord?.label,
        observationRecord?.entityType,
        observationAttachment?.context?.imageUrl,
    ]);

    const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const trimmedAvatarUrl = avatarUrl.trim();
        const normalizedAvatarId = trimmedAvatarUrl ? (avatarId ?? null) : (avatarId ?? null);
        const trimmedLabel = label.trim();
        const trimmedType = type.trim();

        let resolveObservation: RosterFormValues["resolveObservation"] | undefined;
        let referenceImages: RosterFormValues["referenceImages"] | undefined;

        if (observationPrompt?.observationId && (observationPrompt.attachmentId ?? 0) > 0) {
            resolveObservation = {
                attachmentId: observationPrompt.attachmentId ?? 0,
                observationId: observationPrompt.observationId,
                status: "matched",
                label: trimmedLabel,
                entityType: trimmedType,
            };
        }

        if (observationRecord && observationAttachment) {
            const rosterConfidenceValue = getRosterConfidenceValue(observationRecord, topCandidate);
            const detectionConfidenceValue = getDetectionConfidenceValue(observationRecord);
            const referenceMetadata: Record<string, unknown> = {
                source: "recognition",
                area: observationRecord.area,
            };

            if (rosterConfidenceValue !== null) {
                referenceMetadata.confidence = rosterConfidenceValue;
            }

            if (detectionConfidenceValue !== null) {
                referenceMetadata.detectionConfidence = detectionConfidenceValue;
            }

            if (observationRecord.match) {
                const { similarity, threshold, confidence } = observationRecord.match;
                if (similarity) {
                    referenceMetadata.similarity = similarity;
                }
                if (threshold) {
                    referenceMetadata.threshold = threshold;
                }
                if (confidence) {
                    referenceMetadata.matchConfidence = confidence;
                } else if (rosterConfidenceValue !== null) {
                    referenceMetadata.matchConfidence = rosterConfidenceValue;
                }
            } else if (rosterConfidenceValue !== null) {
                referenceMetadata.matchConfidence = rosterConfidenceValue;
            }

            if (observationRecord.observationId) {
                referenceMetadata.observationId = observationRecord.observationId;
            }

            if (observationRecord.entityType) {
                referenceMetadata.entityType = observationRecord.entityType;
            }

            if (trimmedLabel) {
                referenceMetadata.label = trimmedLabel;
            }

            Object.keys(referenceMetadata).forEach((key) => {
                if (referenceMetadata[key] === undefined || referenceMetadata[key] === null) {
                    delete referenceMetadata[key];
                }
            });

            const boundingBox = observationRecord.boundingBox?.length ? observationRecord.boundingBox : null;

            referenceImages = [
                {
                    attachmentId: observationAttachment.attachmentId ?? null,
                    imageUrl: observationAttachment.context?.imageUrl ?? null,
                    observationId: observationRecord.observationId ?? null,
                    boundingBox,
                    metadata: referenceMetadata,
                },
            ];
        }

        void onSubmit({
            remoteId: entry?.remoteId ?? null,
            label: trimmedLabel,
            type: trimmedType,
            avatarUrl: trimmedAvatarUrl ? trimmedAvatarUrl : null,
            avatarId: normalizedAvatarId,
            ...(resolveObservation ? { resolveObservation } : {}),
            ...(referenceImages ? { referenceImages } : {}),
        });
    };

    const mode = entry?.remoteId ? __("Edit Entry", "context-alt-text") : __("Add Entry", "context-alt-text");
    const status: RosterEntry["status"] = entry?.status ?? "LOCAL";
    const remoteIdDisplay = entry?.remoteId ?? __("Not yet synced", "context-alt-text");
    const updatedDisplay = entry?.updatedAt
        ? new Date(entry.updatedAt).toLocaleString()
        : __("Pending first sync", "context-alt-text");
    const fallbackLabelValue =
        label.trim() !== ""
            ? label
            : draftValues?.label && draftValues.label.trim() !== ""
              ? draftValues.label
              : (entry?.label ?? observationRecord?.label ?? "");
    const matchConfidenceValue = observationRecord ? getRosterConfidenceValue(observationRecord, topCandidate) : null;
    const confidenceDisplay = formatPercentage(matchConfidenceValue);
    const similarityDisplay = observationRecord?.match ? formatPercentage(observationRecord.match.similarity) : null;
    const thresholdDisplay = observationRecord?.match ? formatPercentage(observationRecord.match.threshold) : null;
    const attachmentLabel = observationAttachment?.context?.filename ?? null;

    return (
        <aside className="cat-roster__editor">
            <h3>{mode}</h3>

            <div className="cat-roster__editor-status" role="status" aria-live="polite">
                <StatusBadge status={status} />
                <dl>
                    <div>
                        <dt>{__("Remote ID", "context-alt-text")}</dt>
                        <dd>{remoteIdDisplay}</dd>
                    </div>
                    <div>
                        <dt>{__("Last updated", "context-alt-text")}</dt>
                        <dd>{updatedDisplay}</dd>
                    </div>
                </dl>
            </div>

            <Form onSubmit={handleSubmit}>
                {observationPrompt && (
                    <div className="cat-roster__editor-context" role="status" aria-live="polite">
                        <strong>
                            {observationPrompt.remoteId
                                ? __(
                                      "Resolve the linked observation by confirming this roster entry.",
                                      "context-alt-text",
                                  )
                                : __("Saving this entry will resolve a recognition observation.", "context-alt-text")}
                        </strong>
                        <p>
                            {observationPrompt.remoteId
                                ? __(
                                      "Review the details and save to continue embedding processing.",
                                      "context-alt-text",
                                  )
                                : __(
                                      "Complete the fields below and save to begin embedding generation for the flagged observation.",
                                      "context-alt-text",
                                  )}
                        </p>
                        {observationRecord && (
                            <dl className="cat-roster__observation-details">
                                {attachmentLabel && (
                                    <div>
                                        <dt>{__("Attachment", "context-alt-text")}</dt>
                                        <dd>{attachmentLabel}</dd>
                                    </div>
                                )}
                                {observationAttachment?.attachmentId ? (
                                    <div>
                                        <dt>{__("Attachment ID", "context-alt-text")}</dt>
                                        <dd>{observationAttachment.attachmentId}</dd>
                                    </div>
                                ) : null}
                                {observationRecord.entityType && (
                                    <div>
                                        <dt>{__("Entity type", "context-alt-text")}</dt>
                                        <dd>{observationRecord.entityType}</dd>
                                    </div>
                                )}
                                {confidenceDisplay && (
                                    <div>
                                        <dt>{__("Match confidence", "context-alt-text")}</dt>
                                        <dd>{confidenceDisplay}</dd>
                                    </div>
                                )}
                                {similarityDisplay && (
                                    <div>
                                        <dt>{__("Match similarity", "context-alt-text")}</dt>
                                        <dd>{similarityDisplay}</dd>
                                    </div>
                                )}
                                {thresholdDisplay && (
                                    <div>
                                        <dt>{__("Match threshold", "context-alt-text")}</dt>
                                        <dd>{thresholdDisplay}</dd>
                                    </div>
                                )}
                            </dl>
                        )}
                    </div>
                )}
                <FormField name="label" className="cat-field">
                    <FormLabel htmlFor="cat-roster-label">{__("Label", "context-alt-text")}</FormLabel>
                    <FormControl asChild>
                        <input
                            id="cat-roster-label"
                            type="text"
                            required
                            value={label}
                            onChange={(event) => setLabel(event.target.value)}
                        />
                    </FormControl>
                    <FormMessage match="valueMissing">
                        {__("Please enter a label for this roster entry.", "context-alt-text")}
                    </FormMessage>
                </FormField>
                <FormField name="type" className="cat-field">
                    <FormLabel htmlFor="cat-roster-type">{__("Type", "context-alt-text")}</FormLabel>
                    <FormControl asChild>
                        <input
                            id="cat-roster-type"
                            type="text"
                            required
                            value={type}
                            onChange={(event) => setType(event.target.value)}
                        />
                    </FormControl>
                    <FormMessage match="valueMissing">
                        {__("Please enter a type for this roster entry.", "context-alt-text")}
                    </FormMessage>
                </FormField>

                <AvatarPicker
                    avatarUrl={avatarUrl}
                    avatarId={avatarId}
                    fallbackLabel={fallbackLabelValue}
                    onChange={({
                        avatarUrl: nextUrl,
                        avatarId: nextId,
                    }: {
                        avatarUrl: string;
                        avatarId: number | null;
                    }) => {
                        setAvatarUrl(nextUrl);
                        setAvatarId(nextId);
                    }}
                    disabled={submitting}
                />

                <FormField name="avatarUrl" className="cat-field">
                    <FormLabel htmlFor="cat-roster-avatar">{__("Avatar URL", "context-alt-text")}</FormLabel>
                    <FormControl asChild>
                        <input
                            id="cat-roster-avatar"
                            type="url"
                            value={avatarUrl}
                            placeholder="https://example.test/image.jpg"
                            onChange={(event) => {
                                setAvatarUrl(event.target.value);
                                setAvatarId(null);
                            }}
                        />
                    </FormControl>
                    <FormMessage match="typeMismatch">
                        {__("Please enter a valid URL.", "context-alt-text")}
                    </FormMessage>
                    <p className="description cat-field__description">
                        {__(
                            "Optional image URL used as a reference thumbnail and seed for embeddings.",
                            "context-alt-text",
                        )}
                    </p>
                </FormField>
                <div className="cat-roster__editor-actions">
                    <FormSubmit className="cat-button cat-button--primary" disabled={submitting}>
                        {submitting ? __("Saving…", "context-alt-text") : __("Save", "context-alt-text")}
                    </FormSubmit>
                </div>
            </Form>
        </aside>
    );
};
