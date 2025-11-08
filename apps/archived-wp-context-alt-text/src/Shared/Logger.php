<?php

declare(strict_types=1);

namespace ContextAltText\Shared;

/**
 * Simple logger with timestamps for debugging
 */
final class Logger
{
    private static bool $enabled = true;
    private static string $logFile = '';

    /**
     * Enable/disable logging
     */
    public static function setEnabled(bool $enabled): void
    {
        self::$enabled = $enabled;
    }

    /**
     * Set log file path (optional - will use error_log if not set)
     */
    public static function setLogFile(string $path): void
    {
        self::$logFile = $path;
    }

    /**
     * Log a debug message
     */
    public static function debug(string $message, array $context = []): void
    {
        self::log('DEBUG', $message, $context);
    }

    /**
     * Log an info message
     */
    public static function info(string $message, array $context = []): void
    {
        self::log('INFO', $message, $context);
    }

    /**
     * Log a warning message
     */
    public static function warn(string $message, array $context = []): void
    {
        self::log('WARN', $message, $context);
    }

    /**
     * Log an error message
     */
    public static function error(string $message, array $context = []): void
    {
        self::log('ERROR', $message, $context);
    }

    /**
     * Internal log method
     */
    private static function log(string $level, string $message, array $context): void
    {
        if (!self::$enabled) {
            return;
        }

        $timestamp = gmdate('Y-m-d H:i:s.v');
        $contextStr = empty($context) ? '' : ' ' . wp_json_encode($context, JSON_UNESCAPED_SLASHES);
        $logMessage = sprintf('[%s] [%s] [CAT] %s%s', $timestamp, $level, $message, $contextStr);

        if (self::$logFile !== '' && is_writable(dirname(self::$logFile))) {
            // phpcs:ignore WordPress.PHP.DevelopmentFunctions.error_log_error_log
            error_log($logMessage . PHP_EOL, 3, self::$logFile);
        } else {
            // phpcs:ignore WordPress.PHP.DevelopmentFunctions.error_log_error_log
            error_log($logMessage);
        }
    }
}
