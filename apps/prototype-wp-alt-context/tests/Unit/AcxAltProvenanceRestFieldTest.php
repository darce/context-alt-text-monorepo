<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\Api
 */
class AcxAltProvenanceRestFieldTest extends TestCase
{
    private const FULL_ENVELOPE = [
        'adapter' => 'seeded',
        'model_id' => 'seeded-v1',
        'model_version' => '1.0',
        'prompt_or_task_version' => 'task-3',
        'image_hash' => 'abc123',
        'context_hash' => 'def456',
        'generated_at' => '2026-08-25T00:00:00+00:00',
        'alt_text_draft' => 'A photograph of a lake.',
        'backend_result_id' => 'res-1',
    ];

    public function testRegisterRoutesExposesReadOnlyAltProvenanceField(): void
    {
        $api = new Api();
        $api->register_routes();

        $field = $this->findRegisteredField('attachment', 'acx_alt_provenance');
        $this->assertNotNull($field);
        $this->assertArrayHasKey('get_callback', $field['args']);
        $this->assertIsCallable($field['args']['get_callback']);
        $this->assertArrayNotHasKey('update_callback', $field['args']);
        $this->assertArrayHasKey('schema', $field['args']);
        $this->assertTrue($field['args']['schema']['readonly'] ?? false);
        $this->assertSame(
            ['adapter', 'model_id'],
            array_keys($field['args']['schema']['properties'] ?? [])
        );
    }

    public function testAbsentMetaProjectsNull(): void
    {
        $this->assertNull($this->projectForAttachment(11));
    }

    public function testArrayMetaProjectsAdapterAndModelIdOnly(): void
    {
        $this->setPostMeta(11, '_acx_description_provenance', self::FULL_ENVELOPE);

        $projection = $this->projectForAttachment(11);

        $this->assertSame(
            [
                'adapter' => 'seeded',
                'model_id' => 'seeded-v1',
            ],
            $projection
        );
        $this->assertSame(['adapter', 'model_id'], array_keys($projection));
        $this->assertArrayNotHasKey('image_hash', $projection);
        $this->assertArrayNotHasKey('context_hash', $projection);
        $this->assertArrayNotHasKey('backend_result_id', $projection);
        $this->assertArrayNotHasKey('alt_text_draft', $projection);
        $this->assertArrayNotHasKey('generated_at', $projection);
        $this->assertArrayNotHasKey('model_version', $projection);
        $this->assertArrayNotHasKey('prompt_or_task_version', $projection);
    }

    public function testJsonStringMetaDecodesThenProjects(): void
    {
        $this->setPostMeta(11, '_acx_description_provenance', json_encode(self::FULL_ENVELOPE));

        $projection = $this->projectForAttachment(11);

        $this->assertSame(
            [
                'adapter' => 'seeded',
                'model_id' => 'seeded-v1',
            ],
            $projection
        );
        $this->assertSame(['adapter', 'model_id'], array_keys($projection));
    }

    public function testEmptyAdapterProjectsNull(): void
    {
        $this->setPostMeta(
            11,
            '_acx_description_provenance',
            ['adapter' => '', 'model_id' => 'seeded-v1']
        );

        $this->assertNull($this->projectForAttachment(11));
    }

    public function testWhitespaceAdapterProjectsNull(): void
    {
        $this->setPostMeta(
            11,
            '_acx_description_provenance',
            ['adapter' => "  \t", 'model_id' => 'seeded-v1']
        );

        $this->assertNull($this->projectForAttachment(11));
    }

    public function testMissingAdapterKeyProjectsNull(): void
    {
        $this->setPostMeta(
            11,
            '_acx_description_provenance',
            ['model_id' => 'seeded-v1']
        );

        $this->assertNull($this->projectForAttachment(11));
    }

    public function testMissingModelIdKeepsAdapterAndNullModelId(): void
    {
        $this->setPostMeta(
            11,
            '_acx_description_provenance',
            ['adapter' => 'seeded']
        );

        $projection = $this->projectForAttachment(11);

        $this->assertSame(
            [
                'adapter' => 'seeded',
                'model_id' => null,
            ],
            $projection
        );
        $this->assertSame(['adapter', 'model_id'], array_keys($projection));
    }

    /**
     * @return array{adapter: string, model_id: string|null}|null
     */
    private function projectForAttachment(int $attachmentId): mixed
    {
        $api = new Api();
        $api->register_routes();
        $field = $this->findRegisteredField('attachment', 'acx_alt_provenance');
        $this->assertNotNull($field);
        $callback = $field['args']['get_callback'] ?? null;
        $this->assertIsCallable($callback);

        return $callback(['id' => $attachmentId], 'acx_alt_provenance', null, 'attachment');
    }

    /**
     * @return array<string,mixed>|null
     */
    private function findRegisteredField(string $objectType, string $attribute): ?array
    {
        foreach ($GLOBALS['__ac_rest_fields'] ?? [] as $definition) {
            if (!is_array($definition)) {
                continue;
            }
            if (
                ($definition['object_type'] ?? null) === $objectType
                && ($definition['attribute'] ?? null) === $attribute
            ) {
                return $definition;
            }
        }

        return null;
    }
}
