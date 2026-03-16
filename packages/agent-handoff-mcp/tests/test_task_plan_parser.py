from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "task_plan_parser.py"


def _load_parser_module():
    spec = importlib.util.spec_from_file_location("task_plan_parser", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load task_plan_parser module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_task_plan_extracts_heading_and_plan_id(tmp_path: Path) -> None:
    module = _load_parser_module()
    plan = tmp_path / "plan.md"
    plan.write_text(
        "## Phase 1: Backend\n"
        "<!-- plan-id: backend-one -->\n"
        "- [ ] Implement backend slice\n"
        "- [x] Already done\n"
    )
    items = module.parse_task_plan(plan)
    assert len(items) == 2
    assert items[0].heading == "Phase 1: Backend"
    assert items[0].explicit_plan_id == "backend-one"
    assert items[1].checked is True


def test_normalize_plan_item_strips_lane_annotation() -> None:
    module = _load_parser_module()
    item = module.ParsedPlanItem(
        text="[lane:frontend] Add UI coverage",
        checked=False,
        heading="Phase 5: Frontend",
        line_start=42,
        ordinal=1,
    )
    normalized = module.normalize_plan_item(item)
    assert normalized.explicit_lane == "frontend"
    assert normalized.summary == "Add UI coverage"


def test_derive_plan_item_id_generates_phase_heading_slug_when_comment_missing() -> None:
    module = _load_parser_module()
    item = module.ParsedPlanItem(
        text="Implement backend slice",
        checked=False,
        heading="Phase 1: Backend",
        line_start=12,
        ordinal=1,
    )
    assert module.derive_plan_item_id(item) == "phase-1::phase-1-backend::checklist_1"


def test_map_plan_item_to_lane_uses_heading_then_routing_hints() -> None:
    module = _load_parser_module()
    manifest = {
        "lanes": {"backend-domain": {}, "frontend": {}, "wp-proxy": {}},
        "heading_to_lane": {"Phase 1: Backend": "backend-domain"},
        "plan_routing_hints": [
            {
                "heading": "Phase 6: Integration Tests",
                "text_prefix": "PHP integration test:",
                "lane": "wp-proxy",
            }
        ],
    }
    backend = module.DerivedSlice(
        plan_item_id="phase-1::backend::checklist_1",
        summary="Implement backend data model",
        body="Implement backend data model",
        heading="Phase 1: Backend",
        line_start=10,
    )
    php = module.DerivedSlice(
        plan_item_id="phase-6::integration::checklist_1",
        summary="PHP integration test: retention status endpoint proxies backend policy and caches correctly.",
        body="PHP integration test: retention status endpoint proxies backend policy and caches correctly.",
        heading="Phase 6: Integration Tests",
        line_start=20,
    )
    assert module.map_plan_item_to_lane(backend, manifest=manifest) == "backend-domain"
    assert module.map_plan_item_to_lane(php, manifest=manifest) == "wp-proxy"


def test_derive_plan_item_id_auto_generates_from_heading_and_ordinal(tmp_path: Path) -> None:
    module = _load_parser_module()
    plan = tmp_path / "plan.md"
    plan.write_text(
        "## Phase 2: Frontend polish\n"
        "- [ ] Wire up status badge\n"
        "- [ ] Add error boundary\n"
        "## Unrelated section\n"
        "- [x] Already done item\n"
    )
    items = module.parse_task_plan(plan)
    assert len(items) == 3
    id_0 = module.derive_plan_item_id(items[0])
    id_1 = module.derive_plan_item_id(items[1])
    id_2 = module.derive_plan_item_id(items[2])
    # Phase-based prefix
    assert id_0.startswith("phase-2::")
    assert id_1.startswith("phase-2::")
    # Non-phase heading falls back to phase-x
    assert id_2.startswith("phase-x::")
    # Ordinals differ within the same heading
    assert id_0.endswith("::checklist_1")
    assert id_1.endswith("::checklist_2")
    # Ordinal resets under a new heading
    assert id_2.endswith("::checklist_1")
    # All three IDs are unique
    assert len({id_0, id_1, id_2}) == 3
