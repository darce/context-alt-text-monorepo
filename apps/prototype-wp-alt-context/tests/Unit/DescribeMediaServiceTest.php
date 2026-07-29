<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Api\DescribeHostInterface;
use AltContext\Api\Services\DescribeMediaService;
use AltContext\Api\Services\DescriptionBudgetService;
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
            'tier'                   => 'provisional_cpu',
            'result_generation'      => 0,
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
        $service = new DescribeMediaService($host, null, $repo);

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

        $usage = (new DescriptionBudgetService())->usage_summary();
        $this->assertSame(1, $usage['attempts']);
        $this->assertSame(1, $usage['successes']);
        $this->assertSame(0, $usage['failures']);
    }

    public function testRegisterRoutesExposesWriteIntentArgs(): void
    {
        $this->controller->register_routes();

        $route = null;
        foreach ($GLOBALS['__ac_rest_routes'] as $definition) {
            if (($definition['namespace'] ?? null) === 'acx/v1' && ($definition['route'] ?? null) === '/recognition/describe') {
                $route = $definition;
                break;
            }
        }

        $this->assertIsArray($route);
        $args = $route['args']['args'] ?? array();
        $this->assertArrayHasKey('media_id', $args);
        $this->assertArrayHasKey('write_alt', $args);
        $this->assertSame('boolean', $args['write_alt']['type'] ?? null);
        $this->assertFalse($args['write_alt']['default'] ?? true);
        $this->assertArrayHasKey('force', $args);
        $this->assertSame('boolean', $args['force']['type'] ?? null);
        $this->assertFalse($args['force']['default'] ?? true);
    }

    public function testPreviewOnlyDoesNotWriteAltTextOrProvenance(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));
        $this->assertArrayNotHasKey('alt_text_write', $result->get_data());
    }

    public function testWriteIntentPersistsMissingAltTextAndProvenance(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('written', $result->get_data()['alt_text_write']['status'] ?? null);

        $writtenAlt = get_post_meta(42, '_wp_attachment_image_alt', true);
        $this->assertSame('A photo.', $writtenAlt);

        $provenance = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($provenance);
        $this->assertSame('seeded', $provenance['adapter']);
        $this->assertSame('seeded-fixtures', $provenance['model_id']);
        $this->assertSame('1', $provenance['model_version']);
        $this->assertSame('1', $provenance['prompt_or_task_version']);
        $this->assertSame(str_repeat('a', 64), $provenance['image_hash']);
        $this->assertSame(str_repeat('b', 64), $provenance['context_hash']);
        $this->assertArrayHasKey('generated_at', $provenance);
        // BR-100: history resolves Generated-alt from this key — must equal the
        // exact string written to _wp_attachment_image_alt, not a re-derivation.
        $this->assertSame($writtenAlt, $provenance['alt_text_draft']);
        $this->assertSame('A photo.', $provenance['alt_text_draft']);
    }

    public function testWriteIntentSkipsExistingAltTextByDefault(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'Human-authored alt');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('Human-authored alt', get_post_meta(42, '_wp_attachment_image_alt', true));
        // No alt write → no provenance envelope at all (no fabricated alt_text_draft).
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));
        $this->assertSame('skipped_existing_alt', $result->get_data()['alt_text_write']['status'] ?? null);
    }

    /**
     * BR-108: force no-op on a pre-wave envelope (no alt_text_draft key) still
     * fires (identity match is draft-free) and heals the draft key into place
     * without restamping generated_at or rewriting the rest of the envelope.
     */
    public function testForceNoOpHealsMissingAltTextDraftOnPreWaveEnvelope(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
        // Prior envelope deliberately omits alt_text_draft (pre-wave shape).
        $existingProvenance = array(
            'adapter'                => 'seeded',
            'model_id'               => 'seeded-fixtures',
            'model_version'          => '1',
            'prompt_or_task_version' => '1',
            'image_hash'             => str_repeat('a', 64),
            'context_hash'           => str_repeat('b', 64),
            'generated_at'           => '2026-01-01T00:00:00+00:00',
        );
        $this->setPostMeta(42, '_acx_description_provenance', $existingProvenance);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $req->set_param('force', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('forced_overwrite', $result->get_data()['alt_text_write']['status'] ?? null);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));

        $healed = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($healed);
        // Draft key healed; identity + generated_at preserved (not a full restamp).
        $this->assertSame('A photo.', $healed['alt_text_draft']);
        $this->assertSame('2026-01-01T00:00:00+00:00', $healed['generated_at']);
        $this->assertSame('seeded', $healed['adapter']);
        $this->assertSame(str_repeat('a', 64), $healed['image_hash']);
    }

    /**
     * BR-108: force no-op with a stale alt_text_draft corrects the key so the
     * audit trail matches the draft the operator actually has in alt meta.
     */
    public function testForceNoOpCorrectsStaleAltTextDraft(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
        $existingProvenance = array(
            'adapter'                => 'seeded',
            'model_id'               => 'seeded-fixtures',
            'model_version'          => '1',
            'prompt_or_task_version' => '1',
            'image_hash'             => str_repeat('a', 64),
            'context_hash'           => str_repeat('b', 64),
            'generated_at'           => '2026-01-01T00:00:00+00:00',
            'alt_text_draft'         => 'STALE DRAFT',
        );
        $this->setPostMeta(42, '_acx_description_provenance', $existingProvenance);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $req->set_param('force', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('forced_overwrite', $result->get_data()['alt_text_write']['status'] ?? null);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));

        $healed = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($healed);
        $this->assertSame('A photo.', $healed['alt_text_draft']);
        $this->assertNotSame('STALE DRAFT', $healed['alt_text_draft']);
        // Rest of envelope stable.
        $this->assertSame('2026-01-01T00:00:00+00:00', $healed['generated_at']);
        $this->assertSame('seeded-fixtures', $healed['model_id']);
    }

    /**
     * BR-104: empty alt_text_draft must not write alt meta or provenance, and
     * must report skipped_empty_alt_text (CLI parity).
     */
    public function testWriteIntentSkipsEmptyAltTextDraft(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $body = $this->validBackendBody(42);
        $body['alt_text_draft'] = '';
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());
        $this->assertSame('skipped_empty_alt_text', $result->get_data()['alt_text_write']['status'] ?? null);
        $this->assertSame('', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));
    }

    /**
     * BR-104: force=true with an empty draft must not clear a human-authored alt.
     * Pre-fix this reported written and stored '' — irreversible data loss.
     */
    public function testForceWriteDoesNotClearHumanAltOnEmptyDraft(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'Human-authored alt');
        $body = $this->validBackendBody(42);
        $body['alt_text_draft'] = '   ';
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $req->set_param('force', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('skipped_empty_alt_text', $result->get_data()['alt_text_write']['status'] ?? null);
        $this->assertTrue($result->get_data()['alt_text_write']['existing_alt_present'] ?? false);
        $this->assertSame('Human-authored alt', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));
    }

    /**
     * BR-116: non-string alt_text_draft is a boundary violation (502), not
     * silently coerced to '' (REST) or '42' (CLI cast).
     */
    public function testNonStringAltTextDraftReturns502(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $body = $this->validBackendBody(42);
        $body['alt_text_draft'] = 42;
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('invalid_description_envelope', $result->get_error_code());
        $this->assertSame(502, $result->get_error_data()['status'] ?? null);
        $this->assertStringContainsString('alt_text_draft', $result->get_error_message());
        $this->assertSame('', get_post_meta(42, '_wp_attachment_image_alt', true));
    }

    public function testForceWriteOverwritesExistingAltTextAndStoresProvenance(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'Human-authored alt');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $req->set_param('force', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('forced_overwrite', $result->get_data()['alt_text_write']['status'] ?? null);
        $this->assertIsArray(get_post_meta(42, '_acx_description_provenance', true));
    }

    public function testForceWritePreservesMatchingGeneratedProvenance(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
        // Envelope already carries the correct draft — no-op must leave it byte-identical.
        $existingProvenance = array(
            'adapter'                => 'seeded',
            'model_id'               => 'seeded-fixtures',
            'model_version'          => '1',
            'prompt_or_task_version' => '1',
            'image_hash'             => str_repeat('a', 64),
            'context_hash'           => str_repeat('b', 64),
            'generated_at'           => '2026-01-01T00:00:00+00:00',
            'alt_text_draft'         => 'A photo.',
        );
        $this->setPostMeta(42, '_acx_description_provenance', $existingProvenance);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $req->set_param('write_alt', true);
        $req->set_param('force', true);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame($existingProvenance, get_post_meta(42, '_acx_description_provenance', true));
        $this->assertSame('forced_overwrite', $result->get_data()['alt_text_write']['status'] ?? null);
    }

    /**
     * BR-116: shared normaliser is the single definition for draft coercion.
     */
    public function testNormalizeAltTextDraftTrimsStringsAndRejectsNonStringsAsEmpty(): void
    {
        $this->assertSame('A photo.', DescribeMediaService::normalize_alt_text_draft('  A photo.  '));
        $this->assertSame('', DescribeMediaService::normalize_alt_text_draft(''));
        $this->assertSame('', DescribeMediaService::normalize_alt_text_draft('   '));
        $this->assertSame('', DescribeMediaService::normalize_alt_text_draft(42));
        $this->assertSame('', DescribeMediaService::normalize_alt_text_draft(null));
        $this->assertSame('', DescribeMediaService::normalize_alt_text_draft(array('nope')));
    }

    /**
     * @return array<string,mixed>
     */
    private function validBackendBodyWithLong(int $media_id, string $long = 'A tabby cat lounging on a woven mat in warm afternoon light.'): array
    {
        $body = $this->validBackendBody($media_id);
        $body['alt_text_long'] = $long;
        return $body;
    }

    private function plantWritableAttachment(int $id): void
    {
        $this->plantAttachment($id, "\xff\xd8\xff\xe0bytes", 'jpg');
        // plantAttachment seeds a non-empty description; description-write
        // tests start from the common empty-description state.
        $GLOBALS['__ac_posts'][$id]->post_content = '';
    }

    private function writeRequest(int $media_id, bool $force = false): WP_REST_Request
    {
        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', $media_id);
        $req->set_param('write_alt', true);
        if ($force) {
            $req->set_param('force', true);
        }
        return $req;
    }

    public function testAltPlusDescriptionWritesLongToAttachmentDescription(): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame(
            'A tabby cat lounging on a woven mat in warm afternoon light.',
            $GLOBALS['__ac_posts'][42]->post_content
        );
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('written', $write['status']);
        $this->assertSame('written', $write['description_write'] ?? null);
    }

    public function testAltStyleDefaultNeverWritesDescriptionEvenWhenLongPresent(): void
    {
        // Option unset -> alt_only default = current behavior byte-identical.
        $this->plantWritableAttachment(42);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', $GLOBALS['__ac_posts'][42]->post_content);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('written', $write['status']);
        $this->assertArrayNotHasKey('description_write', $write);
    }

    public function testInvalidAltStyleValueDegradesToAltOnly(): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'bogus_style');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('', $GLOBALS['__ac_posts'][42]->post_content);
        $this->assertArrayNotHasKey('description_write', $result->get_data()['alt_text_write']);
    }

    public function testAltPlusDescriptionWithoutLongTextSkipsDescriptionWrite(): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', $GLOBALS['__ac_posts'][42]->post_content);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('written', $write['status']);
        $this->assertSame('skipped_no_long_text', $write['description_write'] ?? null);
    }

    public function testAltPlusDescriptionSkipsExistingDescriptionWithoutForce(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg'); // description pre-filled
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('A long description.', $GLOBALS['__ac_posts'][42]->post_content);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('written', $write['status']);
        $this->assertSame('skipped_existing_description', $write['description_write'] ?? null);
    }

    public function testAltPlusDescriptionForceOverwritesExistingDescription(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg'); // description pre-filled
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42, true));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(
            'A tabby cat lounging on a woven mat in warm afternoon light.',
            $GLOBALS['__ac_posts'][42]->post_content
        );
        $this->assertSame('forced_overwrite', $result->get_data()['alt_text_write']['description_write'] ?? null);
    }

    public function testSkippedExistingAltAlsoSkipsDescriptionWrite(): void
    {
        $this->plantWritableAttachment(42);
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'Human-authored alt');
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('', $GLOBALS['__ac_posts'][42]->post_content);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('skipped_existing_alt', $write['status']);
        $this->assertArrayNotHasKey('description_write', $write);
    }

    public function testPreviewNeverWritesDescriptionEvenWithLongAndStyle(): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('', $GLOBALS['__ac_posts'][42]->post_content);
        $this->assertArrayNotHasKey('alt_text_write', $result->get_data());
        // Optional upstream field passes through untouched (rg-015).
        $this->assertSame(
            'A tabby cat lounging on a woven mat in warm afternoon light.',
            $result->get_data()['alt_text_long']
        );
    }

    public function testRegistersAndServesMissingAltDryRunWithoutBackendCall(): void
    {
        $GLOBALS['__ac_posts'][42] = (object) array('ID' => 42, 'post_title' => 'Missing');
        $GLOBALS['__ac_get_posts_results'][] = $GLOBALS['__ac_posts'][42];
        $GLOBALS['__ac_attachment_mimes'][42] = 'image/jpeg';
        $GLOBALS['__ac_attached_file'][42] = $this->tempDir . '/42-missing.jpg';
        $GLOBALS['__ac_post_meta'][42]['_wp_attachment_image_alt'] = '';

        $this->controller->register_routes();

        $route = null;
        foreach ($GLOBALS['__ac_rest_routes'] as $definition) {
            if (($definition['namespace'] ?? null) === 'acx/v1' && ($definition['route'] ?? null) === '/recognition/describe/candidates') {
                $route = $definition;
                break;
            }
        }

        $this->assertIsArray($route);
        $this->assertSame('GET', $route['args']['methods'] ?? null);
        $this->assertArrayHasKey('limit', $route['args']['args'] ?? array());
        $this->assertArrayHasKey('offset', $route['args']['args'] ?? array());

        $req = new WP_REST_Request('GET', '/acx/v1/recognition/describe/candidates');
        $req->set_param('limit', 10);
        $req->set_param('offset', 0);
        $result = $this->controller->list_description_candidates($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());
        $this->assertSame(array(42), array_column($result->get_data()['candidates'], 'media_id'));
        $this->assertSame(array(), $this->getHttpCalls());
    }

    public function testBuildsBoundedContextPackFromAttachmentParentTermsAndProductMeta(): void
    {
        $bytes = "\xff\xd8\xff\xe0fake-jpeg-bytes";
        $this->plantAttachment(42, $bytes, 'jpg');
        $GLOBALS['__ac_posts'][42]->post_parent = 77;
        $GLOBALS['__ac_posts'][77] = (object) array(
            'ID'           => 77,
            'post_title'   => 'Trail jackets for spring',
            'post_excerpt' => 'Lightweight red jackets for spring hikes.',
            'post_content' => 'Private body should not travel.',
            'post_type'    => 'product',
            'post_status'  => 'publish',
        );
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'Model in a red jacket');
        $this->setPostMeta(77, '_sku', 'JKT-RED-1');
        $this->setPostMeta(77, '_price', '129.00');

        $term = wp_insert_term('Jackets', 'product_cat', array('slug' => 'jackets'));
        wp_set_object_terms(77, array($term['term_id']), 'product_cat');

        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $body = $this->getHttpCalls()[0]['args']['body'];
        preg_match('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body, $m);
        $contextPack = json_decode($m[1], true)['context_pack'];

        $this->assertSame('Photo 42', $contextPack['attachment']['title']);
        $this->assertSame('A caption.', $contextPack['attachment']['caption']);
        $this->assertSame('Model in a red jacket', $contextPack['attachment']['alt_text']);
        $this->assertSame('Trail jackets for spring', $contextPack['post']['title']);
        $this->assertSame('product', $contextPack['post']['post_type']);
        $this->assertSame('publish', $contextPack['post']['status']);
        $this->assertArrayNotHasKey('description', $contextPack['post']);
        $this->assertSame('Jackets', $contextPack['taxonomy_terms'][0]['name']);
        $this->assertSame('JKT-RED-1', $contextPack['product']['sku']);
        $this->assertSame('129.00', $contextPack['product']['price']);
    }

    public function testContextPackExcludesNonPublicParentPostContent(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $GLOBALS['__ac_posts'][42]->post_parent = 77;
        $GLOBALS['__ac_posts'][77] = (object) array(
            'ID'           => 77,
            'post_title'   => 'Draft product',
            'post_excerpt' => 'Draft teaser',
            'post_type'    => 'product',
            'post_status'  => 'draft',
        );

        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $this->controller->describe_media($req);

        $body = $this->getHttpCalls()[0]['args']['body'];
        preg_match('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body, $m);
        $contextPack = json_decode($m[1], true)['context_pack'];

        $this->assertArrayNotHasKey('post', $contextPack);
        $this->assertArrayNotHasKey('product', $contextPack);
    }

    public function testContextPackTruncatesMultibyteTextWithoutBreakingJson(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $GLOBALS['__ac_posts'][42]->post_title = str_repeat('€', 170);

        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $this->controller->describe_media($req);

        $body = $this->getHttpCalls()[0]['args']['body'];
        preg_match('/name="request".*?\r\n\r\n(\{.*?\})\r\n/s', $body, $m);
        $envelope = json_decode($m[1], true);

        $this->assertIsArray($envelope);
        $this->assertSame(str_repeat('€', 160), $envelope['context_pack']['attachment']['title']);
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

    public function testBudgetLimitBlocksBeforeBackendDispatch(): void
    {
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');
        $this->setOption('acx_description_budget_max_attempts', 0);

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', 42);
        $result = $this->controller->describe_media($req);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_budget_attempt_limit_exceeded', $result->get_error_code());
        $this->assertSame(429, $result->get_error_data()['status'] ?? null);
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

    public function testMissingTierFieldsInUpstreamEnvelopeReturns502(): void
    {
        // HARM-02: backend regression dropping VLM-3 wire fields must 502, not pass through.
        $this->plantAttachment(42, "\xff\xd8\xff\xe0bytes", 'jpg');

        $body = $this->validBackendBody(42);
        unset($body['tier'], $body['result_generation']);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
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

        $usage = (new DescriptionBudgetService())->usage_summary();
        $errors = (new DescriptionBudgetService())->recent_errors();
        $this->assertSame(1, $usage['attempts']);
        $this->assertSame(1, $usage['failures']);
        $this->assertSame('upstream_http_415', $errors[0]['error_code']);
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
