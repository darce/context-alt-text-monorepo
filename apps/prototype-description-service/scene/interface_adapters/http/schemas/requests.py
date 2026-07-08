"""Request schema for POST /scene/describe/multipart (the JSON ``request`` part)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AttachmentContext(BaseModel):
    """Bounded attachment-level context collected by WordPress."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=160)
    caption: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=1000)
    alt_text: str | None = Field(default=None, max_length=500)
    filename: str | None = Field(default=None, max_length=255)


class PostContext(BaseModel):
    """Bounded parent post/product context visible to public users."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    excerpt: str | None = Field(default=None, max_length=1000)
    post_type: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=32)


class TaxonomyTermContext(BaseModel):
    """Public taxonomy signal attached to the media or parent content."""

    model_config = ConfigDict(extra="forbid")

    taxonomy: str = Field(max_length=64)
    name: str = Field(max_length=120)
    slug: str | None = Field(default=None, max_length=120)


class ProductContext(BaseModel):
    """Optional bounded commerce signal."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    sku: str | None = Field(default=None, max_length=120)
    price: str | None = Field(default=None, max_length=64)
    short_description: str | None = Field(default=None, max_length=1000)


class IdentityPolicyContext(BaseModel):
    """Bounded identity policy signal collected by WordPress."""

    model_config = ConfigDict(extra="forbid")

    person_naming: str = Field(max_length=32)


class IdentityContextItem(BaseModel):
    """A user-confirmed roster identity safe for description context."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    identity_id: str | None = Field(default=None, max_length=120)
    cluster_id: str | None = Field(default=None, max_length=120)
    source: str | None = Field(default=None, max_length=64)


class IdentityContext(BaseModel):
    """Roster-bound identity context and review reasons from WordPress."""

    model_config = ConfigDict(extra="forbid")

    policy: IdentityPolicyContext
    identities: list[IdentityContextItem] = Field(default_factory=list, max_length=20)
    review_reasons: list[str] = Field(default_factory=list, max_length=20)


class ContextPack(BaseModel):
    """Typed context pack consumed by description adapters.

    WordPress owns source collection and privacy filtering; the backend owns
    normalizing, hashing, and deciding whether an adapter can apply it.
    """

    model_config = ConfigDict(extra="forbid")

    attachment: AttachmentContext | None = None
    post: PostContext | None = None
    taxonomy_terms: list[TaxonomyTermContext] = Field(default_factory=list, max_length=20)
    product: ProductContext | None = None
    identity: IdentityContext | None = None


class DescribeImageEnvelope(BaseModel):
    """JSON envelope accompanying the single ``image_<media_id>`` multipart part.

    ``media_id`` must equal the ``image_<media_id>`` part suffix (validated at the
    route, 422 on mismatch). ``context`` remains accepted for older WordPress
    callers; ``context_pack`` is the typed E20-9 contract consumed by adapters.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(description="Tenant UUID; canonicalized to lowercase.")
    media_id: int = Field(gt=0, description="WordPress attachment id; must equal the image_<media_id> part suffix.")
    context: dict[str, Any] | None = Field(
        default=None,
        description="Legacy WP context: title/caption/description/filename.",
    )
    context_pack: ContextPack | None = Field(default=None, description="Typed bounded WordPress context pack.")

    @field_validator("tenant_id")
    @classmethod
    def _canonical_uuid(cls, value: str) -> str:
        # uuid.UUID() raises ValueError on malformed input -> pydantic ValidationError.
        return str(uuid.UUID(value))


class DescribeRunCreateRequest(BaseModel):
    """JSON request for an async bulk describe run."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(description="Tenant UUID; canonicalized to lowercase.")
    media_ids: list[int] = Field(description="WordPress attachment ids to describe.")

    @field_validator("tenant_id")
    @classmethod
    def _canonical_run_uuid(cls, value: str) -> str:
        return str(uuid.UUID(value))

    @field_validator("media_ids")
    @classmethod
    def _positive_media_ids(cls, value: list[int]) -> list[int]:
        if any(media_id <= 0 for media_id in value):
            raise ValueError("media_ids must be positive integers")
        return value
