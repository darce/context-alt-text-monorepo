<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RecognitionApiKeyStore;
use AltContext\Api\SettingsController;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\SettingsController
 */
class SettingsSaveDeploymentKeyBindingTest extends TestCase
{
    private SettingsController $controller;
    private string|false $originalRecognitionApiKeyEnvironment;

    protected function setUp(): void
    {
        parent::setUp();
        $this->originalRecognitionApiKeyEnvironment = getenv( 'ACX_RECOGNITION_API_KEY' );
        putenv( 'ACX_RECOGNITION_API_KEY' );
        $this->controller = new SettingsController();
    }

    protected function tearDown(): void
    {
        if ( false === $this->originalRecognitionApiKeyEnvironment ) {
            putenv( 'ACX_RECOGNITION_API_KEY' );
        } else {
            putenv( 'ACX_RECOGNITION_API_KEY=' . $this->originalRecognitionApiKeyEnvironment );
        }

        parent::tearDown();
    }

    public function testFilterManagedKeyRejectsRemoteOptionUrlAndPreservesExistingOption(): void
    {
        $this->setOption( 'acx_recognition_url', 'https://existing.example' );
        $this->addFilterManagedKey();

        $response = $this->saveUrl( 'https://attacker.example' );

        $this->assertInstanceOf( WP_Error::class, $response );
        $this->assertSame( 'deployment_key_requires_deployment_url', $response->get_error_code() );
        $this->assertSame( 400, $response->get_error_data()['status'] );
        $this->assertSame(
            'A deployment-managed recognition API key is configured; set the recognition URL with ACX_RECOGNITION_URL or the acx_recognition_base_url filter instead of saving it here.',
            $response->get_error_message()
        );
        $this->assertSame( 'https://existing.example', get_option( 'acx_recognition_url' ) );
    }

    public function testEnvironmentManagedKeyRejectsRemoteOptionUrl(): void
    {
        putenv( 'ACX_RECOGNITION_API_KEY=environment-managed-test-key' );
        $this->setOption( 'acx_recognition_url', 'https://existing.example' );

        $response = $this->saveUrl( 'https://attacker.example' );

        $this->assertInstanceOf( WP_Error::class, $response );
        $this->assertSame( 'deployment_key_requires_deployment_url', $response->get_error_code() );
        $this->assertSame( 400, $response->get_error_data()['status'] );
        $this->assertSame( 'https://existing.example', get_option( 'acx_recognition_url' ) );
    }

    public function testFilterManagedKeyAllowsLoopbackOptionUrl(): void
    {
        $this->addFilterManagedKey();

        $response = $this->saveUrl( 'http://localhost:8000' );

        $this->assertInstanceOf( WP_REST_Response::class, $response );
        $this->assertSame( 'http://localhost:8000', get_option( 'acx_recognition_url' ) );
    }

    public function testFilterManagedKeyAllowsOptionUrlWhenDeploymentUrlIsPresent(): void
    {
        $this->addFilterManagedKey();
        add_filter( 'acx_recognition_base_url', static fn ( $configured ): string => 'https://deployment.example' );

        $response = $this->saveUrl( 'https://other.example' );

        $this->assertInstanceOf( WP_REST_Response::class, $response );
        $this->assertSame( 'https://other.example', get_option( 'acx_recognition_url' ) );
    }

    public function testOptionManagedKeyAllowsRemoteOptionUrl(): void
    {
        $this->setOption( RecognitionApiKeyStore::OPTION_NAME, 'admin-managed-test-key' );

        $response = $this->saveUrl( 'https://option.example' );

        $this->assertInstanceOf( WP_REST_Response::class, $response );
        $this->assertSame( 'https://option.example', get_option( 'acx_recognition_url' ) );
    }

    public function testFilterManagedKeyAllowsClearingOptionUrl(): void
    {
        $this->addFilterManagedKey();
        $this->setOption( 'acx_recognition_url', 'https://existing.example' );

        $response = $this->saveUrl( '' );

        $this->assertInstanceOf( WP_REST_Response::class, $response );
        $this->assertSame( '', get_option( 'acx_recognition_url' ) );
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testConstantManagedKeyRejectsRemoteOptionUrl(): void
    {
        require_once __DIR__ . '/../bootstrap.php';
        define( 'ACX_RECOGNITION_API_KEY', 'constant-managed-test-key' );
        $this->setOption( 'acx_recognition_url', 'https://existing.example' );

        $response = $this->saveUrl( 'https://attacker.example' );

        $this->assertInstanceOf( WP_Error::class, $response );
        $this->assertSame( 'deployment_key_requires_deployment_url', $response->get_error_code() );
        $this->assertSame( 400, $response->get_error_data()['status'] );
        $this->assertSame( 'https://existing.example', get_option( 'acx_recognition_url' ) );
    }

    private function addFilterManagedKey(): void
    {
        add_filter( 'acx_recognition_api_key', static fn ( $configured ): string => 'filter-managed-test-key' );
    }

    private function saveUrl( string $url ): WP_REST_Response|WP_Error
    {
        $this->setUserCapability( 'manage_options', true );
        $request = new WP_REST_Request( 'POST', '/acx/v1/settings' );
        $request->set_body_params( array( 'url' => $url ) );

        return $this->controller->save_settings( $request );
    }
}
