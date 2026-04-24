# UI Design Research - Comprehensive Reference for LLM-Generated Interfaces

**Purpose**: Production reference material for encoding high-quality UI design knowledge into a Claude skill. Compiled from web research across design systems, modern trends, and AI UI generation best practices (Feb 2026).

---

## Table of Contents

1. [A. Visual Design Fundamentals](#a-visual-design-fundamentals)
2. [B. Design Systems & Component Libraries](#b-design-systems--component-libraries)
3. [C. Layout & Composition](#c-layout--composition)
4. [D. Modern UI Trends (2024-2026)](#d-modern-ui-trends-2024-2026)
5. [E. Practical Implementation](#e-practical-implementation)
6. [F. Encoding This Into a Claude Skill](#f-encoding-this-into-a-claude-skill)

---

## A. Visual Design Fundamentals

### A1. Color Theory

#### The 60-30-10 Rule

The foundational color distribution framework from interior design, universally applied to UI:

- **60% - Primary/Dominant color**: Background, large surfaces. Usually neutral (white, off-white, dark gray). Creates the canvas.
- **30% - Secondary color**: Cards, panels, navigation, sidebars. Supports the primary and adds depth.
- **10% - Accent color**: CTAs, buttons, icons, active states, links. Draws attention to interactive elements.

This ratio ensures the accent color is instantly visible, making it faster for users to identify actionable elements.

#### Color Harmony Methods

| Method | Description | Use Case |
|--------|-------------|----------|
| **Monochromatic** | One hue, varying lightness/saturation | Minimal, elegant UIs |
| **Analogous** | Adjacent hues on wheel (e.g. blue + teal + green) | Harmonious, nature-inspired |
| **Complementary** | Opposite hues (e.g. blue + orange) | High contrast, attention-grabbing CTAs |
| **Split-complementary** | One hue + two adjacent to its complement | Less tension than complementary, more nuance |
| **Triadic** | Three evenly spaced hues | Vibrant, playful interfaces |

#### OKLCH Color Space (Modern Standard)

OKLCH is the modern CSS color model that should replace RGB/HSL for palette generation:

- **O** = Perceptual lightness (0-1) - predictable contrast behavior
- **K** = Chroma (saturation, 0-0.4) - consistent across hues
- **L** = Lightness
- **C** = Chroma
- **H** = Hue (0-360)

**Why OKLCH wins for design systems:**
- Perceptually uniform: if you keep lightness consistent across palettes, contrast ratios stay constant
- No "unexpected darkening" like HSL
- Algorithmic palette generation: rotate hue while keeping L and C fixed = consistent visual weight
- CSS native: `oklch(0.7 0.15 250)` works in all modern browsers

#### WCAG Contrast Requirements

| Level | Normal Text | Large Text (18pt+/14pt bold+) |
|-------|-------------|-------------------------------|
| **AA** | 4.5:1 minimum | 3:1 minimum |
| **AAA** | 7:1 minimum | 4.5:1 minimum |
| **Non-text** (icons, borders) | 3:1 | 3:1 |

**Practical rules:**
- Body text on backgrounds: always meet AA (4.5:1)
- Interactive element borders: 3:1 against background
- Disabled elements: exempt from contrast requirements but should still be visually distinguishable
- Focus indicators: 3:1 against adjacent colors
- Never rely on color alone to convey information (color blindness)

#### Palette Generation Algorithm

```
1. Choose brand hue H (0-360)
2. Set neutral base: oklch(0.98 0.005 H) for light, oklch(0.15 0.01 H) for dark
3. Generate scale by varying L (lightness):
   - 50:  oklch(0.97 0.01 H)   // lightest bg
   - 100: oklch(0.93 0.02 H)   // subtle bg
   - 200: oklch(0.87 0.04 H)   // hover states
   - 300: oklch(0.78 0.08 H)   // borders
   - 400: oklch(0.68 0.12 H)   // placeholder text
   - 500: oklch(0.55 0.15 H)   // secondary text
   - 600: oklch(0.45 0.15 H)   // primary text
   - 700: oklch(0.37 0.13 H)   // headings
   - 800: oklch(0.28 0.10 H)   // bold elements
   - 900: oklch(0.20 0.08 H)   // darkest
   - 950: oklch(0.13 0.06 H)   // near-black
4. Accent: rotate hue by 30-180 degrees, higher chroma (0.18-0.25)
5. Semantic colors: success=green(H~145), warning=yellow(H~85), error=red(H~25), info=blue(H~250)
6. Verify all text/bg combinations meet WCAG AA
```

#### CSS Variables Pattern

```css
:root {
  /* Brand scale */
  --color-primary-50: oklch(0.97 0.01 250);
  --color-primary-100: oklch(0.93 0.025 250);
  --color-primary-500: oklch(0.55 0.15 250);
  --color-primary-900: oklch(0.20 0.08 250);

  /* Semantic */
  --color-bg: var(--color-primary-50);
  --color-surface: white;
  --color-text: var(--color-primary-900);
  --color-text-muted: var(--color-primary-500);
  --color-border: var(--color-primary-200);
  --color-accent: oklch(0.65 0.2 30);

  /* Functional */
  --color-success: oklch(0.65 0.18 145);
  --color-warning: oklch(0.75 0.15 85);
  --color-error: oklch(0.55 0.2 25);
  --color-info: oklch(0.6 0.15 250);
}

.dark {
  --color-bg: var(--color-primary-950);
  --color-surface: var(--color-primary-900);
  --color-text: var(--color-primary-50);
  --color-text-muted: var(--color-primary-400);
  --color-border: var(--color-primary-700);
}
```

### A2. Typography

#### Type Scale (Modular Scale)

A modular scale creates mathematical harmony between font sizes. Common ratios:

| Ratio | Name | Factor | Best For |
|-------|------|--------|----------|
| 1.125 | Major Second | Tight | Dense data UIs, dashboards |
| 1.200 | Minor Third | Moderate | Body-heavy content, apps |
| 1.250 | Major Third | **Recommended** | General purpose, balanced |
| 1.333 | Perfect Fourth | Generous | Marketing, editorial |
| 1.414 | Augmented Fourth | Dramatic | Landing pages, hero sections |
| 1.618 | Golden Ratio | Extreme | Bold editorial, art-directed |

**Implementation (base 16px, ratio 1.25):**

```
Step -2: 10.24px  (0.64rem)  - Caption, fine print
Step -1: 12.80px  (0.80rem)  - Small labels
Step  0: 16.00px  (1.00rem)  - Body text (base)
Step  1: 20.00px  (1.25rem)  - Large body, lead
Step  2: 25.00px  (1.563rem) - H4
Step  3: 31.25px  (1.953rem) - H3
Step  4: 39.06px  (2.441rem) - H2
Step  5: 48.83px  (3.052rem) - H1
Step  6: 61.04px  (3.815rem) - Display
```

#### Font Pairing Principles

**Core rule: Create contrast, not conflict.**

| Strategy | Heading | Body | Effect |
|----------|---------|------|--------|
| **Serif + Sans** | Playfair Display | Source Sans 3 | Classic editorial elegance |
| **Display + Clean** | Clash Display | Inter | Modern startup energy |
| **Mono + Sans** | JetBrains Mono | IBM Plex Sans | Technical, developer-focused |
| **Slab + Geometric** | Roboto Slab | Nunito | Friendly yet grounded |
| **Variable weight** | Single font, 200-900 weights | Same family | Cohesive, efficient loading |

**Font categories by context:**

| Context | Recommended Fonts | Avoid |
|---------|------------------|-------|
| **Code/Technical** | JetBrains Mono, Fira Code, Space Grotesk | Comic Sans, cursive |
| **Editorial/Blog** | Playfair Display, Crimson Pro, Fraunces, Newsreader | System fonts |
| **SaaS/Startup** | Clash Display, Satoshi, Cabinet Grotesk | Times New Roman |
| **Corporate** | IBM Plex family, Source Sans 3 | Papyrus, Impact |
| **Distinctive** | Bricolage Grotesque, Obviously, Newsreader | Arial, Helvetica |

**The "AI Slop" fonts to avoid (these signal generic AI generation):**
- Inter, Roboto, Open Sans, Lato, Arial, system-ui, sans-serif defaults
- Space Grotesk (overused as "distinctive" alternative - now equally generic)

**Weight pairing rule:** Use extremes for impact - pair 100/200 with 800/900 (not 400 vs 600). Size jumps of 3x+ create drama, 1.5x creates subtlety.

#### Line Height & Spacing

```
Body text (14-18px):  line-height 1.5-1.75
Large body (18-24px): line-height 1.4-1.6
Headings (24-48px):   line-height 1.1-1.3
Display (48px+):      line-height 1.0-1.15

Letter-spacing:
- Body: 0 to 0.01em (natural)
- Small caps/labels: 0.05-0.1em (open up)
- Large headings: -0.01 to -0.03em (tighten)
- All-caps: 0.05-0.15em (always expand)
```

#### Paragraph Width (Measure)

- Optimal: 45-75 characters per line
- Ideal: ~66 characters
- Minimum readable: 40 characters
- Maximum before fatigue: 80 characters
- CSS: `max-width: 65ch` on paragraph containers

### A3. Spacing System

#### The 4px Base Grid

All spacing values derive from a base unit, typically 4px. This creates visual rhythm and alignment.

```
Token    px    rem     Use
------------------------------------------
0        0     0       Reset
0.5      2     0.125   Hairline borders, fine adjustments
1        4     0.25    Tight inline spacing
1.5      6     0.375   Compact elements
2        8     0.5     Input padding, button padding-y
3        12    0.75    List item gaps, small card padding
4        16    1       Standard padding, section margins
5        20    1.25    Card padding, form group gaps
6        24    1.5     Section padding, comfortable gaps
8        32    2       Large section padding
10       40    2.5     Page section margins
12       48    3       Major section breaks
16       64    4       Hero padding, generous spacing
20       80    5       Full section breaks
24       96    6       Page-level spacing
```

**Tailwind mapping:**

```
p-1 = 4px    p-2 = 8px    p-3 = 12px   p-4 = 16px
p-5 = 20px   p-6 = 24px   p-8 = 32px   p-10 = 40px
p-12 = 48px  p-16 = 64px  p-20 = 80px  p-24 = 96px
```

**Rules:**
- Internal component spacing: 4-12px (p-1 to p-3)
- Component padding: 12-24px (p-3 to p-6)
- Between components: 16-32px (gap-4 to gap-8)
- Between sections: 48-96px (py-12 to py-24)
- Between page regions: 64-128px (py-16 to py-32)

### A4. Visual Hierarchy

**The four levers of hierarchy (in order of power):**

1. **Size** - Largest = most important. 3x+ jump for primary hierarchy.
2. **Color/Contrast** - High contrast = attention. Muted = secondary. Accent = action.
3. **Weight** - Bold (700-900) for emphasis. Light (300-400) for supporting.
4. **Position** - Top-left = first seen (LTR). Center = focal point. Isolated = important.

**Hierarchy levels in a typical page:**

```
Level 1: Page title / Hero heading    - Display size, heaviest weight, brand color
Level 2: Section headings             - H2 size, bold, strong contrast
Level 3: Subsection / Card titles     - H3/H4 size, semibold
Level 4: Body text                    - Base size, regular weight, default color
Level 5: Supporting / Secondary text  - Smaller size, lighter weight, muted color
Level 6: Metadata / Captions          - Smallest, lightest, most muted
```

**CTA hierarchy:**

```
Primary CTA:   Filled button, accent color, larger size, shadow
Secondary CTA: Outlined button, neutral color, standard size
Tertiary CTA:  Text link / ghost button, subtle color
Destructive:   Red/error color, filled or outlined based on danger level
```

### A5. Iconography Principles

**Sizing:**
- Inline with text: match x-height or cap height (16-20px typically)
- Standalone actions: 24px (standard), 20px (compact), 32px (touch targets)
- Feature/marketing icons: 32-48px
- Hero/decorative: 64px+

**Consistency rules:**
- Use one icon library throughout (Lucide, Heroicons, Phosphor, Tabler)
- Match stroke weight to font weight (2px stroke = regular text, 1.5px = light)
- Maintain consistent sizing per context (all nav icons same size, all button icons same size)
- Optical alignment: icons often need 1-2px visual adjustment to appear centered

**Color:**
- Interactive icons: inherit text color, change on hover/active
- Decorative icons: muted or accent color
- Status icons: semantic colors (green check, red x, yellow warning)
- Never make icons the sole indicator of meaning (always pair with text or aria-label)

**Recommended libraries:**
- **Lucide React** - Clean, consistent, 1000+ icons, MIT license, tree-shakeable
- **Heroicons** - By Tailwind team, 300+ icons, two styles (outline/solid)
- **Phosphor Icons** - 7000+ icons, 6 weights, highly customizable
- **Tabler Icons** - 5000+ icons, 2px stroke, MIT license

---

## B. Design Systems & Component Libraries

### B1. Material Design 3 (Google)

**Core foundations (7 pillars):**

1. **Color** - Dynamic Color system extracts palette from user's wallpaper. Tonal palettes with 13 tones per hue. Light/dark themes auto-generated.
2. **Typography** - Type scale with 15 roles (display large/medium/small, headline L/M/S, title L/M/S, body L/M/S, label L/M/S). Google Sans default.
3. **Shape** - Rounded corners with scale (none, extra-small 4dp, small 8dp, medium 12dp, large 16dp, extra-large 28dp, full). Shape morphing in M3 Expressive.
4. **Motion** - Duration tokens (short1-4, medium1-4, long1-4, extra-long1-4). Easing: emphasized, emphasized-decelerate, emphasized-accelerate, standard, standard-decelerate, standard-accelerate. Spring-based motion in M3 Expressive.
5. **Interaction** - Ripple effects, state layers (hover 8% opacity, focus 10%, press 10%, drag 16%).
6. **Layout** - 4dp baseline grid. Responsive columns (4 compact, 8 medium, 12 expanded). Margins and gutters adapt per breakpoint.
7. **Elevation** - 5 levels (0dp, 1dp, 3dp, 6dp, 8dp, 12dp). Tonal elevation in M3 (color shift instead of shadow).

**Key M3 design principles:**
- Personal (Dynamic Color, user-centric customization)
- Adaptive (responsive to device, input method, screen size)
- Expressive (bold color, organic motion, distinctive shapes)

**M3 Expressive update (2025):**
- 35 new shapes + shape morphing
- Spring-based animations that bounce and stretch
- More colorful, vibrant component styles
- Increased emotional engagement through motion

### B2. Apple Human Interface Guidelines

**Core principles:**

1. **Clarity** - Clean, precise, uncluttered. Limited elements. Clear symbols and icons.
2. **Deference** - Content is primary. UI recedes to support content, not compete with it.
3. **Depth** - Layers, translucency, motion convey hierarchy and spatial relationships.

**Liquid Glass (2025 redesign):**
- Most significant visual overhaul since iOS 7 (2013)
- Translucent, glass-like UI elements with optical refraction
- Elements respond dynamically to light, content, and motion
- Rounded, fluid shapes that adapt to content
- Simulates real-world glass physics

**Key HIG values:**
- **Consistency** - Learned behaviors transfer across apps and platforms
- **Direct manipulation** - Users interact with content directly, not through abstract controls
- **Feedback** - Every action has visible, immediate response
- **Metaphors** - Familiar real-world concepts guide digital interaction
- **User control** - Users initiate actions, app responds (never the reverse)

**Typography:**
- SF Pro (system font) with optical sizing
- Dynamic Type supports user-preferred sizes
- 11 text styles with semantic meaning (Large Title, Title 1-3, Headline, Body, Callout, Subhead, Footnote, Caption 1-2)

### B3. Shadcn/ui (Why It Works)

**Philosophy: Copy, don't install.**

Instead of `npm install component-library`, you run `npx shadcn-ui@latest add button` which copies the component source code into your project. You own it. You edit it. You control everything.

**Architecture:**
- **Radix UI primitives** - Unstyled, accessible base components (dialogs, dropdowns, tooltips, etc.) with ARIA compliance, keyboard navigation, focus management built in
- **Tailwind CSS styling** - All visual styling via utility classes, easily customizable
- **CSS variables for theming** - `--primary`, `--secondary`, `--accent`, `--destructive`, `--muted`, `--card`, `--popover` etc.
- **TypeScript first** - Full type safety, IntelliSense support

**Why developers prefer it:**
1. **No abstraction tax** - Code is in your project, not behind a package version
2. **Accessibility for free** - Radix handles ARIA, keyboard, focus management
3. **Customization = editing a file** - Change Tailwind classes directly in JSX
4. **Tree-shaking by design** - Only components you add exist in bundle
5. **Composable** - Small building blocks combine into complex UI
6. **Design token consistency** - CSS variables ensure coherent theming

**Default component set:**
Accordion, Alert, AlertDialog, AspectRatio, Avatar, Badge, Button, Calendar, Card, Carousel, Chart, Checkbox, Collapsible, Combobox, Command, ContextMenu, DataTable, DatePicker, Dialog, Drawer, DropdownMenu, Form, HoverCard, Input, Label, Menubar, NavigationMenu, Pagination, Popover, Progress, RadioGroup, Resizable, ScrollArea, Select, Separator, Sheet, Skeleton, Slider, Sonner (Toast), Switch, Table, Tabs, Textarea, Toast, Toggle, ToggleGroup, Tooltip

### B4. Tailwind CSS Design Philosophy

**Utility-first principle:**
Instead of writing semantic CSS classes (`.card-header { padding: 1rem; ... }`), apply utility classes directly to elements (`class="p-4 font-semibold text-lg"`). This:

- Eliminates naming decisions
- Reduces CSS file bloat
- Makes styles visible at the HTML level
- Enforces design constraints through limited options
- Enables rapid prototyping

**Design constraint system:**
Tailwind's predefined values create guardrails:
- Colors: curated palette with consistent lightness steps (50-950)
- Spacing: 4px-based scale (0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64, 72, 80, 96)
- Font sizes: curated scale (xs, sm, base, lg, xl, 2xl-9xl)
- Border radius: scale (none, sm, DEFAULT, md, lg, xl, 2xl, 3xl, full)
- Shadows: curated depth levels (sm, DEFAULT, md, lg, xl, 2xl, inner, none)

**Key patterns:**
```html
<!-- Responsive: mobile-first -->
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3">

<!-- Dark mode -->
<div class="bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100">

<!-- Interactive states -->
<button class="bg-blue-500 hover:bg-blue-600 active:bg-blue-700
               focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
               disabled:opacity-50 disabled:cursor-not-allowed">

<!-- Transitions -->
<div class="transition-all duration-200 ease-in-out">
```

### B5. Common Component Patterns

#### Buttons

```
Sizes:     xs (h-7 px-2 text-xs)
           sm (h-8 px-3 text-sm)
           md (h-9 px-4 text-sm)  -- default
           lg (h-10 px-6 text-base)
           xl (h-12 px-8 text-lg)

Variants:  default (filled, primary color)
           secondary (filled, muted color)
           outline (border, transparent bg)
           ghost (no border, no bg, text only)
           destructive (red/error color)
           link (underlined text)

States:    default -> hover -> active -> focus -> disabled
           Each state has visual feedback (color shift, shadow, ring)

Rules:     - Min touch target: 44x44px (mobile)
           - Icon + text: icon 16-20px, 8px gap
           - Icon only: equal width/height, aria-label required
           - Loading: show spinner, disable interaction
           - Never stack more than 3 buttons in a row
```

#### Cards

```
Anatomy:   [Optional Image/Media]
           [Header: Title + Subtitle/Badge]
           [Body: Content/Description]
           [Footer: Actions/Metadata]

Patterns:  - Rounded corners (8-16px / rounded-lg to rounded-2xl)
           - Subtle border OR shadow (not both heavily)
           - Consistent internal padding (p-4 to p-6)
           - Hover: slight lift (translate-y + shadow increase) OR border color change
           - Clickable cards: cursor-pointer + focus ring on the whole card

Variants:  Default (border), Elevated (shadow), Interactive (hover lift),
           Featured (accent border or bg tint), Compact (less padding)
```

#### Forms

```
Layout:    - Label above input (most accessible, most common)
           - Label left of input (dense data forms, wide screens only)
           - Floating label (inside input, moves up on focus - trendy but less accessible)
           - Placeholder-only (avoid - disappears on input, poor UX)

Input:     - Height: 36-44px (h-9 to h-11)
           - Padding: 8-12px horizontal (px-2 to px-3)
           - Border: 1px solid, muted color
           - Focus: ring + border color change
           - Error: red border + error message below
           - Disabled: reduced opacity, not-allowed cursor

Groups:    - Vertical stack: gap-4 to gap-6 between fields
           - Horizontal: gap-4, wrap on mobile
           - Sections: gap-8 with divider or heading
           - Required indicator: asterisk (*) on label, not input
```

#### Tables

```
Structure: - Sticky header
           - Alternating row colors OR horizontal dividers (not both)
           - Hover highlight on rows
           - Right-align numbers, left-align text
           - Consistent cell padding (px-4 py-3)

Advanced:  - Sortable columns: icon indicator
           - Selectable rows: checkbox column
           - Expandable rows: chevron + detail panel
           - Pagination: bottom-right, show count
           - Empty state: centered message with illustration

Mobile:    - Horizontal scroll OR card layout transformation
           - Priority columns (most important visible, rest in expansion)
```

#### Modals/Dialogs

```
Anatomy:   [Overlay: bg-black/50 or bg-black/80]
           [Container: centered, max-width, rounded, shadow]
             [Header: Title + Close button]
             [Body: Scrollable content]
             [Footer: Action buttons, right-aligned]

Rules:     - Max width: sm (384px), md (448px), lg (512px), xl (576px)
           - Focus trap: keyboard focus stays inside modal
           - Close: X button, Escape key, overlay click (configurable)
           - Animate: fade in overlay + scale/slide in container
           - Prevent body scroll when open
           - Primary action on right, cancel on left
```

---

## C. Layout & Composition

### C1. Grid Systems

#### 12-Column Grid

The 12-column grid is the industry standard because 12 divides evenly by 2, 3, 4, and 6, enabling flexible layouts.

**Breakpoints (Tailwind defaults):**

```
sm:  640px   (mobile landscape)
md:  768px   (tablet portrait)
lg:  1024px  (tablet landscape / small desktop)
xl:  1280px  (desktop)
2xl: 1536px  (large desktop)
```

**Column distribution patterns:**

```
Full width:           col-span-12
Half:                 col-span-6  col-span-6
Thirds:               col-span-4  col-span-4  col-span-4
Quarters:             col-span-3  col-span-3  col-span-3  col-span-3
Sidebar + Main:       col-span-3  col-span-9
Sidebar + Main + Aside: col-span-2  col-span-7  col-span-3
Content centered:     col-start-3 col-span-8
```

**Tailwind CSS Grid implementation:**

```html
<!-- 12-column grid -->
<div class="grid grid-cols-12 gap-6">
  <aside class="col-span-12 md:col-span-3">Sidebar</aside>
  <main class="col-span-12 md:col-span-9">Content</main>
</div>

<!-- Auto-fit responsive grid (no breakpoints needed) -->
<div class="grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-6">
  <!-- Cards auto-arrange based on available space -->
</div>
```

#### CSS Grid Patterns

```css
/* Holy Grail Layout */
.layout {
  display: grid;
  grid-template:
    "header header header" auto
    "nav    main   aside" 1fr
    "footer footer footer" auto
    / 200px 1fr 200px;
  min-height: 100vh;
}

/* Magazine/Editorial Layout */
.editorial {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 1.5rem;
}
.feature { grid-column: span 8; grid-row: span 2; }
.sidebar { grid-column: span 4; }
.article { grid-column: span 4; }

/* Bento Grid */
.bento {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  grid-auto-rows: 200px;
  gap: 1rem;
}
.bento-wide { grid-column: span 2; }
.bento-tall { grid-row: span 2; }
.bento-featured { grid-column: span 2; grid-row: span 2; }
```

### C2. Whitespace Usage

**Types of whitespace:**
- **Micro whitespace** (2-8px): Between letters, between icon and label, inline elements
- **Meso whitespace** (8-24px): Between form fields, list items, card internal padding
- **Macro whitespace** (24-96px): Between sections, page margins, header/content gap
- **Container whitespace** (>96px): Page-level margins, hero section breathing room

**Rules of thumb:**
- More whitespace = more premium/luxury feel
- Less whitespace = more information density (acceptable for dashboards, data tools)
- Consistent whitespace units matter more than the actual amount
- Double the spacing when crossing a hierarchy level (e.g. 16px within a group, 32px between groups)
- Padding inside containers should relate to the container's size (larger containers = more padding)

### C3. Responsive Strategy

**Mobile-first approach (industry standard 2025):**

1. Design for 320px width first
2. Progressively enhance with `min-width` media queries
3. Content stacks vertically on mobile, spreads horizontally on desktop
4. Touch targets minimum 44x44px on mobile
5. Reduce font sizes by ~1 scale step on mobile
6. Collapse navigation to hamburger/drawer below md
7. Images: full-width on mobile, constrained on desktop

**Breakpoint strategy:**

```
Mobile:   < 640px   - Single column, stacked content
Tablet:   640-1024px - 2 columns, collapsible sidebar
Desktop:  1024-1280px - Full layout, sidebar visible
Large:    > 1280px  - Content max-width with centered layout
```

**Container max-widths:**
```
Content:    max-w-prose (65ch, ~640px) - Readable text
Dashboard:  max-w-7xl (1280px) - Full-width data
Marketing:  max-w-6xl (1152px) - Balanced presence
App shell:  max-w-full - Edge to edge
```

**Modern techniques (reduce breakpoints):**
- `clamp()` for fluid sizing
- `grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))` for auto-responsive grids
- Container queries (`@container`) for component-level responsiveness
- Logical properties (`margin-inline`, `padding-block`) for RTL support

### C4. Content Density vs Breathing Room

**Decision framework:**

| Interface Type | Density | Spacing Scale | Typography |
|---------------|---------|---------------|------------|
| **Dashboard/Admin** | High | Compact (4-8px gaps) | Smaller (13-14px base) |
| **SaaS Application** | Medium | Standard (8-16px gaps) | Standard (15-16px base) |
| **Marketing/Landing** | Low | Generous (16-32px gaps) | Large (16-18px base) |
| **Editorial/Blog** | Low-Medium | Content-focused | Large (18-20px base) |
| **E-commerce** | Medium-High | Product-focused | Standard (14-16px base) |

### C5. Above-the-Fold Priorities

What must be visible without scrolling:

1. **Clear value proposition** - What is this? What does it do for me?
2. **Primary CTA** - The one action you want users to take
3. **Visual anchor** - Hero image, illustration, or key visual
4. **Navigation** - How to explore further
5. **Trust signal** - Social proof, brand recognition, or security indicator

**Hero section patterns:**
- Split (text left, visual right) - Most common SaaS
- Centered (text center, visual below) - Clean, focused
- Full-screen (background image/video, text overlay) - Dramatic, immersive
- Asymmetric (diagonal split, overlapping elements) - Creative, memorable

---

## D. Modern UI Trends (2024-2026)

### D1. Glassmorphism / Frosted Glass

**What it is:** Semi-transparent elements with backdrop blur, creating a frosted glass effect where background content is visible but obscured.

**When to use:**
- Navigation bars over hero images
- Overlay panels and sidebars
- Cards over gradient/image backgrounds
- Notification toasts
- Modal overlays

**When to avoid:**
- Text-heavy content (readability concerns)
- Accessibility-critical interfaces
- Performance-sensitive mobile pages (blur is GPU-intensive)
- Over flat, solid backgrounds (no visual benefit)

**Implementation:**

```html
<!-- Tailwind CSS -->
<div class="backdrop-blur-md bg-white/30 border border-white/20
            rounded-2xl shadow-lg p-6">
  <!-- Content -->
</div>

<!-- Dark mode variant -->
<div class="backdrop-blur-xl bg-gray-900/40 border border-gray-700/30
            rounded-2xl shadow-2xl p-6">
  <!-- Content -->
</div>

<!-- Full nav bar -->
<nav class="fixed top-0 inset-x-0 z-50
            backdrop-blur-lg bg-white/70 dark:bg-gray-950/70
            border-b border-gray-200/50 dark:border-gray-800/50">
  <!-- Nav content -->
</nav>
```

**Key properties:**
- `backdrop-blur-sm` (4px), `backdrop-blur` (8px), `backdrop-blur-md` (12px), `backdrop-blur-lg` (16px), `backdrop-blur-xl` (24px), `backdrop-blur-2xl` (40px), `backdrop-blur-3xl` (64px)
- Background opacity: `/10` to `/40` for light, `/30` to `/60` for dark
- Always add a subtle border (white/20 or white/10) for edge definition
- Add shadow for depth separation

**Browser note:** Firefox has full support now (previously limited). Safari and Chrome have had support since 2020+.

### D2. Bento Grid Layouts

**What it is:** Modular grid layouts inspired by Japanese bento boxes - content organized into clearly separated, asymmetrical sections of varying sizes.

**When to use:**
- Feature showcases
- Dashboard overviews
- Portfolio/work displays
- Product highlights
- About/team pages

**Implementation:**

```html
<!-- Tailwind Bento Grid -->
<div class="grid grid-cols-1 md:grid-cols-4 gap-4">
  <!-- Featured: 2x2 -->
  <div class="md:col-span-2 md:row-span-2 bg-gradient-to-br from-blue-500 to-purple-600
              rounded-2xl p-8 text-white">
    <h2 class="text-3xl font-bold">Main Feature</h2>
    <p>Description</p>
  </div>

  <!-- Standard: 1x1 -->
  <div class="bg-gray-100 dark:bg-gray-800 rounded-2xl p-6">
    <h3>Feature 2</h3>
  </div>

  <!-- Wide: 2x1 -->
  <div class="md:col-span-2 bg-gray-100 dark:bg-gray-800 rounded-2xl p-6">
    <h3>Feature 3</h3>
  </div>

  <!-- Standard: 1x1 -->
  <div class="bg-gray-100 dark:bg-gray-800 rounded-2xl p-6">
    <h3>Feature 4</h3>
  </div>
</div>
```

**Design rules:**
- Consistent gap (usually 12-16px / gap-3 to gap-4)
- Rounded corners (16-24px / rounded-2xl to rounded-3xl)
- Mix sizes: at least one large (2x2), some wide (2x1), and several standard (1x1)
- Each cell should have a single clear purpose
- Use color/gradients on featured cells, neutrals on standard
- Maintain visual weight balance (heavy cells diagonal to each other)

### D3. Dark Mode Design

**It is not just inverting colors.** Dark mode requires its own design decisions:

**Color adjustments:**
- Background: not pure black (#000) - use dark gray (oklch ~0.13-0.18) to avoid OLED halation
- Text: not pure white (#fff) - use off-white (oklch ~0.93-0.95) to reduce eye strain
- Surfaces: slightly lighter than background (1-2 steps) for depth
- Borders: lighter than surface but subtle (opacity 10-30%)
- Shadows: nearly invisible in dark mode - use border or surface color difference instead
- Accent colors: may need lightness boost to maintain contrast
- Images: consider reducing brightness/contrast slightly

**Semantic adjustments:**
```css
/* Light mode */
--surface-elevated: white;
--shadow-color: oklch(0 0 0 / 0.1);

/* Dark mode */
--surface-elevated: oklch(0.22 0.01 250);
--shadow-color: oklch(0 0 0 / 0.3);  /* Heavier shadow or skip entirely */
```

**Implementation pattern:**

```html
<html class="dark">
<body class="bg-white dark:bg-gray-950 text-gray-900 dark:text-gray-100">
  <div class="bg-gray-50 dark:bg-gray-900 border-gray-200 dark:border-gray-800">
    <h2 class="text-gray-900 dark:text-gray-50">Title</h2>
    <p class="text-gray-600 dark:text-gray-400">Description</p>
    <button class="bg-blue-600 dark:bg-blue-500 text-white">Action</button>
  </div>
</body>
```

**Tailwind dark mode:**
- `darkMode: 'class'` in config (toggle via JS)
- `darkMode: 'media'` (follows OS preference)
- All color classes support `dark:` prefix

### D4. Micro-interactions & Animations

**Categories:**

| Type | Duration | Purpose | Example |
|------|----------|---------|---------|
| **Feedback** | 100-200ms | Confirm user action | Button press, toggle switch |
| **State change** | 200-400ms | Show transition between states | Tab switch, accordion |
| **Entrance** | 300-500ms | Introduce new content | Modal appear, card load |
| **Exit** | 200-300ms | Remove content (faster than entrance) | Modal dismiss, notification |
| **Loading** | Continuous | Indicate processing | Skeleton, spinner, progress |
| **Delight** | 300-800ms | Surprise and please | Success animation, confetti |

**High-impact moments (focus here):**
1. **Page load** - Staggered reveal of hero elements (animation-delay creates orchestrated entrance)
2. **Scroll-triggered reveals** - Fade-up as sections enter viewport
3. **Hover states** - Subtle lift, glow, or color shift on interactive elements
4. **Form feedback** - Shake on error, checkmark on success
5. **Navigation transitions** - Smooth page/route changes

**Easing functions:**

```css
/* Standard easings */
--ease-in:     cubic-bezier(0.4, 0, 1, 0.7);        /* Accelerate */
--ease-out:    cubic-bezier(0, 0.3, 0.6, 1);         /* Decelerate */
--ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);         /* Both */

/* Expressive easings */
--ease-spring:    cubic-bezier(0.34, 1.56, 0.64, 1);   /* Overshoot */
--ease-bounce:    cubic-bezier(0.68, -0.55, 0.27, 1.55); /* Bounce */
--ease-snappy:    cubic-bezier(0.2, 0, 0, 1);            /* Quick and sharp */

/* Modern: linear() for complex curves */
--ease-spring-linear: linear(
  0, 0.006, 0.025, 0.056, 0.1, 0.157, 0.227, 0.31,
  0.406, 0.516, 0.638, 0.772, 0.917, 1.074, 1.139,
  1.185, 1.209, 1.215, 1.204, 1.181, 1.149, 1.113,
  1.076, 1.042, 1.013, 0.99, 0.974, 0.964, 0.96,
  0.961, 0.966, 0.974, 0.983, 0.992, 0.999, 1.003,
  1.005, 1.005, 1.004, 1.002, 1
);
```

**Best practice rules:**
- Functional animations (feedback, state): 150-250ms with ease-out
- Decorative animations (entrance, delight): 300-600ms with ease-in-out or spring
- Exits should be faster than entrances (200ms vs 300ms)
- `transform` and `opacity` only for 60fps (avoid animating layout properties)
- `will-change: transform` for elements that will animate
- Respect `prefers-reduced-motion`:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

**Tailwind animation utilities:**

```html
<!-- Fade in on scroll (with Intersection Observer JS) -->
<div class="opacity-0 translate-y-4 transition-all duration-500 ease-out
            data-[visible=true]:opacity-100 data-[visible=true]:translate-y-0">

<!-- Staggered entrance -->
<div class="animate-fade-in [animation-delay:0ms]">Item 1</div>
<div class="animate-fade-in [animation-delay:100ms]">Item 2</div>
<div class="animate-fade-in [animation-delay:200ms]">Item 3</div>

<!-- Hover lift -->
<div class="transition-all duration-200 hover:-translate-y-1 hover:shadow-lg">

<!-- Pulse for attention -->
<span class="animate-pulse">Live</span>

<!-- Skeleton loading -->
<div class="animate-pulse bg-gray-200 dark:bg-gray-700 rounded h-4 w-3/4"></div>
```

### D5. Gradient Usage

**Types and use cases:**

```css
/* Linear gradient - directional flow */
background: linear-gradient(135deg, oklch(0.7 0.2 280), oklch(0.5 0.25 320));

/* Radial gradient - focal emphasis */
background: radial-gradient(circle at 30% 50%, oklch(0.6 0.2 250), oklch(0.2 0.05 250));

/* Conic gradient - circular/clock-like */
background: conic-gradient(from 45deg, oklch(0.7 0.2 0), oklch(0.7 0.2 120), oklch(0.7 0.2 240), oklch(0.7 0.2 360));

/* Mesh gradient (multiple radial gradients layered) */
background:
  radial-gradient(at 40% 20%, oklch(0.8 0.15 280) 0px, transparent 50%),
  radial-gradient(at 80% 0%, oklch(0.75 0.12 200) 0px, transparent 50%),
  radial-gradient(at 0% 50%, oklch(0.85 0.1 320) 0px, transparent 50%),
  oklch(0.15 0.02 260);
```

**Tailwind gradient classes:**

```html
<!-- Simple gradient -->
<div class="bg-gradient-to-br from-blue-500 via-purple-500 to-pink-500">

<!-- Text gradient -->
<h1 class="bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">

<!-- Gradient border -->
<div class="p-[1px] bg-gradient-to-r from-blue-500 to-purple-500 rounded-xl">
  <div class="bg-white dark:bg-gray-950 rounded-xl p-6">Content</div>
</div>
```

**Rules:**
- 2-3 colors maximum per gradient (more = muddy)
- Analogous hues (adjacent on wheel) create smooth transitions
- Complementary hues create vibrant, energetic gradients
- Use gradients on large surfaces (heroes, cards, backgrounds) not on small elements
- Ensure text over gradients meets contrast requirements at ALL points

### D6. Neumorphism (When Appropriate)

**What it is:** Soft, extruded UI elements that appear to push out of or sink into a monochromatic surface, using paired light and dark shadows.

**CSS implementation:**

```css
/* Extruded (raised) */
.neu-raised {
  background: #e0e0e0;
  border-radius: 16px;
  box-shadow:
    8px 8px 16px #bebebe,
    -8px -8px 16px #ffffff;
}

/* Inset (pressed) */
.neu-inset {
  background: #e0e0e0;
  border-radius: 16px;
  box-shadow:
    inset 8px 8px 16px #bebebe,
    inset -8px -8px 16px #ffffff;
}

/* Dark mode neumorphism */
.dark .neu-raised {
  background: #2d2d2d;
  box-shadow:
    8px 8px 16px #1a1a1a,
    -8px -8px 16px #404040;
}
```

**When to use:**
- Toggle switches and sliders (tactile feel)
- Music/media player controls
- Smart home interfaces
- Calculator buttons
- Dashboard widget containers (sparingly)

**When to avoid:**
- Text-heavy interfaces (low contrast issues)
- Complex forms (too many elements, visual confusion)
- Data-dense dashboards (everything blends together)
- Accessibility-critical applications
- Production business tools (looks playful, not professional)

**Important:** Neumorphism has known accessibility problems - low contrast between elements makes it hard for visually impaired users. If used, add subtle borders or increase shadow contrast. Never make an entire interface neumorphic - use it as an accent on specific components.

### D7. AI-Native Interfaces

**Emerging patterns (2025-2026):**

1. **Conversational panel** - Chat-based interface as primary interaction (ChatGPT, Claude)
2. **Side panel assistant** - AI in persistent sidebar alongside traditional UI (Copilot, Canvas)
3. **Generative UI** - AI generates interface components dynamically based on context
4. **Inline AI actions** - AI suggestions embedded within existing workflows (Notion AI, Gmail suggestions)
5. **Progressive disclosure** - AI shows more/less based on user expertise level

**Design principles for AI interfaces:**
- Show confidence levels when AI is uncertain
- Always provide "undo" or "reject" for AI actions
- Stream responses progressively (don't wait for completion)
- Use skeleton/shimmer states during AI processing
- Make AI-generated content visually distinguishable from user content
- Provide editing capabilities for AI output
- Show reasoning/sources when possible

**UI patterns:**
```
Chat:        Alternating message bubbles, streaming text, suggested prompts
Side panel:  Resizable drawer, context-aware suggestions, action buttons
Inline:      Highlighted suggestions, accept/reject/modify controls
Generative:  Component streaming, real-time preview, iteration controls
```

---

## E. Practical Implementation

### E1. CSS/Tailwind Patterns Reference

#### Container Patterns

```html
<!-- Centered content container -->
<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">

<!-- Full-bleed section with contained content -->
<section class="bg-gray-50 dark:bg-gray-900 py-16 sm:py-24">
  <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
    <!-- Content -->
  </div>
</section>

<!-- Prose container for long-form text -->
<article class="mx-auto max-w-prose px-4">
  <div class="prose dark:prose-invert lg:prose-lg">
    <!-- Markdown/HTML content -->
  </div>
</article>
```

#### Card Patterns

```html
<!-- Elevated card with hover -->
<div class="group rounded-2xl border border-gray-200 dark:border-gray-800
            bg-white dark:bg-gray-900 p-6 shadow-sm
            transition-all duration-200 hover:shadow-md hover:-translate-y-0.5">
  <h3 class="text-lg font-semibold text-gray-900 dark:text-gray-50
             group-hover:text-blue-600 dark:group-hover:text-blue-400
             transition-colors">
    Card Title
  </h3>
  <p class="mt-2 text-gray-600 dark:text-gray-400">
    Card description
  </p>
</div>

<!-- Gradient border card -->
<div class="rounded-2xl p-[1px] bg-gradient-to-br from-blue-500 to-purple-500">
  <div class="rounded-2xl bg-white dark:bg-gray-950 p-6">
    <h3>Premium Card</h3>
  </div>
</div>

<!-- Glass card -->
<div class="rounded-2xl backdrop-blur-xl bg-white/20 dark:bg-gray-900/30
            border border-white/30 dark:border-gray-700/30
            shadow-xl p-6">
  <h3 class="text-white font-semibold">Glass Card</h3>
</div>
```

#### Button Patterns

```html
<!-- Primary button -->
<button class="inline-flex items-center justify-center gap-2
               rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white
               shadow-sm transition-all duration-150
               hover:bg-blue-700 active:bg-blue-800
               focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600
               disabled:opacity-50 disabled:cursor-not-allowed">
  <svg class="h-4 w-4" ...><!-- icon --></svg>
  Button Text
</button>

<!-- Ghost button -->
<button class="inline-flex items-center justify-center gap-2
               rounded-lg px-4 py-2.5 text-sm font-medium text-gray-700 dark:text-gray-300
               transition-all duration-150
               hover:bg-gray-100 dark:hover:bg-gray-800
               active:bg-gray-200 dark:active:bg-gray-700
               focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-400">
  Ghost Button
</button>

<!-- Gradient button -->
<button class="inline-flex items-center justify-center gap-2
               rounded-lg bg-gradient-to-r from-blue-600 to-purple-600
               px-4 py-2.5 text-sm font-semibold text-white
               shadow-md shadow-blue-500/25
               transition-all duration-200
               hover:shadow-lg hover:shadow-blue-500/40 hover:-translate-y-0.5
               active:translate-y-0">
  Gradient Button
</button>
```

#### Input Patterns

```html
<!-- Standard input with label -->
<div class="space-y-1.5">
  <label for="email" class="block text-sm font-medium text-gray-700 dark:text-gray-300">
    Email address
  </label>
  <input id="email" type="email" placeholder="you@example.com"
         class="block w-full rounded-lg border border-gray-300 dark:border-gray-700
                bg-white dark:bg-gray-900 px-3 py-2 text-sm
                text-gray-900 dark:text-gray-100
                placeholder:text-gray-400 dark:placeholder:text-gray-500
                transition-colors duration-150
                focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 focus:outline-none
                disabled:bg-gray-50 dark:disabled:bg-gray-800 disabled:cursor-not-allowed" />
</div>

<!-- Input with error -->
<div class="space-y-1.5">
  <label class="block text-sm font-medium text-gray-700">Email</label>
  <input class="block w-full rounded-lg border-2 border-red-500
                bg-red-50 px-3 py-2 text-sm text-gray-900
                focus:border-red-500 focus:ring-2 focus:ring-red-500/20" />
  <p class="text-sm text-red-600 flex items-center gap-1">
    <svg class="h-4 w-4"><!-- error icon --></svg>
    Please enter a valid email address
  </p>
</div>
```

### E2. Color Palette Generation (Algorithmic)

**Step-by-step process:**

```javascript
// 1. Start with brand hue
const brandHue = 250; // Blue

// 2. Generate tonal palette
function generatePalette(hue) {
  return {
    50:  `oklch(0.97 0.01 ${hue})`,
    100: `oklch(0.93 0.025 ${hue})`,
    200: `oklch(0.87 0.05 ${hue})`,
    300: `oklch(0.78 0.09 ${hue})`,
    400: `oklch(0.68 0.12 ${hue})`,
    500: `oklch(0.55 0.15 ${hue})`,
    600: `oklch(0.45 0.15 ${hue})`,
    700: `oklch(0.37 0.12 ${hue})`,
    800: `oklch(0.28 0.09 ${hue})`,
    900: `oklch(0.20 0.07 ${hue})`,
    950: `oklch(0.13 0.05 ${hue})`,
  };
}

// 3. Generate complementary accent
const accentHue = (brandHue + 150) % 360; // ~40 (orange-ish)
const accent = generatePalette(accentHue);

// 4. Semantic colors (fixed hues, adjust L for light/dark)
const semantic = {
  success: generatePalette(145), // Green
  warning: generatePalette(85),  // Yellow
  error:   generatePalette(25),  // Red
  info:    generatePalette(250), // Blue (can match brand)
};

// 5. Neutral scale (very low chroma, tinted with brand hue)
function generateNeutrals(hue) {
  return {
    50:  `oklch(0.985 0.003 ${hue})`,
    100: `oklch(0.965 0.005 ${hue})`,
    200: `oklch(0.925 0.006 ${hue})`,
    300: `oklch(0.87 0.008 ${hue})`,
    400: `oklch(0.71 0.01 ${hue})`,
    500: `oklch(0.55 0.01 ${hue})`,
    600: `oklch(0.44 0.01 ${hue})`,
    700: `oklch(0.37 0.008 ${hue})`,
    800: `oklch(0.27 0.006 ${hue})`,
    900: `oklch(0.20 0.005 ${hue})`,
    950: `oklch(0.13 0.003 ${hue})`,
  };
}
```

### E3. Responsive Typography with clamp()

**Formula:**
```
font-size: clamp(min, preferred, max);
preferred = min + (max - min) * ((100vw - minViewport) / (maxViewport - minViewport))
```

**Practical implementation:**

```css
:root {
  /* Type scale with fluid sizing */
  --text-xs:    clamp(0.694rem, 0.657rem + 0.19vw, 0.8rem);
  --text-sm:    clamp(0.833rem, 0.776rem + 0.29vw, 1rem);
  --text-base:  clamp(1rem, 0.913rem + 0.43vw, 1.25rem);
  --text-lg:    clamp(1.2rem, 1.07rem + 0.65vw, 1.563rem);
  --text-xl:    clamp(1.44rem, 1.246rem + 0.97vw, 1.953rem);
  --text-2xl:   clamp(1.728rem, 1.444rem + 1.42vw, 2.441rem);
  --text-3xl:   clamp(2.074rem, 1.666rem + 2.04vw, 3.052rem);
  --text-4xl:   clamp(2.488rem, 1.91rem + 2.89vw, 3.815rem);

  /* Spacing scale (fluid) */
  --space-xs:   clamp(0.25rem, 0.2rem + 0.25vw, 0.5rem);
  --space-sm:   clamp(0.5rem, 0.4rem + 0.5vw, 1rem);
  --space-md:   clamp(1rem, 0.8rem + 1vw, 2rem);
  --space-lg:   clamp(1.5rem, 1.1rem + 2vw, 3.5rem);
  --space-xl:   clamp(2rem, 1.4rem + 3vw, 5rem);
  --space-2xl:  clamp(3rem, 2rem + 5vw, 8rem);
}

body { font-size: var(--text-base); }
h1   { font-size: var(--text-4xl); }
h2   { font-size: var(--text-3xl); }
h3   { font-size: var(--text-2xl); }
h4   { font-size: var(--text-xl); }
h5   { font-size: var(--text-lg); }
.small { font-size: var(--text-sm); }
```

**Accessibility note:** Always combine `vw` with `rem` in the preferred value so fonts scale with zoom (pure `vw` does not respond to zoom, violating WCAG).

### E4. Animation Timing & Easing Best Practices

**Duration guidelines:**

```
Micro (instant feedback):        100-150ms
Small (state change):            150-250ms
Medium (content transition):     250-400ms
Large (page/modal transition):   400-600ms
Elaborate (orchestrated reveal): 600-1000ms (with staggered delays)
```

**Easing selection guide:**

| Animation Type | Easing | Why |
|---------------|--------|-----|
| Elements entering | ease-out | Decelerates into final position (natural arrival) |
| Elements leaving | ease-in | Accelerates out (natural departure) |
| State changes (color, size) | ease-in-out | Smooth both directions |
| Playful/bouncy effects | spring / cubic-bezier with overshoot | Creates delight |
| Loading indicators | linear | Consistent, predictable |
| Scroll-triggered | ease-out | Smooth reveal as content settles |

**Performance rules:**
- Only animate `transform` and `opacity` for 60fps
- Avoid animating: `width`, `height`, `top`, `left`, `margin`, `padding`, `border`, `font-size`
- Use `will-change: transform` sparingly (only on elements about to animate)
- Batch DOM reads and writes to avoid layout thrashing
- Use `requestAnimationFrame` for JS animations
- CSS animations > JS animations for simple transitions

**Spring animation implementation (CSS linear()):**

```css
/* Bouncy spring */
.spring-bounce {
  transition: transform 600ms linear(
    0, 0.009, 0.035 2.1%, 0.141, 0.281 6.7%, 0.723 12.9%,
    0.938 16.7%, 1.017, 1.077, 1.121, 1.149 24.3%,
    1.159, 1.163, 1.161, 1.154 29.9%, 1.129 32.8%,
    1.051 39.6%, 1.017 43.1%, 0.991, 0.977 51%,
    0.975 57.1%, 0.997 69.8%, 1.003 76.9%, 1
  );
}

/* Gentle spring */
.spring-gentle {
  transition: transform 500ms linear(
    0, 0.019, 0.074 2.8%, 0.286 8.3%, 0.586 14.7%,
    0.838 20.6%, 1.013 26.2%, 1.105 31.4%,
    1.139 36.1%, 1.137 40.9%, 1.083 52%,
    1.037 62.3%, 1.013 73.1%, 1.002 84.2%, 1
  );
}
```

---

## F. Encoding This Into a Claude Skill

### F1. What Reference Materials to Include

**Essential (must be in the skill file):**

1. **Anti-patterns list** - Specific things to NEVER do (the "AI slop" avoidance list)
2. **Font recommendations** - Categorized by context with specific family names
3. **Color approach** - The 60-30-10 rule + OKLCH generation approach
4. **Spacing scale** - The 4px grid with Tailwind mappings
5. **Component patterns** - At minimum: button variants, card patterns, input states
6. **Animation guidelines** - Duration ranges, easing selection, performance rules

**Important (include as condensed reference):**

7. **Design system principles** - MD3, Apple HIG, shadcn/ui philosophy (condensed)
8. **Layout patterns** - Grid templates, responsive breakpoints, container widths
9. **Accessibility** - WCAG contrast minimums, focus management, motion preferences
10. **Trend vocabulary** - Glassmorphism, bento grid, dark mode implementation patterns

**Reference only (link or mention but don't embed):**

11. **Full type scale calculations** - Point to tools (utopia.fyi, fluid-type-scale.com)
12. **Complete component libraries** - Point to shadcn/ui docs
13. **Icon libraries** - List names, not embed catalogues
14. **Inspiration sources** - List URLs

### F2. Decision Trees for Design Choices

#### Choosing a Visual Direction

```
START: What is the interface for?
├── Data-heavy tool (dashboard, admin, analytics)
│   ├── Tone: Professional, dense
│   ├── Color: Neutral-dominant, semantic accents
│   ├── Typography: Clean sans-serif, smaller base (14px)
│   ├── Spacing: Compact
│   └── Animation: Minimal, functional only
│
├── Marketing/Landing page
│   ├── Tone: Bold, memorable, brand-forward
│   ├── Color: Brand-dominant, dramatic accents, gradients OK
│   ├── Typography: Display font + body font, large sizes
│   ├── Spacing: Generous, breathing room
│   └── Animation: Orchestrated entrance, scroll reveals, hover delight
│
├── SaaS application
│   ├── Tone: Clean, efficient, trustworthy
│   ├── Color: Neutral base, single accent for actions
│   ├── Typography: Readable sans-serif, 15-16px base
│   ├── Spacing: Standard (Tailwind defaults)
│   └── Animation: State transitions, loading states
│
├── Editorial/Content site
│   ├── Tone: Refined, readable, content-first
│   ├── Color: High contrast, minimal palette
│   ├── Typography: Serif for body, sans for UI, 18px+ base
│   ├── Spacing: Content-focused, generous line height
│   └── Animation: Subtle, content-respecting
│
├── Creative/Portfolio
│   ├── Tone: Distinctive, artistic, unexpected
│   ├── Color: Any approach, bold choices
│   ├── Typography: Highly distinctive, experimental
│   ├── Spacing: Intentional (can be extreme in either direction)
│   └── Animation: Can be elaborate, showcases capability
│
└── E-commerce
    ├── Tone: Trust-building, product-focused
    ├── Color: Clean base, urgency accents (red/orange for sales)
    ├── Typography: Clear, scannable
    ├── Spacing: Product grid focused, information dense
    └── Animation: Product image interactions, cart feedback
```

#### Choosing Dark vs Light

```
Default to LIGHT when:
- Content-heavy reading experience
- Print-oriented (documents, reports)
- Majority audience is general public
- Brand is warm/friendly/approachable

Default to DARK when:
- Creative/portfolio/showcase
- Developer/technical tools
- Entertainment/media focused
- Brand is premium/luxury/modern
- Dashboard with data visualization (colors pop more)

ALWAYS support both when:
- SaaS application (user preference)
- System tool (respect OS setting)
```

#### Choosing Animation Complexity

```
MINIMAL animations when:
- Data-dense interface
- Enterprise/B2B tool
- Performance-critical mobile web
- User base includes accessibility needs
- Content changes frequently

MODERATE animations when:
- SaaS product (standard case)
- E-commerce
- Content sites
→ Focus: page transitions, loading states, hover feedback

ELABORATE animations when:
- Marketing/landing pages
- Portfolio/creative showcase
- Onboarding flows
- Demo/presentation modes
→ Focus: scroll-triggered reveals, orchestrated entrances, micro-interactions
```

### F3. Code Snippet Libraries to Embed

The skill should embed these ready-to-use patterns:

**1. Page layout skeleton:**
```html
<div class="min-h-screen bg-white dark:bg-gray-950 text-gray-900 dark:text-gray-100">
  <nav class="sticky top-0 z-50 border-b border-gray-200 dark:border-gray-800
              bg-white/80 dark:bg-gray-950/80 backdrop-blur-lg">
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <!-- Logo, nav items, actions -->
    </div>
  </nav>
  <main class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
    <!-- Page content -->
  </main>
</div>
```

**2. Hero section:**
```html
<section class="relative overflow-hidden py-24 sm:py-32">
  <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
    <div class="mx-auto max-w-2xl text-center">
      <h1 class="text-4xl font-bold tracking-tight sm:text-6xl">
        Headline Goes Here
      </h1>
      <p class="mt-6 text-lg leading-8 text-gray-600 dark:text-gray-400">
        Supporting description text
      </p>
      <div class="mt-10 flex items-center justify-center gap-4">
        <a href="#" class="rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold
                          text-white shadow-sm hover:bg-blue-700">Get started</a>
        <a href="#" class="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Learn more <span aria-hidden="true">&rarr;</span>
        </a>
      </div>
    </div>
  </div>
</section>
```

**3. Feature grid (bento):**
```html
<div class="grid grid-cols-1 md:grid-cols-4 gap-4">
  <div class="md:col-span-2 md:row-span-2 rounded-2xl bg-gradient-to-br
              from-blue-500 to-indigo-600 p-8 text-white">
    <h3 class="text-2xl font-bold">Primary Feature</h3>
    <p class="mt-2 text-blue-100">Description</p>
  </div>
  <div class="rounded-2xl bg-gray-50 dark:bg-gray-900 border border-gray-200
              dark:border-gray-800 p-6">
    <h3 class="font-semibold">Feature 2</h3>
  </div>
  <div class="rounded-2xl bg-gray-50 dark:bg-gray-900 border border-gray-200
              dark:border-gray-800 p-6">
    <h3 class="font-semibold">Feature 3</h3>
  </div>
  <div class="md:col-span-2 rounded-2xl bg-gray-50 dark:bg-gray-900 border
              border-gray-200 dark:border-gray-800 p-6">
    <h3 class="font-semibold">Feature 4</h3>
  </div>
</div>
```

### F4. How v0 and Similar Tools Structure Their Prompts

Based on the leaked v0 system prompt and analysis of successful UI generation tools:

**v0 approach:**
1. **Identity declaration** - "You are v0, Vercel's AI-powered assistant specialized in generating user interfaces"
2. **Technology stack lock** - React, Next.js 14+, TypeScript, Tailwind CSS, shadcn/ui, Radix UI, Lucide icons
3. **Hard rules** - Always use shadcn/ui unless specified otherwise, always use Tailwind variable-based colors (`bg-primary`, not `bg-blue-500`), always responsive, never output raw SVG, never use indigo/blue by default
4. **Quality enforcement** - Complete, copyable code. Production-grade. Include default props.
5. **Accessibility baseline** - WCAG 2.1, semantic HTML, ARIA, keyboard nav, focus management
6. **Media handling** - Placeholder images via URL pattern, specific approved image sources
7. **Thinking requirement** - Use `<Thinking />` tags before generating

**Anthropic's recommended approach (from their cookbook):**
1. **Problem framing** - Explicitly state that Claude tends toward generic "AI slop" aesthetics
2. **Design dimensions** - Address typography, color, motion, backgrounds separately
3. **Anti-pattern list** - Name specific things to avoid (Inter, purple gradients, predictable layouts)
4. **Encouragement** - "Think outside the box", "vary between light/dark", "make unexpected choices"
5. **Context-specificity** - "Interpret creatively for the context"

**Optimal skill structure:**
```
1. Role definition
2. Design thinking process (understand context before coding)
3. Technology preferences / constraints
4. Anti-patterns (what to NEVER do)
5. Design principles (what to ALWAYS do)
6. Component patterns (ready-to-use snippets)
7. Decision trees (how to choose between approaches)
8. Quality checklist (verify before outputting)
```

### F5. Quality Checklist (for skill verification step)

Before outputting any UI code, verify:

```
Typography:
[ ] Font choice is distinctive (not Inter/Roboto/Arial/system)
[ ] Font pairing has contrast (different categories or extreme weight difference)
[ ] Heading hierarchy is clear (size + weight progression)
[ ] Body text is readable (16px+, 1.5+ line height, <75ch width)

Color:
[ ] Cohesive palette (not random colors)
[ ] 60-30-10 distribution (dominant/secondary/accent)
[ ] All text meets WCAG AA contrast (4.5:1 for normal, 3:1 for large)
[ ] Dark mode works (if applicable) - not just inverted, properly designed
[ ] CSS variables used for all colors

Layout:
[ ] Responsive (works at 320px, 768px, 1280px+)
[ ] Consistent spacing (using scale, not arbitrary values)
[ ] Content hierarchy is clear
[ ] Interactive elements have adequate touch targets (44px+ on mobile)

Components:
[ ] Buttons have hover, active, focus, disabled states
[ ] Inputs have labels, placeholders, error states
[ ] Cards have consistent padding and spacing
[ ] Links are distinguishable from text

Animation:
[ ] Functional animations are subtle (150-250ms)
[ ] Performance-safe (transform/opacity only)
[ ] prefers-reduced-motion respected
[ ] Page entrance uses staggered delays (not all at once)

Accessibility:
[ ] Semantic HTML (header, nav, main, footer, section, article)
[ ] Focus management (visible focus ring, logical tab order)
[ ] ARIA labels on icon-only buttons
[ ] No color-only information conveyance
[ ] Alt text on images

Code Quality:
[ ] Complete and self-contained (copy-pasteable)
[ ] No placeholder/TODO content
[ ] Responsive classes applied
[ ] Dark mode classes applied (if applicable)
```

---

## Sources

### LLM UI Generation
- [Prompting for Frontend Aesthetics - Anthropic Cookbook](https://platform.claude.com/cookbook/coding-prompting-for-frontend-aesthetics)
- [Improving Frontend Design Through Skills - Claude Blog](https://claude.com/blog/improving-frontend-design-through-skills)
- [Claude Code UI Agents Repository](https://github.com/mustafakendiguzel/claude-code-ui-agents)
- [Building Beautiful Websites with Claude Code](https://raduan.xyz/blog/claude-code-for-landing)
- [LLM UI Design Rankings 2025](https://smartscope.blog/en/ai-development/llm-ui-design-ranking-2025/)

### v0 / Vercel
- [v0 System Prompt (March 2025)](https://agentic-design.ai/prompt-hub/vercel/v0-20250306)
- [V0 System Prompt Repository](https://github.com/2-fly-4-ai/V0-system-prompt)
- [How to Prompt v0 - Vercel Blog](https://vercel.com/blog/how-to-prompt-v0)
- [Working with Figma and Custom Design Systems in v0](https://vercel.com/blog/working-with-figma-and-custom-design-systems-in-v0)

### Design Systems
- [Material Design 3 Foundations](https://m3.material.io/foundations)
- [Material 3 Expressive](https://supercharge.design/blog/material-3-expressive)
- [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines)
- [Shadcn/ui](https://ui.shadcn.com/)
- [Why Designers Should Care About Tailwind and Shadcn](https://annaarteeva.medium.com/why-designers-should-care-about-tailwind-and-shadcn-especially-in-the-ai-era-55b744c42603)

### Color & Typography
- [OKLCH in CSS - Evil Martians](https://evilmartians.com/chronicles/oklch-in-css-why-quit-rgb-hsl)
- [OKLCH Accessible Color Palettes - LogRocket](https://blog.logrocket.com/oklch-css-consistent-accessible-color-palettes)
- [60-30-10 Rule in UI Design](https://hype4.academy/articles/design/60-30-10-rule-in-ui)
- [Font Pairings - Figma Resource](https://www.figma.com/resource-library/font-pairings/)
- [Pairing Typefaces - Nielsen Norman Group](https://www.nngroup.com/articles/pairing-typefaces/)

### Responsive & Layout
- [Fluid Type Scale with CSS Clamp](https://www.aleksandrhovhannisyan.com/blog/fluid-type-scale-with-css-clamp/)
- [Modern Fluid Typography - Smashing Magazine](https://www.smashingmagazine.com/2022/01/modern-fluid-typography-css-clamp/)
- [Responsive Design Breakpoints 2025 - BrowserStack](https://www.browserstack.com/guide/responsive-design-breakpoints)
- [CSS Grid Common Layouts - MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Grid_layout/Common_grid_layouts)

### Animation
- [Spring Animations in CSS - Josh Comeau](https://www.joshwcomeau.com/animation/linear-timing-function/)
- [Easing Functions Cheat Sheet](https://easings.net/)
- [CSS Linear Easing Function - Chrome Developers](https://developer.chrome.com/docs/css-ui/css-linear-easing-function)
- [Web Animation Best Practices - GitHub](https://gist.github.com/uxderrick/07b81ca63932865ef1a7dc94fbe07838)
- [Tips for Better CSS Transitions](https://joshcollinsworth.com/blog/great-transitions)

### Modern Trends
- [UI Design Trends 2025](https://ergomania.eu/top-ui-design-trends-2025/)
- [UI/UX Design Trends 2026](https://www.index.dev/blog/ui-ux-design-trends)
- [Neumorphism 2.0 in 2025](https://ecommercewebdesign.agency/the-rise-of-neumorphism-2-0-soft-shadows-and-skeuomorphism-in-2025-designs/)
- [Glassmorphism with Tailwind CSS](https://www.epicweb.dev/tips/creating-glassmorphism-effects-with-tailwind-css)
- [Bento Grid Layouts 2025](https://www.orbix.studio/blogs/bento-grid-dashboard-design-aesthetics)

### Design Tokens
- [Design Tokens Explained - Contentful](https://www.contentful.com/blog/design-token-system/)
- [Design Tokens Format Module 2025.10](https://www.designtokens.org/tr/drafts/format/)
- [Tokens in Design Systems - EightShapes](https://medium.com/eightshapes-llc/tokens-in-design-systems-25dd82d58421)

### AI-Native Interfaces
- [Generative User Interfaces - AI SDK](https://ai-sdk.dev/docs/ai-sdk-ui/generative-user-interfaces)
- [A2UI - Google Developers Blog](https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/)
- [Where Should AI Sit in Your UI - UX Collective](https://uxdesign.cc/where-should-ai-sit-in-your-ui-1710a258390e)
