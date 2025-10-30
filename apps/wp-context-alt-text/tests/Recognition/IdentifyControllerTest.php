<?php

declare(strict_types=1);

use ContextAltText\Recognition\IdentifyController;
use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionClientException;
use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Security\Security;
use PHPUnit\Framework\MockObject\MockObject;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class IdentifyControllerTest extends TestCase
{
    private IdentifyController $controller;
    /** @var MockObject&RecognitionClient */
    private $mockRecognitionClient;
    /** @var MockObject&RosterService */
    private $mockRosterService;
    /** @var MockObject&Security */
    private $mockSecurity;

    protected function setUp(): void
    {
        parent::setUp();

        // Reset global state
        $GLOBALS['__cat_http_queue'] = [];
        $GLOBALS['__cat_http_calls'] = [];
        $GLOBALS['__cat_current_user_can'] = true;
        $GLOBALS['__cat_nonce_verified'] = true;
        $GLOBALS['__cat_options']['cat_settings'] = [
            'recognition' => [
                'baseUrl' => 'https://recognition.example.test',
                'timeoutMs' => 15000,
                'modelProfile' => '',
                'enabled' => true,
            ],
        ];

        // Stub attachment post for tests
        $GLOBALS['__cat_posts'][123] = (object) [
            'ID' => 123,
            'post_type' => 'attachment',
            'post_mime_type' => 'image/jpeg',
        ];

        // Create mock dependencies
        $this->mockRecognitionClient = $this->createMock(RecognitionClient::class);
        $this->mockRosterService = $this->createMock(RosterService::class);
        $this->mockSecurity = $this->createMock(Security::class);

        // Controller uses these mocks
        $this->controller = new IdentifyController(
            $this->mockRecognitionClient,
            $this->mockRosterService,
            $this->mockSecurity
        );
    }

    public function test_returns_401_for_unauthenticated_requests(): void
    {
        $GLOBALS['__cat_current_user_can'] = false;

        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(false);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/identify');
        $request->set_body_params([
            'attachmentId' => 123,
            'faces' => [
                ['bbox' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.4]],
            ],
        ]);

        $response = $this->controller->identify($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('rest_forbidden', $response->get_error_code());
        $this->assertSame(401, $response->get_error_data()['status']);
    }

    public function test_returns_400_for_invalid_attachment_id(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Mock get_post to return false (invalid attachment)
        $GLOBALS['__cat_posts'][99999] = false;

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/identify');
        $request->set_body_params([
            'attachmentId' => 99999,
            'faces' => [
                ['bbox' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.4]],
            ],
        ]);

        $response = $this->controller->identify($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_attachment', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status']);
    }

    public function test_returns_400_for_missing_bbox_coordinates(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/identify');
        $request->set_body_params([
            'attachmentId' => 123,
            'faces' => [
                ['bbox' => ['x' => 0.1, 'y' => 0.2]], // Missing width and height
            ],
        ]);

        $response = $this->controller->identify($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_request', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status']);
        $this->assertStringContainsString('bbox', $response->get_error_message());
    }

    public function test_returns_error_when_recognition_service_is_unavailable(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Mock valid attachment
        $GLOBALS['__cat_posts'][123] = (object)[
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        // Mock recognition client to throw exception
        $this->mockRecognitionClient
            ->expects($this->once())
            ->method('embedFaces')
            ->willThrowException(new RecognitionClientException('Service unavailable', 503));

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/identify');
        $request->set_body_params([
            'attachmentId' => 123,
            'faces' => [
                ['bbox' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.4]],
            ],
        ]);

        $response = $this->controller->identify($request);

    $this->assertInstanceOf(\WP_Error::class, $response);
    $this->assertSame('recognition_service_unavailable', $response->get_error_code());
    $this->assertSame(503, $response->get_error_data('recognition_service_unavailable')['status']);
    }

    public function test_returns_successful_response_with_suggestions(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Mock valid attachment
        $GLOBALS['__cat_posts'][123] = (object)[
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        // Mock recognition client responses
        $this->mockRecognitionClient
            ->expects($this->once())
            ->method('embedFaces')
            ->willReturn([
                'embeddings' => [[0.1, 0.2, 0.3]], // Mock embedding
            ]);

        $this->mockRecognitionClient
            ->expects($this->once())
            ->method('suggestMatches')
            ->willReturn([
                'suggestions' => [
                    [
                        ['rosterId' => 'person-1', 'display' => 'Ana Rodriguez', 'score' => 0.95],
                        ['rosterId' => 'person-2', 'display' => 'Carlos Santos', 'score' => 0.87],
                    ],
                ],
            ]);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/identify');
        $request->set_body_params([
            'attachmentId' => 123,
            'faces' => [
                ['bbox' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.4]],
            ],
        ]);

        $response = $this->controller->identify($request);

        $this->assertIsArray($response);
        $this->assertArrayHasKey('faces', $response);
        $this->assertCount(1, $response['faces']);

        $face = $response['faces'][0];
        $this->assertArrayHasKey('faceId', $face);
        $this->assertArrayHasKey('clusterId', $face);
        $this->assertArrayHasKey('suggestions', $face);
        $this->assertSame('cluster-0', $face['clusterId']);
        $this->assertCount(2, $face['suggestions']);
        $this->assertSame('Ana Rodriguez', $face['suggestions'][0]['display']);
    }

    public function test_persists_observation_when_label_provided(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Mock valid attachment
        $GLOBALS['__cat_posts'][123] = (object)[
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        // Mock recognition client
        $this->mockRecognitionClient
            ->expects($this->once())
            ->method('embedFaces')
            ->willReturn(['embeddings' => [[0.1, 0.2, 0.3]]]);

        // Mock roster service to confirm observation persisted
        $this->mockRosterService
            ->expects($this->once())
            ->method('createObservation')
            ->with(
                $this->equalTo(123), // attachmentId
                $this->anything(), // embedding
                $this->equalTo('person-1'), // rosterId
                $this->anything() // bbox
            )
            ->willReturn(456); // observationId

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/identify');
        $request->set_body_params([
            'attachmentId' => 123,
            'faces' => [
                [
                    'bbox' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.4],
                    'label' => ['rosterId' => 'person-1'],
                ],
            ],
        ]);

        $response = $this->controller->identify($request);

        $this->assertIsArray($response);
        $this->assertArrayHasKey('faces', $response);
        $this->assertSame(456, $response['faces'][0]['observationId']);
    }

    public function test_creates_new_roster_person_for_new_name(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Mock valid attachment
        $GLOBALS['__cat_posts'][123] = (object)[
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        // Mock recognition client
        $this->mockRecognitionClient
            ->expects($this->once())
            ->method('embedFaces')
            ->willReturn(['embeddings' => [[0.1, 0.2, 0.3]]]);

        // Mock roster service to create new person
        $this->mockRosterService
            ->expects($this->once())
            ->method('createPerson')
            ->with($this->equalTo('Maria Silva'))
            ->willReturn('person-new-123');

        $this->mockRosterService
            ->expects($this->once())
            ->method('createObservation')
            ->willReturn(789);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/identify');
        $request->set_body_params([
            'attachmentId' => 123,
            'faces' => [
                [
                    'bbox' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.4],
                    'label' => ['newName' => 'Maria Silva'],
                ],
            ],
        ]);

        $response = $this->controller->identify($request);

        $this->assertIsArray($response);
        $this->assertArrayHasKey('faces', $response);
        $this->assertSame(789, $response['faces'][0]['observationId']);
    }

    public function test_updates_existing_roster_for_roster_id(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Mock valid attachment
        $GLOBALS['__cat_posts'][123] = (object)[
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        // Mock recognition client
        $this->mockRecognitionClient
            ->expects($this->once())
            ->method('embedFaces')
            ->willReturn(['embeddings' => [[0.1, 0.2, 0.3]]]);

        // Mock roster service - should NOT create new person
        $this->mockRosterService
            ->expects($this->never())
            ->method('createPerson');

        $this->mockRosterService
            ->expects($this->once())
            ->method('createObservation')
            ->with(
                $this->equalTo(123),
                $this->anything(),
                $this->equalTo('person-existing'),
                $this->anything()
            )
            ->willReturn(999);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/identify');
        $request->set_body_params([
            'attachmentId' => 123,
            'faces' => [
                [
                    'bbox' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.4],
                    'label' => ['rosterId' => 'person-existing'],
                ],
            ],
        ]);

        $response = $this->controller->identify($request);

        $this->assertIsArray($response);
        $this->assertSame(999, $response['faces'][0]['observationId']);
    }

    public function test_syncs_embedding_to_faiss_on_label_confirmation(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Mock valid attachment
        $GLOBALS['__cat_posts'][123] = (object)[
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        $mockEmbedding = [0.1, 0.2, 0.3];

        // Mock recognition client
        $this->mockRecognitionClient
            ->expects($this->once())
            ->method('embedFaces')
            ->willReturn(['embeddings' => [$mockEmbedding]]);

        // Mock roster service
        $this->mockRosterService
            ->expects($this->once())
            ->method('createObservation')
            ->willReturn(456);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/identify');
        $request->set_body_params([
            'attachmentId' => 123,
            'faces' => [
                [
                    'bbox' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.4],
                    'label' => ['rosterId' => 'person-1'],
                ],
            ],
        ]);

        $response = $this->controller->identify($request);

        $this->assertIsArray($response);
        $this->assertArrayHasKey('faces', $response);
        $face = $response['faces'][0];
        $this->assertSame(456, $face['observationId']);
    $this->assertSame('delegated', $face['syncStatus']);
    $this->assertArrayNotHasKey('syncError', $face);
    }

    public function test_syncs_embedding_for_new_person_creation(): void
    {
        $this->mockSecurity
            ->expects($this->once())
            ->method('verifyCapability')
            ->with('upload_files')
            ->willReturn(true);

        // Mock valid attachment
        $GLOBALS['__cat_posts'][123] = (object)[
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        $mockEmbedding = [0.5, 0.6, 0.7];

        // Mock recognition client
        $this->mockRecognitionClient
            ->expects($this->once())
            ->method('embedFaces')
            ->willReturn(['embeddings' => [$mockEmbedding]]);

        // Mock roster service creating new person
        $this->mockRosterService
            ->expects($this->once())
            ->method('createPerson')
            ->with($this->equalTo('João Costa'))
            ->willReturn('person-new-456');

        $this->mockRosterService
            ->expects($this->once())
            ->method('createObservation')
            ->willReturn(888);

        $request = new WP_REST_Request('POST', '/cat/v1/recognition/identify');
        $request->set_body_params([
            'attachmentId' => 123,
            'faces' => [
                [
                    'bbox' => ['x' => 0.5, 'y' => 0.5, 'width' => 0.2, 'height' => 0.2],
                    'label' => ['newName' => 'João Costa'],
                ],
            ],
        ]);

        $response = $this->controller->identify($request);

        $this->assertIsArray($response);
        $this->assertSame(888, $response['faces'][0]['observationId']);
        $this->assertSame('delegated', $response['faces'][0]['syncStatus']);
    }
}
