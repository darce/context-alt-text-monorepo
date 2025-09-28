<?php

declare(strict_types=1);

namespace ContextAltText\Support;

final class Env
{
    /**
     * Load simple KEY=VALUE pairs from a .env file into $_ENV / getenv.
     */
    public static function load(string $filePath): void
    {
        if (!is_readable($filePath)) {
            return;
        }

        $lines = file($filePath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        if ($lines === false) {
            return;
        }

        foreach ($lines as $line) {
            $line = trim($line);
            if ($line === '' || str_starts_with($line, '#')) {
                continue;
            }

            $parts = explode('=', $line, 2);
            if (count($parts) !== 2) {
                continue;
            }

            [$name, $value] = $parts;
            $name = trim($name);
            $value = trim($value);

            if ($value !== '') {
                $value = self::stripQuotes($value);
            }

            if ($name === '' || getenv($name) !== false) {
                continue;
            }

            $_ENV[$name] = $value;
            putenv(sprintf('%s=%s', $name, $value));
        }
    }

    private static function stripQuotes(string $value): string
    {
        if (
            (str_starts_with($value, '"') && str_ends_with($value, '"')) ||
            (str_starts_with($value, "'") && str_ends_with($value, "'"))
        ) {
            return substr($value, 1, -1);
        }

        return $value;
    }
}
