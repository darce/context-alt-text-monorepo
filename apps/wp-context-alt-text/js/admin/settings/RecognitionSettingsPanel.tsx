import React from "react";
import { __, sprintf } from "@wordpress/i18n";

import { dispatchNotice, notifyError } from "@/admin/notices";
import type { FeatureFlags, RecognitionSettingsPayload } from "@/admin/types";
import { FALLBACK_RECOGNITION_SETTINGS } from "@/admin/dashboardData";
import { VALIDATION } from "@/admin/constants/validation";
import { Checkbox } from "@/components/ui/checkbox";

const sanitizeUrl = (value: string): string => value.trim();

const isValidUrl = (value: string): boolean => {
    const trimmed = value.trim();

    if (trimmed === "") {
        return true;
    }

    if (!VALIDATION.URL.PATTERN.test(trimmed)) {
        return false;
    }

    try {
        new URL(trimmed);
        return true;
    } catch {
        return false;
    }
};

const clampTimeout = (value: number): number => {
    if (!Number.isFinite(value) || value <= 0) {
        return VALIDATION.TIMEOUT_MS.DEFAULT;
    }

    return Math.min(VALIDATION.TIMEOUT_MS.MAX, Math.max(VALIDATION.TIMEOUT_MS.MIN, Math.trunc(value)));
};

interface RecognitionSettingsPanelProps {
    initialSettings: RecognitionSettingsPayload;
    restNonce: string;
    saveEndpoint: string;
    testEndpoint: string;
    canManage: boolean;
    featureFlags: FeatureFlags;
}

interface FieldErrors {
    baseUrl: string | null;
    timeoutMs: string | null;
}

type TestResultState = {
    status: "success" | "error";
    message: string;
    timestamp: number;
} | null;

interface SaveResponse {
    settings?: RecognitionSettingsPayload;
    featureFlags?: FeatureFlags;
    message?: string;
}

const initialErrors: FieldErrors = {
    baseUrl: null,
    timeoutMs: null,
};

export const RecognitionSettingsPanel = ({
    initialSettings,
    restNonce,
    saveEndpoint,
    testEndpoint,
    canManage,
    featureFlags,
}: RecognitionSettingsPanelProps): React.JSX.Element => {
    const initialRef = React.useRef<RecognitionSettingsPayload>(initialSettings);
    const [form, setForm] = React.useState<RecognitionSettingsPayload>(initialSettings);
    const [errors, setErrors] = React.useState<FieldErrors>(initialErrors);
    const [isSaving, setIsSaving] = React.useState(false);
    const [isTesting, setIsTesting] = React.useState(false);
    const [lastTestResult, setLastTestResult] = React.useState<TestResultState>(null);
    const [flags, setFlags] = React.useState<FeatureFlags>(featureFlags);

    const runValidation = React.useCallback((state: RecognitionSettingsPayload): FieldErrors => {
        const nextErrors: FieldErrors = { ...initialErrors };

        if (state.baseUrl.trim() !== "" && !isValidUrl(state.baseUrl)) {
            nextErrors.baseUrl = __("Enter a valid HTTPS URL.", "context-alt-text");
        }

        const timeout = clampTimeout(Number(state.timeoutMs));
        if (timeout !== state.timeoutMs) {
            nextErrors.timeoutMs = sprintf(
                __("Timeout must be between %1$d ms and %2$d ms.", "context-alt-text"),
                1_000,
                120_000,
            );
        }

        return nextErrors;
    }, []);

    const hasChanges = React.useMemo(() => {
        const initial = initialRef.current;
        return (
            initial.baseUrl !== form.baseUrl ||
            initial.apiKey !== form.apiKey ||
            initial.timeoutMs !== form.timeoutMs ||
            initial.modelProfile !== form.modelProfile ||
            initial.enabled !== form.enabled
        );
    }, [form]);

    const handleFieldChange = React.useCallback(
        <K extends keyof RecognitionSettingsPayload>(key: K, value: RecognitionSettingsPayload[K]) => {
            setForm((current) => {
                const nextState: RecognitionSettingsPayload = {
                    ...current,
                    [key]: key === "timeoutMs" && typeof value === "number" ? clampTimeout(value) : value,
                } as RecognitionSettingsPayload;

                if (key === "baseUrl" || key === "timeoutMs") {
                    setErrors(runValidation(nextState));
                }

                return nextState;
            });
        },
        [runValidation],
    );

    const handleSubmit = React.useCallback(
        (event: React.FormEvent<HTMLFormElement>) => {
            event.preventDefault();

            if (!canManage || !saveEndpoint) {
                notifyError(__("You do not have permission to update settings.", "context-alt-text"));
                return;
            }

            const validation = runValidation(form);
            if (validation.baseUrl || validation.timeoutMs) {
                setErrors(validation);
                notifyError(__("Please resolve validation errors before saving.", "context-alt-text"));
                return;
            }

            setIsSaving(true);
            setErrors(initialErrors);

            const persist = async () => {
                try {
                    const response = await fetch(saveEndpoint, {
                        method: "POST",
                        credentials: "same-origin",
                        headers: {
                            "Content-Type": "application/json",
                            Accept: "application/json",
                            ...(restNonce ? { "X-WP-Nonce": restNonce } : {}),
                        },
                        body: JSON.stringify({
                            baseUrl: sanitizeUrl(form.baseUrl),
                            apiKey: form.apiKey.trim(),
                            timeoutMs: clampTimeout(form.timeoutMs),
                            modelProfile: form.modelProfile.trim(),
                            enabled: form.enabled,
                        }),
                    });

                    const payload = (await response.json().catch(() => ({}))) as SaveResponse & { message?: string };

                    if (!response.ok) {
                        throw new Error(payload?.message ?? __("Unable to save settings.", "context-alt-text"));
                    }

                    const nextSettings = payload.settings ?? form;

                    initialRef.current = nextSettings;
                    setForm(nextSettings);
                    setFlags(payload.featureFlags ?? flags);

                    dispatchNotice(
                        "success",
                        payload.message ?? __("Recognition settings updated.", "context-alt-text"),
                        {
                            id: "cat-recognition-settings-saved",
                            spokenMessage: __("Recognition settings updated successfully.", "context-alt-text"),
                        },
                    );
                } catch (error) {
                    const message =
                        error instanceof Error
                            ? error.message
                            : __("An unexpected error occurred.", "context-alt-text");
                    notifyError(message, { id: "cat-recognition-settings-error" });
                } finally {
                    setIsSaving(false);
                }
            };

            void persist();
        },
        [canManage, saveEndpoint, restNonce, form, runValidation, flags],
    );

    const handleTestConnection = React.useCallback(() => {
        if (!testEndpoint) {
            notifyError(__("Test endpoint is not available.", "context-alt-text"));
            return;
        }

        if (form.baseUrl.trim() === "") {
            setErrors((current) => ({
                ...current,
                baseUrl: __("Provide a base URL before testing the connection.", "context-alt-text"),
            }));
            notifyError(__("Enter a service URL before running the test.", "context-alt-text"));
            return;
        }

        if (!isValidUrl(form.baseUrl)) {
            setErrors((current) => ({
                ...current,
                baseUrl: __("Enter a valid HTTPS URL before testing.", "context-alt-text"),
            }));
            notifyError(__("Fix validation issues before testing.", "context-alt-text"));
            return;
        }

        setIsTesting(true);
        setLastTestResult(null);

        const runTest = async () => {
            try {
                const response = await fetch(testEndpoint, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Content-Type": "application/json",
                        Accept: "application/json",
                        ...(restNonce ? { "X-WP-Nonce": restNonce } : {}),
                    },
                    body: JSON.stringify({}),
                });

                const payload = (await response.json().catch(() => ({}))) as { status?: string; message?: string };

                if (!response.ok) {
                    throw new Error(
                        payload?.message ?? __("Recognition service did not respond successfully.", "context-alt-text"),
                    );
                }

                const statusText = payload.status ?? "ok";

                setLastTestResult({
                    status: "success",
                    message: sprintf(__("Recognition service is reachable (%s).", "context-alt-text"), statusText),
                    timestamp: Date.now(),
                });

                dispatchNotice("success", __("Recognition service is reachable.", "context-alt-text"), {
                    id: "cat-recognition-test-success",
                });
            } catch (error) {
                const message =
                    error instanceof Error ? error.message : __("Recognition service test failed.", "context-alt-text");
                setLastTestResult({
                    status: "error",
                    message,
                    timestamp: Date.now(),
                });
                notifyError(message, { id: "cat-recognition-test-error" });
            } finally {
                setIsTesting(false);
            }
        };

        void runTest();
    }, [testEndpoint, restNonce, form.baseUrl]);

    return (
        <div className="cat-recognition-settings">
            <header className="cat-recognition-settings__header">
                <h2>{__("Recognition Service", "context-alt-text")}</h2>
                <p>
                    {__(
                        "Configure how Context Alt Text connects to the external recognition service.",
                        "context-alt-text",
                    )}
                </p>
            </header>

            <section className="cat-recognition-settings__status">
                <strong>{__("Integration status", "context-alt-text")}</strong>
                <ul>
                    <li>
                        {sprintf(
                            __("Recognition mode: %s", "context-alt-text"),
                            form.enabled ? __("Enabled", "context-alt-text") : __("Disabled", "context-alt-text"),
                        )}
                    </li>
                    <li>
                        {sprintf(
                            __("Workbench recognition surface: %s", "context-alt-text"),
                            flags.workbenchRecognition
                                ? __("Active", "context-alt-text")
                                : __("Inactive", "context-alt-text"),
                        )}
                    </li>
                    <li>
                        {sprintf(
                            __("Roster UI: %s", "context-alt-text"),
                            flags.rosterEnabled ? __("Active", "context-alt-text") : __("Inactive", "context-alt-text"),
                        )}
                    </li>
                </ul>
            </section>

            {!canManage && (
                <div className="notice notice-warning inline" role="alert">
                    <p>{__("You do not have permission to modify recognition settings.", "context-alt-text")}</p>
                </div>
            )}

            <form className="cat-recognition-settings__form" onSubmit={handleSubmit}>
                <table className="form-table" role="presentation">
                    <tbody>
                        <tr>
                            <th scope="row">
                                <label htmlFor="cat-recognition-enabled">
                                    {__("Enable recognition integration", "context-alt-text")}
                                </label>
                            </th>
                            <td>
                                <label className="cat-recognition-settings__toggle">
                                    <Checkbox
                                        id="cat-recognition-enabled"
                                        checked={form.enabled}
                                        onCheckedChange={(checked) => handleFieldChange("enabled", checked === true)}
                                        disabled={!canManage || isSaving}
                                    />
                                    <span>
                                        {__(
                                            "Enable to expose recognition-powered workflows in the admin UI.",
                                            "context-alt-text",
                                        )}
                                    </span>
                                </label>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row">
                                <label htmlFor="cat-recognition-base-url">
                                    {__("Service base URL", "context-alt-text")}
                                </label>
                            </th>
                            <td>
                                <input
                                    id="cat-recognition-base-url"
                                    type="url"
                                    className="regular-text code"
                                    value={form.baseUrl}
                                    onChange={(event) => handleFieldChange("baseUrl", event.target.value)}
                                    onBlur={() => setErrors(runValidation(form))}
                                    placeholder="https://recognition.example/api"
                                    disabled={!canManage || isSaving}
                                />
                                <p className="description">
                                    {__(
                                        "All API requests will be issued relative to this base URL.",
                                        "context-alt-text",
                                    )}
                                </p>
                                {errors.baseUrl && (
                                    <p className="cat-recognition-settings__error" role="alert">
                                        {errors.baseUrl}
                                    </p>
                                )}
                            </td>
                        </tr>
                        <tr>
                            <th scope="row">
                                <label htmlFor="cat-recognition-api-key">{__("API key", "context-alt-text")}</label>
                            </th>
                            <td>
                                <input
                                    id="cat-recognition-api-key"
                                    type="password"
                                    className="regular-text"
                                    value={form.apiKey}
                                    onChange={(event) => handleFieldChange("apiKey", event.target.value)}
                                    disabled={!canManage || isSaving}
                                />
                                <p className="description">
                                    {__(
                                        "Optional bearer token sent with each recognition request.",
                                        "context-alt-text",
                                    )}
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row">
                                <label htmlFor="cat-recognition-model-profile">
                                    {__("Model profile", "context-alt-text")}
                                </label>
                            </th>
                            <td>
                                <input
                                    id="cat-recognition-model-profile"
                                    type="text"
                                    className="regular-text"
                                    value={form.modelProfile}
                                    onChange={(event) => handleFieldChange("modelProfile", event.target.value)}
                                    disabled={!canManage || isSaving}
                                />
                                <p className="description">
                                    {__(
                                        "Specify a target model/profile identifier when supported by the service.",
                                        "context-alt-text",
                                    )}
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row">
                                <label htmlFor="cat-recognition-timeout">
                                    {__("Request timeout (ms)", "context-alt-text")}
                                </label>
                            </th>
                            <td>
                                <input
                                    id="cat-recognition-timeout"
                                    type="number"
                                    className="small-text"
                                    min={1_000}
                                    max={120_000}
                                    step={500}
                                    value={form.timeoutMs}
                                    onChange={(event) => handleFieldChange("timeoutMs", Number(event.target.value))}
                                    onBlur={() => setErrors(runValidation(form))}
                                    disabled={!canManage || isSaving}
                                />
                                <p className="description">
                                    {__(
                                        "Maximum duration to wait for responses before aborting the request.",
                                        "context-alt-text",
                                    )}
                                </p>
                                {errors.timeoutMs && (
                                    <p className="cat-recognition-settings__error" role="alert">
                                        {errors.timeoutMs}
                                    </p>
                                )}
                            </td>
                        </tr>
                    </tbody>
                </table>

                <div className="cat-recognition-settings__actions">
                    <button
                        type="submit"
                        className="button button-primary"
                        disabled={!canManage || isSaving || !hasChanges || !saveEndpoint}
                    >
                        {isSaving ? __("Saving…", "context-alt-text") : __("Save changes", "context-alt-text")}
                    </button>
                    <button
                        type="button"
                        className="button"
                        onClick={handleTestConnection}
                        disabled={isSaving || isTesting || !canManage || !testEndpoint}
                    >
                        {isTesting ? __("Testing…", "context-alt-text") : __("Test connection", "context-alt-text")}
                    </button>
                    {isTesting && <span className="spinner is-active" aria-hidden="true" />}
                </div>
            </form>

            {lastTestResult && (
                <div
                    className={`notice ${lastTestResult.status === "success" ? "notice-success" : "notice-error"} inline`}
                    role="status"
                    aria-live="polite"
                >
                    <p>{lastTestResult.message}</p>
                </div>
            )}
        </div>
    );
};
