# UX Design Expert - Comprehensive Research Document

Research compiled: 2026-02-18
Purpose: Foundation for building a Claude UX Design Expert skill

---

## Table of Contents

- [A. Core UX Frameworks and Principles](#a-core-ux-frameworks-and-principles)
  - [A1. Nielsen's 10 Usability Heuristics](#a1-nielsens-10-usability-heuristics)
  - [A2. Don Norman's Design Principles](#a2-don-normans-design-principles)
  - [A3. Laws of UX](#a3-laws-of-ux)
  - [A4. Information Architecture](#a4-information-architecture)
  - [A5. Accessibility - WCAG 2.2](#a5-accessibility---wcag-22)
- [B. UX Process Methodology](#b-ux-process-methodology)
  - [B1. User Research Methods](#b1-user-research-methods)
  - [B2. Persona Creation](#b2-persona-creation)
  - [B3. User Journey Mapping](#b3-user-journey-mapping)
  - [B4. Wireframing Principles](#b4-wireframing-principles)
  - [B5. Usability Testing](#b5-usability-testing)
- [C. Common UX Patterns](#c-common-ux-patterns)
  - [C1. Navigation Patterns](#c1-navigation-patterns)
  - [C2. Form Design](#c2-form-design)
  - [C3. Error Handling and Validation](#c3-error-handling-and-validation)
  - [C4. Onboarding Flows](#c4-onboarding-flows)
  - [C5. Search and Filtering](#c5-search-and-filtering)
  - [C6. Mobile-First vs Responsive](#c6-mobile-first-vs-responsive)
  - [C7. Empty, Loading, and Error States](#c7-empty-loading-and-error-states)
- [D. Encoding Into a Claude Skill](#d-encoding-into-a-claude-skill)
  - [D1. Format That Works Best for LLM Consumption](#d1-format-that-works-best-for-llm-consumption)
  - [D2. Decision Trees and Checklists](#d2-decision-trees-and-checklists)
  - [D3. Skill Structure Recommendations](#d3-skill-structure-recommendations)
  - [D4. Reference Implementations](#d4-reference-implementations)
- [Sources](#sources)

---

## A. Core UX Frameworks and Principles

### A1. Nielsen's 10 Usability Heuristics

The gold standard of interface evaluation, created by Jakob Nielsen (NN/g). Used in heuristic evaluations - a method where 3-5 evaluators independently assess a UI against these principles to identify ~75-80% of all usability issues without user testing.

#### 1. Visibility of System Status

**Principle:** The design should always keep users informed about what is going on, through appropriate feedback within a reasonable amount of time.

**Why it matters:** When users know the current system status, they learn the outcome of their prior interactions and determine next steps. Predictable interactions create trust.

**Practical examples:**
- Progress bars during file uploads showing percentage complete
- "You Are Here" indicators on maps and breadcrumb navigation
- Read receipts and typing indicators in messaging apps
- Shopping cart badge showing item count
- Save confirmation messages ("Changes saved 2 seconds ago")
- Step indicators in multi-step forms ("Step 2 of 4")

**Violations to watch for:**
- Button clicked but no visual feedback
- Form submitted but no confirmation
- Background process running with no indicator
- Page loading with no skeleton/spinner

#### 2. Match Between System and Real World

**Principle:** The design should speak the users' language. Use words, phrases, and concepts familiar to the user, rather than internal jargon. Follow real-world conventions, making information appear in a natural and logical order.

**Practical examples:**
- Shopping cart icon (not "purchase aggregation module")
- Stovetop controls matching burner layout
- Trash can/recycle bin for deleted files
- Calendar using familiar date formats
- "Checkout" not "finalize transaction processing"

**Violations to watch for:**
- Technical error codes shown to users (HTTP 500)
- Internal database field names in UI
- Features named by engineering team, not by user mental model

#### 3. User Control and Freedom

**Principle:** Users need a clearly marked "emergency exit" to leave the unwanted action without having to go through an extended process.

**Practical examples:**
- Undo/Redo (Cmd+Z everywhere)
- "Cancel" buttons on all dialogs
- Gmail "Undo Send" (timed)
- Back button always works
- Easy account deletion/deactivation
- "Are you sure?" for destructive actions, but not for routine ones

**Violations to watch for:**
- No way to cancel mid-flow
- No undo for destructive actions
- Forced completion of wizard before exit
- Hard to find "go back" option

#### 4. Consistency and Standards

**Principle:** Users should not have to wonder whether different words, situations, or actions mean the same thing. Follow platform and industry conventions.

**Practical examples:**
- Same icon means the same action throughout the app
- Form validation style consistent across all forms
- Color coding consistent (red = error, green = success)
- Button placement consistent (primary right, secondary left - or the reverse, but always the same)
- Following OS conventions (iOS patterns on iOS, Material on Android)

**Violations to watch for:**
- "Save" vs "Submit" vs "Done" for the same action
- Different navigation patterns on different pages
- Inconsistent date formats
- Mixing design systems

#### 5. Error Prevention

**Principle:** Good designs prevent problems from occurring in the first place. Either eliminate error-prone conditions, or check for them and present users with a confirmation option before they commit to the action.

**Two types:**
- **Slip prevention:** User intends correct action but makes a motor/attention error (autocomplete, constraints, smart defaults)
- **Mistake prevention:** User's mental model doesn't match reality (clear labels, progressive disclosure, preview before commit)

**Practical examples:**
- Input masks for phone numbers (###-###-####)
- Disabled submit button until form is valid
- Calendar date pickers instead of text input
- Autosave (don't require manual save)
- Confirmation dialog before deleting
- Search suggestions / autocomplete
- Greyed-out unavailable options instead of hiding them

**Violations to watch for:**
- Free-text input where structured input is possible
- No confirmation for irreversible actions
- Allowing invalid input then showing error later

#### 6. Recognition Rather Than Recall

**Principle:** Minimize the user's memory load by making elements, actions, and options visible. The user should not have to remember information from one part of the interface to another.

**Practical examples:**
- Recent items / search history
- Dropdown menus instead of requiring typed input
- Inline help text showing expected format
- Album thumbnails alongside titles (Spotify)
- Breadcrumbs showing where you are
- Autocomplete with recent/suggested entries
- Tooltips on icons

**Violations to watch for:**
- Requiring users to remember codes or IDs
- Unlabeled icons
- Settings that reference other settings by name without link
- Forms asking for info the system already has

#### 7. Flexibility and Efficiency of Use

**Principle:** Accelerators - unseen by the novice user - may speed up interaction for the expert user. Allow users to tailor frequent actions.

**Practical examples:**
- Keyboard shortcuts (power users)
- Touch gestures (swipe to delete)
- Customizable dashboards
- Recently used / favorites
- Quick actions / right-click context menus
- Bulk operations (select all, batch edit)
- Amazon's many filters for different shopping styles

**Violations to watch for:**
- No keyboard navigation
- No shortcuts for power users
- Requiring same number of clicks for frequent vs rare actions
- One-size-fits-all interface with no customization

#### 8. Aesthetic and Minimalist Design

**Principle:** Interfaces should not contain information which is irrelevant or rarely needed. Every extra unit of information in an interface competes with the relevant units of information and diminishes their relative visibility.

**Practical examples:**
- Progressive disclosure (show details on demand)
- Clean dashboards with expandable sections
- Prioritized navigation (not everything in the main nav)
- White space to reduce visual noise
- Content hierarchy with clear visual weight

**Violations to watch for:**
- Information overload on a single screen
- Decorative elements that distract from function
- Showing all options at once instead of progressive disclosure
- Dense forms without grouping or visual hierarchy

#### 9. Help Users Recognize, Diagnose, and Recover from Errors

**Principle:** Error messages should be expressed in plain language (no error codes), precisely indicate the problem, and constructively suggest a solution.

**Practical examples:**
- "Your password must include at least 8 characters" not "Error: PASSWD_INVALID"
- "The email 'xyz' is not valid. Example: name@example.com"
- "This username is taken. Try: john.smith2, jsmith_23"
- Highlighting the specific field with the error
- Inline error messages next to the field, not at top of page
- Link to help article from error message

**Violations to watch for:**
- "An error occurred" (no specifics)
- Technical error codes (HTTP 403, ERR_CONNECTION)
- Error message far from the problem field
- No suggested fix

#### 10. Help and Documentation

**Principle:** It's best if the system can be used without documentation, but it may be necessary to provide help. Any such information should be easy to search, focused on the user's task, list concrete steps, and not be too large.

**Practical examples:**
- Contextual tooltips ("?" icon next to complex fields)
- Searchable help center
- Interactive tutorials / product tours
- FAQ section
- Chatbot / live support
- Empty state guidance ("No projects yet. Create your first project")

**Violations to watch for:**
- No help at all
- Help buried in footer with no search
- Help written from system perspective, not user task perspective
- Outdated documentation

---

### A2. Don Norman's Design Principles

From "The Design of Everyday Things" - six fundamental principles of interaction design that apply to physical and digital products alike.

#### 1. Affordances

**Definition:** The possible actions an object allows - the relationship between the properties of an object and the capabilities of the agent that determine how the object could possibly be used.

**In digital design:**
- A button affords clicking (raised, shadowed, colored)
- A text field affords typing (bordered rectangle with cursor)
- A slider affords dragging (handle on a track)
- A link affords navigation (colored, underlined text)
- A scrollable area affords scrolling (content visually extends beyond viewport)

**Key insight:** An affordance exists whether or not it is perceived. A signifier is needed to communicate the affordance.

#### 2. Signifiers

**Definition:** Signals that communicate where the action should take place and how to use the affordance. They tell you how to use something.

**In digital design:**
- A placeholder text in an input field ("Enter your email...")
- A cursor change on hover (pointer for clickable, I-beam for text)
- A chevron (>) indicating expandable/drillable content
- Underlined blue text signifying a hyperlink
- A hamburger icon (three lines) signifying a hidden menu
- Drag handles (dots/lines) signifying draggable items
- Scroll indicators (thin bar, "scroll for more" text)

**Key insight:** The most common design failures involve missing or misleading signifiers. The user knows the affordance exists but can't figure out where or how to use it.

#### 3. Constraints

**Definition:** Limitations that prevent misuse by reducing what actions are possible. They guide behavior by making wrong actions impossible or unlikely.

**Four types:**
- **Physical constraints:** Input masks, disabled buttons, max character limits
- **Cultural constraints:** Red = danger/stop, green = go/success (varies by culture)
- **Semantic constraints:** A "delete" button near a file name is understood as deleting that file
- **Logical constraints:** Greying out impossible menu options, hiding irrelevant form fields

**In digital design:**
- Date picker restricting to valid dates only
- Character limit counters on text areas
- Disabled "Next" button until required fields filled
- File upload accepting only certain file types
- Permission-based feature visibility

#### 4. Mapping

**Definition:** The relationship between controls and their effects. Natural mapping takes advantage of spatial analogies and cultural standards.

**In digital design:**
- Scroll direction matching content movement
- Volume slider left=low, right=high
- Tab order matching visual layout (left-to-right, top-to-bottom)
- Color temperature slider (blue=cool, red=warm)
- Map zoom: pinch in/out matches magnification
- Brightness slider icon showing sun getting bigger

**Key insight:** When mapping is natural, the user doesn't need to think about which control does what. Bad mapping (like stovetop knobs in a line for burners in a square) causes constant errors.

#### 5. Feedback

**Definition:** Sending back information about what action has been done and what has been accomplished. Must be immediate, informative, and not excessive.

**In digital design:**
- Button press state change (color, depth, animation)
- Form field validation as you type (green checkmark)
- Loading spinners, progress bars, skeleton screens
- Toast notifications ("Item added to cart")
- Sound effects (notification ding, error buzz)
- Haptic feedback on mobile (vibration on long press)

**Properties of good feedback:**
- Immediate (< 100ms for direct manipulation)
- Proportional (small action = subtle feedback, big action = prominent feedback)
- Not annoying (avoid feedback for every micro-interaction)
- Informative (tells you what happened, not just that something happened)

#### 6. Conceptual Model

**Definition:** An explanation, usually highly simplified, of how something works. The user's understanding of how the system operates based on visible signals.

**In digital design:**
- File/folder metaphor for organizing documents
- Desktop metaphor (icons, windows, trash)
- Shopping cart metaphor for e-commerce
- Conversation metaphor for messaging (bubbles, threads)
- Timeline metaphor for social feeds

**Key insight:** When the user's conceptual model matches the system's actual behavior, the product feels intuitive. Most UX failures stem from a mismatch between the designer's model and the user's model. Bridge the gap through consistent signifiers and feedback.

---

### A3. Laws of UX

21 laws from psychology, cognitive science, and design that govern how humans interact with interfaces. Organized by category.

#### Heuristic Laws

**1. Aesthetic-Usability Effect**
Users perceive aesthetically pleasing designs as more usable, even when they have the same functionality as less attractive alternatives. An attractive interface may mask minor usability issues during initial interaction.

- *Implication:* Invest in visual polish - it literally makes your product more forgivable. But never let beauty hide functional problems.

**2. Fitts's Law**
The time to acquire a target is a function of the distance to and the size of the target. Larger, closer targets are faster to click/tap.

- *Implication:* Make primary actions big and reachable. Place important buttons in easy-to-reach areas (bottom of mobile screens, corners for desktop). Touch targets minimum 44x44px (WCAG). Increase spacing between destructive and constructive actions.

**3. Goal-Gradient Effect**
Users accelerate their behavior as they approach the goal. Motivation increases with visible progress.

- *Implication:* Show progress bars. Use "You're almost done!" messaging. Pre-fill forms where possible. Start progress indicators slightly filled (coffee shop punch cards often start with 2 stamps free).

**4. Hick's Law**
The time to make a decision increases logarithmically with the number of options. More choices = slower decisions = more abandonment.

- *Implication:* Limit options. Break complex decisions into steps. Use progressive disclosure. Provide smart defaults. Recommended/highlighted options reduce decision time. Navigation menus: 5-7 top-level items max.

**5. Jakob's Law**
Users spend most of their time on OTHER sites. They expect your site to work the same way as all the other sites they already know.

- *Implication:* Use established patterns (logo top-left links to home, search top-right, cart icon, hamburger menu). Innovate on value proposition, not on how the UI works. When you must deviate, provide guidance.

**6. Miller's Law**
The average person can keep 7 (plus or minus 2) items in working memory.

- *Implication:* Chunk information into groups of 5-9. Phone numbers: 555-123-4567, not 5551234567. Use tabs, cards, sections to group related content. Don't overwhelm with too many visible options.

**7. Parkinson's Law**
Work expands to fill the time allotted. Give a user 10 minutes to fill a form, it takes 10 minutes.

- *Implication:* Set time expectations ("This takes 2 minutes"). Use autofill, smart defaults, and pre-population to accelerate. Make processes feel faster than expected.

#### Gestalt Laws (Perception)

**8. Law of Common Region**
Elements within a shared boundary (card, container, background color) are perceived as grouped.

- *Implication:* Use cards, borders, and background colors to visually group related elements. A product card groups image + title + price + CTA.

**9. Law of Proximity**
Objects near each other are perceived as related.

- *Implication:* Place labels close to their fields. Group related actions together. Increase spacing between unrelated sections. The space between elements conveys relationship.

**10. Law of Pragnanz (Simplicity)**
People interpret complex images in the simplest form possible.

- *Implication:* Use simple shapes, clear icons, unambiguous graphics. The Olympic rings are perceived as overlapping circles, not a complex polygon.

**11. Law of Similarity**
Elements that look similar are perceived as having the same function.

- *Implication:* Style all clickable elements consistently. All form errors should look the same. Differentiate categories through consistent visual treatment (color, shape, size).

**12. Law of Uniform Connectedness**
Visually connected elements (lines, arrows, shared background) are perceived as more related than disconnected elements.

- *Implication:* Use connecting lines in step indicators. Progress bars connecting steps. Visual flowcharts for processes.

#### Cognitive Bias Laws

**13. Peak-End Rule**
People judge an experience based on how they felt at its most intense point (peak) and at its end, rather than the average.

- *Implication:* Design memorable positive peaks (delightful animations, congratulation screens). Make the ending strong (great confirmation page, follow-up email, "share your achievement"). Fix the worst pain point first - it's the "negative peak."

**14. Serial Position Effect**
People best remember the first and last items in a series.

- *Implication:* Put the most important navigation items first and last. Key information at the beginning and end of pages. Most critical features in first and last positions.

**15. Von Restorff Effect (Isolation Effect)**
When multiple similar items are present, the one that differs most is most likely to be remembered.

- *Implication:* Highlight CTAs with contrasting colors. Make important elements visually distinct. Pricing table: highlight the recommended plan with different color/badge. But use sparingly - if everything is highlighted, nothing is.

**16. Zeigarnik Effect**
People remember uncompleted tasks better than completed ones. Incompleteness creates psychological tension.

- *Implication:* Progress indicators for incomplete profiles. Checklists with remaining items. "You're 80% done" profile completeness bars. But be careful - too many incomplete tasks can feel overwhelming.

#### Universal Principles

**17. Doherty Threshold**
Productivity soars when computer and user interact at a pace (<400ms) that ensures neither has to wait for the other.

- *Implication:* Target < 400ms for all interactions. Use optimistic UI updates (show result immediately, sync in background). Skeleton screens for content loading. Prefetch likely next actions. If something takes > 1s, show a progress indicator.

**18. Occam's Razor**
Among competing solutions, the one with the fewest assumptions (simplest) is most likely correct.

- *Implication:* Remove everything that doesn't serve the user's goal. If a feature can be cut without reducing core value, cut it. Prefer simple workflows over clever ones. "Perfection is achieved not when there is nothing more to add, but when there is nothing left to take away."

**19. Pareto Principle (80/20 Rule)**
80% of effects come from 20% of causes.

- *Implication:* Identify the 20% of features that serve 80% of users and optimize those. 80% of support tickets come from 20% of issues - fix those first. Focus design effort on high-impact areas.

**20. Postel's Law (Robustness Principle)**
Be liberal in what you accept, conservative in what you send.

- *Implication:* Accept multiple input formats (dates: "Feb 18", "02/18/2026", "2026-02-18"). Don't reject input for formatting issues you can auto-correct. Accept "USA", "US", "United States" for country. But output consistently.

**21. Tesler's Law (Law of Conservation of Complexity)**
Every system has an inherent amount of irreducible complexity. The question is: who deals with it - the user or the system?

- *Implication:* Absorb complexity in the system, not the user. Smart defaults handle complexity. Auto-detect timezone instead of asking. But don't oversimplify - removing a necessary feature creates different complexity.

---

### A4. Information Architecture

The structural design of shared information environments - how content is organized, labeled, and connected so users can find what they need.

#### Core IA Principles

**1. Organization Schemes**
- **Alphabetical:** A-Z listings (contact lists, glossaries)
- **Chronological:** Time-based (news feeds, activity logs)
- **Geographical:** Location-based (store locators, maps)
- **Topical:** Subject-based (documentation, wikis)
- **Task-based:** By user action (dashboard, admin panels)
- **Audience-based:** By user type (developer docs vs user docs)

**2. Labeling**
- Use user language, not internal terminology
- Be specific ("Settings" > "More", "Account Security" > "Options")
- Test labels with card sorting
- Consistent terminology across the product

**3. Navigation Systems**
- **Global navigation:** Always visible, consistent across pages
- **Local navigation:** Context-specific to current section
- **Contextual navigation:** In-content links to related items
- **Utility navigation:** Secondary functions (login, help, language)
- **Breadcrumbs:** Show current position in hierarchy

**4. Search Systems**
- Search bar always accessible
- Results relevance-ranked
- Faceted filtering for large result sets
- Search suggestions and autocomplete

#### IA Research Methods

**Card Sorting (Generative)**
Users organize labeled cards into groups that make sense to them. Reveals users' mental models.

- **Open sort:** Users create their own categories and labels. Best for early-stage IA when you have no existing structure.
- **Closed sort:** Users sort cards into predefined categories. Best for validating an existing IA.
- **Hybrid sort:** Pre-defined categories but users can create new ones.
- Tools: Optimal Workshop, UserTesting, Maze

**Tree Testing (Evaluative)**
Users find items in a text-only hierarchy. Tests whether the IA works without visual design distractions.

- Present users with a task ("Find the return policy")
- They navigate a text tree to find it
- Measures: success rate, directness, time
- Best used after card sorting to validate the resulting structure

**Workflow:** Card sort to generate ideas --> Build IA --> Tree test to validate --> Iterate

---

### A5. Accessibility - WCAG 2.2

The Web Content Accessibility Guidelines (WCAG 2.2) contain 86 success criteria across three conformance levels (A, AA, AAA). Level AA is the legal standard in most jurisdictions (ADA, Section 508, EN 301 549).

#### Four Principles (POUR)

**Perceivable** - Content must be presentable to users in ways they can perceive.
- Text alternatives for non-text content (alt text for images)
- Captions for audio/video
- Content can be presented in different ways without losing meaning
- Sufficient color contrast (4.5:1 for normal text, 3:1 for large text)
- Don't use color alone to convey information

**Operable** - Users must be able to operate the interface.
- All functionality available via keyboard
- No keyboard traps
- Sufficient time to interact (or ability to extend)
- No flashing content (> 3 flashes/second)
- Skip navigation link
- Descriptive page titles and link text
- Multiple ways to find content (search, sitemap, navigation)

**Understandable** - Content and interface must be understandable.
- Language of page declared in HTML
- Consistent navigation across pages
- Consistent component behavior
- Input instructions and error identification
- Error suggestions and prevention

**Robust** - Content must be interpretable by assistive technologies.
- Valid HTML
- ARIA roles, states, and properties used correctly
- Status messages programmatically determinable

#### Key WCAG 2.2 Additions (over 2.1)

**Focus Appearance (AA):** Focus indicators must have a minimum size and contrast. Focus must not be entirely hidden by overlapping content.

**Dragging Movements (AA):** Any functionality that uses dragging must have a single-pointer alternative (e.g., up/down arrows instead of drag-and-drop).

**Target Size (Minimum) (AA):** Interactive targets must be at least 24x24 CSS pixels, unless inline or essential. Recommended: 44x44px.

**Consistent Help (A):** If help mechanisms (contact info, chatbot, FAQ) exist on multiple pages, they must appear in the same relative location.

**Redundant Entry (A):** Don't require users to re-enter information they've already provided in the same process.

**Accessible Authentication (Minimum) (AA):** Cognitive function tests (like remembering a password) must have alternatives (paste support, biometrics, password managers).

#### Quick Accessibility Checklist for Developers

```
PERCEIVABLE
[ ] All images have meaningful alt text (or alt="" for decorative)
[ ] Videos have captions and audio descriptions
[ ] Color contrast passes (4.5:1 text, 3:1 large text, 3:1 UI components)
[ ] Color is never the only indicator (use icons, text, patterns too)
[ ] Text can be resized to 200% without loss of content
[ ] Content works in landscape and portrait

OPERABLE
[ ] All interactive elements reachable by keyboard (Tab, Enter, Space, Arrows)
[ ] Visible focus indicators on all interactive elements
[ ] No keyboard traps
[ ] Skip-to-content link present
[ ] Touch targets >= 44x44px
[ ] No flashing content
[ ] Page has descriptive <title>

UNDERSTANDABLE
[ ] Page language set (<html lang="en">)
[ ] Form fields have visible labels (not just placeholders)
[ ] Error messages identify the field and suggest a fix
[ ] Navigation is consistent across pages
[ ] Instructions don't rely solely on sensory characteristics ("click the red button")

ROBUST
[ ] Valid, semantic HTML (headings hierarchy, landmark regions)
[ ] ARIA used correctly (only when native HTML can't do the job)
[ ] Components have accessible names
[ ] Dynamic content changes announced to screen readers (aria-live)
```

---

## B. UX Process Methodology

### B1. User Research Methods

Research methods mapped to the product lifecycle and when to use each.

#### Research Landscape (2x2 Matrix)

|                  | **Attitudinal** (what users say) | **Behavioral** (what users do) |
|------------------|----------------------------------|-------------------------------|
| **Qualitative**  | User interviews, Focus groups, Diary studies | Usability testing, Field studies, Contextual inquiry |
| **Quantitative** | Surveys, Card sorting | A/B testing, Analytics, Click tracking, Eye tracking |

#### Method Guide

**User Interviews** (Qualitative, Attitudinal)
- When: Discovery phase, understanding user needs/motivations/pain points
- Sample: 5-8 users per segment
- Duration: 30-60 min
- Output: Themes, quotes, insight statements
- Tips: Ask "why" 5 times. Use open-ended questions. Never lead. Record with permission.

**Contextual Inquiry** (Qualitative, Behavioral)
- When: Understanding real-world usage context
- Observe users in their natural environment using the product
- Best for: Understanding workarounds, environmental constraints, workflows

**Surveys** (Quantitative, Attitudinal)
- When: Validating hypotheses at scale, measuring satisfaction
- Sample: 100+ respondents for statistical significance
- Types: NPS, SUS (System Usability Scale), CSAT, custom
- Tips: Max 10 minutes. Mix Likert scales with open-ends. Avoid leading questions.

**Guerrilla Testing** (Qualitative, Behavioral)
- When: Quick validation of concepts, early prototypes
- Approach: 5-minute tests with random people (cafe, office, street)
- Sample: 5-10 people
- Best for: Catching obvious usability issues fast and cheap

**A/B Testing** (Quantitative, Behavioral)
- When: Optimizing existing features, choosing between options
- Requires: Statistical significance (typically 95% confidence)
- Measures: Conversion rate, completion rate, error rate, time on task
- Tips: Test one variable at a time. Run long enough for significance. Account for novelty effect.

**Analytics Review** (Quantitative, Behavioral)
- When: Understanding current usage patterns
- Tools: Google Analytics, Mixpanel, Amplitude, Hotjar
- Metrics: Funnel drop-offs, page flow, bounce rate, feature usage
- Best for: Identifying WHAT is happening (pair with qualitative to understand WHY)

**Usability Testing** (Qualitative, Behavioral)
- When: Evaluating designs (prototypes or live products)
- Sample: 5 users uncover ~85% of usability issues (Nielsen)
- Types: Moderated (in-person/remote), Unmoderated (recorded)
- Output: Task success rate, error rate, time on task, SUS score
- Tips: Write realistic tasks. Think-aloud protocol. Don't help the user.

**Diary Studies** (Qualitative, Mixed)
- When: Understanding behavior over time
- Duration: 1-4 weeks
- Participants: 10-15
- Best for: Capturing habits, triggers, context changes

---

### B2. Persona Creation

#### What is a Persona

A research-based fictional representation of your target user segment. NOT a demographic profile - it's a behavior/goals/pain profile.

#### Persona Template

```
NAME: [Realistic name + photo]
ROLE: [Job title or life context]
AGE: [Age range, not exact]
TECH SAVVINESS: [Low / Medium / High]

BIO: [2-3 sentences about their context]

GOALS:
- [What they want to accomplish with your product]
- [Underlying motivation]
- [Success criteria]

FRUSTRATIONS:
- [Current pain points]
- [What's blocking them]
- [What annoys them about existing solutions]

BEHAVIORS:
- [How they currently solve this problem]
- [What tools/products they use]
- [Usage frequency and context]

QUOTE: "[A realistic quote that captures their perspective]"

SCENARIO: [A brief narrative of them using the product in context]
```

#### Best Practices

- Base on real research data (interviews, surveys, analytics)
- 2-4 personas per product (primary + secondary)
- Make them specific enough to be useful in design decisions
- Include anti-personas (who you're NOT designing for)
- Review and update quarterly
- Pin them in the team workspace

#### Jobs-to-Be-Done (JTBD) Alternative

Instead of (or alongside) personas, define user jobs:

```
When [situation], I want to [motivation], so I can [expected outcome].
```

Examples:
- "When I'm commuting, I want to quickly check my team's updates, so I can respond before my first meeting."
- "When I get a new lead, I want to see their company info, so I can personalize my outreach."

JTBD focuses on the functional and emotional needs rather than demographics. Best used in combination with personas.

---

### B3. User Journey Mapping

#### What is a Journey Map

A visualization of the end-to-end experience a user has with a product, from initial awareness through long-term use. Shows actions, thoughts, emotions, and opportunities at each stage.

#### Journey Map Structure

```
STAGE:        Awareness --> Consideration --> Onboarding --> Regular Use --> Advocacy
ACTIONS:      [What the user does at each stage]
TOUCHPOINTS:  [Where they interact - web, email, app, support]
THOUGHTS:     [What they're thinking]
EMOTIONS:     [How they feel - mapped on a satisfaction curve]
PAIN POINTS:  [Friction, confusion, frustration]
OPPORTUNITIES:[Where we can improve]
```

#### How to Build One

1. Define scope (which persona, which scenario)
2. Gather data (interviews, analytics, support tickets)
3. Map stages (typically 4-7 macro stages)
4. Fill in details per stage (actions, thoughts, emotions)
5. Identify pain points and moments of truth
6. Generate opportunity statements
7. Prioritize improvements by impact vs effort

#### Types

- **Current state:** Maps the experience as it exists today
- **Future state:** Vision of the ideal experience
- **Day-in-the-life:** Broader context beyond your product
- **Service blueprint:** Backstage processes that support the journey

---

### B4. Wireframing Principles

#### Purpose of Wireframes

Low-fidelity representations of screen layouts that communicate:
- Content hierarchy and placement
- Interaction flow
- Functionality (what's on the page)
- NOT visual design (no colors, fonts, images)

#### Wireframing Best Practices

**Content-first approach:**
- Define content hierarchy before layout
- Real content > Lorem ipsum (use realistic text lengths)
- Prioritize: what MUST be on this screen vs nice-to-have

**Layout principles:**
- Follow F-pattern (content pages) or Z-pattern (landing pages) reading patterns
- Most important content above the fold
- Consistent grid system (8px or 4px base)
- Generous whitespace
- Clear visual hierarchy (size, weight, contrast, spacing)

**Interaction annotations:**
- Annotate what happens on click/tap/hover
- Show conditional states (logged in vs out, empty vs populated)
- Document edge cases (0 items, 100+ items, max-length text)
- Include error states

**Fidelity spectrum:**
- **Sketches:** Paper, whiteboard. Minutes to create. For exploring ideas.
- **Low-fi wireframes:** Basic shapes, placeholder text. For layout decisions.
- **Mid-fi wireframes:** Real content, accurate spacing. For stakeholder review.
- **High-fi prototypes:** Interactive, near-final. For usability testing.

**Tools:** Figma, Sketch, Balsamiq, Whimsical, pen and paper

---

### B5. Usability Testing

#### The 5-User Rule

Jakob Nielsen demonstrated that 5 users find approximately 85% of usability problems. Diminishing returns after that. Better to test with 5, fix issues, and test again with 5 more.

#### Test Design

**Task construction:**
- Write realistic scenarios, not instructions
- Bad: "Click on the navigation menu and select Settings"
- Good: "You want to change your notification preferences. Go ahead."
- 5-7 tasks per session
- Mix easy, medium, and difficult tasks
- Include at least one "impossible" task to see how users handle failure

**Metrics to collect:**
- Task success rate (binary: completed or not)
- Time on task
- Error rate (wrong clicks, backtracks)
- Satisfaction (post-task rating, SUS score)
- Qualitative observations (confusion, hesitation, workarounds)

**Think-aloud protocol:**
- Ask users to verbalize their thoughts as they navigate
- Don't prompt or help
- Note hesitations, questions, and assumptions
- Record the session (screen + audio)

**Reporting:**
- Severity rating per issue (Critical / Major / Minor / Cosmetic)
- Frequency (how many users encountered it)
- Screenshot/recording clip of the issue
- Recommended fix
- Priority matrix (severity x frequency)

#### Remote vs In-Person

| Aspect | Remote Unmoderated | Remote Moderated | In-Person |
|--------|-------------------|-------------------|-----------|
| Cost | Low | Medium | High |
| Speed | Fast (async) | Medium | Slow |
| Sample | Large | Medium | Small |
| Depth | Shallow | Deep | Deepest |
| Context | Low (can't see environment) | Medium | High |
| Best for | Quick validation, A/B comparison | Exploratory, complex tasks | Complex products, accessibility |

---

## C. Common UX Patterns

### C1. Navigation Patterns

#### Pattern Selection Guide

| Pattern | Best For | Avoid When |
|---------|----------|------------|
| **Top nav bar** | Marketing sites, docs, 5-7 sections | Deep hierarchy, many sections |
| **Sidebar** | Admin panels, dashboards, tools | Mobile-first, simple sites |
| **Tab bar (bottom)** | Mobile apps, 3-5 primary actions | > 5 items, desktop apps |
| **Hamburger menu** | Mobile secondary nav, space-constrained | Primary navigation (hides discoverability) |
| **Breadcrumbs** | Deep hierarchies, e-commerce | Flat architecture |
| **Mega menu** | Large sites with many categories | Simple sites, mobile |
| **Bottom sheet** | Mobile actions, filters | Primary content |

#### Best Practices

- Primary navigation always visible (not hidden behind hamburger on desktop)
- Current location always indicated (active state)
- Max 7 top-level items (Miller's Law)
- Mobile: bottom tab bar for primary actions (thumb zone)
- Breadcrumbs as secondary nav, never as primary
- Logo always links home
- Search always accessible
- Persistent navigation across pages (Consistency)

#### Common Mistakes

- Hamburger menu as sole navigation on desktop (kills discoverability)
- Too many navigation levels (>3 clicks to any content)
- No visual indication of current location
- Navigation labels that are ambiguous ("Solutions", "Resources", "More")
- Dropdown menus that require precision hovering (Fitts's Law violation)

---

### C2. Form Design

#### Core Principles

**1. Minimize fields**
- Only ask what you need right now
- Split long forms into steps
- Every field you add reduces completion rate ~10%

**2. Single-column layout**
- Multi-column forms increase completion time and errors
- Exception: short related fields (City + State + Zip)

**3. Labels above fields**
- Labels above fields are faster to scan than left-aligned labels
- Never use placeholder-only labels (disappear on focus, accessibility issue)
- Placeholder text: use for format hints ("e.g., john@example.com")

**4. Logical grouping**
- Group related fields with headings and whitespace
- Personal info, then address, then payment
- Use fieldsets semantically

**5. Smart defaults and autofill**
- Pre-populate what you know (country from IP, name from account)
- Support browser autofill (correct `autocomplete` attributes)
- Default to most common choice

**6. Progressive disclosure**
- Show advanced options only when needed
- "Add coupon code" as expandable, not always visible
- Conditional fields (show shipping address only if "different from billing")

#### Field-Specific Guidelines

| Field Type | Best Practice |
|-----------|--------------|
| Email | Single field, validate format on blur, show error inline |
| Password | Show requirements upfront, allow show/hide toggle, support paste |
| Phone | Single field with formatting, accept any format (Postel's Law) |
| Date | Use date picker for ranges, text input for known dates (birthdate) |
| Address | Use address autocomplete (Google Places, etc.) |
| Credit card | Auto-detect card type, format as you type, show card icon |
| Name | Single "Full name" field, not First + Last (cultural sensitivity) |
| Country | Dropdown with search/type-ahead, pre-select based on IP |

---

### C3. Error Handling and Validation

#### Validation Strategy

**When to validate:**

| Trigger | Use When |
|---------|----------|
| On blur (after leaving field) | Format validation (email, phone). Best default. |
| On submit | Required field check, cross-field validation |
| On keypress (real-time) | Character limits, password strength, search |
| Never on focus | Don't show errors before user has tried to enter data |

**Rule:** Validate AFTER the error happens (on blur), not before. Remove the error as soon as the input is corrected (real-time on keypress during correction).

#### Error Message Anatomy

```
[Icon] [Specific problem]. [How to fix it].
```

**Good examples:**
- "Please enter a valid email address. Example: name@company.com"
- "Password must be at least 8 characters. You've entered 6."
- "This username is taken. Try: john.smith2 or jsmith_23"
- "Card number is incomplete. Visa cards have 16 digits."

**Bad examples:**
- "Invalid input"
- "Error"
- "Please fill in all required fields" (which ones?)
- "Validation failed: ERR_422_UNPROCESSABLE"

#### Visual Error Design

- Red border on the field (#D32F2F or similar)
- Error icon (!) to the left of the message
- Error text directly below the field, not at page top
- Don't remove the user's input - let them correct it
- Keep the error visible until corrected
- On submit with errors: scroll to first error, focus the field
- Color + icon + text (never color alone - accessibility)

#### Success States

- Green checkmark on valid fields (not all fields - only confusing/complex ones)
- Inline "Available!" for username checks
- Progressive: show real-time as user types for passwords, usernames
- Don't overdo positive validation - it becomes noise

---

### C4. Onboarding Flows

#### Onboarding Patterns

**1. Product Tour / Walkthrough**
- 3-5 tooltips highlighting key features
- Always skippable
- Show progress ("2 of 4")
- Trigger on first login only
- Don't cover the UI - point to it
- Best for: feature-rich products, significant UI changes

**2. Progressive Disclosure**
- Introduce features as they become relevant
- "You just created your first project! Here's how to invite teammates."
- Contextual, just-in-time learning
- Best for: complex products, ongoing education

**3. Checklist / Setup Wizard**
- Clear steps: "Complete your profile (3 of 5 done)"
- Visual progress
- Users can complete in any order
- Celebrate completion
- Best for: products requiring configuration

**4. Empty State Guidance**
- When a section has no data, show what to do
- "No contacts yet. Import from CSV or add manually."
- Include a clear CTA
- Show example/sample data option
- Best for: data-driven products

**5. Interactive Tutorial**
- User performs real actions with guidance
- "Try creating a task now" with a guided overlay
- Sandbox mode with sample data
- Best for: complex tools, technical products

#### Onboarding Anti-Patterns

- Showing everything at once (cognitive overload)
- Mandatory 10+ step tour you can't skip
- Teaching abstract concepts instead of letting users do things
- No way to re-access the onboarding later
- Onboarding separate from the real product (separate "tutorial mode")
- Assuming users will remember training from weeks ago

#### Key Metrics

- Time to first value (how fast user achieves their goal)
- Activation rate (% completing key setup actions)
- Onboarding completion rate
- Drop-off by step
- Return rate within 7 days

---

### C5. Search and Filtering

#### Search UX Fundamentals

**Search bar:**
- Always visible (not hidden behind icon on content-heavy sites)
- Full width or prominent placement
- Placeholder text indicating scope ("Search products...", "Search documentation...")
- Minimum 30 characters visible width
- Submit on Enter, also clickable search icon

**Autocomplete / Typeahead:**
- Show suggestions after 2-3 characters
- Display 5-8 suggestions max (avoid choice paralysis)
- Support keyboard navigation (Up/Down + Enter)
- Show recent searches separately from suggestions
- Highlight matching portion of suggestions
- Include category/type indicators for diverse results
- "Tap-ahead" - allow refining a suggestion

**Search results:**
- Show result count
- Highlight query terms in results
- Relevance-ranked by default
- Clear "no results" state with suggestions
- Spell correction ("Did you mean...?")
- Related/alternative searches

#### Filtering Best Practices

**Faceted search:**
- Show result count per filter option
- Update counts dynamically as filters applied
- Allow multiple selections within a category
- Show active filters with easy removal (chips)
- "Clear all" option
- Filters don't reset on page navigation

**Filter placement:**
- Sidebar: best for desktop with many filter categories
- Top bar: best for few filter categories, horizontal layout
- Bottom sheet: best for mobile
- Floating filter button: mobile secondary option

**Filter interaction:**
- Checkboxes for multi-select
- Radio buttons for single-select
- Sliders for ranges (price, date)
- Search within filter options for long lists
- "Apply" button for expensive queries, instant for cheap ones
- Show active filters summary above results

#### Common Mistakes

- No "clear filters" option
- Filters resulting in zero results with no guidance
- Search not tolerant of typos
- No search suggestions or autocomplete
- Filtering resets scroll position
- No indication of how many results match

---

### C6. Mobile-First vs Responsive

#### Mobile-First Design

**Philosophy:** Design for the smallest screen first, then enhance for larger screens. Forces prioritization of content and features.

**Core constraints:**
- Touch targets: minimum 44x44px with 8px spacing
- Thumb zone: most frequent actions in the bottom 1/3 of screen
- One-handed use: 75% of users use phones one-handed
- Bandwidth: optimize for slower connections
- Screen real estate: every pixel is premium

**Mobile-specific patterns:**
- Bottom tab bar for primary navigation (iOS: 5 items max)
- Pull-to-refresh for content feeds
- Swipe gestures for secondary actions (swipe to delete, archive)
- Bottom sheets for contextual actions
- Floating action button (FAB) for primary action
- Stack horizontal layouts vertically
- Collapsible sections for long content

#### Responsive Breakpoints

```
Mobile:     320px - 767px
Tablet:     768px - 1023px
Desktop:    1024px - 1439px
Large:      1440px+
```

**What changes between breakpoints:**
- Navigation: Bottom tab --> Sidebar or top nav
- Layout: Single column --> Multi-column grid
- Content: Progressive disclosure --> Show more at once
- Touch targets: Larger on mobile --> Standard on desktop
- Typography: Scales up (clamp() for fluid type)
- Images: Responsive with srcset/picture

#### Responsive Design Principles

- Fluid grids (percentages, fr units), not fixed widths
- Flexible images (max-width: 100%)
- Media queries at natural content breakpoints, not device widths
- Content priority: same content accessible everywhere, layout adapts
- Test on real devices, not just browser resize
- Consider touch AND mouse (hover states as enhancement)

---

### C7. Empty, Loading, and Error States

These "edge case" screens are encountered by EVERY user. They define the perceived quality of the product.

#### Empty States

**Types:**
1. **First-use empty:** User hasn't created content yet
2. **No results:** Search/filter returned nothing
3. **Cleared data:** User deleted all items
4. **Error empty:** System failure prevents showing content

**Best practices:**
- Never show a completely blank screen
- Explain what will appear here and how to get it
- Include a clear primary CTA ("Create your first project", "Import data")
- Show illustration or helpful graphic (but not decorative fluff)
- Offer sample/demo data option for complex products
- Make the empty state educational, not just decorative

**Examples:**
```
[Illustration of empty inbox]
"No messages yet"
"Messages from your team will appear here."
[Invite teammates] [Learn more]
```

#### Loading States

**Duration-based approach:**
| Duration | Pattern | Example |
|----------|---------|---------|
| < 100ms | No indicator | Instant interactions |
| 100ms - 1s | Subtle indicator | Button spinner, opacity change |
| 1s - 10s | Skeleton screen OR spinner | Page load, data fetch |
| > 10s | Progress bar with % | File upload, export |
| Unknown | Indeterminate spinner + explanation | "Processing your request..." |

**Skeleton screens:**
- Show page layout structure with placeholder shapes
- Animate with subtle shimmer/pulse
- Match the actual content layout (not generic)
- Better than spinners for content-heavy pages (reduces perceived wait time)
- Don't use for actions (use inline spinner for button clicks)

**Best practices:**
- Always show SOMETHING is happening (visibility of system status)
- Set expectations ("This usually takes about 30 seconds")
- Allow cancellation for long operations
- Optimistic UI: show the result immediately, sync in background
- Lazy load below-the-fold content
- Prefetch likely next pages

#### Error States

**Types:**
1. **Connection error:** "You appear to be offline. Cached data shown."
2. **Server error:** "Something went wrong on our end. We're looking into it."
3. **Permission error:** "You don't have access. Request access from [admin]."
4. **Not found:** "This page doesn't exist. Here are some helpful links."
5. **Timeout:** "This is taking longer than expected. [Retry] or [Cancel]"

**Best practices:**
- Plain language, no technical jargon
- Explain what happened and what user can do
- Provide action buttons (Retry, Go Home, Contact Support)
- Preserve user's data/input when possible
- Log the error on the backend for debugging
- Custom 404/500 pages with navigation
- Offline mode: show cached data with "offline" indicator

---

## D. Encoding Into a Claude Skill

### D1. Format That Works Best for LLM Consumption

Based on research into effective LLM prompt engineering and the existing skill format in this repository:

**What works:**
1. **Structured checklists** - LLMs follow checklists reliably. Numbered steps with clear pass/fail criteria.
2. **Decision trees as IF/THEN rules** - "IF mobile design, THEN bottom tab bar for primary nav. IF > 5 sections, THEN sidebar navigation."
3. **Examples over explanations** - "Good: [example]. Bad: [example]." is more effective than paragraphs explaining the principle.
4. **Severity tags** - `[CRITICAL]`, `[RECOMMENDED]`, `[NICE-TO-HAVE]` help prioritize which rules to apply first.
5. **Context triggers** - "When the user asks to review a design..." or "When building a form..." activates the right section.
6. **Concise tables** - Pattern selection guides as tables are highly effective for LLM pattern matching.

**What doesn't work:**
1. Long theoretical explanations (LLM already knows the theory)
2. Ambiguous guidelines ("make it look nice")
3. Too many rules without prioritization (everything is important = nothing is)
4. Rules without examples (no anchor for correct behavior)

**Optimal structure:**
```
SKILL.md
  - Frontmatter (name, description, triggers)
  - Role definition (who Claude becomes)
  - Process (step-by-step what to do)
  - Decision trees (conditional logic)
  - Checklists (verification)
  - Pattern libraries (quick-reference tables)
  - Anti-patterns (what NOT to do)
```

### D2. Decision Trees and Checklists

#### Master Decision Tree: UX Review

```
INPUT: User shows a design, asks for UX review, or asks to build a UI

STEP 1: CONTEXT
  - What type of product? (SaaS, e-commerce, content, tool, mobile app)
  - Who are the users? (technical/non-technical, frequency, context)
  - What is the core user task on this screen?
  - What devices/platforms?

STEP 2: HEURISTIC SCAN (run all 10)
  For each heuristic, ask:
    - Is this principle satisfied? (Yes/Partially/No)
    - If No: specific violation + severity (Critical/Major/Minor)
    - Suggested fix with example

STEP 3: PATTERN CHECK
  - Is the navigation pattern appropriate for the content/platform?
  - Are forms following best practices?
  - Are error/empty/loading states handled?
  - Is the information architecture logical?

STEP 4: ACCESSIBILITY QUICK CHECK
  - Color contrast sufficient?
  - Keyboard navigable?
  - Touch targets sized correctly?
  - Screen reader compatible?

STEP 5: PRIORITIZED RECOMMENDATIONS
  Output format:
    CRITICAL (must fix): [issues that block users]
    MAJOR (should fix): [issues that frustrate users]
    MINOR (nice to fix): [issues that could be improved]
    POSITIVE: [what works well - always include this]
```

#### Master Checklist: Building a New UI

```
BEFORE CODING
[ ] User task clearly defined
[ ] Target users identified (persona/JTBD)
[ ] Content hierarchy established
[ ] Navigation pattern selected (with rationale)
[ ] Responsive strategy defined
[ ] Key user flows mapped

DURING CODING
[ ] Semantic HTML structure
[ ] Consistent spacing system (4px or 8px base)
[ ] Typography hierarchy (max 2-3 font sizes in body)
[ ] Color system with semantic tokens (error, success, warning)
[ ] Interactive states defined (default, hover, focus, active, disabled)
[ ] Form validation strategy (when to validate, error format)
[ ] Loading/empty/error states for all data-dependent sections
[ ] Keyboard navigation works (Tab, Enter, Escape, Arrows)
[ ] Touch targets >= 44px on mobile

AFTER CODING
[ ] Run through Nielsen's 10 heuristics
[ ] Check WCAG AA compliance (contrast, alt text, focus, labels)
[ ] Test on mobile viewport (375px)
[ ] Test with keyboard only
[ ] Test empty states and error states
[ ] Review with real content (not lorem ipsum)
```

### D3. Skill Structure Recommendations

Based on analysis of the existing `frontend-design` skill and the `skill-creator` guidance:

**Recommended skill architecture:**

```
skills/ux-design/
  SKILL.md          - Main skill (concise, actionable rules)
  UX_RESEARCH.md    - This document (reference, not loaded by default)
```

**SKILL.md should contain:**
1. **Role definition** (1-2 sentences) - "You are a UX design expert..."
2. **Activation triggers** - When to use this skill
3. **Process** - Step-by-step workflow (decision tree from D2)
4. **Quick-reference tables** - Pattern selection, checklist
5. **Anti-patterns** - Common mistakes to avoid
6. **Output format** - How to structure UX feedback

**SKILL.md should NOT contain:**
- Full theory explanations (Claude already knows Nielsen's heuristics)
- History or origin stories of principles
- Lengthy examples (one good/bad pair per concept is enough)
- This research document's full content (too many tokens)

**Key insight from research:** The most effective LLM UX prompts work as a "Composite Design Intelligence" - they activate the LLM's existing knowledge of Tufte, Nielsen, Norman, etc. by referencing these frameworks, then add specific decision logic and output formatting that the LLM doesn't have natively.

### D4. Reference Implementations

#### samim.io "Design Intelligence" Prompt Approach

The most effective LLM UX prompt found during research positions the LLM as a "Composite Design Intelligence Model" drawing from design reference clusters:
- Clarity and Information Design (Tufte, Wurman)
- Usability and Human Factors (Nielsen, Norman)
- Minimalism and Structure (Rams, Vignelli, Alexander)
- Visualization and Interaction (Victor, Shneiderman)
- Systems and Conceptual Modeling (Simon, Kay)
- Cognitive Flow (Sierra, Csikszentmihalyi)

Mandatory output structure: Improved Version, Rationale, Principles Applied, Optional Alternatives.

Rules: No vague language. Always produce an improved version, never just critique. Maintain input format integrity.

#### ui-ux-pro-max-skill Approach

A Claude Code skill that uses a reasoning engine with parallel lookups:
- 100 product-type categories
- 67 style recommendations
- 96 color palettes
- 24 landing page patterns
- 57 typography pairings

Key features: Industry-specific reasoning rules, anti-pattern databases, pre-delivery validation checklists, responsive breakpoint testing criteria.

#### Claude Code UI Agents Approach

Collection of 9 specialized subagent prompts:
- Design System Generator
- Universal UI/UX Design Methodology
- Mobile Design Philosophy
- React Component Architect
- CSS Architecture Specialist
- User Persona Creator
- Micro-Interactions Expert
- Mobile-First Layout Expert
- ARIA Implementation Specialist

Pattern: Each prompt is a focused expert role with specific output format and evaluation criteria.

---

## Sources

### LLM + UX Design
- [Useful LLM Prompt for UI/UX Design - samim.io](https://samim.io/p/2025-11-29-useful-llm-prompt-for-ui_ux-design/)
- [UI UX Pro Max Skill - GitHub](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
- [Claude Code UI Agents - GitHub](https://github.com/mustafakendiguzel/claude-code-ui-agents)
- [Claude for Code: Streamline Product Design - UX Planet](https://uxplanet.org/claude-for-code-how-to-use-claude-to-streamline-product-design-process-97d4e4c43ca4)
- [Complete Collection of Claude Code Prompts for UX/UI - Medium](https://medium.com/@henriallevi/complete-collection-of-claude-code-prompts-to-avoid-generic-ux-ui-design-4565496cd894)
- [Role of LLMs in UI/UX Design - Systematic Review](https://arxiv.org/html/2507.04469v1)

### UX Frameworks and Principles
- [10 Usability Heuristics - NN/g](https://www.nngroup.com/articles/ten-usability-heuristics/)
- [21 Laws of UX Explained - UX Design Institute](https://www.uxdesigninstitute.com/blog/laws-of-ux/)
- [Laws of UX - lawsofux.com](https://lawsofux.com/fittss-law/)
- [24 UX Design Principles Build-For Framework - UXmatters](https://www.uxmatters.com/mt/archives/2025/07/24-ux-design-principles-of-the-build-for-framework.php)
- [UX Design Principles for 2025 - UXPin](https://www.uxpin.com/studio/blog/ux-design-principles/)
- [10 UI/UX Fundamental Laws 2025 - UX Playbook](https://uxplaybook.org/articles/10-ui-ux-fundamental-laws-2025)
- [5 UX Design Frameworks 2025 - UX Playbook](https://uxplaybook.org/articles/5-fundamental-ux-design-frameworks-2025)

### Don Norman
- [Don Norman Principles of Interaction - UX Magazine](https://uxmag.com/articles/understanding-don-normans-principles-of-interaction)
- [Design of Everyday Things Summary - TianPan.co](https://tianpan.co/blog/2025-08-31-the-design-of-everyday-things)

### Accessibility
- [WCAG 2.2 AA Summary and Checklist - Level Access](https://www.levelaccess.com/blog/wcag-2-2-aa-summary-and-checklist-for-website-owners/)
- [WCAG Checklist - DigitalA11Y](https://www.digitala11y.com/wcag-checklist/)
- [WCAG Compliance Checklist - BrowserStack](https://www.browserstack.com/guide/wcag-compliance-checklist)
- [WebAIM WCAG 2 Checklist](https://webaim.org/standards/wcag/checklist)
- [WCAG 2.2 Compliance Roadmap - AllAccessible](https://www.allaccessible.org/blog/wcag-22-compliance-checklist-implementation-roadmap)

### Heuristic Evaluation
- [How to Conduct Heuristic Evaluation - NN/g](https://www.nngroup.com/articles/how-to-conduct-a-heuristic-evaluation/)
- [Heuristic Evaluation Guide 2025 - Owle Studio](https://www.owlestudio.com/business-resilience-tips-2-2/12087/)
- [Heuristic Evaluation Template - Miro](https://miro.com/templates/heuristic-evaluation/)
- [UX Design Audit Checklist - Eleken](https://www.eleken.co/blog-posts/a-checklist-for-ux-design-audit-based-on-jakob-nielsens-10-usability-heuristics)

### User Research
- [Which UX Research Methods - NN/g](https://www.nngroup.com/articles/which-ux-research-methods/)
- [11 UX Research Methods - Maze](https://maze.co/guides/ux-research/methods/)
- [Usability Testing 101 - NN/g](https://www.nngroup.com/articles/usability-testing-101/)
- [JTBD in UX Research - User Interviews](https://www.userinterviews.com/ux-research-field-guide-chapter/jobs-to-be-done-jtbd-framework)
- [User Persona Templates - User Interviews](https://www.userinterviews.com/blog/templates-personas-jtbd-mental-models)

### UX Patterns
- [Form Errors Design Guidelines - NN/g](https://www.nngroup.com/articles/errors-forms-design-guidelines/)
- [Inline Form Validation - Baymard](https://baymard.com/blog/inline-form-validation)
- [Autocomplete Design Best Practices - Baymard](https://baymard.com/blog/autocomplete-design)
- [Search Filter UX - Algolia](https://www.algolia.com/blog/ux/search-filter-ux-best-practices)
- [Skeleton Screens 101 - NN/g](https://www.nngroup.com/articles/skeleton-screens/)
- [Empty State Design - Eleken](https://www.eleken.co/blog-posts/empty-state-ux)
- [Empty States in Complex Applications - NN/g](https://www.nngroup.com/articles/empty-state-interface-design/)
- [Onboarding UX Patterns - Eleken](https://www.eleken.co/blog-posts/user-onboarding-ux-patterns-a-guide-for-saas-companies)
- [Onboarding Best Practices 2025 - UX Design Institute](https://www.uxdesigninstitute.com/blog/ux-onboarding-best-practices-guide/)
- [Loading, Empty, Error States - Agriculture Design System](https://design-system.agriculture.gov.au/patterns/loading-error-empty-states)
- [Faceted Search Best Practices - Fact-Finder](https://www.fact-finder.com/blog/faceted-search/)

### Information Architecture
- [Card Sorting - NN/g](https://www.nngroup.com/articles/card-sorting-definition/)
- [Card Sorting vs Tree Testing - NN/g](https://www.nngroup.com/articles/card-sorting-tree-testing-differences/)
- [Filter Categories and Values - NN/g](https://www.nngroup.com/articles/filter-categories-values/)
