<?php

declare(strict_types=1);

use ContextAltText\Workbench\WorkbenchMediaResolver;

final class FakeWorkbenchMediaResolver extends WorkbenchMediaResolver
{
    /** @var array{items: array<int,array{id:string,title:string,status:string,thumbnailUrl:?string,updatedAt:?string,altText:?string,mimeType:?string,dimensions:array{width:int,height:int}|null,editUrl:?string}>, total:int, totalPages:int} */
    private array $payload;

    /**
     * @param array{items: array<int,array{id:string,title:string,status:string,thumbnailUrl:?string,updatedAt:?string,altText:?string,mimeType:?string,dimensions:array{width:int,height:int}|null,editUrl:?string}>, total:int, totalPages:int} $payload
     */
    public function __construct(array $payload)
    {
        parent::__construct();
        $this->payload = $payload;
    }

    public function fetch(array $args = []): array
    {
        return $this->payload;
    }
}
