# Settings Documentation Implementation Plan

**Goal:** Document new clustering settings for suggestion bands, anchor splits, and quality thresholds

**Problem:** New settings added without user-facing documentation or configuration examples

**Solution:** Create configuration guide with examples and update existing architecture docs

---

## Phase 0: Scaffolding (Documentation Only)

No code scaffolding needed - this is documentation work only.

---

## Phase 1: Configuration Guide

### 1.1 Create Settings Guide

**File:** `docs/architecture/backend-recognition-service/clustering-settings.md` (NEW)

```markdown
# Clustering Settings Configuration

## Overview

The recognition service uses type-safe settings defined in `recognition/application/settings/clustering.py`.
All settings have hardcoded defaults and can be overridden programmatically (no `.env` files).

## Settings Reference

### Suggestion Band Settings

Control when marginal candidates become suggestions vs auto-accept/reject.

| Setting | Default | Description |
|---------|---------|-------------|
| `suggestion_floor` | 0.75 | Lower bound for suggestion band. Below this → hard reject |
| `suggestion_ceiling` | 0.85 | Upper bound for suggestion band. At/above → auto-accept |
| `early_stage_suggestion_enabled` | True | Route borderline matches to suggestions early |

**Example:**

\`\`\`python
from recognition.application.settings import ClusteringSettings

settings = ClusteringSettings(
    suggestion_floor=0.70,  # More lenient - capture more marginal cases
    suggestion_ceiling=0.88,  # Stricter - fewer auto-accepts
)
\`\`\`

**Impact:** Lower floor creates more suggestions (reduces false negatives), higher ceiling reduces auto-accepts (prevents false positives).

### Anchor Split Settings

Control forced binary splits when hierarchical clustering fails.

| Setting | Default | Description |
|---------|---------|-------------|
| `anchor_split_similarity_floor` | 0.85 | Minimum similarity to keep identities with anchor |

**Example:**

\`\`\`python
settings = ClusteringSettings(
    anchor_split_similarity_floor=0.80,  # Allow more faces in anchor group
)
\`\`\`

**Impact:** Lower floor keeps more identities with anchor (larger anchor group), higher floor forces stricter separation.

### Quality Threshold Settings

Prevent low-quality detections from becoming suggestions.

| Setting | Default | Description |
|---------|---------|-------------|
| `fatal_confidence_floor` | 0.30 | Minimum detection confidence - below this suppresses suggestions |
| `fatal_quality_floor` | 0.20 | Minimum quality score - below this suppresses suggestions |

**Example:**

\`\`\`python
settings = ClusteringSettings(
    fatal_confidence_floor=0.40,  # Stricter quality gate
    fatal_quality_floor=0.25,
)
\`\`\`

**Impact:** Higher floors reject more low-quality faces, lower floors are more permissive.

## Configuration Patterns

### Production Tuning

\`\`\`python
# Conservative - minimize false positives
production_settings = ClusteringSettings(
    suggestion_floor=0.78,
    suggestion_ceiling=0.88,
    fatal_confidence_floor=0.35,
)
\`\`\`

### Development/Testing

\`\`\`python
# Permissive - surface more edge cases for review
dev_settings = ClusteringSettings(
    suggestion_floor=0.65,
    suggestion_ceiling=0.82,
    fatal_confidence_floor=0.25,
)
\`\`\`

### Cold-Start Datasets

\`\`\`python
# Strict acceptance, broad suggestion band
cold_start_settings = ClusteringSettings(
    suggestion_ceiling=0.90,  # Higher bar for auto-accept
    suggestion_floor=0.70,  # Wider suggestion band
)
\`\`\`

## Updating Settings

Settings are defined in code, not `.env` files, for type safety and version control.

To change settings:

1. Modify defaults in \`clustering.py\`:

\`\`\`python
class ClusteringSettings(BaseModel):
    suggestion_floor: float = Field(
        default=0.75,  # Update here
        description="Minimum similarity for suggestion creation.",
    )
\`\`\`

2. Or override when building services:

\`\`\`python
custom_settings = ClusteringSettings(suggestion_floor=0.70)
assignment_gate = AssignmentGate(settings=custom_settings, ...)
\`\`\`

## Migration Notes

**v4.2.8 Changes:**

- Added `suggestion_floor` and `suggestion_ceiling` for marginal reject handling
- Added `anchor_split_similarity_floor` for forced binary splits
- Added `fatal_confidence_floor` and `fatal_quality_floor` for quality gating

**Backward Compatibility:**

All new settings have defaults matching previous hardcoded behavior.
Existing code continues to work without changes.

## Observability

Settings are logged in recognition run metadata:

\`\`\`json
{
  "run_id": "...",
  "settings_snapshot": {
    "suggestion_floor": 0.75,
    "suggestion_ceiling": 0.85,
    ...
  }
}
\`\`\`

Query `recognition_runs.settings_snapshot` to audit historical configurations.

## Related Documentation

- [Assignment Gate Architecture](../../../agentic/diagrams/backend-uml/components/assignment-gate.mmd)
- [Suggestion Strategy](../../../tasks/4.0/4.2.8/cluster-split-and-suggestions-implementation.md)
- [API Reference](../../../agentic/contracts/clustering-api.md)
\`\`\`

### 1.2 Update Architecture Index

**File:** `docs/architecture/README.md`

Add link to new settings guide in Backend section.

---

## Phase 2: Inline Documentation

### 2.1 Add Usage Examples to Docstrings

**File:** `recognition/application/settings/clustering.py`

Add module-level docstring with examples:

```python
\"\"\"Clustering and assignment thresholds for the recognition service.

Configuration uses pydantic BaseModel with hardcoded defaults (no .env files).
Override by passing explicit values when constructing settings.

Example:
    >>> from recognition.application.settings import ClusteringSettings
    >>> settings = ClusteringSettings(
    ...     suggestion_floor=0.70,
    ...     suggestion_ceiling=0.88,
    ... )
    >>> settings.suggestion_floor
    0.70

New in v4.2.8:
    - suggestion_floor: Lower bound for suggestion band
    - suggestion_ceiling: Upper bound for suggestion band
    - anchor_split_similarity_floor: Minimum similarity for anchor groups
    - fatal_confidence_floor: Quality gate for detection confidence
    - fatal_quality_floor: Quality gate for face quality scores
\"\"\"
```

### 2.2 Update Field Descriptions

Already complete - existing `Field(description=...)` values are clear.

---

## Verification Plan

### Automated Tests

No code changes, no new tests needed.

### Manual Verification

**Prerequisites:**
1. Review existing settings code: `recognition/application/settings/clustering.py`
2. Review usage: `grep -r "ClusteringSettings" apps/prototype-description-service/`

**Test Steps:**

1. **Verify Documentation Accuracy:**
   - Open `docs/architecture/backend-recognition-service/clustering-settings.md`
   - Cross-reference each setting with actual code
   - Verify defaults match source code
   - Test example code snippets in Python REPL

2. **Verify Completeness:**
   - List all fields in `ClusteringSettings`
   - Check each new field (v4.2.8) is documented
   - Verify migration notes mention all changes

3. **Verify Examples:**
   - Copy production tuning example
   - Run in Python REPL to ensure valid syntax
   - Verify settings object constructs without errors

**Expected Outcome:** Documentation matches implementation, examples run without errors

---

##Implementation Checklist

- [ ] Create `docs/architecture/backend-recognition-service/clustering-settings.md`
- [ ] Document all suggestion band settings
- [ ] Document anchor split settings
- [ ] Document quality threshold settings
- [ ] Add configuration patterns (production, dev, cold-start)
- [ ] Add migration notes for v4.2.8
- [ ] Add observability section
- [ ] Update module docstring in `clustering.py`
- [ ] Update architecture README with link
- [ ] Manual review: verify accuracy against code
- [ ] Manual test: run example snippets in REPL

---

## Acceptance Criteria

✅ All new settings (v4.2.8) documented with descriptions  
✅ Configuration examples provided for common scenarios  
✅ Migration notes explain backward compatibility  
✅ Inline docstring updated with examples  
✅ Documentation verified against actual code  
✅ Example snippets tested in Python REPL
