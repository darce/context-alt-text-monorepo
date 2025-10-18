/**
 * Logger utility with timestamps for frontend debugging
 */

const formatTimestamp = (): string => {
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, "0");
    const minutes = String(now.getMinutes()).padStart(2, "0");
    const seconds = String(now.getSeconds()).padStart(2, "0");
    const ms = String(now.getMilliseconds()).padStart(3, "0");
    return `${hours}:${minutes}:${seconds}.${ms}`;
};

const createLogger = (prefix: string) => ({
    log: (...args: unknown[]) => {
        console.log(`[${formatTimestamp()}] [${prefix}]`, ...args);
    },
    info: (...args: unknown[]) => {
        console.info(`[${formatTimestamp()}] [${prefix}]`, ...args);
    },
    warn: (...args: unknown[]) => {
        console.warn(`[${formatTimestamp()}] [${prefix}]`, ...args);
    },
    error: (...args: unknown[]) => {
        console.error(`[${formatTimestamp()}] [${prefix}]`, ...args);
    },
    debug: (...args: unknown[]) => {
        if (process.env.NODE_ENV === "development") {
            console.debug(`[${formatTimestamp()}] [${prefix}]`, ...args);
        }
    },
});

export const logger = createLogger("Context Alt Text");
export default logger;
