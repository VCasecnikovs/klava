---
user_invocable: true
name: frontend-design
description: Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications (examples include websites, landing pages, dashboards, React components, HTML/CSS layouts, or when styling/beautifying any web UI). Generates creative, polished code and UI design that avoids generic AI aesthetics.
license: Complete terms in LICENSE.txt
---

This skill guides creation of distinctive, production-grade frontend interfaces that avoid generic "AI slop" aesthetics. Implement real working code with exceptional attention to aesthetic details and creative choices.

The user provides frontend requirements: a component, page, application, or interface to build. They may include context about the purpose, audience, or technical constraints.

## Design Thinking

Before coding, understand the context and commit to a BOLD aesthetic direction:
- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick an extreme: brutally minimal, maximalist chaos, retro-futuristic, organic/natural, luxury/refined, playful/toy-like, editorial/magazine, brutalist/raw, art deco/geometric, soft/pastel, industrial/utilitarian, etc. There are so many flavors to choose from. Use these for inspiration but design one that is true to the aesthetic direction.
- **Constraints**: Technical requirements (framework, performance, accessibility).
- **Differentiation**: What makes this UNFORGETTABLE? What's the one thing someone will remember?

**CRITICAL**: Choose a clear conceptual direction and execute it with precision. Bold maximalism and refined minimalism both work - the key is intentionality, not intensity.

Then implement working code (HTML/CSS/JS, React, Vue, etc.) that is:
- Production-grade and functional
- Visually striking and memorable
- Cohesive with a clear aesthetic point-of-view
- Meticulously refined in every detail

## Frontend Aesthetics Guidelines

Focus on:
- **Typography**: Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics; unexpected, characterful font choices. Pair a distinctive display font with a refined body font.
- **Color & Theme**: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes.
- **Motion**: Use animations for effects and micro-interactions. Prioritize CSS-only solutions for HTML. Use Motion library for React when available. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (animation-delay) creates more delight than scattered micro-interactions. Use scroll-triggering and hover states that surprise.
- **Spatial Composition**: Unexpected layouts. Asymmetry. Overlap. Diagonal flow. Grid-breaking elements. Generous negative space OR controlled density.
- **Backgrounds & Visual Details**: Create atmosphere and depth rather than defaulting to solid colors. Add contextual effects and textures that match the overall aesthetic. Apply creative forms like gradient meshes, noise textures, geometric patterns, layered transparencies, dramatic shadows, decorative borders, custom cursors, and grain overlays.

NEVER use generic AI-generated aesthetics like overused font families (Inter, Roboto, Arial, system fonts), cliched color schemes (particularly purple gradients on white backgrounds), predictable layouts and component patterns, and cookie-cutter design that lacks context-specific character.

Interpret creatively and make unexpected choices that feel genuinely designed for the context. No design should be the same. Vary between light and dark themes, different fonts, different aesthetics. NEVER converge on common choices (Space Grotesk, for example) across generations.

**IMPORTANT**: Match implementation complexity to the aesthetic vision. Maximalist designs need elaborate code with extensive animations and effects. Minimalist or refined designs need restraint, precision, and careful attention to spacing, typography, and subtle details. Elegance comes from executing the vision well.

Remember: Claude is capable of extraordinary creative work. Don't hold back, show what can truly be created when thinking outside the box and committing fully to a distinctive vision.

**Extended reference:** `UI_DESIGN_RESEARCH.md` in this skill folder (1636 lines of detailed design systems, patterns, and code snippets).

## Design System Foundations

### Color System

**60-30-10 Rule** (always):
- 60% primary/background (neutral - white, off-white, dark gray)
- 30% secondary (cards, panels, navigation)
- 10% accent (CTAs, active states, links)

**Palette generation with OKLCH** (prefer over RGB/HSL):
```css
/* Brand hue H (0-360), generate scale by varying L */
--color-50:  oklch(0.97 0.01 H);   /* lightest bg */
--color-100: oklch(0.93 0.02 H);
--color-200: oklch(0.87 0.04 H);
--color-300: oklch(0.78 0.08 H);
--color-400: oklch(0.68 0.12 H);
--color-500: oklch(0.58 0.15 H);   /* primary */
--color-600: oklch(0.48 0.14 H);
--color-700: oklch(0.39 0.12 H);
--color-800: oklch(0.30 0.10 H);
--color-900: oklch(0.22 0.07 H);   /* darkest */
```

**Contrast requirements:** 4.5:1 for text (AA), 3:1 for large text/UI elements. Never rely on color alone.

### Typography System

**Modular scale** (pick one ratio, use consistently):
| Ratio | Name | Vibe |
|-------|------|------|
| 1.125 | Major Second | Tight, dense UIs |
| 1.200 | Minor Third | General purpose |
| 1.250 | Major Third | Bold, spacious |
| 1.333 | Perfect Fourth | Strong hierarchy |
| 1.414 | Augmented Fourth | Editorial, dramatic |
| 1.618 | Golden Ratio | Maximum drama |

**Font pairing rule:** Pair from DIFFERENT categories (serif + sans, geometric + humanist). Same category = bland.

**Fluid typography with clamp():**
```css
--text-sm: clamp(0.8rem, 0.17vw + 0.76rem, 0.89rem);
--text-base: clamp(1rem, 0.34vw + 0.91rem, 1.19rem);
--text-lg: clamp(1.25rem, 0.61vw + 1.1rem, 1.58rem);
--text-xl: clamp(1.56rem, 1.03vw + 1.31rem, 2.11rem);
--text-2xl: clamp(1.95rem, 1.66vw + 1.54rem, 2.81rem);
--text-3xl: clamp(2.44rem, 2.58vw + 1.8rem, 3.75rem);
```

**Readable text:** 16px+ body, 1.5+ line-height, max 75ch width.

### Spacing System (4px base grid)

Use Tailwind spacing scale consistently:
- **Micro** (within components): 4-8px (p-1, p-2, gap-1, gap-2)
- **Component** (between elements): 12-24px (gap-3 to gap-6)
- **Section** (between sections): 48-96px (py-12 to py-24)
- **Page** (container padding): 16-64px (px-4 to px-16)

### Component States

Every interactive element needs ALL of these:
- Default, Hover, Focus (visible ring!), Active/Pressed, Disabled (with explanation why)
- Loading state for async actions
- Error state for form inputs (red border + message below)

## Layout Decision Tree

| Interface Type | Layout Pattern |
|---------------|---------------|
| Marketing/Landing | Full-width sections, hero + alternating content blocks |
| Dashboard/Admin | Sidebar (240-280px) + main content area, 12-col grid |
| SaaS/App | Top nav + sidebar, content density medium-high |
| Editorial/Blog | Single column (max 720px), generous margins |
| E-commerce | Grid of cards (3-4 col desktop, 2 col tablet, 1 col mobile) |
| Portfolio | Bento grid or masonry layout |

**Responsive breakpoints:**
```css
sm: 640px    /* Large phone landscape */
md: 768px    /* Tablet portrait */
lg: 1024px   /* Tablet landscape / small desktop */
xl: 1280px   /* Desktop */
2xl: 1536px  /* Wide desktop */
```

## Animation Timing

| Purpose | Duration | Easing |
|---------|----------|--------|
| Hover feedback | 150ms | ease-out |
| Button press | 100ms | ease-in-out |
| Tooltip appear | 200ms | ease-out |
| Modal open | 250ms | cubic-bezier(0.16, 1, 0.3, 1) |
| Modal close | 200ms | ease-in |
| Page transition | 300-500ms | cubic-bezier(0.22, 1, 0.36, 1) |
| Staggered reveals | 50-100ms delay per item | ease-out |

**Rules:** Only animate `transform` and `opacity` for performance. Always respect `prefers-reduced-motion`. Spring easing (`linear(...)`) for playful UI.

## Pre-Output Quality Check

Before delivering any UI code:

```
Typography:  [ ] Distinctive font (not Inter/Roboto/Arial)
             [ ] Clear heading hierarchy (size + weight progression)
             [ ] Readable body (16px+, 1.5 line-height, <75ch)
Color:       [ ] Cohesive palette with CSS variables
             [ ] 60-30-10 distribution
             [ ] WCAG AA contrast (4.5:1 text, 3:1 UI)
Layout:      [ ] Responsive (320px, 768px, 1280px+)
             [ ] Consistent spacing from scale
             [ ] Touch targets 44px+ on mobile
Components:  [ ] All interactive states (hover, focus, active, disabled)
             [ ] Form inputs have labels + error states
Animation:   [ ] Functional = subtle (150-250ms)
             [ ] Transform/opacity only
             [ ] prefers-reduced-motion respected
A11y:        [ ] Semantic HTML (header, nav, main, footer)
             [ ] Focus indicators visible
             [ ] ARIA on icon-only buttons
Code:        [ ] Complete and self-contained
             [ ] No placeholder/TODO
             [ ] Dark mode support (if applicable)
```
