# AgriChat admin panel and site design

Team NASA-AN? · NASA Space Apps Challenge 2026, Field Shift · Draft v0.1


**Who uses it.** The project team during the demo, and possibly a municipal agriculture technician. They need to see, within seconds, whether the system is alive and fresh, what farmers sent and what AgriChat replied, and whether the AI is doing anything it should not. The design is a calm monitoring console built for fast scanning, with a very small set of actions and no editing of anything scientific.

### Visual direction

Friendly but data-dense: a white canvas, generous whitespace, soft rounded cards, and the logo's palette used with discipline. Colors were sampled from the logo file. The sprout leaf is an estimate by eye, so sample the logo file once it is added.

| Role | Color | Use |
|---|---|---|
| Ink | `#0F1111` | Text, outline style |
| Bubble green | `#9CCF6B` | Tints, chart fills, sidebar highlight |
| Leaf green | about `#96D63F` | Small accents |
| Deep green | derived, about `#2F6B3A` | Buttons and links, so text passes contrast |
| Carrot orange | `#F4741E` | Brand accent, active-item marker, attention badges (fills only) |
| Stem green | `#508E57` | Secondary charts, borders |

Orange is too light for small text on white, so use it for fills and icons with dark text on top. Status never relies on color alone: every badge carries an icon and a word.

### Layout

A left sidebar (collapsing to a top bar on phones) with Dashboard, Activity, Messages, Farmers, Indicators and Knowledge base. A slim top bar shows a live status chip (for example "Gateway: last event 2 min ago") and the session time left. Use the icon-only part of the logo (bubble and carrot) in the sidebar and as the favicon. The full logo goes on the login page. Treat the logo as an asset and do not redraw it.

### Pages

| Page | Content |
|---|---|
| Login | One centered card with the logo, a password field, a plain "too many attempts, try again in 15 minutes" message, and a note that the session lasts 8 hours |
| Dashboard | Four stat cards (profiles, messages in 24 hours, template versus model share, gateway status); a data-freshness strip with the latest POWER row, the latest SMAP day and a `smap` or `power` badge for `soilwet_source`, turning amber when stale; a recent-activity feed |
| Activity | A timeline of events: registered, recommendation sent, fallback used, refusal, model call failed, duplicate dropped, rate limit hit, STOP received. Filter by type |
| Messages | The log. Columns: direction arrow, time, shortened hash, intent chip, template-ID chip, message text. Outbound rows show a length meter such as `128/150`. Filipino text expands to show its English translation. Filters: intent, template, direction. On phones, rows become cards |
| Farmers | Table with shortened hash, barangay, water source, last crop, priority, registered date. Delete opens a confirm dialog that names the profile and says its messages are deleted too. No phone numbers anywhere |
| Indicators | Read-only table grouped by crop and sowing window, with small bars for `n_adequate` out of `n_years`. A locked panel lists thresholds, weights and the ENSO rule, labelled "Fixed before the hindcast; changed only in the repo" |
| Knowledge base | The 19 documents with source-tag chips (BSWM, PinoyRice, HVCDP), links, and usable chunks by crop and topic. A line states that restricted chunks are not loaded |

### Details that matter

- **Empty, loading and error states** on every page, with a friendly message and an icon.
- **Accessibility:** WCAG AA contrast, visible focus rings, 44 px touch targets, keyboard-usable tables.
- **No scientific editing:** nothing in the panel edits thresholds, weights, crops or the knowledge base.
- **Stack fit:** server-rendered Jinja2 templates, plain CSS with design tokens, a small vanilla JavaScript file, and Chart.js only if a chart is needed. No framework and no build step, matching the technical spec.

### A gap in the spec

The `messages` table keeps only the last 3 messages per number, and `processed_events` stores just an event ID and a time. A real Activity timeline, and the model-call log that the spec says feeds the AI-use disclosure, are therefore not possible as written.

Recommended fix: add a small `events` table with no message text and no phone data. Suggested columns:

- `id`
- `type`
- `intent`
- `template_id`
- `source` (`keyword`, `model` or `fallback`)
- `latency_ms`
- `created_at`

If the team does not add it, merge Activity into Messages. Decision: the `events` table is added.

## Logo

The logo goes at `web/static/img/logo.png` (full) and `web/static/img/logo-icon.png` (bubble and carrot crop).
Until it is added, templates show a text wordmark "AgriChat" in deep green in the same place, and pages must look finished without the image.

## Public site

The public pages use the same tokens, type scale and components as the admin panel, so both read as one product.
