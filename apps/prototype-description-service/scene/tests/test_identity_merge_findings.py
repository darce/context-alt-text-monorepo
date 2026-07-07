"""Repro tests for the 20260707 review-parallel findings (auto-fix cycle).

One test per fixed finding; IDs in test names map to the handoff findings.
"""

import uuid
from datetime import UTC, datetime

import pytest

from scene.application.identity_merge import (
    ConfirmedFace,
    DeterministicNlgRealizer,
    NamingMode,
    NamingPolicy,
    NamingSkipReason,
    NormalizedBox,
    PhraseBox,
    PositionalFallbackRealizer,
    containment_match,
    merge_identities,
    resolve_naming_allowed,
)
from scene.application.identity_merge.merge import IdentityAssociation
from scene.infrastructure.vlm.florence_local_adapter import LocalCpuDescriptionAdapter
from scene.tests.identity_merge_helpers import make_association, make_face, make_phrase_box


def _face(label, *, x=0.4, y=0.2, w=0.05, h=0.08, roster_id="roster-1", confidence=0.95):
    return make_face(label, x=x, y=y, w=w, h=h, roster_id=roster_id, confidence=confidence)


def _pb(phrase, caption, box, occurrence=0):
    return make_phrase_box(phrase, caption, box=box, occurrence=occurrence)


def _assoc(caption, phrase, label, box=None, occurrence=0):
    return make_association(caption, phrase, label, box=box, occurrence=occurrence)


class TestS1MergeCore:
    def test_br02_duplicate_value_equal_boxes_stay_ambiguous(self):
        caption = "A person stands."
        box = NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.8)
        pb_a = _pb("A person", caption, box)
        pb_b = PhraseBox(phrase="A person", span_start=0, span_end=8, box=box)
        face_a = _face("Daniel", x=0.35)
        face_b = _face("Sarah", x=0.5)
        assert containment_match([face_a, face_b], [pb_a, pb_b]) == []

    def test_br03_equal_area_tie_is_no_match(self):
        caption = "A man and a woman."
        face = _face("Daniel", x=0.45, y=0.4)
        left = _pb("A man", caption, NormalizedBox(x=0.1, y=0.1, width=0.4, height=0.8))
        right = _pb("a woman", caption, NormalizedBox(x=0.4, y=0.1, width=0.4, height=0.8))
        assert left.box.area == right.box.area
        assert containment_match([face], [left, right]) == []

    def test_br04_area_guard_failure_does_not_promote_to_larger_box(self):
        caption = "Two people in a room."
        face = _face("Daniel", x=0.42, y=0.32, w=0.16, h=0.26)  # ~0.0416 area
        tight = _pb("people", caption, NormalizedBox(x=0.4, y=0.3, width=0.2, height=0.3))  # 0.06
        scene = _pb("a room", caption, NormalizedBox(x=0.0, y=0.0, width=1.0, height=1.0))
        # face fails the 0.5 ratio against tight (0.0416 > 0.03) but passes vs scene.
        assert containment_match([face], [tight, scene]) == []

    def test_br07_zero_area_face_never_matches(self):
        caption = "A man stands."
        face = _face("Daniel", w=0.0, h=0.0)
        person = _pb("A man", caption, NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7))
        assert containment_match([face], [person]) == []


class TestS2Realizer:
    def test_br01_curly_apostrophe_possessive(self):
        caption = "A man’s hat lies on the table."
        realizer = DeterministicNlgRealizer()
        named = realizer.realize(
            caption=caption,
            associations=[_assoc(caption, "A man’s hat", "Daniel")],
            confirmed_faces=[],
        )
        assert named == "Daniel’s hat lies on the table."

    @pytest.mark.parametrize(
        ("caption", "expected"),
        [
            ("A man opens the door. A man is waving.", "Daniel opens the door. They are waving."),
            ("A man opens the door. A man has a beard.", "Daniel opens the door. They have a beard."),
            # AF-BR-01 round 2: e-final stems keep their 'e'; ambiguous -es
            # families (watch/ache, focus/use) keep the name instead.
            ("A man opens the door. A man gazes at the sea.", "Daniel opens the door. They gaze at the sea."),
            ("A man opens the door. A man pushes the cart.", "Daniel opens the door. They push the cart."),
            ("A man opens the door. A man watches the sea.", "Daniel opens the door. Daniel watches the sea."),
            ("A man opens the door. A man focuses the lens.", "Daniel opens the door. Daniel focuses the lens."),
            # AF-BR-02: capitalized word after the mention is a proper noun,
            # never a verb to mutate.
            ("A man opens the door. A man Smith waves.", "Daniel opens the door. Daniel Smith waves."),
        ],
    )
    def test_br02_r4_verb_agreement(self, caption, expected):
        realizer = DeterministicNlgRealizer()
        named = realizer.realize(
            caption=caption,
            associations=[
                _assoc(caption, "A man", "Daniel", occurrence=0),
                _assoc(caption, "A man", "Daniel", occurrence=1),
            ],
            confirmed_faces=[],
        )
        assert named == expected

    def test_br02_r4_unconfident_transform_keeps_name(self):
        caption = "A man opens the door. A man always waves."
        realizer = DeterministicNlgRealizer()
        named = realizer.realize(
            caption=caption,
            associations=[
                _assoc(caption, "A man", "Daniel", occurrence=0),
                _assoc(caption, "A man", "Daniel", occurrence=1),
            ],
            confirmed_faces=[],
        )
        assert named == "Daniel opens the door. Daniel always waves."

    def test_br03_overlapping_spans_never_corrupt(self):
        caption = "A man's hat lies there."
        outer = _assoc(caption, "A man's hat", "Daniel")
        inner = _assoc(caption, "A man", "Sarah")
        realizer = DeterministicNlgRealizer()
        named = realizer.realize(caption=caption, associations=[outer, inner], confirmed_faces=[])
        assert named == "Daniel's hat lies there."  # inner overlapping span dropped

    def test_br04_embedded_possessive_degrades_to_bare_name(self):
        caption = "A man holding his son's toy smiles."
        realizer = DeterministicNlgRealizer()
        named = realizer.realize(
            caption=caption,
            associations=[_assoc(caption, "A man holding his son's toy", "Daniel")],
            confirmed_faces=[],
        )
        assert named == "Daniel smiles."

    def test_br05_empty_caption_fallback_has_no_leading_space(self):
        named = PositionalFallbackRealizer().realize(caption="", associations=[], confirmed_faces=[_face("Daniel")])
        assert named == "Pictured from left: Daniel."


class TestS3Policy:
    def test_br01_rosterless_face_is_never_nameable(self):
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        assert resolve_naming_allowed(_face("Daniel", roster_id=None), policy) is False
        result = merge_identities(
            caption="A man stands.",
            phrase_boxes=[],
            confirmed_faces=[_face("Daniel", roster_id=None)],
            policy=policy,
        )
        assert result.named_draft == "A man stands."
        assert result.provenance.reason == NamingSkipReason.NO_ELIGIBLE_IDENTITIES

    def test_br03_stale_span_association_not_in_provenance(self):
        caption = "A man stands by the window."
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        good = _pb("A man", caption, NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7))
        stale = PhraseBox(
            phrase="a ghost", span_start=50, span_end=57, box=NormalizedBox(x=0.7, y=0.1, width=0.25, height=0.7)
        )
        daniel = _face("Daniel", x=0.4)
        sarah = _face("Sarah", x=0.8, roster_id="roster-2")
        result = merge_identities(
            caption=caption, phrase_boxes=[good, stale], confirmed_faces=[daniel, sarah], policy=policy
        )
        assert result.named_draft == "Daniel stands by the window."
        assert [n.name for n in result.provenance.injected_names] == ["Daniel"]
        assert result.provenance.mode == NamingMode.GROUNDED

    def test_br03_repeated_mention_dedupes_injected_names(self):
        caption = "A man opens the door. A man is waving."
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        box1 = NormalizedBox(x=0.1, y=0.1, width=0.2, height=0.6)
        box2 = NormalizedBox(x=0.6, y=0.1, width=0.2, height=0.6)
        result = merge_identities(
            caption=caption,
            phrase_boxes=[_pb("A man", caption, box1, 0), _pb("A man", caption, box2, 1)],
            confirmed_faces=[_face("Daniel", x=0.15), _face("Daniel", x=0.65)],
            policy=policy,
        )
        assert [n.name for n in result.provenance.injected_names] == ["Daniel"]


class TestS4Grounding:
    def test_br01_malformed_bbox_rows_skipped(self):
        parsed = {
            "bboxes": [[1, 2, 3], "junk", [10.0, 10.0, 60.0, 90.0], [5, 5, 5, 5]],
            "labels": ["a", "b", "A man", "d"],
        }
        boxes = LocalCpuDescriptionAdapter._parse_phrase_grounding(
            parsed, caption="A man stands.", image_width=100, image_height=100
        )
        assert len(boxes) == 1
        assert boxes[0].phrase == "A man"

    def test_br02_invalid_span_box_cannot_steal_a_match(self):
        caption = "A man stands."
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        valid = _pb("A man", caption, NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7))
        thief = PhraseBox(
            phrase="hallucinated",
            span_start=-1,
            span_end=-1,
            box=NormalizedBox(x=0.38, y=0.15, width=0.1, height=0.2),  # smaller, contains face center
        )
        result = merge_identities(
            caption=caption, phrase_boxes=[valid, thief], confirmed_faces=[_face("Daniel", x=0.4)], policy=policy
        )
        assert result.named_draft == "Daniel stands."
        assert [n.name for n in result.provenance.injected_names] == ["Daniel"]

    def test_br05_empty_label_gets_invalid_span(self):
        parsed = {"bboxes": [[0.0, 0.0, 10.0, 10.0]], "labels": [""]}
        boxes = LocalCpuDescriptionAdapter._parse_phrase_grounding(
            parsed, caption="A man stands.", image_width=100, image_height=100
        )
        assert (boxes[0].span_start, boxes[0].span_end) == (-1, -1)


class TestHarm:
    def test_harm01_merge_import_does_not_load_sqlalchemy_models(self):
        import importlib
        import sys

        saved = dict(sys.modules)
        for mod in list(sys.modules):
            if mod.startswith(("scene.application.identity_merge", "db.models")):
                del sys.modules[mod]
        try:
            importlib.import_module("scene.application.identity_merge.merge")
            assert not any(m.startswith("db.models") for m in sys.modules), (
                "importing the pure merge seam must not pull db.models"
            )
        finally:
            sys.modules.update(saved)

    def test_harm03_positional_mode_reported(self):
        policy = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())
        result = merge_identities(
            caption="Two people.", phrase_boxes=[], confirmed_faces=[_face("Daniel")], policy=policy
        )
        assert result.provenance.mode == NamingMode.POSITIONAL


class TestJoinFilters:
    """S1-BR-01/05/06 + S3-BR-07: disposed rows, label hygiene, cross-tenant."""

    @pytest.mark.asyncio
    async def test_join_excludes_disposed_hygiene_and_cross_tenant(self):
        from sqlalchemy import Table, text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        from db.models.base_imports import _DB_SETTINGS, Base
        from db.models.identity import IdentityCluster, IdentityMember, MediaIdentity
        from db.models.tenant import Tenant
        from scene.application.identity_merge import load_confirmed_faces

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[
                    Table("tenants", Base.metadata),
                    Table("media_identities", Base.metadata),
                    Table("identity_clusters", Base.metadata),
                    Table("identity_members", Base.metadata),
                ],
            )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        media_id = 9001

        def make_identity(tenant_id, disposed=False, bbox=(10, 10, 20, 20)):
            return MediaIdentity(
                tenant_id=tenant_id,
                media_id=media_id,
                media_url="http://t.local/x.jpg",
                bbox_x=bbox[0],
                bbox_y=bbox[1],
                bbox_width=bbox[2],
                bbox_height=bbox[3],
                confidence=0.95,
                embedding=[1.0] + [0.0] * (_DB_SETTINGS.pgvector_dimension - 1),
                disposed_at=datetime.now(tz=UTC) if disposed else None,
            )

        async with factory() as s:
            tenant = Tenant(id=uuid.uuid4(), site_url="http://t.local")
            other = Tenant(id=uuid.uuid4(), site_url="http://other.local")
            s.add_all([tenant, other])
            await s.flush()

            async def link(identity, cluster, member_tenant=None):
                s.add_all([identity, cluster])
                await s.flush()
                s.add(
                    IdentityMember(
                        tenant_id=member_tenant or identity.tenant_id,
                        cluster_id=cluster.id,
                        identity_id=identity.id,
                        similarity=0.9,
                    )
                )

            await link(
                make_identity(tenant.id),
                IdentityCluster(tenant_id=tenant.id, label="Keep Me", user_confirmed=True, roster_id=uuid.uuid4()),
            )
            await link(
                make_identity(tenant.id, disposed=True, bbox=(1, 1, 9, 9)),
                IdentityCluster(tenant_id=tenant.id, label="Disposed Identity", user_confirmed=True),
            )
            await link(
                make_identity(tenant.id, bbox=(2, 2, 9, 9)),
                IdentityCluster(
                    tenant_id=tenant.id,
                    label="Disposed Cluster",
                    user_confirmed=True,
                    disposed_at=datetime.now(tz=UTC),
                ),
            )
            await link(
                make_identity(tenant.id, bbox=(3, 3, 9, 9)),
                IdentityCluster(tenant_id=tenant.id, label="   ", user_confirmed=True),
            )
            await link(
                make_identity(tenant.id, bbox=(4, 4, 9, 9)),
                IdentityCluster(tenant_id=tenant.id, label="CLUSTER-9", user_confirmed=True),
            )
            await link(
                make_identity(tenant.id, bbox=(5, 5, 0, 9)),
                IdentityCluster(tenant_id=tenant.id, label="Zero Width", user_confirmed=True),
            )
            # cross-tenant: member row under our tenant pointing at another
            # tenant's confirmed cluster must not leak that label.
            await link(
                make_identity(tenant.id, bbox=(6, 6, 9, 9)),
                IdentityCluster(tenant_id=other.id, label="Other Tenant", user_confirmed=True),
                member_tenant=tenant.id,
            )
            await s.commit()

            faces = await load_confirmed_faces(
                s, tenant_id=tenant.id, media_id=media_id, image_width=100, image_height=100
            )
            assert [f.label for f in faces] == ["Keep Me"]
        await engine.dispose()
