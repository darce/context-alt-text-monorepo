# Public Demo WP Plugin Launch Assessment

> **Date**: 2026-04-30
> **Author**: Codex
> **Scope**: E15 public WordPress demo for `demo.altcontext.com`, ACX plugin, and `api.altcontext.com` OCI backend
> **Status**: Final

This assessment reviews how to launch a working public demonstration of the WordPress plugin connected to the live OCI recognition backend. The shortest conversion-oriented path is a public marketing/demo page at `demo.altcontext.com` plus a locked-down WordPress admin demo driven by the operator against seeded media. A fully public upload experience is promising, but it is not the fastest route because the current plugin surface is admin-only and most ACX routes require privileged WordPress capabilities.

**Related docs:**

- [E15 Public Demo Launch Readiness](../epics/v0.4.0/public-demo-launch-readiness-epic.md)
- [E15-3 WordPress Demo Provisioning](../tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md)
- [E15-3a LocalWP -> OCI Backend Round-Trip Verification](../tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md)
- [Roadmap v4](../roadmaps/roadmap-v4.md)
- [SaaS Operations Roadmap](../roadmaps/roadmap-saas-operations.md)

## Executive Summary

Launch the first public demo as a controlled, conversion-first WordPress site: public page visible to visitors, seeded media library, pre-created persons/rosters, and an operator-only admin workflow that runs the live scan against `api.altcontext.com`. Do not publish wp-admin credentials broadly and do not give visitors raw API keys. The plugin already supports the backend URL/API-key settings surface, Workbench scan flow, local projection, and multipart media upload to the backend, but those flows are built for authenticated WordPress admins.

For hosting, use cheap managed/shared WordPress hosting or a small managed WordPress VPS for `demo.altcontext.com`, not the existing OCI inference VM. Co-hosting WordPress on the OCI backend VM is feasible, but it weakens isolation and puts PHP/MySQL/CMS risk next to the recognition service. Fly.io can run WordPress and MySQL, but it adds container/database/volume ops without making the demo meaningfully more convincing. A dedicated bare-metal server is overkill.

The highest-conversion public experience is a two-step path: first ship a simple live-demo page with curated screenshots/video and a "request demo / get early access" CTA, then add a narrow public interactive page where visitors pick from approved sample portraits or upload a small image against pre-seeded public-domain identities. The interactive page should be a separate public demo surface, not a public opening of the existing admin UI.

## Key Findings

### F1. Current ACX UI is admin-only, so public admin access is the wrong default

The WordPress admin menu registers Dashboard, Workbench, Roster, and Settings under `manage_options`, which usually means administrator-level access. REST settings, roster, scan, and job routes use the same privileged capability for mutating or sensitive recognition flows.

Current evidence:

- `apps/prototype-wp-alt-context/src/admin/class-menu.php:29` registers the top-level ACX menu.
- `apps/prototype-wp-alt-context/src/admin/class-menu.php:33` gates the menu with `manage_options`.
- `apps/prototype-wp-alt-context/src/admin/class-menu.php:53` gates Workbench with `manage_options`.
- `apps/prototype-wp-alt-context/src/admin/class-menu.php:62` gates Roster with `manage_options`.
- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:73` registers `/recognition/analyze`.
- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:80` gates analysis with `can_manage_recognition`.
- `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php:40` maps `can_manage_recognition()` to `current_user_can('manage_options')`.
- `apps/prototype-wp-alt-context/src/api/class-settings-controller.php:62` registers `/settings/test`.
- `apps/prototype-wp-alt-context/src/api/class-settings-controller.php:73` maps settings access to `manage_options`.

**Impact:** Giving public demo visitors admin access is equivalent to giving them broad site administration power. Even a temporary demo account would invite content changes, plugin settings changes, API key misuse, and cleanup work after each visitor.

### F2. The repo already defines the MVP as a curator-driven demo, not a public upload app

E15's MVP is a public WordPress URL plus a manual end-to-end pass. E15-3 explicitly says a curator opens Workbench, triggers a scan against seeded media, and sees recognition results. That aligns with the existing plugin implementation.

Current evidence:

- `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md:34` defines the objective as a public demo URL showing the plugin against a live backend.
- `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md:57` sets backend budget at OCI Always Free and `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md:59` sets WP demo budget at roughly shared-hosting cost.
- `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md:196` makes the Phase 3 goal a public WordPress page demonstrating the plugin.
- `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md:200` chooses shared PHP hosting for the WP demo.
- `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md:208` requires the public page to load and `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md:209` requires admin UI access.
- `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md:20` requires a public URL with the plugin installed.
- `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md:22` specifies a curator-triggered Workbench scan.
- `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md:79` seeds 5-10 recognizable images.

**Impact:** The fastest path should complete E15-3 as written. Changing the demo into a public upload app is a product expansion and should be a follow-on slice.

### F3. A public interactive page is not blocked by the backend, but it requires a new frontend/public plugin surface

The plugin already proxies image bytes to the backend by default, so a future public demo does not need to expose WordPress media URLs. The current public-surface gap is UI and authorization, not transport.

Current evidence:

- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:144` notes multipart transport sends image bytes inline.
- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:186` routes multipart analysis through `analyze_media_multipart()`.
- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:245` caps multipart batches at 5 images.
- `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php:246` caps multipart payloads at 25 MiB.
- `apps/prototype-wp-alt-context/src/api/class-api.php:181` allows Workbench media list access for `upload_files`, but roster/dashboard/settings/recognition mutations remain more privileged.
- No shortcode, block, `wp_enqueue_scripts`, or frontend render surface was found under `apps/prototype-wp-alt-context/src` or `apps/prototype-wp-alt-context/js`.

**Impact:** A public visitor upload path can be built safely if it is a narrow route with its own nonce/CAPTCHA/rate-limit policy and no access to wp-admin. It should not reuse the full admin SPA by weakening its capabilities.

### F4. OCI can host WordPress, but the current backend VM already consumes the obvious Always Free allocation

Repo docs record the existing OCI backend as `VM.Standard.A1.Flex` with 4 ARM cores, 24 GB RAM, and 200 GB disk. Oracle's current Always Free docs say the free A1 allocation is 3,000 OCPU-hours and 18,000 GB-hours per month, equivalent to 4 OCPUs and 24 GB RAM, plus 200 GB combined boot/block volume storage in the home region. That means a second free A1 WordPress VM is unlikely unless the backend VM is resized and storage is reallocated.

Current evidence:

- `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md:76` records the existing backend VM as 4 ARM cores, 24 GB RAM, 200 GB disk.
- Oracle documents the Always Free A1 allocation as 4 OCPUs/24 GB equivalent and 200 GB block volume resources: [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
- Oracle also notes idle Always Free compute instances may be reclaimed under low CPU/network/memory utilization thresholds: [Oracle Always Free idle compute instances](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

**Impact:** Running WordPress on the same OCI PAYG account is possible, but a clean second free VM is not the efficient path unless you intentionally shrink the backend instance. Co-hosting on the existing VM saves a few dollars but increases operational coupling.

### F5. Fly.io is viable for WordPress but not the most efficient demo host

Fly.io has a documented WordPress path using the official WordPress image and a MySQL database. Its docs show WordPress defaults to a shared CPU 1 GB app machine, and its storage model requires persistent volumes for state. Fly volumes are local to a single server and not automatically replicated.

Current evidence:

- Fly's WordPress guide says WordPress needs a MySQL database and can be launched from the official WordPress image: [Fly WordPress guide](https://fly.io/docs/languages-and-frameworks/wordpress/).
- The same guide shows a default app machine of `shared-cpu-1x, 1GB RAM`: [Fly WordPress launch output](https://fly.io/docs/languages-and-frameworks/wordpress/).
- Fly pricing lists shared CPU machine prices by RAM size: [Fly pricing](https://fly.io/docs/about/pricing/).
- Fly volumes docs state volumes are persistent local storage, tied to one server, with no automatic replication: [Fly volumes overview](https://fly.io/docs/volumes/overview/).

**Impact:** Fly is better for containerized app demos than low-touch WordPress demos. It adds self-managed MySQL/volume/backups work that shared WordPress hosting largely removes.

### F6. The conversion funnel needs a public page even if the working product surface remains admin-only

The roadmap's product goal is a polished face-management tool for non-technical WordPress admins. That is not the same as making wp-admin public. The public page should sell the value, explain the admin workflow, show proof from the live backend, and collect leads.

Current evidence:

- `docs/roadmaps/roadmap-v4.md:10` frames the product as a polished face-management tool for non-technical WordPress admins.
- `docs/roadmaps/roadmap-v4.md:25` requires curation-first precedence.
- `docs/roadmaps/roadmap-v4.md:26` requires the sovereign model to continue rendering from local projection.
- `docs/roadmaps/roadmap-saas-operations.md:12` names the longer-term SaaS goal: sign up, get an API key, manage usage, pay, and get support without manual provisioning.
- `docs/roadmaps/roadmap-saas-operations.md:18` states that manual key provisioning does not scale past early users.

**Impact:** The demo should convert users into calls, waitlist signups, or early-access installs before full self-serve key management exists.

## Demo Paths

### Path A. Controlled Live Demo on Managed WordPress Host

**Description:** `demo.altcontext.com` is a public WordPress site with a conversion page and seeded media gallery. The ACX plugin is installed and configured against `https://api.altcontext.com`. A private operator/admin account runs the Workbench scan live during sales calls or records a short live-backend video. Visitors do not receive wp-admin access or API keys.

**Hosting:** Managed/shared WordPress host or small managed WordPress VPS. Cloudflare DNS/TLS in front. This matches E15-3.

**Access model:** Public front page, private admin. Optional password-protected "demo room" page with screenshots/video and a booking CTA.

**Demo content:** 5-10 image seed set. Prefer public-domain or permissively licensed public figures, official government/public-institution portraits, or explicitly licensed sample portraits. Include attribution and a clear "not endorsed by subjects" note if public figures are used.

**Pros:** Fastest, safest, aligns with current code and E15-3, good enough for conversion calls, no new public attack surface.

**Cons:** Less self-serve. Visitors cannot independently upload arbitrary images.

**Best for:** Shipping the first public demo within the current MVP boundary.

### Path B. Public Guided Upload Page Against Pre-Seeded Identities

**Description:** Add a public page that lets visitors choose from approved sample images or upload one small image to match against pre-created identities. The page shows "recognized as X / closest match / confidence" plus a CTA. It should be a new public plugin route or a lightweight separate app that talks to WordPress/server-side proxy, not wp-admin.

**Hosting:** Same WordPress host as Path A, or a separate small app at `demo.altcontext.com/try`.

**Access model:** Public visitor page with nonce, CAPTCHA or turnstile, file type validation, size cap, IP/session throttling, per-demo API key tier, and no raw API key exposure.

**Demo content:** Pre-created rosters for a small set of licensed public-domain figures. Users can upload or select images of those identities; unknown people should produce "no confident match" rather than fake certainty.

**Pros:** Strongest proof of functionality; more memorable; supports SEO and self-serve conversion.

**Cons:** Requires product work. Must handle abuse, privacy language, upload retention/deletion, license/provenance, and rate limits.

**Best for:** Follow-on conversion lift after Path A is live and E15-3 has passed.

### Path C. Disposable Public Admin Sandbox

**Description:** Give visitors a temporary WordPress admin login for a demo sandbox that resets on a schedule. They can use the real ACX admin UI.

**Hosting:** Separate disposable WordPress instance, ideally not the main `demo.altcontext.com` install.

**Access model:** Time-limited accounts, reset job, no production API key, strict outbound limits, and throwaway media library.

**Pros:** Shows the actual plugin without building a new public UI.

**Cons:** High operational and security burden. Current ACX admin pages require `manage_options`, so a visitor sandbox account is too powerful unless a demo-only capability layer is built.

**Best for:** Private workshops only, after a custom low-privilege demo role exists.

### Path D. Static/Recorded Demo With Lead Capture Only

**Description:** `demo.altcontext.com` is a static or WordPress page with screenshots, before/after examples, and a recorded live-backend demo video. No user-interactive recognition.

**Hosting:** Any static host or the same WordPress host.

**Access model:** Public page only.

**Pros:** Safest and quickest public page; good SEO; easy to polish.

**Cons:** Does not prove the live backend is working to skeptical users unless paired with live sessions.

**Best for:** A same-day landing page if provisioning or E15-3a is delayed.

## Hosting Assessment

| Option | Feasibility | Fit for first demo | Notes |
| --- | --- | --- | --- |
| Shared/managed WordPress hosting | High | Best | Matches E15-3. WordPress.org recommends PHP 8.3+, MySQL 8.0+/MariaDB 10.6+, and HTTPS; E15-3 allows PHP 8.1+ but vendor decision should prefer WordPress.org's current recommendation where available. |
| Existing OCI backend VM | Medium | Avoid for first demo | Technically feasible via Docker/Caddy, but mixes PHP/MySQL/CMS with inference and Postgres. Current VM already uses the documented free A1 size. |
| Separate OCI VM under same PAYG | Medium-low at $0; medium if paid | Not first choice | Free path likely requires resizing/reallocating current backend resources. Paid path is fine but loses the cost advantage and increases ops. |
| Fly.io WordPress + MySQL | Medium | Not first choice | Officially possible, but requires self-managed MySQL, volumes, backups, and stateful app operations. Better for app services than simple WP demo hosting. |
| Dedicated bare-metal server | High but excessive | No | More control than needed. Use only if this becomes a high-traffic showcase or you want a single long-lived managed VPS for many demos. |

## Access and Security Position

Do not leave wp-admin open for public access. Do not distribute backend API keys to demo visitors. The current safe boundary is: WordPress stores the raw API key server-side; the visitor never sees it; the backend sees a tenant-scoped key; public traffic is limited to normal WordPress pages.

For Path A, create only operator accounts. For live sales calls, screenshare the admin workflow or drive it yourself. If someone needs hands-on access, create a named, temporary account for that person only, rotate/revoke the demo key afterward if the session was untrusted, and reset the WP install if needed.

For Path B, build a public endpoint with a separate demo key, its own lower rate limit, and no write access to roster/settings/admin mutation routes. Add upload terms, max image count, max bytes, MIME validation, retention/deletion policy, and abuse protection before opening it.

## Conversion and SEO Recommendations

The first public viewport at `demo.altcontext.com` should sell the outcome, not the infrastructure: "Find people in your WordPress media library and make accessibility metadata easier to maintain." Show a short before/after: unlabeled media, scan, recognized identities, improved workflow.

Recommended page sections:

- Above fold: product value, a real screenshot/video still, "Book a live demo" and "Get early access" CTAs.
- Proof panel: live backend status, last demo scan timestamp, number of seeded images scanned, sample recognition result.
- Workflow: upload media, scan faces, review roster, write alt text/XMP.
- Trust: privacy note, no visitor API keys, demo images are licensed/public-domain, self-hostable backend.
- SEO: target "WordPress media library face recognition", "WordPress accessibility alt text workflow", "AI image accessibility WordPress plugin", and "WordPress face roster plugin".
- Lead capture: one short form with role/site URL/email; tag leads by "wants demo", "wants install", or "just exploring".

## Recommendation

Choose **Path A now**, with the public site on managed/shared WordPress hosting and the backend staying on OCI. This is the most efficient conversion demo because it proves the full live plugin path without creating a public admin/security problem. Complete E15-3a first; if it passes, provision the WordPress host and point `demo.altcontext.com` there.

Then schedule **Path B as the first conversion follow-on**. Build a small public guided upload page around preloaded identities and approved sample images. This gives the product the "try it yourself" moment without weakening the admin UI. Keep public uploads narrow and demo-key scoped.

Reject public admin access as the default. Keep Fly.io as a fallback only if the team specifically wants containerized WordPress and accepts database/volume ops. Use OCI co-hosting only as an emergency budget path; the few dollars saved are not worth coupling the CMS to the inference VM for the first public demo.

## Immediate Next Steps

1. Finish E15-3a LocalWP -> OCI verification; do not buy/provision public WP hosting until it passes.
2. Create `docs/tasks/15.0/E15-3-host-decision-record.md` selecting a managed/shared WordPress host that meets WordPress.org requirements and E15-3's resource floor.
3. Provision `demo.altcontext.com` as a public WordPress site with Cloudflare/TLS, ACX plugin ZIP install, production demo key stored server-side, and seeded licensed images.
4. Seed 5-10 images and pre-create persons/rosters for 3-5 identities. Prefer licensed/public-domain recognizable figures and document provenance.
5. Build the conversion page before sharing the URL: screenshot/video, demo scan proof, CTA, privacy/licensing note, and lead form.
6. After the controlled demo is live, spec the public guided upload page as a follow-on slice.

## References

- WordPress.org requirements: [PHP 8.3+, MariaDB 10.6+ or MySQL 8.0+, HTTPS](https://wordpress.org/about/requirements/)
- Oracle Always Free resources: [A1 allocation, block volume, idle reclaim policy](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- Fly.io WordPress guide: [Run a WordPress App](https://fly.io/docs/languages-and-frameworks/wordpress/)
- Fly.io pricing: [Resource Pricing](https://fly.io/docs/about/pricing/)
- Fly.io storage: [Fly Volumes overview](https://fly.io/docs/volumes/overview/)
