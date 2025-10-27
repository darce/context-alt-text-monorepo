<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Shared\Config\SettingsRepository;
use function __;
use function add_action;
use function add_settings_field;
use function add_settings_section;
use function do_settings_sections;
use function esc_attr;
use function esc_html__;
use function esc_html_e;
use function filter_var;
use function get_option;
use function is_array;
use function is_numeric;
use function is_string;
use function register_setting;
use function rtrim;
use function sanitize_text_field;
use function settings_errors;
use function settings_fields;
use function submit_button;
use function trim;
use const FILTER_VALIDATE_URL;

class PluginSettingsPage
{
    public const ROOT_ID = 'context-alt-text-settings-root';

    private const OPTION_NAME = 'cat_settings';
    private const SETTINGS_GROUP = 'context-alt-text-settings';
    private const PAGE_SLUG = 'context-alt-text-settings';
    private const SECTION_ID = 'context-alt-text-recognition';
    private const DEFAULT_TIMEOUT_MS = 15000;
    private const MIN_TIMEOUT_MS = 1000;
    private const MAX_TIMEOUT_MS = 120000;
    private SettingsRepository $settingsRepository;

    public function __construct(?SettingsRepository $settingsRepository = null)
    {
        $this->settingsRepository = $settingsRepository ?? new SettingsRepository();
    }

    public function init(): void
    {
        add_action('admin_init', [$this, 'register_settings']);
    }

    public function render(): void
    {
?>
        <div class="wrap context-alt-text-admin">
            <h1><?php esc_html_e('Context Alt Text Settings', 'context-alt-text'); ?></h1>
            <form method="post" action="options.php">
                <?php settings_fields(self::SETTINGS_GROUP); ?>
                <?php settings_errors(self::SETTINGS_GROUP); ?>
                <?php do_settings_sections(self::PAGE_SLUG); ?>
                <?php submit_button(__('Save Settings', 'context-alt-text')); ?>
            </form>
            <div id="<?php echo esc_attr(self::ROOT_ID); ?>" class="context-alt-text-settings-root" hidden>
                <p class="description">
                    <?php esc_html_e('Settings UI loading…', 'context-alt-text'); ?>
                </p>
            </div>
        </div>
    <?php
    }

    public function register_settings(): void
    {
        register_setting(
            self::SETTINGS_GROUP,
            self::OPTION_NAME,
            [
                'type' => 'array',
                'sanitize_callback' => [$this, 'sanitize_settings'],
                'default' => [
                    'base_url' => '',
                    'timeout_ms' => self::DEFAULT_TIMEOUT_MS,
                    'model_profile' => '',
                ],
            ]
        );

        add_settings_section(
            self::SECTION_ID,
            __('Recognition Service', 'context-alt-text'),
            [$this, 'render_recognition_section_intro'],
            self::PAGE_SLUG
        );

        add_settings_field(
            'context_alt_text_recognition_base_url',
            __('Service Base URL', 'context-alt-text'),
            [$this, 'render_base_url_field'],
            self::PAGE_SLUG,
            self::SECTION_ID
        );

        add_settings_field(
            'context_alt_text_recognition_timeout',
            __('Request Timeout (ms)', 'context-alt-text'),
            [$this, 'render_timeout_field'],
            self::PAGE_SLUG,
            self::SECTION_ID
        );

        add_settings_field(
            'context_alt_text_recognition_model',
            __('Model Profile', 'context-alt-text'),
            [$this, 'render_model_profile_field'],
            self::PAGE_SLUG,
            self::SECTION_ID
        );
    }

    public function render_recognition_section_intro(): void
    {
        echo '<p>' . esc_html__('Configure how the plugin connects to the recognition service.', 'context-alt-text') . '</p>';
    }

    public function render_base_url_field(): void
    {
        $settings = $this->get_settings();
        $value = $settings['base_url'];
    ?>
        <input
            type="url"
            name="<?php echo esc_attr(self::OPTION_NAME); ?>[base_url]"
            id="context-alt-text-recognition-base-url"
            value="<?php echo esc_attr($value); ?>"
            class="regular-text"
            placeholder="https://example.test/api" />
        <p class="description">
            <?php esc_html_e('Base URL for the recognition service (e.g. https://service.example/api).', 'context-alt-text'); ?>
        </p>
    <?php
    }

    public function render_timeout_field(): void
    {
        $settings = $this->get_settings();
        $value = $settings['timeout_ms'];
    ?>
        <input
            type="number"
            name="<?php echo esc_attr(self::OPTION_NAME); ?>[timeout_ms]"
            id="context-alt-text-recognition-timeout"
            min="<?php echo esc_attr((string) self::MIN_TIMEOUT_MS); ?>"
            max="<?php echo esc_attr((string) self::MAX_TIMEOUT_MS); ?>"
            step="1000"
            value="<?php echo esc_attr((string) $value); ?>"
            class="small-text" />
        <p class="description">
            <?php esc_html_e('Maximum duration in milliseconds to wait for recognition responses.', 'context-alt-text'); ?>
        </p>
    <?php
    }

    public function render_model_profile_field(): void
    {
        $settings = $this->get_settings();
        $value = $settings['model_profile'];
    ?>
        <input
            type="text"
            name="<?php echo esc_attr(self::OPTION_NAME); ?>[model_profile]"
            id="context-alt-text-recognition-model"
            value="<?php echo esc_attr($value); ?>"
            class="regular-text" />
        <p class="description">
            <?php esc_html_e('Optional model/profile identifier to request from the backend service.', 'context-alt-text'); ?>
        </p>
<?php
    }

    /**
     * @param mixed $input
     *
     * @return array<string,mixed>
     */
    public function sanitize_settings($input): array
    {
        $allSettings = $this->settingsRepository->getAll();
        $recognition = isset($allSettings['recognition']) && is_array($allSettings['recognition'])
            ? $allSettings['recognition']
            : [
                'baseUrl' => '',
                'timeoutMs' => self::DEFAULT_TIMEOUT_MS,
                'modelProfile' => '',
                'apiKey' => '',
                'enabled' => false,
            ];

        $baseUrl = isset($recognition['baseUrl']) && is_string($recognition['baseUrl'])
            ? trim($recognition['baseUrl'])
            : '';

        $timeout = isset($recognition['timeoutMs']) && is_numeric($recognition['timeoutMs'])
            ? (int) $recognition['timeoutMs']
            : self::DEFAULT_TIMEOUT_MS;

        $modelProfile = isset($recognition['modelProfile']) && is_string($recognition['modelProfile'])
            ? $recognition['modelProfile']
            : '';

        if (is_array($input)) {
            if (array_key_exists('base_url', $input)) {
                $candidate = trim((string) $input['base_url']);
                if ($candidate === '') {
                    $baseUrl = '';
                } else {
                    $validated = filter_var($candidate, FILTER_VALIDATE_URL);
                    if ($validated !== false) {
                        $baseUrl = rtrim((string) $validated, '/');
                    }
                }
            }

            if (array_key_exists('timeout_ms', $input)) {
                $timeoutCandidate = (int) $input['timeout_ms'];
                if ($timeoutCandidate <= 0) {
                    $timeoutCandidate = self::DEFAULT_TIMEOUT_MS;
                }

                $timeout = max(self::MIN_TIMEOUT_MS, min(self::MAX_TIMEOUT_MS, $timeoutCandidate));
            }

            if (array_key_exists('model_profile', $input)) {
                $modelProfile = sanitize_text_field((string) $input['model_profile']);
            }
        }

        $recognition['baseUrl'] = $baseUrl;
        $recognition['timeoutMs'] = $timeout;
        $recognition['modelProfile'] = $modelProfile;

        $allSettings['recognition'] = $recognition;
        $allSettings['base_url'] = $baseUrl;
        $allSettings['timeout_ms'] = $timeout;
        $allSettings['model_profile'] = $modelProfile;

        return $allSettings;
    }

    /**
     * @return array{base_url:string,timeout_ms:int,model_profile:string}
     */
    private function get_settings(): array
    {
        $stored = $this->settingsRepository->getAll();
        $recognition = isset($stored['recognition']) && is_array($stored['recognition'])
            ? $stored['recognition']
            : [];

        $baseUrl = '';
        if (isset($stored['base_url']) && is_string($stored['base_url'])) {
            $baseUrl = trim($stored['base_url']);
        } elseif (isset($recognition['baseUrl']) && is_string($recognition['baseUrl'])) {
            $baseUrl = trim($recognition['baseUrl']);
        }

        $timeout = self::DEFAULT_TIMEOUT_MS;
        if (isset($stored['timeout_ms']) && is_numeric($stored['timeout_ms'])) {
            $timeout = (int) $stored['timeout_ms'];
        } elseif (isset($recognition['timeoutMs']) && is_numeric($recognition['timeoutMs'])) {
            $timeout = (int) $recognition['timeoutMs'];
        }
        $timeout = max(self::MIN_TIMEOUT_MS, min(self::MAX_TIMEOUT_MS, $timeout));

        $modelProfile = '';
        if (isset($stored['model_profile']) && is_string($stored['model_profile'])) {
            $modelProfile = trim($stored['model_profile']);
        } elseif (isset($recognition['modelProfile']) && is_string($recognition['modelProfile'])) {
            $modelProfile = trim($recognition['modelProfile']);
        }

        return [
            'base_url' => $baseUrl,
            'timeout_ms' => $timeout,
            'model_profile' => $modelProfile,
        ];
    }
}
