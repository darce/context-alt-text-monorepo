from __future__ import annotations

import uuid

from scene.application.describe_jobs import DescribeJobStatus, InMemoryDescribeJobStore
from scene.domain.description import DescriptionResultTier


def test_enqueue_and_retrieve_describe_job() -> None:
    store = InMemoryDescribeJobStore()
    tenant_id = uuid.uuid4()

    job = store.enqueue(
        tenant_id=tenant_id,
        media_id=42,
        image_bytes=b"image",
        context={"caption": "Launch"},
    )

    assert job.job_id
    assert job.status is DescribeJobStatus.QUEUED
    assert job.tier is None
    assert store.get(job.job_id) == job
    assert store.next_queued().job_id == job.job_id


def test_job_store_supersedes_provisional_with_monotonic_final() -> None:
    store = InMemoryDescribeJobStore()
    job = store.enqueue(tenant_id=uuid.uuid4(), media_id=7, image_bytes=b"image", context=None)

    provisional = store.set_provisional(job.job_id, visual_facts={"alt_text_draft": "CPU caption"})
    final = store.set_final(job.job_id, visual_facts={"alt_text_draft": "GPU caption"})

    assert provisional.status is DescribeJobStatus.PROVISIONAL
    assert provisional.tier is DescriptionResultTier.PROVISIONAL_CPU
    assert provisional.result_generation == 1
    assert final.status is DescribeJobStatus.FINAL
    assert final.tier is DescriptionResultTier.FINAL_GPU
    assert final.result_generation == 2
    assert final.visual_facts == {"alt_text_draft": "GPU caption"}
    assert final.image_bytes == b""


def test_job_store_eviction_removes_terminal_jobs() -> None:
    store = InMemoryDescribeJobStore(max_jobs=1)
    old = store.enqueue(tenant_id=uuid.uuid4(), media_id=1, image_bytes=b"old", context=None)
    store.set_final(old.job_id, visual_facts={"alt_text_draft": "done"})

    new = store.enqueue(tenant_id=uuid.uuid4(), media_id=2, image_bytes=b"new", context=None)

    assert store.get(old.job_id) is None
    assert store.get(new.job_id) is not None
