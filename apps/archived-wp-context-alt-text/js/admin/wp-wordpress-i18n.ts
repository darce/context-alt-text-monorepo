type I18nExports = typeof import("@wordpress/i18n");

type GlobalWithWP = typeof globalThis & {
    wp?: {
        i18n?: unknown;
    };
};

const resolveWordPressI18n = (): I18nExports => {
    const globalRef = globalThis as GlobalWithWP;
    const candidate = globalRef.wp?.i18n;

    if (candidate && typeof candidate === "object") {
        return candidate as I18nExports;
    }

    throw new Error(
        "WordPress i18n runtime is unavailable. Ensure the wp-i18n script is enqueued before the Context Alt Text bundle.",
    );
};

const runtime = resolveWordPressI18n();

export default runtime;
export const {
    __,
    _x,
    _n,
    _nx,
    sprintf,
    isRTL,
    setLocaleData,
    getLocaleData,
    resetLocaleData,
    defaultI18n,
    hasTranslation,
    subscribe,
} = runtime;
