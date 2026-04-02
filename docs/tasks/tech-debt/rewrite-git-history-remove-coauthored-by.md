# Tech Debt: Rewrite Git History to Remove Co-Authored-By Trailers

## Problem

Multiple commits across the repository contain `Co-Authored-By` trailers attributing AI models. This is unwanted and must be stripped from all git history.

## Scope

~20 commits across multiple branches contain the trailer. Run:

```bash
git log --all --grep="Co-Authored-By" --oneline
```

## Fix

Use `git filter-branch` or `git filter-repo` to strip the trailer from all commits:

```bash
git filter-repo --message-callback '
import re
return re.sub(rb"\n\s*Co-Authored-By:.*", b"", message)
'
```

Then force-push all affected branches.

## Prerequisite

- Coordinate with any collaborators before force-pushing
- Back up refs before rewrite

## Rule

**No commit in this repository may contain a `Co-Authored-By` trailer or any AI/model attribution.** This is a mandatory, permanent rule — not a preference.
