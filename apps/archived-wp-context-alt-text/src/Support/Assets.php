<?php

declare(strict_types=1);

namespace ContextAltText\Support;

final class Assets
{
    private static ?array $manifest = null;

    public static function getEntry(string $entry): ?array
    {
        self::loadManifest();

        return self::$manifest[$entry] ?? null;
    }

    public static function assetUrl(string $relativePath): string
    {
        $base = trailingslashit(CONTEXT_ALT_TEXT_PLUGIN_URL . 'public/assets/dist');

        return $base . ltrim($relativePath, '/');
    }

    private static function loadManifest(): void
    {
        if (self::$manifest !== null) {
            return;
        }

        $manifestPath = CONTEXT_ALT_TEXT_PLUGIN_DIR . 'public/assets/dist/.vite/manifest.json';

        if (!is_readable($manifestPath)) {
            self::$manifest = [];
            return;
        }

        $contents = file_get_contents($manifestPath);
        if ($contents === false) {
            self::$manifest = [];
            return;
        }

        $data = json_decode($contents, true);
        self::$manifest = is_array($data) ? $data : [];
    }
}
