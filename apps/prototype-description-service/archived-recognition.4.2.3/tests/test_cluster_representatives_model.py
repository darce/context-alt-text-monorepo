import uuid

from db.models import IdentityClusterRepresentative
from db.settings import get_database_settings


def test_identity_cluster_representative_fields():
    settings = get_database_settings()
    embedding = [0.0] * settings.pgvector_dimension

    rep = IdentityClusterRepresentative(
        tenant_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        identity_id=uuid.uuid4(),
        embedding=embedding,
        quality_score=0.9,
        diversity_score=0.5,
    )

    assert rep.__tablename__ == "identity_cluster_representatives"
    assert rep.embedding == embedding
    assert rep.quality_score == 0.9
    assert rep.diversity_score == 0.5


def test_identity_cluster_representative_requires_embedding_length():
    settings = get_database_settings()
    rep = IdentityClusterRepresentative(
        tenant_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        identity_id=uuid.uuid4(),
        embedding=[1.0] * settings.pgvector_dimension,
        quality_score=0.4,
    )

    assert len(rep.embedding) == settings.pgvector_dimension
