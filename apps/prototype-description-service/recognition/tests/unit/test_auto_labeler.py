"""Unit tests for auto-labeling helpers."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from recognition.application.labeling.auto_labeler import allocate_person_label, should_auto_label
from recognition.application.settings.clustering import AutoLabelSettings


class TestShouldAutoLabel:
    def test_returns_false_when_disabled(self) -> None:
        settings = AutoLabelSettings(enabled=False)
        assert not should_auto_label(
            member_count=5,
            similarities=[0.9, 0.9, 0.9],
            algorithm="hdbscan",
            settings=settings,
        )

    def test_returns_false_for_manual_algorithm(self) -> None:
        settings = AutoLabelSettings()
        assert not should_auto_label(
            member_count=5,
            similarities=[0.9, 0.9],
            algorithm="manual",
            settings=settings,
        )

    def test_returns_false_below_member_threshold(self) -> None:
        settings = AutoLabelSettings(min_members=3)
        assert not should_auto_label(
            member_count=2,
            similarities=[0.9, 0.9],
            algorithm="hdbscan",
            settings=settings,
        )

    def test_returns_false_below_similarity_threshold(self) -> None:
        settings = AutoLabelSettings(similarity_floor=0.85)
        assert not should_auto_label(
            member_count=5,
            similarities=[0.80, 0.82, 0.78],
            algorithm="hdbscan",
            settings=settings,
        )

    def test_returns_true_when_all_criteria_met(self) -> None:
        settings = AutoLabelSettings(min_members=3, similarity_floor=0.85)
        assert should_auto_label(
            member_count=5,
            similarities=[0.90, 0.88, 0.92],
            algorithm="hdbscan",
            settings=settings,
        )

    def test_uses_average_not_minimum_similarity(self) -> None:
        settings = AutoLabelSettings(similarity_floor=0.85)
        similarities = [0.90, 0.90, 0.90, 0.70]  # avg = 0.85
        assert should_auto_label(
            member_count=4,
            similarities=similarities,
            algorithm="hdbscan",
            settings=settings,
        )


class TestAllocatePersonLabel:
    @pytest.mark.asyncio
    async def test_returns_sequential_labels(self, db_session, tenant) -> None:
        label1 = await allocate_person_label(str(tenant.id), db_session)
        label2 = await allocate_person_label(str(tenant.id), db_session)
        label3 = await allocate_person_label(str(tenant.id), db_session)

        assert label1 == "Person 1"
        assert label2 == "Person 2"
        assert label3 == "Person 3"

    @pytest.mark.asyncio
    async def test_respects_custom_prefix(self, db_session, tenant) -> None:
        label = await allocate_person_label(str(tenant.id), db_session, prefix="Identity")
        assert label == "Identity 1"

    @pytest.mark.asyncio
    async def test_concurrent_allocations_are_unique(self, db_session, tenant) -> None:
        engine = cast(AsyncEngine, db_session.bind)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async def allocate_with_session() -> str:
            async with session_factory() as session:
                label = await allocate_person_label(str(tenant.id), session)
                await session.commit()
                return label

        labels = await asyncio.gather(*[allocate_with_session() for _ in range(10)])
        assert len(set(labels)) == 10
