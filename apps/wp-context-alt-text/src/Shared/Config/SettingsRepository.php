<?php

declare(strict_types=1);

namespace ContextAltText\Shared\Config;

use function array_key_exists;
use function array_replace_recursive;
use function filter_var;
use function get_option;
use function is_array;
use function is_bool;
use function is_numeric;
use function is_string;
use function rtrim;
use function trim;
use function update_option;

use const FILTER_VALIDATE_BOOLEAN;
use const FILTER_VALIDATE_URL;
use const FILTER_NULL_ON_FAILURE;

/**
 * Central store for persisted plugin settings.
 */
class SettingsRepository
{
    public const OPTION_KEY = 'cat_settings';
    private const LEGACY_RECOGNITION_OPTION = 'context_alt_text_recognition_settings';
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

        // Back-fill from legacy option if available and new settings are empty.
        $normalized = $this->mergeLegacyRecognitionSettings($normalized);

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
        $this->syncLegacyRecognitionOption($next['recognition']);

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
        $this->syncLegacyRecognitionOption($next['recognition']);
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
        $merged['recognition']['enabled'] = $this->sanitizeBool($merged['recognition']['enabled']);
        $merged['featureFlags']['recognitionEnabled'] = $merged['recognition']['enabled'];

        foreach (['baseUrl', 'apiKey', 'modelProfile'] as $key) {
            $value = $merged['recognition'][$key] ?? '';
            $merged['recognition'][$key] = is_string($value) ? trim($value) : '';
        }

        if ($merged['recognition']['baseUrl'] !== '' && filter_var($merged['recognition']['baseUrl'], FILTER_VALIDATE_URL) === false) {
            $merged['recognition']['baseUrl'] = '';
        }

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
            $next['baseUrl'] = ($candidate !== '' && filter_var($candidate, FILTER_VALIDATE_URL) !== false)
                ? rtrim($candidate, '/')
                : '';
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
            $next['enabled'] = $this->sanitizeBool($incoming['enabled']);
        }

        return $next;
    }

    /**
     * Merge data from the legacy option if the new payload is missing values.
     *
     * @param array<string,mixed> $payload
     * @return array<string,mixed>
     */
    private function mergeLegacyRecognitionSettings(array $payload): array
    {
        $legacy = get_option(self::LEGACY_RECOGNITION_OPTION);

        if (!is_array($legacy)) {
            return $payload;
        }

        $recognition = $payload['recognition'];

        if (($recognition['baseUrl'] ?? '') === '' && isset($legacy['base_url']) && is_string($legacy['base_url'])) {
            $candidate = trim($legacy['base_url']);
            if ($candidate !== '' && filter_var($candidate, FILTER_VALIDATE_URL) !== false) {
                $recognition['baseUrl'] = rtrim($candidate, '/');
            }
        }

        if (($recognition['timeoutMs'] ?? 0) === self::DEFAULT_TIMEOUT_MS && isset($legacy['timeout_ms'])) {
            $recognition['timeoutMs'] = $this->sanitizeTimeout($legacy['timeout_ms']);
        }

        if (($recognition['modelProfile'] ?? '') === '' && isset($legacy['model_profile']) && is_string($legacy['model_profile'])) {
            $recognition['modelProfile'] = trim($legacy['model_profile']);
        }

        if (!($recognition['enabled'] ?? false) && ($recognition['baseUrl'] ?? '') !== '') {
            $recognition['enabled'] = true;
        }

        $payload['recognition'] = $recognition;
        $payload['featureFlags']['recognitionEnabled'] = $recognition['enabled'];

        return $payload;
    }

    /**
     * Ensure the legacy option stays in sync for backwards compatibility.
     *
     * @param array<string,mixed> $recognition
     */
    private function syncLegacyRecognitionOption(array $recognition): void
    {
        $legacy = [
            'base_url' => $recognition['baseUrl'] ?? '',
            'timeout_ms' => $recognition['timeoutMs'] ?? self::DEFAULT_TIMEOUT_MS,
            'model_profile' => $recognition['modelProfile'] ?? '',
        ];

        update_option(self::LEGACY_RECOGNITION_OPTION, $legacy);
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

        if ($timeout < 1000) {
            $timeout = 1000;
        }

        if ($timeout > 120000) {
            $timeout = 120000;
        }

        return $timeout;
    }

    /**
     * @param mixed $value
     */
    private function sanitizeBool($value): bool
    {
        if (is_bool($value)) {
            return $value;
        }

        if (is_string($value)) {
            $value = trim($value);
        }

        if (is_numeric($value) || is_string($value)) {
            return filter_var($value, FILTER_VALIDATE_BOOLEAN, FILTER_NULL_ON_FAILURE) ?? false;
        }

        return false;
    }
}
