<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Api\DescribeHostInterface;
use AltContext\Api\Services\DescribeMediaService;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function json_decode;

/**
 * E19-1 S6: WordPress describe path. The controller resolves one attachment,
 * reads its bytes, attaches inert wp_context, and dispatches a single-image
 * multipart request to the backend /scene/describe/multipart route. The
 * backend response is passed through unchanged; a malformed upstream envelope
 * is rejected with an explicit 502 (rg-015 — never fabricate fields).
 *
 * @covers \AltContext\Api\DescribeController
 * @covers \AltContext\Api\Services\DescribeMediaService
 */
class DescribeMediaServiceTest extends TestCase
{
    private DescribeController $controller;
    private string $tempDir;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->controller = new DescribeController();
        $this->tempDir = sys_get_temp_dir() . '/acx-e19-1-' . uniqid();
        mkdir($this->tempDir, 0o755, true);
    }

    protected function tearDown(): void
    {
        if (is_dir($this->tempDir)) {
            foreach (glob($this->tempDir . '/*') as $f) {
                @unlink($f);
            }
            @rmdir($this->tempDir);
        }
        parent::tearDown();
    }

    private function plantAttachment(int $id, string $bytes, string $extension = 'jpg'): string
    {
        $path = $this->tempDir . "/{$id}.{$extension}";
        file_put_contents($path, $bytes);
        $GLOBALS['__ac_attached_file'][$id] = $path;
        $GLOBALS['__ac_posts'][$id] = (object) array(
            'post_title'   => "Photo {$id}",
            'post_excerpt' => 'A caption.',
            'post_content' => 'A long description.',
        );
        return $path;
    }

    /**
     * @return array<string,mixed>
     */
    private function validBackendBody(int $media_id): array
    {
        return array(
            'tenant_id'              => self::currentTenantId(),
            'media_id'               => $media_id,
            'image_hash'             => str_repeat('a', 64),
            'context_hash'           => str_repeat('b', 64),
            'adapter'                => 'seeded',
            'model_id'               => 'seeded-fixtures',
            'model_version'          => '1',
            'prompt_or_task_version' => '1',
            'visual_facts'           => array('caption' => 'A photo.', 'objects' => array(), 'ocr_text' => null),
            'alt_text_draft'         => 'A photo.',
            'context_used'           => array('sources' => array(), 'applied' => false),
            'provider_disclosure'    => array('provider' => 'none', 'left_service_boundary' => false),
            'cached'                 => false,
            'duration_ms'            => 3,
            'retention_class'        => 'retain_all',
        );
    }

    /**
     * @param array<int,array<string,mixed>> $identityRows
     * @return array<string,mixed>
     */
    private function describeEnvelopeWithIdentityRows(array $identityRows, bool $allowPersonNames): array
    {
        $this->setOption('acx_description_allow_person_names', $allowPersonNames);
        $this->plantAttachment(42, "\xff\xd8\xff\xe0fake-jpeg-bytes", 'jpg');

        $host = new DescribeMediaServiceTestHost(self::currentTenantId(), $this->validBackendBody(42));
        $repo = new DescribeMediaServiceTestIdentityRepository($identityRows);
        $service = new DescribeMediaService($host, $repo);

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $service->describe_media($req);

        $body = $host->lastBody['request'] ?? '';
        $this->assertIsString($body);

        return json_decode($body, true);
    }

    public function testDispatchesSingleImageMultipartToSceneRoute(): void
    {
        $bytes = "\xff\xd8\xff\xe0fake-jpeg-bytes";
        $this->plantAttachment(42, $bytes, 'jpg');
        $GLOBALS['__ac_site_url'] = 'http://acx.test';

        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertNotInstanceOf(WP_Error::class, $result, var_export($result, true));
        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $call = $calls[0];
        $this->assertStringContainsString('/scene/describe/multipart', $call['url']);

        $body = $call['args']['body'];
        $this->assertIsString($body);
        // Exactly one image part with the raw bytes embedded.
        $this->assertStringContainsString('name="image_42"; filename=', $body);
        $this->assertStringContainsString($bytes, $body);

        // The 'request' envelope carries tenant_id + media_id + bounded context pack.
        $this->assertStringContainsString("name=\"request\"\r\n", $body);
        $this->assertMatchesRegularExpression('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body);
        preg_match('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body, $m);
        $envelope = json_decode($m[1], true);
        $this->assertSame(self::currentTenantId(), $envelope['tenant_id']);
        $this->assertSame(42, $envelope['media_id']);
        $this->assertIsArray($envelope['context_pack']);
        $this->assertSame('Photo 42', $envelope['context_pack']['attachment']['title']);
        $this->assertSame('42.jpg', $envelope['context_pack']['attachment']['filename']);
        // No top-level keys the backend's extra='forbid' envelope rejects.
        $this->assertSame(array('tenant_id', 'media_id', 'context_pack'), array_keys($envelope));

        // Response is passed through unchanged.
        $data = $result->get_data();
        $this->assertSame('A photo.', $data['alt_text_draft']);
        $this->assertFalse($data['cached']);
    }

    public function testRosterDescriptionContextEmitsConfirmedIdentityWhenPolicyAllows(): void
    {
        $envelope = $this->describeEnvelopeWithIdentityRows(
            array(
                array(
                    'identity_uuid'     => 'identity-1',
                    'cluster_uuid'      => 'cluster-1',
                    'cluster_label'     => 'Ada Lovelace',
                    'person_name'       => 'Ada Lovelace',
                    'is_user_confirmed' => 1,
                ),
            ),
            true
        );

        $identity = $envelope['context_pack']['identity'];
        $this->assertSame('allowed', $identity['policy']['person_naming']);
        $this->assertSame('Ada Lovelace', $identity['identities'][0]['name']);
        $this->assertSame('roster_confirmed', $identity['identities'][0]['source']);
        $this->assertSame(array(), $identity['review_reasons']);
    }

    public function testRosterDescriptionContextNeverNamesConfirmedClusterWithoutRosterPerson(): void
    {
        // A confirmed cluster with NO assigned roster person (person_id NULL) has
        // cluster_label falling back to the machine label c.label; it must never
        // be named, and must still surface a review reason even when a genuinely
        // confirmed roster person is present on the same image.
        $envelope = $this->describeEnvelopeWithIdentityRows(
            array(
                array(
                    'identity_uuid'     => 'identity-1',
                    'cluster_uuid'      => 'cluster-1',
                    'cluster_label'     => 'Ada Lovelace',
                    'person_name'       => 'Ada Lovelace',
                    'is_user_confirmed' => 1,
                ),
                array(
                    'identity_uuid'     => 'identity-2',
                    'cluster_uuid'      => 'cluster-2',
                    'cluster_label'     => 'Machine Cluster 7',
                    'person_name'       => '',
                    'is_user_confirmed' => 1,
                ),
            ),
            true
        );

        $identity = $envelope['context_pack']['identity'];
        $this->assertCount(1, $identity['identities']);
        $this->assertSame('Ada Lovelace', $identity['identities'][0]['name']);
        $this->assertContains('identity_unconfirmed', $identity['review_reasons']);

        $json = json_encode($envelope);
        $this->assertIsString($json);
        $this->assertStringNotContainsString('Machine Cluster 7', $json);
    }

    public function testRosterDescriptionContextExcludesUnconfirmedMachineLabels(): void
    {
        $envelopeJson = json_encode(
            $this->describeEnvelopeWithIdentityRows(
                array(
                    array(
                        'identity_uuid'     => 'identity-1',
                        'cluster_uuid'      => 'cluster-1',
                        'cluster_label'     => 'Grace Hopper',
                        'is_user_confirmed' => 0,
                    ),
                ),
                true
            )
        );

        $this->assertIsString($envelopeJson);
        $this->assertStringNotContainsString('Grace Hopper', $envelopeJson);
        $this->assertStringContainsString('identity_unconfirmed', $envelopeJson);
    }

    public function testRosterDescriptionContextSuppressesNamesWhenPolicyDisabled(): void
    {
        $envelopeJson = json_encode(
            $this->describeEnvelopeWithIdentityRows(
                array(
                    array(
                        'identity_uuid'     => 'identity-1',
                        'cluster_uuid'      => 'cluster-1',
                        'cluster_label'     => 'Ada Lovelace',
                        'person_name'       => 'Ada Lovelace',
                        'is_user_confirmed' => 1,
                    ),
                ),
                false
            )
        );

        $this->assertIsString($envelopeJson);
        $this->assertStringNotContainsString('Ada Lovelace', $envelopeJson);
        $this->assertStringContainsString('person_naming_policy_disabled', $envelopeJson);
    }

    public function testRosterDescriptionContextRepresentsAmbiguousMachineOnlyState(): void
    {
        $envelope = $this->describeEnvelopeWithIdentityRows(
            array(
                array(
                    'identity_uuid'     => 'identity-1',
                    'cluster_uuid'      => 'cluster-1',
                    'cluster_label'     => 'Candidate One',
                    'is_user_confirmed' => 0,
                ),
                array(
                    'identity_uuid'     => 'identity-2',
                    'cluster_uuid'      => 'cluster-2',
                    'cluster_label'     => 'Candidate Two',
                    'is_user_confirmed' => 0,
                ),
            ),
            true
        );

        $identity = $envelope['context_pack']['identity'];
        $this->assertSame(array(), $identity['identities']);
        $this->assertContains('identity_ambiguous', $identity['review_reasons']);

        // Directly verify the no-name-leak guarantee for the ambiguous path:
        // candidate labels must never appear anywhere in the serialized envelope.
        $json = json_encode($envelope);
        $this->assertIsString($json);
        $this->assertStringNotContainsString('Candidate One', $json);
        $this->assertStringNotContainsString('Candidate Two', $json);
    }

    public function testRejectsUnreadableAttachmentBeforeDispatch(): void
    {
        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 9001);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('describe_attachment_unreadable', $result->get_error_code());
        $this->assertSame(array(), $this->getHttpCalls());
    }

    public function testRejectsMissingMediaId(): void
    {
        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('describe_invalid_media_id', $result->get_error_code());
        $this->assertSame(array(), $this->getHttpCalls());
    }

    public function testRejectsOversizePayloadBeforeDispatch(): void
    {
        $bytes = str_repeat('A', 26 * 1024 * 1024);
        $this->plantAttachment(7, $bytes, 'png');

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 7);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('describe_payload_too_large', $result->get_error_code());
        $this->assertSame(array(), $this->getHttpCalls());
    }

    public function testMalformedUpstreamEnvelopeReturns502(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');

        // Upstream 200 but missing required provenance fields → rg-015 violation.
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => '{"caption":"oops","cached":false}',
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('invalid_description_envelope', $result->get_error_code());
        $this->assertSame(502, $result->get_error_data()['status'] ?? null);
    }

    public function testUpstreamErrorStatusPassesThroughUnwrapped(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');

        // Backend rejects an unsupported MIME with 415 — the proxy must forward
        // it verbatim, not re-wrap it as a 502 envelope error.
        $this->queueHttpResponse(array(
            'response' => array('code' => 415, 'message' => 'Unsupported Media Type'),
            'body'     => '{"detail":"unsupported image type"}',
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(415, $result->get_status());
    }
}

final class DescribeMediaServiceTestHost implements DescribeHostInterface
{
    /**
     * @var array<string,mixed>
     */
    public array $lastBody = array();

    /**
     * @param array<string,mixed> $backendBody
     */
    public function __construct(private string $tenantId, private array $backendBody) {}

    public function get_tenant_id(): string
    {
        return $this->tenantId;
    }

    public function proxy_recognition_request(
        string $method,
        string $path,
        array $body = array(),
        array $query = array(),
        string $request_class = 'auto',
        string $body_kind = 'json',
        ?int $max_body_bytes = null
    ): WP_REST_Response|WP_Error {
        $this->lastBody = $body;
        return new WP_REST_Response($this->backendBody, 200);
    }

    public function is_proxy_unavailable(WP_REST_Response|WP_Error $response): bool
    {
        return false;
    }
}

final class DescribeMediaServiceTestIdentityRepository extends NullIdentityMembersRepository
{
    /**
     * @param array<int,array<string,mixed>> $rows
     */
    public function __construct(private array $rows) {}

    public function list_for_media_ids(string $tenant_id, array $media_ids): array
    {
        return $this->rows;
    }
}
