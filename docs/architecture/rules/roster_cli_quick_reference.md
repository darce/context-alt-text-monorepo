# WP-CLI Roster Commands — Quick Reference

## Available Commands

| Command | Purpose | Safety Level |
|---------|---------|--------------|
| `wp cat-roster status` | View sync metrics and roster stats | ✅ Read-only |
| `wp cat-roster sync` | Pull roster entries from backend | ⚠️ Modifies local data |
| `wp cat-roster migrate_tags` | Migrate legacy tags to taxonomy | ⚠️ Modifies taxonomy |
| `wp cat-roster repair_taxonomy` | Fix taxonomy assignments | ⚠️ Modifies taxonomy |
| `wp cat-roster nuclear_reset --yes` | Delete ALL data | 🚨 DESTRUCTIVE |

## Quick Usage

### Check Current State

```bash
# View roster and sync status
wp cat-roster status

# Count roster entries
wp option get cat_roster_entries --format=json | jq 'length'

# Count taxonomy terms
wp term list cat_roster_entity --format=count

# Count attachments with observations
wp post-meta list --keys=_cat_recognition_observations --format=count
```

### Sync Operations

```bash
# Sync from backend
wp cat-roster sync

# Fix taxonomy after bug fix
wp cat-roster repair-taxonomy
```

### Reset Operations

```bash
# Complete reset (local + remote)
wp cat-roster nuclear_reset --yes

# Reset local only (preserve backend)
wp cat-roster nuclear_reset --yes --keep-remote
```

## Common Workflows

### Fresh Start (Development)

```bash
# 1. Nuclear reset
wp cat-roster nuclear_reset --yes

# 2. Upload new references via UI or API
# ... 

# 3. Run recognition on test images
wp eval 'context_alt_text_recognition_services()->enqueue([123, 456]);'
```

### Fix Taxonomy Bug

```bash
# 1. Fix code bug
# 2. Repair existing data
wp cat-roster repair_taxonomy

# 3. Verify
wp term list cat_roster_entity
```

### Re-sync from Backend

```bash
# 1. Clear local data but keep backend
wp cat-roster nuclear_reset --yes --keep-remote

# 2. Pull from backend
wp cat-roster sync

# 3. Re-run recognition to rebuild observations
wp eval 'context_alt_text_recognition_services()->enqueue([123, 456]);'
```

### Migrate from Legacy Tags

```bash
# 1. Migrate tags
wp cat-roster migrate_tags

# 2. Verify results
wp term list cat_roster_entity --format=table

# 3. Check attachments
wp term list cat_roster_entity --field=count
```

## Flags Reference

### nuclear_reset

| Flag | Required | Effect |
|------|----------|--------|
| `--yes` | ✅ Yes | Confirm destructive operation |
| `--keep-remote` | ❌ Optional | Preserve backend roster data |

### migrate_tags

| Flag | Required | Effect |
|------|----------|--------|
| `--keep-legacy` | ❌ Optional | Retain legacy post_tag after migration |

## Output Interpretation

### status output

```text
Roster Sync Metrics:
  Last Sync: 2024-01-15 14:23:45     ← Last successful sync
  Created: 5                         ← Entries created locally
  Updated: 12                        ← Entries updated
  Deleted: 2                         ← Entries removed
  Conflicts: 0                       ← Sync conflicts
  Errors: 0                          ← Error count
```

### nuclear_reset output

```text
Nuclear reset completed:
  Roster entries deleted: 15         ← Local entries removed
  Remote entries deleted: 15         ← Backend entries removed
  Observation meta entries: 48       ← Postmeta rows deleted
  Taxonomy terms deleted: 15         ← Terms removed
  WordPress options cleared: 5       ← Options deleted
```

## Troubleshooting

### "No remote roster entries found"

**Cause:** Backend roster is empty  
**Solution:** Upload reference images via Roster Manager UI

### "Failed to delete remote entry X"

**Cause:** Backend API error or network issue  
**Solution:** Check backend logs, verify API connectivity

### "No attachments with recognition observations found"

**Cause:** No images have been processed with recognition yet  
**Solution:** Run recognition on some images first

### Taxonomy terms exist but not showing

**Cause:** `wp_set_post_terms` bug (fixed)  
**Solution:** Run `wp cat-roster repair_taxonomy`

## Safety Checklist

Before running destructive commands:

- [ ] Verify you're on a **development** site
- [ ] Database **backup** created (if needed)
- [ ] Understand **what will be deleted**
- [ ] Know **recovery steps** if needed
- [ ] Confirmed with **team members** (if applicable)

## Advanced Usage

### Scripted Reset + Re-sync

```bash
#!/bin/bash
set -e

echo "Resetting local data..."
wp cat-roster nuclear_reset --yes --keep-remote

echo "Re-syncing from backend..."
wp cat-roster sync

echo "Verifying taxonomy..."
TERM_COUNT=$(wp term list cat_roster_entity --format=count)
echo "Taxonomy has $TERM_COUNT terms"

echo "Re-running recognition on test images..."
wp eval 'context_alt_text_recognition_services()->enqueue([123, 456, 789]);'

echo "Done! Check Roster Manager UI to verify."
```

### Batch Processing

```bash
# Get all attachment IDs
IDS=$(wp post list --post_type=attachment --format=ids)

# Run recognition in batches
for BATCH in $(echo $IDS | xargs -n 10); do
    wp eval "context_alt_text_recognition_services()->enqueue([$BATCH]);"
    sleep 2
done
```

### Monitoring Sync State

```bash
# Watch sync state in real-time
watch -n 2 'wp cat-roster status'

# Log sync operations
wp cat-roster sync 2>&1 | tee roster-sync.log
```

## Related Documentation

- [Roster Taxonomy Guide](./roster_taxonomy_guide.md) — Complete taxonomy documentation
- [Nuclear Reset Guide](./roster_nuclear_reset_guide.md) — Detailed reset command documentation
- [Face Recognition Tasks](./face_recognition_tasks.md) — Recognition workflow overview

## Getting Help

```bash
# Show command help
wp help cat-roster
wp help cat-roster nuclear-reset

# Debug mode
wp cat-roster nuclear_reset --yes --debug

# Version info
wp plugin list | grep context-alt-text
```
