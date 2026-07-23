<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\AttachmentFields;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Admin\AttachmentFields
 */
class AttachmentFieldsTest extends TestCase
{
    private AttachmentFields $fields;

    protected function setUp(): void
    {
        parent::setUp();
        $this->fields = new AttachmentFields();
    }

    public function testRegisterFieldsAddsContainerForImageAttachmentWithManageOptions(): void
    {
        $this->setUserCapability('manage_options', true);
        $GLOBALS['__ac_attachment_mimes'][42] = 'image/jpeg';

        $post = (object) ['ID' => 42, 'post_type' => 'attachment'];
        $result = $this->fields->register_fields([], $post);

        $this->assertArrayHasKey('acx_attachment_faces', $result);
        $field = $result['acx_attachment_faces'];
        $this->assertSame('html', $field['input'] ?? null);
        $this->assertFalse($field['show_in_modal'] ?? true);
        $this->assertStringContainsString('id="acx-attachment-faces"', (string) ($field['html'] ?? ''));
        $this->assertStringContainsString('data-attachment-id="42"', (string) ($field['html'] ?? ''));
        $this->assertStringContainsString(' hidden', (string) ($field['html'] ?? ''));
    }

    /**
     * Red-path ([TEST-15]): flipping show_in_modal to true must fail this assertion.
     */
    public function testRegisterFieldsShowInModalIsFalse(): void
    {
        $this->setUserCapability('manage_options', true);
        $GLOBALS['__ac_attachment_mimes'][7] = 'image/png';

        $result = $this->fields->register_fields([], (object) ['ID' => 7]);
        $this->assertArrayHasKey('acx_attachment_faces', $result);
        $this->assertFalse($result['acx_attachment_faces']['show_in_modal']);
        // Mutation-flip guard: the production field must not opt into the media modal.
        $this->assertNotSame(true, $result['acx_attachment_faces']['show_in_modal']);
    }

    public function testRegisterFieldsAbsentForNonImageAttachment(): void
    {
        $this->setUserCapability('manage_options', true);
        $GLOBALS['__ac_attachment_mimes'][9] = 'application/pdf';

        $result = $this->fields->register_fields(['existing' => ['label' => 'x']], (object) ['ID' => 9]);

        $this->assertArrayNotHasKey('acx_attachment_faces', $result);
        $this->assertArrayHasKey('existing', $result);
    }

    public function testRegisterFieldsAbsentWithoutManageOptions(): void
    {
        $this->setUserCapability('manage_options', false);
        $GLOBALS['__ac_attachment_mimes'][3] = 'image/jpeg';

        $result = $this->fields->register_fields([], (object) ['ID' => 3]);

        $this->assertArrayNotHasKey('acx_attachment_faces', $result);
    }

    public function testInitHooksAttachmentFieldsToEdit(): void
    {
        $this->fields->init();

        $this->assertArrayHasKey('attachment_fields_to_edit', $GLOBALS['__ac_filters']);
        $callbacks = $GLOBALS['__ac_filters']['attachment_fields_to_edit'][10] ?? [];
        $this->assertNotEmpty($callbacks);
    }
}
