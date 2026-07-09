# Alt Context -- Feature List

> **Document version:** 1.0  
> **Product version:** 0.2.x (recognition UX and ergonomics milestone)  
> **Author:** Daniel (product owner) / generated with AI assistance  
> **Date:** 2026-03-16  
> **Audience:** WordPress site owners, accessibility teams, content managers, agency decision-makers  
> **Purpose:** Marketing feature reference for landing pages, marketplace listings, and outreach

---

## What Alt Context Does

Alt Context is a WordPress plugin backed by a dedicated recognition service that helps site owners generate accurate, identity-aware alt text for every image in their media library. It detects faces, groups them into clusters, lets you assign real names, and keeps your curation decisions as the permanent source of truth -- even when the underlying AI re-analyzes your images.

---

## Core Capabilities

### Automated Face Detection and Grouping

- Detect faces across your entire media library in batch or on demand
- Automatic hierarchical clustering groups the same person across different photos
- Real-time progress updates via server-sent events -- no page refreshing, no guessing
- Cancel long-running jobs at any time without losing completed work
- Runs on standard hosting (CPU) or accelerates with GPU when available

### Human-in-the-Loop Identity Management

- Review AI-suggested groupings before they take effect
- Accept, reject, or reassign individual faces between clusters
- Merge clusters that represent the same person
- Split clusters that incorrectly combine different people
- Undo merges if a mistake is caught after the fact
- Dismiss irrelevant clusters to keep your workspace focused

### Person Roster

- Create named people and assign clusters to them
- Person identity persists even when clusters are merged, split, or re-analyzed
- Roster-aware autocomplete: start typing a name and matching people surface instantly
- Inline editing -- rename or tag people without leaving the page
- Bulk operations: merge multiple clusters or dismiss several at once

### Intelligent Suggestions

- The system proposes which unassigned faces belong to which person
- Merge suggestions surface when two clusters likely represent the same individual
- Suggestions refresh automatically after every edit you make
- Rejected suggestions are remembered -- the same bad proposal never resurfaces

### Curation-First Conflict Resolution

- Your decisions are ground truth. Period.
- When AI re-analysis disagrees with a choice you already made, the conflict surfaces for your explicit review -- nothing is silently overwritten
- Dedicated conflict inbox in the workbench for reviewing and resolving disagreements
- Failed sync operations appear in a dead letter panel with clear error details and one-click retry

---

## Privacy and Compliance

### Retention Controls

- Set automatic purge policies: delete recognition data after a configurable number of days, on manual trigger, or never
- Export all recognition data as structured JSON -- clusters, members, detection metadata, representative images -- with no raw AI model vectors included
- Manual purge with granular scope: all data, per person, or per cluster
- Full audit log of every retention action (exports, purges, policy changes) with timestamps and actor identity
- Built for GDPR and CCPA readiness: data export and right-to-deletion workflows included out of the box

### Where Your Data Lives

- Your WordPress site stores all people, names, and curation decisions -- these never leave your server
- Face detection and clustering run on the Alt Context hosted service; the service retains only the minimum biometric data needed for recognition to work (cluster representatives and centroids), not every raw embedding
- Edits always flow from your site to the hosted service, never the other way around -- the service cannot change your curation decisions
- Exported data never includes raw AI model vectors, eliminating model-inversion risk
- You can purge all recognition data from the hosted service at any time through the plugin's retention controls

> **Future option:** A self-hosted deployment mode where you control the recognition backend entirely is on the roadmap but is not part of the current release.

#### Plain-Language Glossary

| Term                    | What it means                                                                                                                                                                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Recognition service** | A separate server (hosted by Alt Context) that does the heavy computation -- detecting faces in your photos and figuring out which faces belong to the same person. Your WordPress site talks to it over the internet.                                 |
| **Curation decisions**  | Any choice you make: naming a person, merging two groups of faces, dismissing a suggestion, or rejecting a match. These are stored in your own WordPress database.                                                                                     |
| **Outbox**              | A queue inside your WordPress site that holds changes waiting to be sent to the recognition service. If the service is temporarily unavailable, your edits are saved locally and sent automatically when the connection comes back -- nothing is lost. |
| **Cluster**             | A group of faces the system believes belong to the same person. You review these groups and confirm or correct them.                                                                                                                                   |
| **Purge**               | Permanently deleting recognition data (face detections, clusters, embeddings) from the hosted service on your command.                                                                                                                                 |
| **Embeddings**          | A compact numeric summary of a face that the AI uses to compare faces. These are generated and used by the recognition service; they are never exposed to you or included in data exports.                                                             |

---

## Workflow and Interface

### Dashboard

- At-a-glance coverage percentage: how much of your media library has populated alt text
- Live counts of total persons, unreviewed clusters, and pending conflicts
- Contextual guidance cards that tell you what to do next based on current state
- Quick-action buttons to jump straight to the most useful page

### Workbench

- Tabbed interface for the full scan-to-confirm workflow:
  - **Scan** -- select media items and trigger analysis
  - **Batch** -- review detection results and draft alt text
  - **Confirm** -- final review with inline editing before saving to WordPress
  - **Conflicts** -- resolve curation disagreements
- Sync status indicator with manual sync trigger and health details
- URL-synced tabs with scroll restoration -- bookmark any state and return to it

### Roster Page

- Two-tab layout: manage named people in one tab, browse unassigned clusters in the other
- Table view with sortable columns: name, face count, last updated
- Bulk action bar for multi-select operations with toast confirmations

### Accessibility

- WCAG 2.1 AA compliant across all admin pages
- Full keyboard navigation: tab through fields, arrow keys in grids, enter to submit, escape to cancel
- ARIA labels on every interactive element
- Focus management with dialog trapping and focus restoration on close
- Touch targets at 44px minimum for mobile-friendly use
- Screen reader support with live region announcements for async operations

---

## Architecture Highlights

### Offline-Resilient Operation

- Person management works entirely locally -- no backend round-trip required for roster CRUD
- Cluster operations queue in a local outbox; sync failures never block your workflow
- Stale sync is detected and warned about but does not prevent you from working

### Scalable Async Processing

- Face detection, clustering, export, and purge all run asynchronously with job tracking
- Progress streaming keeps you informed without polling
- Cancellation is always available for long-running operations

### Pluggable Detection Backend

- The recognition service abstracts face detection behind a clean interface boundary
- Current implementation uses InsightFace (ArcFace embeddings, 512-dimensional vectors)
- Backend can be swapped to alternative detection systems without touching the plugin or domain logic

### Metadata Embedding

- Detection results can be written into image EXIF/XMP metadata (JPEG and PNG)
- Downstream tools and other plugins can read face region data without needing the recognition service
- Existing image metadata is preserved; only face region data is added

---

## Technical Requirements

| Requirement         | Detail                                                                 |
| ------------------- | ---------------------------------------------------------------------- |
| WordPress           | 6.0+                                                                   |
| PHP                 | 8.1+                                                                   |
| Recognition service | Self-hosted FastAPI (Python 3.12+, PostgreSQL + pgvector)              |
| Supported platforms | Linux x86_64 (CPU or CUDA GPU), macOS Apple Silicon                    |
| Browser support     | Modern browsers (Chrome, Firefox, Safari, Edge -- latest two versions) |

---

## What's Next

- Scene description capabilities beyond faces -- contextual alt text for objects, settings, and activities
- Bidirectional sync for person name edits
- Representative pin parity between plugin and backend
- Multi-tenant support for agencies managing multiple sites
- Performance optimizations for libraries with 10,000+ images

---

_Alt Context is a commercial WordPress plugin with a free tier for trying it out. Image analysis runs on the Alt Context hosted service and requires purchased tokens. Pricing details are coming soon. Alt Context is under active development. Features described as "next" are planned but not yet shipped._
