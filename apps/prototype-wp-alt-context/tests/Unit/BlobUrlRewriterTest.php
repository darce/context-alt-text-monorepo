<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\BlobUrlRewriter;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\BlobUrlRewriter
 */
class BlobUrlRewriterTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__ac_attachment_urls'] = [];
    }

    protected function tearDown(): void
    {
        $GLOBALS['__ac_attachment_urls'] = [];
        parent::tearDown();
    }

    public function testReturnsWpAttachmentUrlWhenMediaIdResolvesToAttachment(): void
    {
        $GLOBALS['__ac_attachment_urls'][6717] = 'http://example.test/wp-content/uploads/2025/12/face-6717.jpg';

        $rewritten = BlobUrlRewriter::rewrite_string('/recognition/blobs/job-x/6717');

        $this->assertSame(
            'http://example.test/wp-content/uploads/2025/12/face-6717.jpg',
            $rewritten
        );
    }

    public function testFallsBackToSignedUrlWhenMediaIdHasNoWpAttachment(): void
    {
        $rewritten = BlobUrlRewriter::rewrite_string('/recognition/blobs/job-x/9999');

        $parts = \parse_url($rewritten);
        $this->assertSame('/wp-json/acx/v1/recognition/blobs/job-x/9999', $parts['path']);
        $query = [];
        \parse_str($parts['query'] ?? '', $query);
        $this->assertArrayHasKey('token', $query);
    }

    public function testFallsBackToSignedUrlWhenMediaIdNotNumeric(): void
    {
        $GLOBALS['__ac_attachment_urls']['abc'] = 'http://should-not-be-used.test/x.jpg';

        $rewritten = BlobUrlRewriter::rewrite_string('/recognition/blobs/job-x/abc');

        $parts = \parse_url($rewritten);
        $this->assertSame('/wp-json/acx/v1/recognition/blobs/job-x/abc', $parts['path']);
        $query = [];
        \parse_str($parts['query'] ?? '', $query);
        $this->assertArrayHasKey('token', $query);
    }

    public function testRecursiveRewriteMixesWpHitsAndSignedFallbacks(): void
    {
        $GLOBALS['__ac_attachment_urls'][6717] = 'http://example.test/wp-content/uploads/2025/12/hit.jpg';

        $payload = [
            'suggestions' => [
                [
                    'cluster_a_representative_media_url' => '/recognition/blobs/job-a/6717',
                    'cluster_b_representative_media_url' => '/recognition/blobs/job-a/9999',
                ],
            ],
        ];

        $rewritten = BlobUrlRewriter::rewrite($payload);

        $this->assertSame(
            'http://example.test/wp-content/uploads/2025/12/hit.jpg',
            $rewritten['suggestions'][0]['cluster_a_representative_media_url']
        );
        $bParts = \parse_url($rewritten['suggestions'][0]['cluster_b_representative_media_url']);
        $this->assertSame('/wp-json/acx/v1/recognition/blobs/job-a/9999', $bParts['path']);
    }

    public function testRewritesRecognitionBlobPathToSignedRestUrl(): void
    {
        $rewritten = BlobUrlRewriter::rewrite_string('/recognition/blobs/job-x/42');

        $parts = \parse_url($rewritten);
        $this->assertSame('http', $parts['scheme']);
        $this->assertSame('example.test', $parts['host']);
        $this->assertSame('/wp-json/acx/v1/recognition/blobs/job-x/42', $parts['path']);

        $query = [];
        \parse_str($parts['query'] ?? '', $query);
        $this->assertArrayHasKey('expires', $query);
        $this->assertArrayHasKey('token', $query);
        $this->assertGreaterThan(\time(), (int) $query['expires']);

        $expected = BlobUrlRewriter::sign('job-x', '42', (int) $query['expires']);
        $this->assertSame($expected, $query['token']);
    }

    public function testRewritesRecognitionFaceThumbPathToSignedRestUrlWithCropQuery(): void
    {
        $rewritten = BlobUrlRewriter::rewrite_string('/recognition/face-thumbs/job-x/42?x=1&y=2&width=30&height=40');

        $parts = \parse_url($rewritten);
        $this->assertSame('http', $parts['scheme']);
        $this->assertSame('example.test', $parts['host']);
        $this->assertSame('/wp-json/acx/v1/recognition/face-thumbs/job-x/42', $parts['path']);

        $query = [];
        \parse_str($parts['query'] ?? '', $query);
        $this->assertSame('1', $query['x']);
        $this->assertSame('2', $query['y']);
        $this->assertSame('30', $query['width']);
        $this->assertSame('40', $query['height']);
        $this->assertArrayHasKey('expires', $query);
        $this->assertArrayHasKey('token', $query);

        $expected = BlobUrlRewriter::sign(
            'job-x',
            '42',
            (int) $query['expires'],
            'face-thumbs',
            ['x' => 1, 'y' => 2, 'width' => 30, 'height' => 40]
        );
        $this->assertSame($expected, $query['token']);
    }

    public function testDoesNotRewriteIncompleteFaceThumbPath(): void
    {
        $value = '/recognition/face-thumbs/job-x/42?x=1&y=2&width=30';
        $this->assertSame($value, BlobUrlRewriter::rewrite_string($value));
    }

    public function testDoesNotRewriteFaceThumbPathWhenCropExceedsMaxGeometry(): void
    {
        $value = '/recognition/face-thumbs/job-x/42?x=1&y=2&width=40000&height=40';
        $this->assertSame($value, BlobUrlRewriter::rewrite_string($value));
    }

    public function testPassesThroughHttpUrlUnchanged(): void
    {
        $url = 'https://example.com/wp-content/uploads/foo.jpg';
        $this->assertSame($url, BlobUrlRewriter::rewrite_string($url));
    }

    public function testPassesThroughEmptyString(): void
    {
        $this->assertSame('', BlobUrlRewriter::rewrite_string(''));
    }

    public function testRecursivelyRewritesNestedSuggestionStructure(): void
    {
        $payload = [
            'suggestions' => [
                [
                    'id' => 's1',
                    'identity_media_url' => '/recognition/blobs/job-a/9',
                    'representative_media_url' => '/recognition/blobs/job-a/12',
                    'unrelated' => 'https://example.com/img.jpg',
                ],
                [
                    'id' => 's2',
                    'cluster_a_representative_media_url' => '/recognition/blobs/job-b/77',
                    'cluster_b_representative_media_url' => null,
                ],
            ],
            'total' => 2,
        ];

        $rewritten = BlobUrlRewriter::rewrite($payload);

        $cases = [
            [$rewritten['suggestions'][0]['identity_media_url'], 'job-a', '9'],
            [$rewritten['suggestions'][0]['representative_media_url'], 'job-a', '12'],
            [$rewritten['suggestions'][1]['cluster_a_representative_media_url'], 'job-b', '77'],
        ];
        foreach ($cases as [$rewrittenUrl, $job, $media]) {
            $parts = \parse_url($rewrittenUrl);
            $this->assertSame("/wp-json/acx/v1/recognition/blobs/{$job}/{$media}", $parts['path']);
            $query = [];
            \parse_str($parts['query'] ?? '', $query);
            $this->assertSame(
                BlobUrlRewriter::sign($job, $media, (int) $query['expires']),
                $query['token']
            );
        }

        $this->assertSame('https://example.com/img.jpg', $rewritten['suggestions'][0]['unrelated']);
        $this->assertNull($rewritten['suggestions'][1]['cluster_b_representative_media_url']);
        $this->assertSame(2, $rewritten['total']);
    }

    public function testPreservesNonStringScalars(): void
    {
        $this->assertNull(BlobUrlRewriter::rewrite(null));
        $this->assertSame(42, BlobUrlRewriter::rewrite(42));
        $this->assertTrue(BlobUrlRewriter::rewrite(true));
    }

    public function testDoesNotRewritePathsWithSimilarButDifferentPrefix(): void
    {
        $value = '/recognition/blobsfoo/job/1';
        $this->assertSame($value, BlobUrlRewriter::rewrite_string($value));
    }

    public function testDoesNotRewriteIncompleteBlobPath(): void
    {
        $value = '/recognition/blobs/job-only-no-media';
        $this->assertSame($value, BlobUrlRewriter::rewrite_string($value));
    }

    public function testSignatureIsStableForSameInputs(): void
    {
        $first = BlobUrlRewriter::sign('job-a', '99', 1761600000);
        $second = BlobUrlRewriter::sign('job-a', '99', 1761600000);
        $this->assertSame($first, $second);
    }

    public function testSignatureChangesWhenAnyInputChanges(): void
    {
        $base = BlobUrlRewriter::sign('job-a', '99', 1761600000);
        $this->assertNotSame($base, BlobUrlRewriter::sign('job-b', '99', 1761600000));
        $this->assertNotSame($base, BlobUrlRewriter::sign('job-a', '100', 1761600000));
        $this->assertNotSame($base, BlobUrlRewriter::sign('job-a', '99', 1761600001));
        $this->assertNotSame($base, BlobUrlRewriter::sign('job-a', '99', 1761600000, 'face-thumbs'));
        $thumb = BlobUrlRewriter::sign('job-a', '99', 1761600000, 'face-thumbs', [
            'x' => 1,
            'y' => 2,
            'width' => 30,
            'height' => 40,
        ]);
        $this->assertNotSame(
            $thumb,
            BlobUrlRewriter::sign('job-a', '99', 1761600000, 'face-thumbs', [
                'x' => 1,
                'y' => 2,
                'width' => 31,
                'height' => 40,
            ])
        );
    }
}
