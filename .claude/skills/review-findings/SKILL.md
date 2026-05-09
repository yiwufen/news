---
name: review-findings
description: Review user testing findings from the user-tester agent. Use when you are about to modify retrieval, search, or output-related code, or when the user asks about known issues or quality status.
allowed-tools: Read, Grep, Glob
argument-hint: [optional: severity filter like HIGH or CRITICAL, or category like retrieval-accuracy]
---

# Review User Testing Findings

Read and summarize user testing findings from `docs/user-testing/findings.md`.

## Instructions

1. Read `docs/user-testing/findings.md` completely.
2. Read `docs/user-testing/metrics.md` for the quality dashboard.
3. If the user provided an argument, filter by that severity or category.
4. Present a structured summary:

### Output Format

```
## Findings Summary

**Total**: N findings (X OPEN, Y CONFIRMED, Z FIXED)
**By Severity**: CRITICAL: n, HIGH: n, MEDIUM: n, LOW: n

### CRITICAL / HIGH Findings (must address)
- **F<id>** [S<scenario>] <summary>
  Related Defect: #N | Status: OPEN

### Actionable Items (grouped by component)
- `src/retrieval/knowledge_search.py`: F<id>, F<id> — <short description>
- `src/orchestration/graph.py`: F<id> — <short description>
```

5. Cross-reference with `docs/design-issues/retrieval-accuracy-analysis.md` to note
   which known defects have been confirmed by user testing.
6. If findings reference specific source files, include file paths and line numbers.
