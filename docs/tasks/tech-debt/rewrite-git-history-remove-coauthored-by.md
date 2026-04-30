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

## Consolidated Triage Checklist (2026-04-30)

**Disposition:** Policy implemented; historical cleanup still needs explicit verification before archive.
**Evaluation basis:** Current repository instruction surfaces and searchable file contents.

- [x] The no-`Co-Authored-By` rule is codified in `CLAUDE.md` as a mandatory commit-message rule.
- [x] Current file-content search finds policy/example references, but that is not the same as commit-history verification.
- [ ] Run `git log --all --grep="Co-Authored-By" --oneline` in an approved maintenance context and record whether any commit trailers remain.
- [ ] If trailers remain, coordinate collaborators, back up refs, and run the history rewrite from this plan.
- [ ] Archive only after commit history is verified clean or after the rewrite is complete and pushed.
