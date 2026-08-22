## DEMO-UX-1-UXB-02 — FIXED

canon rows satisfied: A11Y-03 — each roster create/edit input now has a visible, programmatically associated label that supplies its announced name.

what changed (files + why):

- `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx`: added a visible `Full name` label and matching stable input ID to the create form; changed the placeholder to the format hint `e.g., Jane Doe`.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesTable.tsx`: added entry-specific IDs and visible associated `Name` and `Tags` labels to both edit-row inputs.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx`: added the TDD regression covering every create-form and edit-row input by accessible role/name, plus explicit visible `<label for>`/`id` assertions so placeholders cannot satisfy the test.
- `apps/prototype-wp-alt-context/js/admin/pages/roster/__tests__/RosterEntriesSection.search.test.tsx`: replaced two stale placeholder-based queries with the create field's accessible label.

RED output (test-first lanes):

```text
$ npx vitest run js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx

 RUN  v4.1.5 /home/ubuntu/w/dux-a11y/apps/prototype-wp-alt-context

 ❯ js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx (1 test | 1 failed) 194ms
     × associates visible labels with every create-form and edit-row input 190ms

 FAIL  js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx > roster input labels [A11Y-03] > associates visible labels with every create-form and edit-row input
TestingLibraryElementError: Unable to find an accessible element with the role "textbox" and name "Full name"

Here are the accessible roles:

  textbox:

  Name "":
  <input
    class="acx-input"
    placeholder="Full Name"
    type="text"
    value=""
  />

 Test Files  1 failed (1)
      Tests  1 failed (1)
   Duration  2.56s
```

GREEN output:

```text
$ npx vitest run js/admin/pages/roster/__tests__/RosterEntriesSection.labels.test.tsx

 RUN  v4.1.5 /home/ubuntu/w/dux-a11y/apps/prototype-wp-alt-context

 Test Files  1 passed (1)
      Tests  1 passed (1)
   Duration  1.78s

$ npx vitest run js/admin/pages/roster/__tests__

 RUN  v4.1.5 /home/ubuntu/w/dux-a11y/apps/prototype-wp-alt-context

 Test Files  14 passed (14)
      Tests  147 passed (147)
   Duration  24.16s
```

residual risk / what a reviewer should attack: The regression proves DOM association and visible rendering in jsdom. Review the dense edit-row layout in a real browser at narrow admin widths, and confirm translated labels/hints remain concise. The directory sweep found no other unlabeled native roster inputs; the search input already had a visible associated label.
