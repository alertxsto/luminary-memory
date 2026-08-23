# Luminary Memory: website design system

This is the implementation contract for the public site in `website/`. The
site should feel like a lunar field archive: a quiet, precise record of how a
memory earns its way into an agent's context.

## Direction

The visual thesis is:

> Memory is trustworthy when its source, scope, evidence, and uncertainty stay
> visible.

The moon is a heavily blurred, realistic photographic silhouette, not a product
illustration or a reason to make the page look like a space dashboard. The page
uses open ledgers, field-note rows, measured dividers, and generous negative
space to teach the memory path.

The site must not use terminal-window chrome, fake application screenshots,
macOS dots, neon syntax panels, log streams, glassmorphism, or dashboard-like
feature tiles.

## Visual tokens

| Role | Token | Value |
| --- | --- | --- |
| Ink background | `--ink` | `#06070a` |
| Night surface | `--night` | `#0b0d12` |
| Raised surface | `--surface` | `#10131a` |
| Raised surface light | `--surface-light` | `#181e2b` |
| Divider | `--line` | `rgba(255, 255, 255, .12)` |
| Strong divider | `--line-strong` | `rgba(233, 246, 255, .22)` |
| Primary text | `--text` | `#ece9e4` |
| Muted text | `--muted` | `#a9b1bf` |
| Quiet text | `--quiet` | `#8f99ad` |
| Moon | `--moon` | `#e9f6ff` |
| Lunar blue accent | `--accent` | `#8ab4e8` |
| Accent light | `--accent-light` | `#b8c8d6` |
| Supported state | `--ok` | `#7fd4a8` |

Lunar blue is the single visual accent. Mint is reserved for a supported or
compatible state. Orange and amber are not part of the visual language. No
decorative accent gradients are allowed.

## Typography

- `Inter` carries display headings, body copy, navigation, and actions.
- `JetBrains Mono` carries metadata, labels, commands, tracked references, and
  small state values.

Display type should be assertive but fit its message in two lines on desktop.
Monospace is supplementary and must never make the page feel like a terminal.

## Layout language

- A sticky, restrained header keeps Why it matters, How it works, Quickstart,
  Docs, and GitHub available.
- The hero pairs one clear promise with a single observation record. A realistic
  full-moon photograph sits behind the record as a heavily blurred silhouette.
- Open rows, top and bottom rules, and alignment create hierarchy. Containers
  use square corners or no corners; rounded cards are not the default grammar.
- The narrative is hero, evidence path, operating principles, quickstart,
  system shape, Hermes boundary, field notes, and closing statement.
- Quickstart commands are copyable documentation rows, not terminal mockups.
- Documentation is a searchable field-note index rendered from
  `website/js/docs-content.js` and `website/js/docs-guides.js` at
  `website/docs.html?doc=<id>`. Documentation reading stays inside the site;
  tracked source paths are shown as provenance, not GitHub destinations.

## Component grammar

- **Observation record:** source, scope, status, and the path from capture to
  return are visible in one inspectable specimen.
- **Evidence path:** five native buttons expose Observe, Scope, Fuse, Check,
  and Return. Each step remains useful without JavaScript.
- **Principle rows:** scope, evidence, core, and conflict are presented as open
  editorial rows rather than a feature-card wall.
- **Quickstart sheet:** install, add, and recall commands have copy actions;
  Python and CLI examples use accessible tabs without terminal chrome.
- **System flow:** ingest, store, recall, and maintain are a measured flow with
  concrete implementation language.
- **Hermes rail:** the provider boundary is paired with a plain configuration
  sheet and an explicit compatibility note.
- **Field-note list:** docs use rows, filters, search, tracked source paths, and
  a live result count.

## Interaction and accessibility

- All controls are native buttons or links with visible focus rings and touch
  targets.
- The skip link, labelled navigation, semantic headings, live proof message,
  code-tab state, and documentation count remain available to assistive
  technology.
- Copy actions preserve their icon, provide a toast, and include a clipboard
  fallback.
- The mobile menu closes after navigation, closes on Escape, and exposes
  `aria-expanded` state.
- Code tabs support arrow, Home, and End keyboard navigation.
- `prefers-reduced-motion` disables reveal transitions and leaves the moon
  static.
- Responsive breakpoints collapse editorial columns into a readable one-column
  rhythm at small widths.

## Content contract

Site claims remain grounded in tracked source documentation. Illustrative
observations are labelled as observations; benchmark superiority is not
claimed; Hermes is described as a public capability boundary rather than a
version promise. The static docs reader carries concise local guides and names
the canonical `develop` source path for provenance without sending readers to
GitHub.

## Finish review

The final review includes HTML and JavaScript syntax checks, desktop and mobile
browser inspection, keyboard-visible focus states, copy/search/tab/proof/docs
interactions, no-terminal visual review, and console-error inspection. A visual
change is incomplete until it preserves this contract and repeats those checks.
