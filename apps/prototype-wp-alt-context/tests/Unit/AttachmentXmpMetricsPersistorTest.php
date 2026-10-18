<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Media\AttachmentXmpMetricsPersistor;
use AltContext\Media\FaceMetricsSourceInterface;
use AltContext\Media\ImageXmpWriter;
use AltContext\Media\JpegXmpInjector;
use AltContext\Media\PngXmpInjector;
use AltContext\Media\XmpImageRegionPacketBuilder;
use AltContext\Tests\TestCase;
use DOMDocument;

/**
 * @covers \AltContext\Media\AttachmentXmpMetricsPersistor
 * @covers \AltContext\Media\ImageXmpWriter
 */
class AttachmentXmpMetricsPersistorTest extends TestCase
{
    /** @var string[] */
    private array $tempFiles = [];

    protected function tearDown(): void
    {
        foreach ($this->tempFiles as $path) {
            if (is_string($path) && file_exists($path)) {
                unlink($path);
            }
        }

        $this->tempFiles = [];
        parent::tearDown();
    }

    public function testPersistForAttachmentWritesXmpToOriginalOnly(): void
    {
        $attachmentId = 55;
        $originalPath = $this->createTempImageFile('acx-original', '.jpg', $this->buildMinimalJpeg());
        $thumbnailPath = $this->createTempImageFile('acx-thumb', '.jpg', 'THUMBNAIL');

        $GLOBALS['__ac_attached_file'][$attachmentId] = $originalPath;
        $GLOBALS['__ac_attachment_mimes'][$attachmentId] = 'image/jpeg';
        $GLOBALS['__ac_attachment_metadata'][$attachmentId] = [
            'width' => 1000,
            'height' => 500,
            'sizes' => [
                'thumbnail' => [
                    'file' => basename($thumbnailPath),
                ],
            ],
        ];

        $source = new class() implements FaceMetricsSourceInterface {
            public function get_identities_for_attachment(int $attachment_id): array
            {
                return [
                    [
                        'media_id' => $attachment_id,
                        'cluster_label' => 'Daniel',
                        'bbox' => [
                            'x' => 320,
                            'y' => 75,
                            'width' => 180,
                            'height' => 120,
                        ],
                        'debug_metrics' => [
                            'pose' => [
                                'pitch' => -12.3,
                                'yaw' => 8.7,
                                'roll' => -2.1,
                            ],
                            'det_score' => 0.94,
                            'landmark_quality' => 0.87,
                        ],
                    ],
                ];
            }
        };

        $persistor = new AttachmentXmpMetricsPersistor(
            new ImageXmpWriter(
                $source,
                new XmpImageRegionPacketBuilder(),
                new JpegXmpInjector(),
                new PngXmpInjector()
            )
        );

        $persistor->persist_for_attachment($attachmentId, 'job-abc');

        $updatedOriginal = file_get_contents($originalPath);
        $this->assertIsString($updatedOriginal);
        $this->assertStringContainsString('http://ns.adobe.com/xap/1.0/', $updatedOriginal);

        $packet = (new JpegXmpInjector())->extract_packet($updatedOriginal);
        $this->assertIsString($packet);

        $dom = new DOMDocument();
        $this->assertTrue($dom->loadXML($packet));

        $rbX = $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::IPTC_NS, 'rbX')->item(0)?->textContent;
        $name = $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::IPTC_NS, 'Name')->item(0)?->textContent;
        $pitch = $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::ACX_NS, 'Pitch')->item(0)?->textContent;
        $yaw = $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::ACX_NS, 'Yaw')->item(0)?->textContent;
        $roll = $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::ACX_NS, 'Roll')->item(0)?->textContent;
        $detScore = $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::ACX_NS, 'DetScore')->item(0)?->textContent;
        $landmarkQuality = $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::ACX_NS, 'LandmarkQuality')->item(0)?->textContent;

        $this->assertSame('0.41', $rbX);
        $this->assertSame('Daniel', $name);
        $this->assertSame('-12.3', $pitch);
        $this->assertSame('8.7', $yaw);
        $this->assertSame('-2.1', $roll);
        $this->assertSame('0.94', $detScore);
        $this->assertSame('0.87', $landmarkQuality);

        $this->assertSame('THUMBNAIL', file_get_contents($thumbnailPath));

        $resultMeta = $GLOBALS['__ac_post_meta'][$attachmentId]['acx_xmp_persist_last_result'] ?? null;
        $this->assertIsArray($resultMeta);
        $this->assertSame('written', $resultMeta['status'] ?? null);
    }

    public function testPersistForAttachmentSkipsWhenIdentityHasNoLabel(): void
    {
        $attachmentId = 56;
        $originalContent = $this->buildMinimalJpeg();
        $originalPath = $this->createTempImageFile('acx-original-unlabeled', '.jpg', $originalContent);

        $GLOBALS['__ac_attached_file'][$attachmentId] = $originalPath;
        $GLOBALS['__ac_attachment_mimes'][$attachmentId] = 'image/jpeg';
        $GLOBALS['__ac_attachment_metadata'][$attachmentId] = [
            'width' => 100,
            'height' => 100,
        ];

        $source = new class() implements FaceMetricsSourceInterface {
            public function get_identities_for_attachment(int $attachment_id): array
            {
                return [
                    [
                        'media_id' => $attachment_id,
                        'cluster_label' => null,
                        'bbox' => [
                            'x' => 10,
                            'y' => 10,
                            'width' => 10,
                            'height' => 10,
                        ],
                        'debug_metrics' => [
                            'pose' => ['pitch' => 0, 'yaw' => 0, 'roll' => 0],
                            'det_score' => 0.5,
                            'landmark_quality' => 0.5,
                        ],
                    ],
                ];
            }
        };

        $persistor = new AttachmentXmpMetricsPersistor(
            new ImageXmpWriter(
                $source,
                new XmpImageRegionPacketBuilder(),
                new JpegXmpInjector(),
                new PngXmpInjector()
            )
        );

        $persistor->persist_for_attachment($attachmentId, 'job-empty');

        $this->assertSame($originalContent, file_get_contents($originalPath));

        $resultMeta = $GLOBALS['__ac_post_meta'][$attachmentId]['acx_xmp_persist_last_result'] ?? null;
        $this->assertIsArray($resultMeta);
        $this->assertSame('skipped', $resultMeta['status'] ?? null);
    }

    public function testPersistForAttachmentSkipsAutoLabelsEvenWhenLabelIsHumanReadable(): void
    {
        $clusterId = 'f2b2e8b5-cc20-4c74-94d4-bf76ff0f0bd7';
        $this->assertIdentitySkipForCurationGate(
            [
                'cluster_id' => $clusterId,
                'cluster_label' => 'Daniel Arce',
                'is_auto_label' => true,
            ],
            57,
            'job-auto-label'
        );
    }

    public function testPersistForAttachmentSkipsWhenLabelMatchesClusterId(): void
    {
        $clusterId = '5eec87ba-7a71-4a95-a4d8-3f4d4fb95f12';
        $this->assertIdentitySkipForCurationGate(
            [
                'cluster_id' => $clusterId,
                'cluster_label' => $clusterId,
                'is_auto_label' => false,
            ],
            58,
            'job-label-equals-cluster-id'
        );
    }

    public function testPersistForAttachmentSkipsUuidLookingLabelsEvenWhenClusterIdDiffers(): void
    {
        $clusterId = 'f2b2e8b5-cc20-4c74-94d4-bf76ff0f0bd7';
        $uuidLikeLabel = 'd4f95da7-cf37-44de-8d63-61f6312b3370';
        $this->assertIdentitySkipForCurationGate(
            [
                'cluster_id' => $clusterId,
                'cluster_label' => $uuidLikeLabel,
                'is_auto_label' => false,
            ],
            59,
            'job-uuid-label'
        );
    }

    public function testEmbedForMediaIdsReturnsProcessedSkippedAndFailedCounts(): void
    {
        $successId = 70;
        $skippedId = 71;

        $successPath = $this->createTempImageFile('acx-batch-success', '.jpg', $this->buildMinimalJpeg());
        $GLOBALS['__ac_attached_file'][$successId] = $successPath;
        $GLOBALS['__ac_attachment_mimes'][$successId] = 'image/jpeg';
        $GLOBALS['__ac_attachment_metadata'][$successId] = [
            'width' => 100,
            'height' => 100,
        ];

        $source = new class() implements FaceMetricsSourceInterface {
            public function get_identities_for_attachment(int $attachment_id): array
            {
                if ($attachment_id !== 70) {
                    return [];
                }

                return [
                    [
                        'media_id' => 70,
                        'cluster_label' => 'Label',
                        'bbox' => [
                            'x' => 5,
                            'y' => 5,
                            'width' => 10,
                            'height' => 10,
                        ],
                        'debug_metrics' => [
                            'pose' => ['pitch' => 1, 'yaw' => 2, 'roll' => 3],
                            'det_score' => 0.8,
                            'landmark_quality' => 0.9,
                        ],
                    ],
                ];
            }
        };

        $persistor = new AttachmentXmpMetricsPersistor(
            new ImageXmpWriter(
                $source,
                new XmpImageRegionPacketBuilder(),
                new JpegXmpInjector(),
                new PngXmpInjector()
            )
        );

        $summary = $persistor->embed_for_media_ids([$successId, $successId, $skippedId, 0]);

        $this->assertSame(['processed' => 1, 'skipped' => 1, 'failed' => 0], $summary);
    }

    private function createTempImageFile(string $prefix, string $extension, string $contents): string
    {
        $path = tempnam(sys_get_temp_dir(), $prefix);
        if ($path === false) {
            $this->fail('Failed to create temporary file.');
        }

        $target = $path . $extension;
        rename($path, $target);
        file_put_contents($target, $contents);
        $this->tempFiles[] = $target;

        return $target;
    }

    /**
     * @param array<string,mixed> $identityOverrides
     */
    private function assertIdentitySkipForCurationGate(array $identityOverrides, int $attachmentId, string $jobId): void
    {
        $originalContent = $this->buildMinimalJpeg();
        $originalPath = $this->createTempImageFile('acx-original-curation-gate', '.jpg', $originalContent);

        $GLOBALS['__ac_attached_file'][$attachmentId] = $originalPath;
        $GLOBALS['__ac_attachment_mimes'][$attachmentId] = 'image/jpeg';
        $GLOBALS['__ac_attachment_metadata'][$attachmentId] = [
            'width' => 200,
            'height' => 200,
        ];

        $identity = array_merge(
            [
                'media_id' => $attachmentId,
                'cluster_id' => null,
                'cluster_label' => null,
                'is_auto_label' => false,
                'bbox' => [
                    'x' => 10,
                    'y' => 10,
                    'width' => 20,
                    'height' => 20,
                ],
                'debug_metrics' => [
                    'pose' => ['pitch' => 1, 'yaw' => 2, 'roll' => 3],
                    'det_score' => 0.7,
                    'landmark_quality' => 0.8,
                ],
            ],
            $identityOverrides
        );

        $source = new class($identity) implements FaceMetricsSourceInterface {
            /** @var array<string,mixed> */
            private array $identity;

            /**
             * @param array<string,mixed> $identity
             */
            public function __construct(array $identity)
            {
                $this->identity = $identity;
            }

            public function get_identities_for_attachment(int $attachment_id): array
            {
                $identity = $this->identity;
                $identity['media_id'] = $attachment_id;
                return [$identity];
            }
        };

        $persistor = new AttachmentXmpMetricsPersistor(
            new ImageXmpWriter(
                $source,
                new XmpImageRegionPacketBuilder(),
                new JpegXmpInjector(),
                new PngXmpInjector()
            )
        );

        $persistor->persist_for_attachment($attachmentId, $jobId);

        $this->assertSame($originalContent, file_get_contents($originalPath));

        $resultMeta = $GLOBALS['__ac_post_meta'][$attachmentId]['acx_xmp_persist_last_result'] ?? null;
        $this->assertIsArray($resultMeta);
        $this->assertSame('skipped', $resultMeta['status'] ?? null);
    }

    private function buildMinimalJpeg(): string
    {
        $app0 = "\xFF\xE0" . pack('n', 16) . "JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00";
        return "\xFF\xD8" . $app0 . "\xFF\xDA\x00\x08" . str_repeat("\x00", 6) . 'IMG' . "\xFF\xD9";
    }
}
