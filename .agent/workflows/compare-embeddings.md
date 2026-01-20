---
description: Compare embedding similarities between media identities
---

**Purpose**: Calculate cosine similarity between face embeddings to debug cluster assignment decisions.

**When to use**:

- Debugging why identities aren't clustering together
- Verifying similarity thresholds
- Investigating false positives/negatives

**Prerequisites**: PostgreSQL running with face embeddings data

**Usage**: Get media IDs from database, then pass to comparison script.

Compare cosine similarity between media identities by media_id. Useful for debugging cluster assignment issues.

1. Get media IDs from the database

```bash
cd apps/prototype-description-service && ./scripts/db_shell.sh -c "SELECT media_id FROM media_identities LIMIT 5;"
```

2. Run the comparison tool

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/python scripts/utilities/compare_media_embeddings.py --media-ids <ID1> <ID2>
```

3. Optional: Filter by cluster ID

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/python scripts/utilities/compare_media_embeddings.py --media-ids <ID1> <ID2> --cluster-id <UUID>
```

4. Optional: Refresh materialized view first

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/python scripts/utilities/compare_media_embeddings.py --media-ids <ID1> <ID2> --refresh-centroids
```
