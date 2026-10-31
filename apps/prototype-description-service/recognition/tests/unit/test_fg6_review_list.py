"""Execute the production qualifying predicate: photos differ from face counts."""

import uuid

import pytest
from sqlalchemy import create_engine, select, text

from db.models import IdentityCluster as ClusterModel
from recognition.infrastructure.repositories.cluster_repository import (
    SqlAlchemyClusterRepository,
    _top_unlabeled_filters,
)


def test_review_minimum_preserves_population_before_pagination():
    tenant = uuid.uuid4()
    other = uuid.uuid4()
    engine = create_engine("sqlite://")
    ids = {
        name: uuid.uuid4()
        for name in ["duplicate", "two-a", "two-b", "unknown", "named", "confirmed", "dismissed", "foreign", "accepted"]
    }
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE identity_clusters(id TEXT, tenant_id TEXT, label TEXT, user_confirmed BOOLEAN, identity_count INTEGER, dismissed_at TEXT)"
            )
        )
        db.execute(text("CREATE TABLE identity_members(cluster_id TEXT, identity_id TEXT, tenant_id TEXT)"))
        db.execute(text("CREATE TABLE media_identities(id TEXT, tenant_id TEXT, media_id INTEGER)"))
        db.execute(
            text(
                "CREATE TABLE identity_suggestions(identity_id TEXT, tenant_id TEXT, resolution TEXT, suggested_cluster_id TEXT)"
            )
        )
        for name, photos in [
            ("duplicate", [1, 1, 1, 1]),
            ("two-a", [1, 2, 2]),
            ("two-b", [3, 4, 4]),
            ("unknown", [0, 5]),
            ("named", [1, 2]),
            ("confirmed", [1, 2]),
            ("dismissed", [1, 2]),
            ("foreign", [1, 2]),
            ("accepted", [1, 2]),
        ]:
            scope = other if name == "foreign" else tenant
            db.execute(
                text("INSERT INTO identity_clusters VALUES(:id,:tenant,:label,:confirmed,:count,:dismissed)"),
                {
                    "id": ids[name].hex,
                    "tenant": scope.hex,
                    "label": "Alice" if name == "named" else None,
                    "confirmed": name == "confirmed",
                    "count": len(photos),
                    "dismissed": "2026-10-31" if name == "dismissed" else None,
                },
            )
            for photo in photos:
                identity = uuid.uuid4().hex
                db.execute(
                    text("INSERT INTO identity_members VALUES(:cluster,:id,:tenant)"),
                    {"cluster": ids[name].hex, "id": identity, "tenant": scope.hex},
                )
                db.execute(
                    text("INSERT INTO media_identities VALUES(:id,:tenant,:photo)"),
                    {"id": identity, "tenant": scope.hex, "photo": photo},
                )
                if name == "accepted":
                    db.execute(
                        text("INSERT INTO identity_suggestions VALUES(:id,:tenant,'accepted',:target)"),
                        {"id": identity, "tenant": scope.hex, "target": uuid.uuid4().hex},
                    )
        eligible = select(ClusterModel.id).where(*_top_unlabeled_filters(tenant, 2, min_photos=2))
        actual = set(db.execute(eligible).scalars())
        assert actual == {ids["two-a"], ids["two-b"]}
        assert len(db.execute(eligible.limit(1).offset(1)).all()) == 1
        assert not db.execute(select(ClusterModel.id).where(*_top_unlabeled_filters(tenant, 2, min_photos=3))).all()
        all_ids = set(db.execute(select(ClusterModel.id).where(*_top_unlabeled_filters(tenant, 2))).scalars())
        assert all_ids == {ids[n] for n in ["duplicate", "two-a", "two-b", "unknown"]}


class _CapturingSession:
    async def execute(self, stmt):
        self.stmt = stmt
        return self

    def all(self):
        return []


async def _generic_listing(tenant, **kwargs):
    session = _CapturingSession()
    await SqlAlchemyClusterRepository(session).get_by_tenant(str(tenant), **kwargs)
    return session.stmt


@pytest.mark.asyncio
async def test_generic_minimum_counts_complete_membership_before_pagination():
    tenant = uuid.uuid4()
    other = uuid.uuid4()
    engine = create_engine("sqlite://")
    # A missing identity row, a null ID and a foreign-tenant identity leave a
    # photo unavailable, like media_id 0, which MediaItem input accepts.
    groups = {
        "incomplete": [0, 55],
        "complete": [55, 56],
        "repeated": [57, 57],
        "null": [58, None],
        "missing": [59, "missing"],
        "foreign": [60, "foreign"],
    }
    ids = {name: uuid.uuid4() for name in groups}
    with engine.begin() as db:
        columns = ",".join(f'"{column.name}" TEXT' for column in ClusterModel.__table__.columns)
        db.execute(text(f"CREATE TABLE identity_clusters({columns})"))
        db.execute(text("CREATE TABLE identity_members(cluster_id TEXT, identity_id TEXT, tenant_id TEXT)"))
        db.execute(text("CREATE TABLE media_identities(id TEXT, tenant_id TEXT, media_id INTEGER)"))
        for name, photos in groups.items():
            db.execute(
                text("INSERT INTO identity_clusters(id, tenant_id, user_confirmed, identity_count) VALUES(:id,:t,0,2)"),
                {"id": ids[name].hex, "t": tenant.hex},
            )
            for photo in photos:
                identity = uuid.uuid4().hex
                db.execute(
                    text("INSERT INTO identity_members VALUES(:cluster,:id,:t)"),
                    {"cluster": ids[name].hex, "id": identity, "t": tenant.hex},
                )
                if photo != "missing":
                    db.execute(
                        text("INSERT INTO media_identities VALUES(:id,:t,:photo)"),
                        {
                            "id": identity,
                            "t": (other if photo == "foreign" else tenant).hex,
                            "photo": 61 if photo == "foreign" else photo,
                        },
                    )

        def listed(stmt):
            return {row[0]: row[-1] for row in db.execute(stmt)}

        assert listed(await _generic_listing(tenant, min_photos=2)) == {ids["complete"]: 2}
        # Unknown counts cannot match, so no page publishes them as known photos.
        assert listed(await _generic_listing(tenant, min_photos=1)) == {ids["complete"]: 2, ids["repeated"]: 1}
        assert set(listed(await _generic_listing(tenant))) == set(ids.values())
