export const handleJsonResponse = async (response: Response): Promise<unknown> => {
    if (response.status === 204) {
        return {};
    }

    const contentType = response.headers.get("Content-Type");

    if (contentType?.includes("application/json")) {
        return response.json();
    }

    const text = await response.text();

    try {
        return JSON.parse(text);
    } catch {
        return {};
    }
};

export const ensureOk = async (response: Response): Promise<Response> => {
    if (!response.ok) {
        const data = await handleJsonResponse(response);
        const message =
            typeof data === "object" && data !== null && "message" in data &&
            typeof (data as { message: unknown }).message === "string"
                ? String((data as { message: string }).message)
                : `Request failed with status ${response.status}`;

        const errorWithData = Object.assign(new Error(message), { data });
        throw errorWithData;
    }

    return response;
};
