<?php

/** Test-only runtime vocabulary reader. Input is trusted repository PHP source. */
declare(strict_types=1);

$source = stream_get_contents(STDIN);
$file = tmpfile();
if ($source === false || $file === false) {
    throw new RuntimeException('Unable to stage the producer source for reflection.');
}

try {
    if (fwrite($file, $source) !== strlen($source)) {
        throw new RuntimeException('Unable to write the complete producer source.');
    }
    require stream_get_meta_data($file)['uri'];
    $producer = new ReflectionClass(AltContext\Api\Services\JobStreamErrorCode::class);
    echo json_encode(array_values($producer->getConstants()), JSON_THROW_ON_ERROR);
} finally {
    fclose($file);
}
