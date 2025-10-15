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
     */
    public function getBaseUrl(): ?string
    {
        $settings = $this->settingsRepository->getRecognitionSettings();
        $option = $settings['baseUrl'] ?? '';

        if ($option === '') {
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
        $settings = $this->settingsRepository->getRecognitionSettings();
        $option = $settings['apiKey'] ?? '';

        if ($option === '') {
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
        $settings = $this->settingsRepository->getRecognitionSettings();
        $timeout = (int) ($settings['timeoutMs'] ?? self::DEFAULT_TIMEOUT_MS);

        $envSetting = $this->getEnv('CAT_RECOGNITION_TIMEOUT_MS');
        if ($envSetting !== null && $envSetting !== '') {
            $timeout = (int) trim($envSetting);
        }

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
        $settings = $this->settingsRepository->getRecognitionSettings();
        $option = $settings['modelProfile'] ?? '';

        if ($option === '') {
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
