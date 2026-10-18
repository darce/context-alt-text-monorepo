# IDREBIND-1 Gate Review

```json
{
  "verdict": "pass_with_findings",
  "findings": [
    {
      "id": "IDREBIND-1-GATE-01",
      "severity": "medium",
      "file": "apps/prototype-wp-alt-context/js/admin/hooks/useMediaIdentities.ts",
      "line": 71,
      "summary": "Transient identity retries can run before the server Retry-After window expires.",
      "failure_scenario": "A 429 with Retry-After: 120 is retryable, but retryDelay ignores the current error and caps the shared cooldown at 30 seconds, so another request can arrive before the server's requested wait has elapsed.",
      "suggested_fix": "Use the shared bounded Retry-After delay for the current error and keep the shared cooldown as a lower bound without capping it below the server window.",
      "canon_id": "RES-13"
    },
    {
      "id": "IDREBIND-1-GATE-02",
      "severity": "medium",
      "file": "apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx",
      "line": 254,
      "summary": "The identity loading indicator is absent while a new query key displays placeholder data.",
      "failure_scenario": "After page one loads media 31, switching to page two with media 42 leaves the identities query fetching with page-one placeholder data; isPending is false and data is defined, so media 42 receives an empty identity list and displays the no-identities state until its request finishes.",
      "suggested_fix": "Treat placeholder data for an in-flight identities query as loading for rows whose media IDs are not covered by that data.",
      "canon_id": "PERC-05"
    },
    {
      "id": "IDREBIND-1-GATE-03",
      "severity": "medium",
      "file": "apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx",
      "line": 128,
      "summary": "The post-save health check can race the automatic mount check and allow a stale result to replace the current one.",
      "failure_scenario": "A configured URL starts a mount probe; if the operator saves a new URL or key before it finishes, the save starts another probe, and the older probe can resolve last and overwrite the newer probe's result with status for the old routing settings.",
      "suggested_fix": "Serialize health checks or ignore probe results whose routing generation predates the latest saved URL or key.",
      "canon_id": "INT-08"
    }
  ]
}
```
