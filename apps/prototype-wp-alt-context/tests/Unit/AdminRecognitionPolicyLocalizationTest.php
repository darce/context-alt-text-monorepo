<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\Admin;
use AltContext\Settings\RecognitionPolicy;
use AltContext\Tests\TestCase;
use ReflectionMethod;

/** @covers \AltContext\Admin\Admin */
class AdminRecognitionPolicyLocalizationTest extends TestCase
{
    private function localizedPolicy(): array
    {
        $method = new ReflectionMethod(Admin::class, 'localize_spa_config');
        $method->invoke(new Admin(), 'policy-test');
        $payload = $GLOBALS['__ac_localized_scripts']['policy-test']['AltContextAdmin'];
        $this->assertArrayHasKey('recognitionPolicy', $payload);
        $this->assertIsArray($payload['recognitionPolicy']);
        return $payload['recognitionPolicy'];
    }

    public function testMissingOptionDefaultsOffWithoutCreatingPolicyOption(): void
    {
        $this->setUserCapability('manage_options', true);
        $this->assertNull(get_option(RecognitionPolicy::OPTION, null));
        $this->assertSame(['enabled' => false, 'canManage' => true], $this->localizedPolicy());
        $this->assertNull(get_option(RecognitionPolicy::OPTION, null));
    }

    public function testPersistedPolicyAndCapabilityAreIndependentPageLoadSnapshots(): void
    {
        foreach ([true, false] as $enabled) {
            $this->assertTrue(RecognitionPolicy::set($enabled));
            foreach ([true, false] as $canManage) {
                $this->setUserCapability('manage_options', $canManage);
                $this->assertSame(
                    ['enabled' => $enabled, 'canManage' => $canManage],
                    $this->localizedPolicy()
                );
                $this->assertSame($enabled ? '1' : '0', get_option(RecognitionPolicy::OPTION));
            }
        }
    }

    public function testMalformedStoredPolicyFailsClosedForDeniedCapability(): void
    {
        $this->setUserCapability('manage_options', false);
        $this->setOption(RecognitionPolicy::OPTION, 'unexpected');
        $this->assertSame(['enabled' => false, 'canManage' => false], $this->localizedPolicy());
        $this->assertSame('unexpected', get_option(RecognitionPolicy::OPTION));
    }
}
