<?php

declare(strict_types=1);

namespace ContextAltText\Shared\Config;

use ContextAltText\Shared\Utils\ValidationHelpers;

use function array_key_exists;
use function array_replace_recursive;
use function get_option;
use function is_array;
use function is_string;
use function trim;
use function update_option;

/**
 * Central store for persisted plugin settings.
 */
class SettingsRepository
{
    public const OPTION_KEY = 'cat_settings';
    private const DEFAULT_TIMEOUT_MS = 15000;

    /**
     * Retrieve the full settings payload.
     *
     * @return array<string,mixed>
     */
    public function getAll(): array
    {
        $stored = get_option(self::OPTION_KEY);

        if (!is_array($stored)) {
            $stored = [];
        }

        $normalized = $this->normalizePayload($stored);

        return $normalized;
    }

    /**
     * @return array{
     *     baseUrl: string,
     *     apiKey: string,
     *     timeoutMs: int,
     *     modelProfile: string,
     *     enabled: bool
     * }
     */
    public function getRecognitionSettings(): array
    {
        $settings = $this->getAll();
        $recognition = $settings['recognition'] ?? [];

        return [
            'baseUrl' => (string) ($recognition['baseUrl'] ?? ''),
            'apiKey' => (string) ($recognition['apiKey'] ?? ''),
            'timeoutMs' => (int) ($recognition['timeoutMs'] ?? self::DEFAULT_TIMEOUT_MS),
            'modelProfile' => (string) ($recognition['modelProfile'] ?? ''),
            'enabled' => (bool) ($recognition['enabled'] ?? false),
        ];
    }

    /**
     * Persist recognition settings and return the updated snapshot.
     *
     * @param array<string,mixed> $payload
     * @return array{
     *     baseUrl: string,
     *     apiKey: string,
     *     timeoutMs: int,
     *     modelProfile: string,
     *     enabled: bool
     * }
     */
    public function saveRecognitionSettings(array $payload): array
    {
        $current = $this->getAll();
        $next = $current;

        if (!isset($next['recognition']) || !is_array($next['recognition'])) {
            $next['recognition'] = [];
        }

        $next['recognition'] = $this->sanitizeRecognitionSettings($payload, $next['recognition']);

        $this->persist($next);

        return $this->getRecognitionSettings();
    }

    public function setRecognitionEnabled(bool $enabled): void
    {
        $current = $this->getAll();
        $next = $current;

        if (!isset($next['recognition']) || !is_array($next['recognition'])) {
            $next['recognition'] = [];
        }

        $next['recognition']['enabled'] = $enabled;

        $this->persist($next);
    }

    /**
     * Persist the provided payload.
     *
     * @param array<string,mixed> $payload
     */
    public function persist(array $payload): void
    {
        update_option(self::OPTION_KEY, $this->normalizePayload($payload));
    }

    /**
     * Normalise stored settings ensuring required structure exists.
     *
     * @param array<string,mixed> $payload
     * @return array<string,mixed>
     */
    private function normalizePayload(array $payload): array
    {
        $defaults = [
            'recognition' => [
                'baseUrl' => '',
                'apiKey' => '',
                'timeoutMs' => self::DEFAULT_TIMEOUT_MS,
                'modelProfile' => '',
                'enabled' => false,
            ],
            'featureFlags' => [
                'recognitionEnabled' => null, // derived from recognition.enabled if null
            ],
        ];

        $merged = array_replace_recursive($defaults, is_array($payload) ? $payload : []);

        // Ensure numeric timeout and boolean flags.
        $merged['recognition']['timeoutMs'] = $this->sanitizeTimeout($merged['recognition']['timeoutMs']);
        $merged['recognition']['enabled'] = ValidationHelpers::sanitizeBool($merged['recognition']['enabled']);
        $merged['featureFlags']['recognitionEnabled'] = $merged['recognition']['enabled'];

        foreach (['baseUrl', 'apiKey', 'modelProfile'] as $key) {
            $value = $merged['recognition'][$key] ?? '';
            $merged['recognition'][$key] = is_string($value) ? trim($value) : '';
        }

        // Validate and sanitize base URL
        $merged['recognition']['baseUrl'] = ValidationHelpers::sanitizeUrl($merged['recognition']['baseUrl']);

        return $merged;
    }

    /**
     * @param array<string,mixed> $incoming
     * @param array<string,mixed> $existing
     * @return array<string,mixed>
     */
    private function sanitizeRecognitionSettings(array $incoming, array $existing): array
    {
        $next = $existing;

        if (array_key_exists('baseUrl', $incoming)) {
            $candidate = is_string($incoming['baseUrl']) ? trim($incoming['baseUrl']) : '';
            $next['baseUrl'] = ValidationHelpers::sanitizeUrl($candidate, true);
        }

        if (array_key_exists('apiKey', $incoming)) {
            $next['apiKey'] = is_string($incoming['apiKey']) ? trim($incoming['apiKey']) : '';
        }

        if (array_key_exists('timeoutMs', $incoming)) {
            $next['timeoutMs'] = $this->sanitizeTimeout($incoming['timeoutMs']);
        }

        if (array_key_exists('modelProfile', $incoming)) {
            $next['modelProfile'] = is_string($incoming['modelProfile']) ? trim($incoming['modelProfile']) : '';
        }

        if (array_key_exists('enabled', $incoming)) {
            $next['enabled'] = ValidationHelpers::sanitizeBool($incoming['enabled']);
        }

        return $next;
    }

    /**
     * @param mixed $value
     */
    private function sanitizeTimeout($value): int
    {
        if (is_string($value)) {
            $value = trim($value);
        }

        $timeout = (int) $value;

        if ($timeout <= 0) {
            $timeout = self::DEFAULT_TIMEOUT_MS;
        }

        return ValidationHelpers::sanitizeTimeout($timeout, 1000, 120000);
    }
}
