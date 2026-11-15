# Handoff 08 - Public site UI/UX redesign (Apple-style)

## Goal

Redesign the public site (`/`, `/data`) so it feels like an Apple product page.
The aim is calm, confident and obvious, not decoration.
The owner dislikes the current UI and found the simulator confusing.
The SMS simulator is what judges will touch first, so it is priority one.

Before starting, load the `apple-design` skill.
It holds the motion, material, typography and design-principle rules this handoff refers to.

## Current state (read before changing anything)

- Stack: FastAPI + Jinja2 templates, plain CSS tokens, vanilla JS, Chart.js from a pinned CDN with SRI. No framework, no build step. Keep it that way.
- Files:
  - `web/templates/base.html` - header, nav (Home, Data and limits), footer.
  - `web/templates/home.html` - hero, simulator (`#simulator`), chart card (`#rotation-chart`) plus duplicate table.
  - `web/templates/data.html` - methods and limits.
  - `web/static/site.css` - tokens shared with the admin panel (palette from `docs/admin-ui.md`).
  - `web/static/simulator.js` - simulator and chart logic.
  - `web/public.py` - routes `/`, `/data`, `POST /simulate`, `GET /indicators/{code}`.
- `POST /simulate` takes `{"from", "text"}` and returns `{reply, length, template_id, translation}`.
  It runs the real SMS handler; a random browser sender ID is used, never a phone number.
- The bot is keyword-only: `REG BATAC ULAN`, then `LAST PALAY`, `PLANT`, `WHY`; plus `HELP`, `STOP`.
  Free text such as "kailan pwede magtanim" returns the "Di ko naintindihan" fallback.
- `tests/test_web.py` asserts parts of the markup (for example `id="rotation-chart"`, `/static/simulator.js`, Chart.js pinned with SRI).
  Update those tests deliberately if the markup changes; do not just delete them.

## Problems observed (screenshot of the dark theme, desktop)

1. No guided flow: six equal chips do not show that REG comes first, and free text fails with no hint of what to type next.
2. One reply renders as three heavy blocks ("You" label, "AgriChat (Filipino)" label plus `61/150 characters`, then an orange "English translation" box).
3. The "phone" is a rounded box, not a phone: native scrollbar, top message clipped, log too short.
4. Chips wrap badly (STOP orphaned on its own row) and all have equal weight.
5. Color clash: blue focus ring against the green and orange palette; the bright green Send button is the loudest element on the page.
6. Chart: a faint ghost square renders near the 40% gridline by Mungbean (a real rendering bug, fix it whatever else happens); the table duplicates the chart; tiny legend; rotated axis title.
7. Hero is a wall of text; the key finding (mungbean holds up in El Nino years, rice and soybean collapse) is buried.
8. Large empty band below the footer.

Reproduce these in a real browser first (both themes, desktop and 375 px phone width) and screenshot them before changing code.

## Target design

### 1. Hero: one message per screen

- One large, tight headline (`clamp()` size, line-height about 1.05, letter-spacing about -0.03em).
- Lead with the result as a big figure, for example "Mungbean: 7 in 10 dry seasons had enough water. Rice: 2 in 10."
- Generous whitespace; one idea per section; gentle fade-up on scroll (disabled under reduced motion).

### 2. Simulator as a realistic phone (priority one)

- Device frame with a status bar and a header "AgriChat - SMS".
- Messages-style bubbles: outgoing right, incoming left, tails, no "You" or "AgriChat (Filipino)" labels.
- English translation as a quiet secondary line under the Filipino bubble, with a "Show translations" toggle; no orange box.
- Character count as a small ring or subtle meter (`128/150`), not a text line.
- Typing indicator (three dots) while `/simulate` is pending.
- New bubbles enter with a critically damped spring (damping 1.0, no overshoot); auto-scroll smoothly; hide the native scrollbar styling clash.
- Input styled like a Messages compose field with a round send button; focus ring uses a brand color.

### 3. Guided first conversation (priority one)

- Chips become contextual "next step" suggestions:
  start shows only `REG BATAC ULAN`; after it, `LAST PALAY`; then `PLANT`; then `WHY`.
- `HELP` and `STOP` move to a small overflow menu in the phone header.
- When the reply is the fallback template, show an inline hint chip with the next expected keyword.
- Optional: a "Play demo" button that runs the whole exchange with realistic pacing, for judges.
- Derive the step from `template_id` in the response, not from string matching on Filipino text.

### 4. Chart

- Replace Chart.js for this single chart with semantic HTML/CSS bars (accessible by default, no CDN dependency).
- iOS-style segmented control "Normal years / El Nino years" that animates bar heights on switch.
- Large direct value labels on the bars; the numeric table moves into a "Show numbers" disclosure.
- If Chart.js is removed, drop its CDN script, the SRI globals in `web/public.py` and update the related tests.

### 5. Materials, type and theme

- Sticky translucent header: `backdrop-filter: blur(20px) saturate(180%)`, semi-transparent background, scroll-edge fade instead of a hard border.
- System font stack (SF on Apple devices); size-specific tracking (tighter on large text, near 0 on body).
- Light theme as the primary look, with a matching dark theme; keep `prefers-color-scheme`.
- Calm the greens; reserve carrot orange for El Nino data and small accents (fills only, never small text on white).
- Press feedback on buttons and chips (`:active { transform: scale(.97) }`, about 100 ms).
- Honor `prefers-reduced-motion`, `prefers-reduced-transparency` and `prefers-contrast`.

### 6. "How it works" strip

Three cards in a horizontal snap carousel: NASA POWER and SMAP data, 45 years of El Nino record, one SMS on any keypad phone.

### 7. Admin console (later, separate PR)

Same tokens, translucent sidebar, iOS-Settings-style inset grouped lists, large stat numbers.
Out of scope for this handoff unless the owner asks.

## Order of work

Ship as separate PRs, each green on CI:

1. Fix the chart ghost square (bug fix: reproduce in the browser first).
2. Simulator phone redesign plus guided flow (sections 2 and 3).
3. Hero and "How it works" (sections 1 and 6).
4. Chart rebuild (section 4).
5. Materials, type and theme pass across the site (section 5), including the footer spacing.

## Constraints

- No framework, no build step. If springs are needed, a small library from cdnjs or jsdelivr with an exact pinned version and SRI is acceptable; prefer CSS where it suffices.
- Accessibility stays at least as good as now: WCAG AA contrast, visible focus, 44 px touch targets, `role="log"` and `aria-live` on the conversation, keyboard use of chips and the segmented control.
- Privacy unchanged: nothing typed is tied to a phone number.
- Follow `docs/engineering-standards.md` and the global rules (Conventional Commits, no AI attribution anywhere in the repo, no em dashes).

## Definition of done

- Every problem listed above is gone, verified by screenshots in light and dark, at desktop and 375 px width, with no horizontal scroll.
- A full simulator run (REG, LAST, PLANT, WHY, plus one free-text message) works end to end in a real browser against the running app.
- `uv run pytest` and lint pass with no new warnings; updated tests cover the new markup and the guided-step logic.
- Reduced-motion and reduced-transparency modes checked.
