<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use function filter_var;
use function get_option;
use function getenv;
use function is_array;
use function is_string;
use function rtrim;
use function trim;

use const FILTER_VALIDATE_URL;

class RecognitionSettings
{
    private const OPTION_KEY = 'context_alt_text_recognition_settings';
    private const DEFAULT_TIMEOUT_MS = 15000;

    /**
     * Retrieve the configured base URL for the recognition service.
     */
    public function getBaseUrl(): ?string
    {
        $option = $this->getOption('base_url');

        if (!$option) {
            $option = $this->getEnv('CAT_RECOGNITION_BASE_URL');
        }

        if (!is_string($option)) {
            return null;
        }

        $trimmed = trim($option);

        if ($trimmed === '') {
            return null;
        }

        $validated = filter_var($trimmed, FILTER_VALIDATE_URL);

        if ($validated === false) {
            return null;
        }

        return rtrim($validated, '/');
    }

    /**
     * Retrieve the API key (if any) for authenticating against the recognition service.
     */
    public function getApiKey(): ?string
    {
        $option = $this->getOption('api_key');

        if (!$option) {
            $option = $this->getEnv('CAT_RECOGNITION_API_KEY');
        }

        if (!is_string($option)) {
            return null;
        }

        $trimmed = trim($option);

        return $trimmed !== '' ? $trimmed : null;
    }

    /**
     * Timeout in milliseconds for outbound HTTP requests to the recognition service.
     */
    public function getTimeoutMs(): int
    {
        $option = $this->getOption('timeout_ms');

        if ($option === null) {
            $envSetting = $this->getEnv('CAT_RECOGNITION_TIMEOUT_MS');
            if ($envSetting !== null && $envSetting !== '') {
                $option = $envSetting;
            }
        }

        if (is_string($option)) {
            $option = trim($option);
        }

        $timeout = (int) $option;

        if ($timeout <= 0) {
            $timeout = self::DEFAULT_TIMEOUT_MS;
        }

        return $timeout;
    }

    /**
     * Optional model profile identifier that should be requested from the backend.
     */
    public function getModelProfile(): ?string
    {
        $option = $this->getOption('model_profile');

        if (!$option) {
            $option = $this->getEnv('CAT_RECOGNITION_MODEL_PROFILE');
        }

        if (!is_string($option)) {
            return null;
        }

        $trimmed = trim($option);

        return $trimmed !== '' ? $trimmed : null;
    }

    public function isConfigured(): bool
    {
        return $this->getBaseUrl() !== null;
    }

    /**
     * @return mixed|null
     */
    private function getOption(string $key)
    {
        $option = get_option(self::OPTION_KEY);

        if (!is_array($option)) {
            return null;
        }

        return $option[$key] ?? null;
    }

    private function getEnv(string $name): ?string
    {
        $value = getenv($name);

        if ($value === false && isset($_ENV[$name])) {
            $value = (string) $_ENV[$name];
        }

        if ($value === false) {
            return null;
        }

        $stringValue = is_string($value) ? $value : (string) $value;

        return trim($stringValue);
    }
}
