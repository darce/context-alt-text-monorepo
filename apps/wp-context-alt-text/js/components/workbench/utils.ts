export const formatWorkbenchDate = (iso?: string): string | null => {
    if (!iso) {
        return null;
    }

    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) {
        return null;
    }

    try {
        return new Intl.DateTimeFormat(undefined, {
            dateStyle: "medium",
            timeStyle: "short",
        }).format(date);
    } catch (error) {
        console.warn("[Context Alt Text] Failed to format date", error);
        return date.toISOString();
    }
};
