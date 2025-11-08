/**
 * AvatarPicker Component
 *
 * Provides an interface for selecting roster avatar images from the WordPress Media Library.
 * Supports image selection, preview, and removal with fallback placeholder display.
 */

import * as React from "react";
import { __, sprintf } from "@wordpress/i18n";
import { getWpMedia } from "../../admin/media";
import { notifyError } from "@/admin/notices";
import type { MediaFrame } from "../../admin/media";
import { isRecord } from "../../admin/type-utils";
import { Avatar, AvatarImage, AvatarFallback } from "../ui/avatar";

interface AvatarPickerProps {
    avatarUrl: string;
    avatarId: number | null;
    fallbackLabel: string;
    onChange: (selection: { avatarUrl: string; avatarId: number | null }) => void;
    disabled: boolean;
}

/**
 * AvatarPicker allows users to select an avatar image from the WordPress Media Library.
 * Displays a preview of the selected image or a fallback placeholder with the first letter
 * of the fallbackLabel.
 *
 * @param avatarUrl - The URL of the currently selected avatar image
 * @param avatarId - The WordPress attachment ID of the selected image
 * @param fallbackLabel - Label used to generate fallback placeholder initial
 * @param onChange - Callback fired when an image is selected or cleared
 * @param disabled - Whether the picker is disabled
 */
export const AvatarPicker = ({
    avatarUrl,
    avatarId,
    fallbackLabel,
    onChange,
    disabled,
}: AvatarPickerProps): React.JSX.Element => {
    const frameRef = React.useRef<MediaFrame | null>(null);

    const openMediaModal = React.useCallback(() => {
        if (disabled) {
            return;
        }

        const mediaFactory = getWpMedia();

        if (!mediaFactory) {
            notifyError(
                __("Media library is unavailable. Ensure WordPress media scripts are enqueued.", "context-alt-text"),
                { id: "cat-roster-media-unavailable" },
            );
            return;
        }

        frameRef.current ??= mediaFactory({
            title: __("Select roster avatar", "context-alt-text"),
            button: { text: __("Use image", "context-alt-text") },
            library: { type: "image" },
            multiple: false,
        });

        const frame = frameRef.current;
        if (!frame) {
            return;
        }

        const onSelect = () => {
            const selection = frame.state()?.get("selection") as
                | {
                      first?: () => { toJSON?: () => Record<string, unknown> };
                  }
                | undefined;

            const selected = selection?.first?.();
            const attachment = selected && typeof selected.toJSON === "function" ? selected.toJSON() : selected;

            if (!isRecord(attachment)) {
                return;
            }

            const getString = (candidate: unknown): string | null =>
                typeof candidate === "string" && candidate.trim() !== "" ? candidate : null;

            const getSizeUrl = (sizes: unknown): string | null => {
                if (!sizes || typeof sizes !== "object") {
                    return null;
                }

                const map = sizes as Record<string, unknown>;

                for (const key of ["medium", "medium_large", "large", "full", "thumbnail"]) {
                    const sizeCandidate = map[key];
                    if (!sizeCandidate || typeof sizeCandidate !== "object") {
                        continue;
                    }

                    const url = getString((sizeCandidate as Record<string, unknown>).url);
                    if (url) {
                        return url;
                    }
                }

                return null;
            };

            const resolvedUrl =
                getSizeUrl((attachment as { sizes?: unknown }).sizes) ??
                getString((attachment as { url?: unknown }).url) ??
                getString((attachment as { source_url?: unknown }).source_url);

            const rawId = (attachment as { id?: unknown }).id;
            const parsedId = typeof rawId === "number" ? rawId : typeof rawId === "string" ? Number(rawId) : NaN;

            if (!resolvedUrl) {
                notifyError(__("Selected image is missing a URL.", "context-alt-text"), {
                    id: "cat-roster-media-missing-url",
                });
                return;
            }

            onChange({
                avatarUrl: resolvedUrl,
                avatarId: Number.isFinite(parsedId) && parsedId > 0 ? parsedId : null,
            });
        };

        frame.off?.("select");
        frame.on("select", onSelect);
        frame.open();
    }, [disabled, onChange]);

    const handleClear = React.useCallback(() => {
        if (disabled) {
            return;
        }

        onChange({ avatarUrl: "", avatarId: null });
    }, [disabled, onChange]);

    const fallbackInitial = (() => {
        const first = fallbackLabel.trim().charAt(0).toUpperCase();
        return first !== "" ? first : "?";
    })();

    return (
        <div className="cat-roster__avatar-field">
            <span className="cat-roster__avatar-label">{__("Avatar", "context-alt-text")}</span>
            <div className="cat-roster__avatar-selector">
                <Avatar className="cat-roster__avatar cat-roster__avatar--preview">
                    <AvatarImage src={avatarUrl} alt={__("Selected avatar preview", "context-alt-text")} />
                    <AvatarFallback delayMs={200}>{fallbackInitial}</AvatarFallback>
                </Avatar>
                <div className="cat-roster__avatar-actions">
                    <button
                        type="button"
                        className="cat-button cat-button--subtle"
                        onClick={openMediaModal}
                        disabled={disabled}
                    >
                        {avatarUrl ? __("Replace image", "context-alt-text") : __("Select image", "context-alt-text")}
                    </button>
                    {avatarUrl && (
                        <button
                            type="button"
                            className="cat-button cat-button--link"
                            onClick={handleClear}
                            disabled={disabled}
                        >
                            {__("Remove", "context-alt-text")}
                        </button>
                    )}
                    {avatarId && (
                        <span className="cat-roster__avatar-meta">
                            {sprintf(__("Attachment ID: %d", "context-alt-text"), avatarId)}
                        </span>
                    )}
                </div>
            </div>
        </div>
    );
};
