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
    public function testRewritesRecognitionBlobPathToSignedRestUrl(): void
    {
        $rewritten = BlobUrlRewriter::rewrite_string('/recognition/blobs/job-x/42');

        $parts = parse_url($rewritten);
        $this->assertSame('http', $parts['scheme']);
        $this->assertSame('example.test', $parts['host']);
        $this->assertSame('/wp-json/acx/v1/recognition/blobs/job-x/42', $parts['path']);

        parse_str($parts['query'] ?? '', $query);
        $this->assertArrayHasKey('expires', $query);
        $this->assertArrayHasKey('token', $query);
        $this->assertGreaterThan(time(), (int) $query['expires']);

        $expected = BlobUrlRewriter::sign('job-x', '42', (int) $query['expires']);
        $this->assertSame($expected, $query['token']);
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
            $parts = parse_url($rewrittenUrl);
            $this->assertSame("/wp-json/acx/v1/recognition/blobs/{$job}/{$media}", $parts['path']);
            parse_str($parts['query'] ?? '', $query);
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
    }
}
