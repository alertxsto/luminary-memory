# Architectural Plan & Design Specification: luminary-memory Landing Page

> **Target File:** `/home/alertxsto/luminary-memory/website/plan.md`  
> **Project:** `luminary-memory` (Self-hosted memory layer for AI agents)  
> **Type:** High-Performance Developer Tool Landing Page (Static Web Application)  
> **Mode:** **Persuade** (Technical decision maker / developer decides, stars, and installs)  
> **Design Philosophy:** Anti-slop, intentional, functional minimalism, dark-theme depth via surface luminance.

---

## 1. Executive Summary & Design Read

### 1.1 Brief & Aesthetic Inference
* **Page Kind:** Developer Tool Landing Page (Single-page static site for open-source Python library / CLI).
* **Audience:** Senior AI engineers, agent builders, backend architects, and open-source practitioners who value privacy, zero-cloud dependency, local execution, and low cognitive overhead.
* **Design Read:** *High-clarity, Linear-style technical minimalist developer tool. Restrained motion, rigorous typographic hierarchy, single accent color on deep slate neutrals, and depth created through background surface luminance shifts rather than harsh borders or gratuitous gradient overlays.*
* **Core Dials:**
  * `DESIGN_VARIANCE: 6` (Structured, content-driven asymmetry without chaotic layouts)
  * `MOTION_INTENSITY: 4` (Crisp micro-interactions, subtle hover feedback, zero infinite loop gimmicks, strictly respecting `prefers-reduced-motion`)
  * `VISUAL_DENSITY: 4` (Balanced spacing scale, high information scent, scannable terminal snippets)

---

## 2. Audit of Existing Scaffold (`index.html`)

The current scaffold at `index.html` provides a foundational outline but contains multiple amateur AI tells, cliché tropes, and functional gaps:

| Current Scaffold Element | Identified Issue / Cliché | Redesign Solution |
| :--- | :--- | :--- |
| **Hero Badge** (`.hero-badge`) | Cliché "biscuit pill" trope right above headline (`v0.1.0 · Apache-2.0`). | Replace with a clean, semantic single-eyebrow or integrated metadata tag inside the terminal code block. |
| **Headline Gradient** (`.gradient`) | Multi-color gradient soup across keywords. | Strictly banned. Pure high-contrast white text (`#F8FAFC`) with single-color brand accent highlighting where necessary. |
| **Feature Icons** (🔒, 🧠, ⚡, 🎯, 🧹, 📈) | Raw OS emoji icons in feature cards (breaks professional devtool aesthetic). | Replace with precision, monochromatic SVG technical glyphs (1.5px stroke width, matching system accent/neutral). |
| **Depth & Boundaries** | Flat cards relying on generic light borders over black. | Layered dark palette: Void (`#090A0C`), Base (`#0F1115`), Surface (`#161920`), Highlight (`#1E222B`) with subtle `1px` top-edge highlight. |
| **Call to Action (CTA) Conflicts** | Multiple duplicate CTAs with identical labels ("Get started" in Nav, Hero, and Quickstart). | Consolidate intent: Primary CTA = **`Quickstart`** (scroll to copyable commands); Secondary = **`Star on GitHub`** with live GitHub release tag. |
| **Architecture Representation** | Plain vertical text cards connected with basic `↓` arrows. | Structured 4-stage interactive pipeline flow with explicit data-flow stages (Ingest, Backend Storage, 4-Way Fusion Recall, Lifecycle Engine). |
| **Interactive Assets** | Missing `css/style.css` and `js/main.js` files; static non-interactive code block. | Self-contained modular CSS system and lightweight vanilla JS for clipboard copy, tab switching (Python vs CLI), and responsive drawer. |

---

## 3. Mandatory Design Principles & Constraints

1. **One Accent Color + Neutrals (No Gradient Soup):**
   * Neutral foundation built on deep Slate/Zinc tones.
   * Single locked accent: **Luminous Emerald / Mint (`#00E599` / `hsl(160, 100%, 45%)`)** signifying memory vitality, speed, and terminal precision.
   * Zero purple-on-dark glowing backdrops, zero rainbow gradient text fills.
2. **Strict Spacing Scale:**
   * Standard 8-point geometric scale strictly enforced: `4px (0.25rem)`, `8px (0.5rem)`, `12px (0.75rem)`, `16px (1rem)`, `24px (1.5rem)`, `32px (2rem)`, `48px (3rem)`, `64px (4rem)`.
3. **Max 2 Typefaces:**
   * **Primary Sans (UI & Display):** `Inter` (or `Geist Sans`) for clean geometric clarity, high legibility at all scales, tight tracking on display headings.
   * **Monospace (Code & Terminal):** `JetBrains Mono` for code blocks, terminal outputs, CLI flags, badges, and latency metrics.
4. **WCAG 2.1 AA Contrast Compliance:**
   * High-contrast text: Primary text on dark surfaces $\ge 12:1$ (exceeds $4.5:1$ requirement).
   * Muted labels and secondary body text strictly maintain $\ge 4.5:1$ contrast against their immediate background.
5. **Single Primary Action Per Viewport:**
   * No competing primary buttons. Primary action is always to test and copy the installation/quickstart snippet or view the repository.
6. **Content-Driven Layout (No Premature Equal-Box Grids):**
   * Grids are shaped around actual value props. Key features get larger visual real estate; secondary details remain compact. No empty filler cells.
7. **Dark Theme Depth via Surface Luminance Shift:**
   * Elevation hierarchy created through background tone stepping (Void $\rightarrow$ Base $\rightarrow$ Card Surface $\rightarrow$ Hover State) rather than stark white borders.
8. **Assertive Typographic Hierarchy:**
   * Hero headline max 2 lines on desktop (`clamp(2.25rem, 5vw, 3.5rem)`), tracking `-0.03em`.
   * Subtext strictly capped at under 20 words (`1.125rem`, line-height `1.6`).

---

## 4. Design Tokens Specification

### 4.1 Color System
```css
:root {
  /* Surface Layers (Luminance Stacking) */
  --bg-void:        #08090b; /* Page background base */
  --bg-base:        #0e1015; /* Main container backgrounds */
  --bg-surface-1:   #14171f; /* Primary cards and section blocks */
  --bg-surface-2:   #1b202b; /* Elevated panels, terminal headers */
  --bg-surface-3:   #242b3a; /* Hover states, active tabs, pill containers */

  /* Borders & Dividers */
  --border-subtle:  rgba(255, 255, 255, 0.05); /* Standard dividers */
  --border-surface: rgba(255, 255, 255, 0.09); /* Card contours */
  --border-focus:   rgba(0, 229, 153, 0.40);   /* Focused interactive items */

  /* Text & Content */
  --text-primary:   #f8fafc; /* Headings, primary code values (WCAG ~17:1) */
  --text-secondary: #94a3b8; /* Body copy, descriptions (WCAG ~7.5:1) */
  --text-muted:     #64748b; /* Captions, inactive tabs, step numbers (WCAG ~4.6:1) */

  /* Locked Brand Accent (Luminous Emerald) */
  --accent:         #00e599; /* Primary accent: CTA, active states, key data */
  --accent-hover:   #00ffaa; /* Interactive hover */
  --accent-subtle:  rgba(0, 229, 153, 0.10); /* Tag backgrounds, glow fills */
  --accent-border:  rgba(0, 229, 153, 0.25); /* Accent highlight borders */

  /* Code Syntax Tokens */
  --syntax-keyword: #38bdf8; /* Light sky blue for def/import/from */
  --syntax-string:  #00e599; /* Brand accent for string literals */
  --syntax-func:    #a78bfa; /* Soft violet for method calls */
  --syntax-comment: #64748b; /* Slate for comments */
}
```

### 4.2 Spacing & Layout Tokens
```css
:root {
  --space-1: 0.25rem;  /* 4px  */
  --space-2: 0.5rem;   /* 8px  */
  --space-3: 0.75rem;  /* 12px */
  --space-4: 1.0rem;   /* 16px */
  --space-5: 1.5rem;   /* 24px */
  --space-6: 2.0rem;   /* 32px */
  --space-7: 3.0rem;   /* 48px */
  --space-8: 4.0rem;   /* 64px */
  --space-9: 6.0rem;   /* 96px */

  --max-width: 1200px;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-pill: 9999px;
}
```

### 4.3 Typography Scale
| Role | Font Family | Size (Mobile $\rightarrow$ Desktop) | Line Height | Weight | Letter Spacing |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Hero Title** | `Inter`, sans-serif | `2.25rem` (36px) $\rightarrow$ `3.5rem` (56px) | `1.1` | `700` | `-0.035em` |
| **Section Title** | `Inter`, sans-serif | `1.75rem` (28px) $\rightarrow$ `2.25rem` (36px) | `1.2` | `600` | `-0.025em` |
| **Card Title** | `Inter`, sans-serif | `1.125rem` (18px) $\rightarrow$ `1.25rem` (20px) | `1.3` | `600` | `-0.015em` |
| **Body Large** | `Inter`, sans-serif | `1.0625rem` (17px) $\rightarrow$ `1.125rem` (18px) | `1.6` | `400` | `0` |
| **Body Regular** | `Inter`, sans-serif | `0.9375rem` (15px) $\rightarrow$ `1.0rem` (16px) | `1.55` | `400` | `0` |
| **Code / Monospace**| `JetBrains Mono` | `0.875rem` (14px) $\rightarrow$ `0.9375rem` (15px) | `1.5` | `500` | `-0.01em` |
| **Eyebrow / Badge** | `JetBrains Mono` | `0.75rem` (12px) | `1.0` | `600` | `+0.08em` |

---

## 5. Per-Section Content, Hierarchy & Component Architecture

```
┌────────────────────────────────────────────────────────┐
│ [01] Top Navigation Bar (Logo | Links | GitHub Button)  │
├────────────────────────────────────────────────────────┤
│ [02] Hero Section (Headline + Copy + Interactive Code) │
├────────────────────────────────────────────────────────┤
│ [03] Value Propositions (6 Core Architectural Strengths)│
├────────────────────────────────────────────────────────┤
│ [04] Quickstart Pipeline (4 Steps: Python & CLI Tabs)   │
├────────────────────────────────────────────────────────┤
│ [05] Architecture Visual Pipeline (Ingest→Store→Recall) │
├────────────────────────────────────────────────────────┤
│ [06] Footer (Metadata | Repository Links | License)    │
└────────────────────────────────────────────────────────┘
```

---

### 5.1 Section 1: Navigation Bar
* **Visual Structure:** Sticky header (`height: 64px`), subtle background blur (`backdrop-filter: blur(12px)`), bottom divider (`--border-subtle`).
* **Content:**
  * **Brand Mark:** Minimalist geometric glyph + `luminary-memory` in `Inter SemiBold`.
  * **Navigation Anchors:** `Features`, `Quickstart`, `Architecture`, `Docs`.
  * **Primary Action:** `GitHub` button with live star counter icon (`svg`) and external link indicator.
* **Responsive Behavior:** Navigation items collapse into a mobile drawer or minimal icon row on screens `< 768px`.

---

### 5.2 Section 2: Hero Section (The Core Conversion Moment)
* **Visual Composition:** Split-screen layout (52% left content, 48% right interactive terminal simulator) on desktop; single-column stacked on mobile.
* **Left Column — Message Hierarchy:**
  * **Eyebrow:** Max 1 per 3 sections rule strictly obeyed. `SELF-HOSTED AI MEMORY LAYER`.
  * **Headline (Strictly 2 lines max):**
    > **Memory your AI agents**  
    > **actually remember.**
  * **Subtext (Under 20 words):**
    > *Durable, cross-session memory with four-strategy fused recall. Runs entirely on your infrastructure — no cloud, zero token bloat.*
  * **Actions:**
    * Primary: `Get Started` button (smooth scroll anchor to `#quickstart`).
    * Secondary: `pip install luminary-memory` quick-copy box with instant 1-click clipboard feedback.
* **Right Column — Terminal Code Simulator:**
  * **Design:** Styled terminal box (`--bg-surface-2`) with macOS-style window controls and tab switcher: `Python API` vs `Terminal CLI`.
  * **Interactive Feature:** Clickable tabs switch between the minimal Python snippet and CLI commands with instant syntax highlighting.
  * **Content (Python Tab):**
    ```python
    from luminary_memory import MemoryClient

    client = MemoryClient(db_path="memory.db")
    client.ingest("The deploy target is staging", tags=["deploy"])

    # 4 strategies fused into one ranked recall
    result = client.recall("where do we deploy?")
    # → 0.942 [deploy] The deploy target is staging
    ```

---

### 5.3 Section 3: Features Grid (6 Architectural Pillars)
* **Layout Structure:** Asymmetric 6-card grid with rhythm.
  * 2 Primary wide spotlight cards (Top row).
  * 4 Compact utility cards (Bottom 2x2 grid).
* **Card Content & Vector Visuals:**

```
┌──────────────────────────────────────┬──────────────────────────────────────┐
│ [Card 1] 4-Strategy Fused Recall      │ [Card 2] 100% Self-Hosted & Private  │
│ (Semantic + Keyword + Temporal + Graph)│ (Zero cloud calls, zero token costs) │
├──────────────────┬───────────────────┼──────────────────┬───────────────────┤
│ [Card 3] Zero    │ [Card 4] Budget-  │ [Card 5] Self-   │ [Card 6] Scalable │
│ Dependencies     │ Aware Truncation  │ Maintaining TTL  │ SQLite → pgvector │
└──────────────────┴───────────────────┴──────────────────┴───────────────────┘
```

1. **Card 1 (Spotlight): Four Retrieval Strategies in One Recall**
   * *Glyph:* Parallel routing merge icon.
   * *Detail:* Semantic (ONNX embeddings), keyword (SQLite FTS5), temporal decay, and co-occurrence graph fuse via Reciprocal Rank Fusion (RRF).
2. **Card 2 (Spotlight): 100% Local & Sovereign**
   * *Glyph:* Shielded CPU node.
   * *Detail:* All memories and embeddings remain inside your process. No third-party API dependencies, no data leakage, zero per-token storage cost.
3. **Card 3: Zero Hard Dependencies**
   * *Glyph:* Lightweight package box.
   * *Detail:* Operates on Python standard library + SQLite out of the box with local CPU embeddings.
4. **Card 4: Budget-Aware Context Safety**
   * *Glyph:* Token gauge meter.
   * *Detail:* Deduplication and strict token budget enforcement prevent memory injections from exploding LLM context windows.
5. **Card 5: Autonomous Store Maintenance**
   * *Glyph:* Automated lifecycle cycle.
   * *Detail:* Built-in lifecycle worker automatically manages TTL decay, near-duplicate consolidation (Jaccard), and stale item pruning.
6. **Card 6: Instant Backend Scalability**
   * *Glyph:* Database switchover fork.
   * *Detail:* Pluggable backend architecture allows migrating from zero-config SQLite to PostgreSQL + pgvector without changing a line of code.

---

### 5.4 Section 4: Quickstart Pipeline (4 Steps to Production)
* **Visual Composition:** Linear vertical pipeline timeline with numeric progress indicators (`1`, `2`, `3`, `4`).
* **Step Breakdown:**
  * **Step 01 — Install:**
    * Action: `pip install luminary-memory`
    * Output indicator: Installs in $< 3$ seconds, includes ONNX CPU runtime.
  * **Step 02 — Ingest Memory:**
    * Action: Store facts, user preferences, or task states with metadata tags and optional TTL.
  * **Step 03 — Query & Recall:**
    * Action: Single `recall()` query executing 4-way parallel fusion returning ranked memories with relevance scores.
  * **Step 04 — Autonomous Maintenance:**
    * Action: `run_lifecycle()` cleans up expired memories and deduplicates near-identical entries.
* **Interactive Element:** Tab switcher at the top of the Quickstart section allowing the developer to view the walkthrough in **Python Script** or **CLI Commands**.

---

### 5.5 Section 5: Architecture Visual Pipeline
* **Visual Blueprint:** Clean, horizontal/vertical responsive flowchart mapping the memory lifecycle across 4 distinct processing phases:

```
[ INGESTION PHASE ]
  Raw Memory String ───► Content Whitelist ───► Local ONNX Embeddings (384-d)
                                                         │
                                                         ▼
[ STORAGE BACKEND ]
  SQLite + FTS5 Table  ◄────────────────────────── Insert / Update
  (or pgvector table)
                                                         │
                                                         ▼
[ RECALL & FUSION ENGINE ]
  Parallel Queries ────► 1. Vector Cosine (Semantic)
                         2. FTS5 BM25 (Keyword)
                         3. Access Decay (Temporal)
                         4. Co-occurrence (Graph)
                                 │
                                 ▼
                         Reciprocal Rank Fusion (RRF, k=60)
                                 │
                                 ▼
                         Jaccard Deduplication (thresh: 0.85)
                                 │
                                 ▼
                         Token Budget Truncation (e.g. 4096 tok)
                                                         │
                                                         ▼
[ AUTONOMOUS LIFECYCLE ]
  Scheduled Sweep ─────► TTL Expiry ──► Consolidation ──► Prune Stale
```

* **Component Design:** Rendered with clean semantic HTML containers and CSS flex/grid lines, annotated with exact algorithmic parameters (`RRF k=60`, `dim=384`, `Jaccard=0.85`).

---

### 5.6 Section 6: Footer & Repository Metadata
* **Content:**
  * Left: Brand identity, version badge (`v0.1.0`), open-source license (`Apache-2.0`).
  * Center: Direct links to GitHub Repository, PyPI Package, Documentation, and Changelog.
  * Right: Author credits (`© 2026 Dwiky Candra`) with responsive alignment.

---

## 6. File Structure & Code Organization

```
/home/alertxsto/luminary-memory/website/
├── plan.md                # This comprehensive architectural plan
├── index.html             # Refactored semantic single-page HTML
├── .nojekyll              # Prevents GitHub Pages Jekyll engine from ignoring files
├── css/
│   ├── tokens.css         # CSS Variables (Color, Typography, Spacing, Surface layers)
│   ├── reset.css          # Modern base reset & box-sizing
│   ├── layout.css         # Responsive containers, grid systems, navigation & footer
│   ├── components.css     # Buttons, cards, terminal simulator, badges, pipeline nodes
│   └── syntax.css         # Monospace code highlight formatting
├── js/
│   ├── app.js             # Tab toggles, 1-click clipboard copy with feedback, nav drawer
│   └── pipeline.js        # Interactive architecture node inspection (optional lightweight)
└── assets/
    ├── favicon.svg        # Scalable SVG brand icon
    └── icons/             # Clean 1.5px monochrome SVG technical icons
```

### 6.1 Pure Vanilla Implementation Strategy
* **Zero JavaScript Frameworks:** No React/Next/Vite overhead for a high-performance marketing/docs landing page. Single HTML load under 25KB gzipped.
* **Vanilla CSS with Native Variables:** Instant painting without CSS runtime overhead.
* **Zero Heavy JS Libraries:** All interactions (tabs, copy buttons, scroll reveal) implemented in lightweight native JS ($< 4\text{ KB}$).

---

## 7. Accessibility (a11y) & Performance Checklist

| Category | Requirement | Implementation Detail |
| :--- | :--- | :--- |
| **Contrast** | WCAG 2.1 AA Compliance | All text elements test $> 4.5:1$ against surface backgrounds. Primary headings $> 12:1$. |
| **Reduced Motion** | `prefers-reduced-motion` | Motion disabled or simplified to opacity transitions when user system setting is enabled. |
| **Keyboard Navigation** | Full Focus Visibility | Explicit `--border-focus` ring with `outline-offset: 2px` on all buttons, tabs, and interactive anchors. |
| **Screen Readers** | Semantic HTML5 & ARIA | `<nav>`, `<main>`, `<section>`, `<code>`, `<pre>`, `aria-label` for icon-only links, `role="tab"` for code switchers. |
| **Performance** | Sub-50ms First Contentful Paint | Critical CSS loaded in `<head>`, fonts preconnected, zero render-blocking third-party scripts. |

---

## 8. Deployment Strategy for GitHub Pages

The website is designed for zero-config GitHub Pages hosting directly from the repository.

### 8.1 GitHub Pages Configuration Options
1. **Option A (Dedicated GitHub Action Workflow — Recommended):**
   * Path: `.github/workflows/deploy-website.yml`
   * Workflow triggers on pushes to `main` modifying `website/**`.
   * Automatically publishes the `/website` directory to the `gh-pages` branch.
2. **Option B (Root / Docs Setting):**
   * Configure GitHub Repository Settings $\rightarrow$ **Pages** $\rightarrow$ Source: Deploy from Branch (`main` / `/website` or `gh-pages`).

### 8.2 GitHub Pages Configuration Requirements
* Include `.nojekyll` in the root of the published artifact to prevent Jekyll from omitting subdirectories or underscore assets.
* Use relative asset paths (`href="css/tokens.css"`, `src="js/app.js"`) so the landing page resolves correctly under custom domain or project paths (`https://alertxsto.github.io/luminary-memory/`).

---

## 9. Phased Implementation Roadmap (For Execution)

* **Phase 1: Token Engine & Base CSS Setup**
  * Create `css/tokens.css`, `css/reset.css`, `css/layout.css`, `css/components.css`.
* **Phase 2: Semantic HTML Structure Overhaul**
  * Refactor `index.html` to align with the 6-section blueprint, eliminating emojis, fixing CTA intent, and establishing the 2-line hero hierarchy.
* **Phase 3: Interactive Components & Assets**
  * Build the tabbed terminal preview (Python vs CLI) and 1-click clipboard copy utility in `js/app.js`.
  * Embed clean inline SVG glyphs in place of emojis.
* **Phase 4: Architecture Visual Pipeline**
  * Implement the responsive 4-phase data-flow diagram with styled node states.
* **Phase 5: Pre-Flight Verification & a11y Audit**
  * Verify mobile collapse breakpoints ($<640\text{px}$, $768\text{px}$, $1024\text{px}$).
  * Verify WCAG AA contrast on all interactive elements.
* **Phase 6: GitHub Pages Deployment Test**
  * Validate path resolution and `.nojekyll` configuration.
