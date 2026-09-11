<?php

declare(strict_types=1);

if (!function_exists('wp_scripts')) {
    function wp_scripts(): object
    {
        return new class {
            /** @var list<array-key> */
            public $queue;

            public function __construct()
            {
                $this->queue = array_keys($GLOBALS['__ac_scripts'] ?? []);
            }

            /**
             * @return mixed
             */
            public function get_data($handle, $key)
            {
                return $GLOBALS['__ac_scripts'][$handle]['data'][$key] ?? false;
            }
        };
    }
}
