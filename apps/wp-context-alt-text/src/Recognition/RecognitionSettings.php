<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Shared\Config\SettingsRepository;

use function filter_var;
use function getenv;
use function is_string;
use function rtrim;
use function trim;

use const FILTER_VALIDATE_URL;

class RecognitionSettings
{
    private const DEFAULT_TIMEOUT_MS = 15000;
    private SettingsRepository $settingsRepository;

    public function __construct(?SettingsRepository $settingsRepository = null)
    {
        $this->settingsRepository = $settingsRepository ?? new SettingsRepository();
    }

    /**
     * Retrieve the configured base URL for the recognition service.
     * 
     * Priority order (12-factor app principle):
     * 1. Environment variable (CAT_RECOGNITION_BASE_URL)
     * 2. WordPress database option (admin UI override)
     */
    public function getBaseUrl(): ?string
    {
        // Check environment variable first
        $envValue = $this->getEnv('CAT_RECOGNITION_BASE_URL');
        if ($envValue !== null && $envValue !== '') {
            $option = $envValue;
        } else {
            // Fallback to database option
            $settings = $this->settingsRepository->getRecognitionSettings();
            $option = $settings['baseUrl'] ?? '';
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
     * 
     * Priority order (12-factor app principle):
     * 1. Environment variable (CAT_RECOGNITION_API_KEY)
     * 2. WordPress database option (admin UI override)
     */
    public function getApiKey(): ?string
    {
        // Check environment variable first
        $envValue = $this->getEnv('CAT_RECOGNITION_API_KEY');
        if ($envValue !== null && $envValue !== '') {
            $option = $envValue;
        } else {
            // Fallback to database option
            $settings = $this->settingsRepository->getRecognitionSettings();
            $option = $settings['apiKey'] ?? '';
        }

        if (!is_string($option)) {
            return null;
        }

        $trimmed = trim($option);

        return $trimmed !== '' ? $trimmed : null;
    }

    /**
     * Timeout in milliseconds for outbound HTTP requests to the recognition service.
     * 
     * Priority order (12-factor app principle):
     * 1. Environment variable (CAT_RECOGNITION_TIMEOUT_MS)
     * 2. WordPress database option (admin UI override)
     * 3. Default value (15000ms)
     */
    public function getTimeoutMs(): int
    {
        // Check environment variable first
        $envSetting = $this->getEnv('CAT_RECOGNITION_TIMEOUT_MS');
        if ($envSetting !== null && $envSetting !== '') {
            $timeout = (int) trim($envSetting);
        } else {
            // Fallback to database option
            $settings = $this->settingsRepository->getRecognitionSettings();
            $timeout = (int) ($settings['timeoutMs'] ?? self::DEFAULT_TIMEOUT_MS);
        }

        if ($timeout <= 0) {
            $timeout = self::DEFAULT_TIMEOUT_MS;
        }

        return $timeout;
    }

    /**
     * Optional model profile identifier that should be requested from the backend.
     * 
     * Priority order (12-factor app principle):
     * 1. Environment variable (CAT_RECOGNITION_MODEL_PROFILE)
     * 2. WordPress database option (admin UI override)
     */
    public function getModelProfile(): ?string
    {
        // Check environment variable first
        $envValue = $this->getEnv('CAT_RECOGNITION_MODEL_PROFILE');
        if ($envValue !== null && $envValue !== '') {
            $option = $envValue;
        } else {
            // Fallback to database option
            $settings = $this->settingsRepository->getRecognitionSettings();
            $option = $settings['modelProfile'] ?? '';
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
