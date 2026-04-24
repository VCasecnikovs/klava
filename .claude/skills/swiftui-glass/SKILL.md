---
name: swiftui-glass
description: Generate SwiftUI Liquid Glass UI code for iOS 26+. Use when building glass effects, translucent materials, navigation overlays, or adopting Apple Liquid Glass design language in SwiftUI apps.
user_invocable: true
---

# SwiftUI Liquid Glass - Comprehensive Reference

Use this skill when generating SwiftUI code that uses Apple's Liquid Glass design language (iOS 26+), glass effects, translucent materials, or any glass-like UI patterns.

## A. Apple's Liquid Glass Design Philosophy

### What is Liquid Glass

Liquid Glass is Apple's unified design language announced at WWDC 2025 (June 9, 2025) for iOS 26, iPadOS 26, macOS Tahoe 26, watchOS 26, and tvOS 26. It is the most significant visual overhaul since iOS 7.

Liquid Glass is a dynamic material system that mimics real glass - featuring translucency, refraction, depth, and motion responsiveness. It continuously adapts to background content, light conditions, and user interactions. The material is translucent and behaves like glass in the real world, with its color informed by surrounding content and intelligently adapting between light and dark environments.

Apple's industrial design team physically fabricated glass of various opacities and lensing properties to closely match the interface properties to those of real glass.

### How It Differs From Generic Glassmorphism

| Aspect | Generic Glassmorphism | Apple Liquid Glass |
|---|---|---|
| Rendering | Static blur + simple transparency | Real-time physically accurate lensing and refraction |
| Adaptivity | Consistent visual properties regardless of context | Actively adapts tint, opacity, and contrast based on what's behind it |
| Light response | None | Specular highlights responding to device motion |
| Interaction | Passive | Scales, bounces, shimmers, touch-point illumination |
| Accessibility | Usually an afterthought | Built-in from the start (auto-adapts to Reduce Transparency, Increase Contrast, Reduce Motion) |
| Cross-platform | Manual per-platform | Unified system across all Apple platforms |
| Performance | Often GPU-heavy | GPU-accelerated with optimized `CABackdropLayer` consolidation |

### When to Use Glass vs Opaque vs Transparent

**USE Liquid Glass for (navigation layer):**
- Navigation bars
- Tab bars and toolbars
- Sidebars
- Floating action buttons
- Menus and popovers
- Controls that overlay main content
- Sheet backgrounds (partial height)

**NEVER use Liquid Glass for (content layer):**
- Scrollable content areas (tables, list items)
- Primary content views
- Media players/viewers
- Text-heavy reading areas

**NEVER stack Glass-on-Glass** - multiple Liquid Glass layers overwhelm users visually and break the material's illusion. The container handles shared sampling.

### Design Principles

**1. Hierarchy (Content-First)**
- Glass enhances rather than competes with content
- Uses adaptive opacity and intelligent layering
- Interface elements recede during content focus, expand when interaction is needed

**2. Dynamism (Responsive Interaction)**
- Every element feels responsive and alive
- Colors shift dynamically based on surroundings
- Motion is fluid with stretching, bouncing, and morphing responses to touch

**3. Consistency (Universal Language)**
- Unifies UI across macOS, iOS, iPadOS, and visionOS
- Shapes follow "concentric principles" with rounded, floating corners
- Controls reflect finger geometry (capsule shapes)

### Multi-Layer Material Architecture

Liquid Glass comprises several adaptive layers:

- **Highlights**: Follow geometry and device motion, creating dimensionality. Light sources shine on the material producing highlights that respond to geometry.
- **Shadows**: Increase opacity behind text (for legibility), decrease over plain backgrounds. Context-aware - the element knows what's behind it.
- **Illumination**: Creates glow feedback that radiates across elements during interaction.
- **Lensing**: Responsive light-bending effect along edges showing depth and separation between layers. Real-time light bending creates sense of physical depth.

### visionOS Influence

Liquid Glass is directly inspired by visionOS spatial computing. The depth, dimensionality, and glass materials from visionOS are now brought to all platforms. This prepares 2D interfaces for eventual spatial computing experiences while maintaining platform-specific qualities.

---

## B. SwiftUI Implementation - Complete API Reference

### Core Modifier: `.glassEffect()`

**Full Signature:**
```swift
func glassEffect<S: Shape>(
    _ glass: Glass = .regular,
    in shape: S = DefaultGlassEffectShape,
    isEnabled: Bool = true
) -> some View
```

**Availability:** iOS 26.0+, macOS 26.0+, watchOS 26.0+, tvOS 26.0+, visionOS 26.0+

### Glass Type Variants

The `Glass` struct provides three predefined instances:

**1. `.regular` - Standard (use for most UI)**
```swift
Text("Hello").padding().glassEffect()
// equivalent to:
Text("Hello").padding().glassEffect(.regular)
```
- Medium transparency, full adaptivity
- Intelligent opacity adjustment
- Maintains legibility automatically
- Use for: toolbars, buttons, navigation bars, tab bars

**2. `.clear` - High transparency**
```swift
Text("Overlay").padding().glassEffect(.clear)
```
- More transparent, shows more background
- Requires dimming layer, limited adaptivity
- Use ONLY when ALL of these are true:
  1. Element sits over media-rich content
  2. Content won't be negatively affected by dimming
  3. Content above glass is bold and bright enough

**3. `.identity` - No effect (for conditional disabling)**
```swift
.glassEffect(isEnabled ? .regular : .identity)
```
- Applies no visual change
- Use for conditional enable/disable without view hierarchy changes

### Glass Modifiers

**Tint - Color blending:**
```swift
.glassEffect(.regular.tint(.blue))
.glassEffect(.regular.tint(.purple.opacity(0.6)))
.glassEffect(.clear.tint(.red))
```
- Conveys semantic meaning (primary actions, states) - NOT decoration
- Use selectively, not on every element
- Vibrant color that adapts to content behind it

**Interactive - Enhanced responsiveness (iOS only):**
```swift
.glassEffect(.regular.interactive())
```
- Enables: scaling, bouncing, shimmering, touch-point illumination, gesture responsiveness
- Handles tap and drag gestures
- Use for buttons and tappable controls

**Chaining (order is irrelevant):**
```swift
.glassEffect(.regular.tint(.orange).interactive())
// same as:
.glassEffect(.regular.interactive().tint(.orange))
```

### Shape Parameter

Built-in shapes for glass:
```swift
.glassEffect(.regular, in: .capsule)           // default
.glassEffect(.regular, in: .circle)
.glassEffect(.regular, in: RoundedRectangle(cornerRadius: 16))
.glassEffect(.regular, in: .rect(cornerRadius: .containerConcentric))  // matches container corners
.glassEffect(.regular, in: .ellipse)
// Any custom Shape protocol implementation
```

**Container-Concentric Corners:**
```swift
.glassEffect(.regular, in: .rect(cornerRadius: .containerConcentric))
```
Automatically aligns corner radius with the container across different displays and window shapes.

### GlassEffectContainer

Groups multiple Liquid Glass shapes into a unified composition. Critical for performance and morphing.

**Why it matters:**
- Glass cannot sample other glass - container provides shared sampling region
- Each `CABackdropLayer` requires 3 offscreen textures. Container consolidates to 1 shared region.
- Enables morphing transitions between elements

```swift
GlassEffectContainer {
    HStack(spacing: 20) {
        Image(systemName: "pencil")
            .frame(width: 44, height: 44)
            .glassEffect()
        Image(systemName: "eraser")
            .frame(width: 44, height: 44)
            .glassEffect()
    }
}
```

**Spacing Parameter - morphing threshold:**
```swift
GlassEffectContainer(spacing: 40.0) {
    // Elements within 40pt of each other will visually blend during transitions
}
```

### Morphing Transitions with glassEffectID

Enables fluid morphing between glass elements when they appear/disappear.

**Requirements:**
1. Elements must be in the same `GlassEffectContainer`
2. Each view has `glassEffectID` with a shared `Namespace`
3. Conditional show/hide triggers the morph
4. Animation must be applied to state changes

**API:**
```swift
func glassEffectID<ID: Hashable>(
    _ id: ID,
    in namespace: Namespace.ID
) -> some View
```

**Complete morphing example:**
```swift
struct MorphingGlassView: View {
    @State private var isExpanded = false
    @Namespace private var namespace

    var body: some View {
        GlassEffectContainer(spacing: 30) {
            VStack(spacing: 30) {
                if isExpanded {
                    Button(action: {}) {
                        Image(systemName: "rotate.right")
                            .frame(width: 44, height: 44)
                    }
                    .buttonStyle(.glass)
                    .buttonBorderShape(.circle)
                    .glassEffectID("rotate", in: namespace)
                }

                HStack(spacing: 30) {
                    if isExpanded {
                        Button(action: {}) {
                            Image(systemName: "circle.lefthalf.filled")
                                .frame(width: 44, height: 44)
                        }
                        .buttonStyle(.glass)
                        .buttonBorderShape(.circle)
                        .glassEffectID("contrast", in: namespace)
                    }

                    Button {
                        withAnimation(.bouncy) {
                            isExpanded.toggle()
                        }
                    } label: {
                        Image(systemName: isExpanded ? "xmark" : "slider.horizontal.3")
                            .frame(width: 44, height: 44)
                    }
                    .buttonStyle(.glass)
                    .buttonBorderShape(.circle)
                    .glassEffectID("toggle", in: namespace)

                    if isExpanded {
                        Button(action: {}) {
                            Image(systemName: "flip.horizontal")
                                .frame(width: 44, height: 44)
                        }
                        .buttonStyle(.glass)
                        .buttonBorderShape(.circle)
                        .glassEffectID("flip", in: namespace)
                    }
                }

                if isExpanded {
                    Button(action: {}) {
                        Image(systemName: "crop")
                            .frame(width: 44, height: 44)
                    }
                    .buttonStyle(.glass)
                    .buttonBorderShape(.circle)
                    .glassEffectID("crop", in: namespace)
                }
            }
        }
    }
}
```

### Glass Button Style

SwiftUI provides a dedicated button style:
```swift
Button("Action") { }
    .buttonStyle(.glass)
    .buttonBorderShape(.circle)    // or .capsule
```

### Pre-iOS-26 Material System (Legacy, still valid for fallbacks)

Available since iOS 15. These create translucent blur effects but lack the dynamic lensing/refraction of Liquid Glass:

```swift
// From thinnest (most transparent) to thickest (most opaque):
.background(.ultraThinMaterial)     // lightest blur, most background shows through
.background(.thinMaterial)          // light blur
.background(.regularMaterial)       // standard blur (default)
.background(.thickMaterial)         // heavy blur
.background(.ultraThickMaterial)    // maximum blur, greatest opacity
.background(.bar)                   // system bar material
```

**With shapes:**
```swift
.background(
    .ultraThinMaterial,
    in: RoundedRectangle(cornerRadius: 16, style: .continuous)
)
```

**Characteristics:**
- Auto-support light and dark mode
- Not simple transparency - uses environment-defined mixing that matches glass
- Available on iOS 15+, macOS 12+

### Backward-Compatible Glass Wrapper

For apps supporting both iOS 26+ and earlier:

```swift
extension View {
    @ViewBuilder
    func glassedEffect(in shape: some Shape, interactive: Bool = false) -> some View {
        if #available(iOS 26.0, *) {
            self.glassEffect(
                interactive ? .regular.interactive() : .regular,
                in: shape
            )
        } else {
            self.background {
                shape.glassed()
            }
        }
    }
}

extension Shape {
    func glassed() -> some View {
        self
            .fill(.ultraThinMaterial)
            .fill(.linearGradient(
                colors: [
                    .primary.opacity(0.08),
                    .primary.opacity(0.05),
                    .primary.opacity(0.01),
                    .clear, .clear, .clear
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            ))
            .stroke(.primary.opacity(0.2), lineWidth: 0.7)
    }
}

// Usage:
Text("Hello")
    .padding()
    .glassedEffect(in: .capsule, interactive: true)
```

### UIKit Bridging

**UIKit Glass Effect (iOS 26+):**
```swift
let glassEffect = UIGlassEffect(glass: .regular, isInteractive: true)
let effectView = UIVisualEffectView(effect: glassEffect)
```

**UIKit Glass via UIViewRepresentable (for SwiftUI rotation issues):**
```swift
struct GlassUIViewRepresentable: UIViewRepresentable {
    func makeUIView(context: Context) -> UIVisualEffectView {
        let effect = UIGlassEffect()
        let view = UIVisualEffectView(effect: effect)
        view.cornerConfiguration = UIView.CornerConfiguration(
            corners: .allCorners,
            radius: .dynamic
        )
        return view
    }

    func updateUIView(_ uiView: UIVisualEffectView, context: Context) {}
}
```

**Legacy UIKit blur (pre-iOS 26):**
```swift
let blurEffect = UIBlurEffect(style: .systemUltraThinMaterial)
let effectView = UIVisualEffectView(effect: blurEffect)
```

### Toolbar and Navigation APIs

**Tab bar minimization:**
```swift
TabView {
    // tabs
}
.tabBarMinimizeBehavior(.onScrollDown)
```

**Toolbar with spacers:**
```swift
.toolbar {
    ToolbarItem { HomeLink() }
    ToolbarSpacer(.fixed)
    ToolbarItem { FavoriteButton() }
    ToolbarItem { ProfileButton() }
    ToolbarSpacer(.fixed)
    ToolbarItem { SearchToggle() }
}
```

**Scroll edge effects:**
```swift
.scrollEdgeEffectStyle(.automatic)  // default
.scrollEdgeEffectStyle(.sharp)
.scrollEdgeEffectStyle(.subtle)
```

**Toolbar tinting:**
```swift
Image(systemName: "heart.fill")
    .tint(.blue)  // overrides monochrome default
```

**Search patterns:**
```swift
// Global search in toolbar
NavigationStack { content }
    .searchable(text: $searchText)

// Dedicated search tab
TabView {
    Tab(role: .search) {
        NavigationStack { content }
    }
}
.searchable(text: $searchText)

// Minimize search toolbar
.searchToolbarBehaviour(.minimize)
```

**Concentric container shape:**
```swift
CustomControl()
    .background(.tint, in: .rect(corner: .containerConcentric()))
```

---

## C. Design Patterns - Complete Code Examples

### Pattern 1: Glass Floating Action Button

```swift
struct GlassFloatingButton: View {
    var body: some View {
        Button {
            // action
        } label: {
            Image(systemName: "plus")
                .font(.title2)
                .foregroundStyle(.white)
                .frame(width: 56, height: 56)
        }
        .glassEffect(.regular.tint(.blue).interactive(), in: .circle)
        .contentShape(.circle)
        .shadow(color: .black.opacity(0.15), radius: 8, y: 4)
    }
}
```

### Pattern 2: Glass Navigation Bar

```swift
struct GlassNavBar: View {
    let title: String

    var body: some View {
        HStack {
            Button(action: {}) {
                Image(systemName: "chevron.left")
                    .frame(width: 44, height: 44)
            }
            .glassEffect(.regular.interactive(), in: .circle)

            Spacer()

            Text(title)
                .font(.headline)
                .foregroundStyle(.white)

            Spacer()

            Button(action: {}) {
                Image(systemName: "ellipsis")
                    .frame(width: 44, height: 44)
            }
            .glassEffect(.regular.interactive(), in: .circle)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .glassEffect(.regular, in: .capsule)
    }
}
```

### Pattern 3: Glass Card

```swift
struct GlassCard: View {
    let title: String
    let subtitle: String
    let icon: String

    var body: some View {
        HStack(spacing: 16) {
            Image(systemName: icon)
                .font(.title)
                .foregroundStyle(.white)
                .frame(width: 50, height: 50)
                .glassEffect(.regular.tint(.blue), in: .circle)

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.headline)
                    .foregroundStyle(.white)
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.7))
            }

            Spacer()

            Image(systemName: "chevron.right")
                .foregroundStyle(.white.opacity(0.5))
        }
        .padding()
        .glassEffect(.regular, in: RoundedRectangle(cornerRadius: 20))
    }
}
```

### Pattern 4: Glass Tab Bar

```swift
struct GlassTabBar: View {
    @Binding var selectedTab: Int
    let tabs: [(icon: String, label: String)]

    var body: some View {
        GlassEffectContainer {
            HStack(spacing: 0) {
                ForEach(tabs.indices, id: \.self) { index in
                    Button {
                        withAnimation(.bouncy) {
                            selectedTab = index
                        }
                    } label: {
                        VStack(spacing: 4) {
                            Image(systemName: tabs[index].icon)
                                .font(.title3)
                            Text(tabs[index].label)
                                .font(.caption2)
                        }
                        .foregroundStyle(selectedTab == index ? .white : .white.opacity(0.5))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                    }
                    .glassEffect(
                        selectedTab == index
                            ? .regular.tint(.blue).interactive()
                            : .regular.interactive(),
                        in: .capsule
                    )
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
        }
        .glassEffect(.regular, in: .capsule)
    }
}
```

### Pattern 5: Glass Sheet/Modal

```swift
struct GlassSheet<Content: View>: View {
    @Binding var isPresented: Bool
    @ViewBuilder let content: Content

    var body: some View {
        if isPresented {
            ZStack(alignment: .bottom) {
                Color.black.opacity(0.3)
                    .ignoresSafeArea()
                    .onTapGesture { isPresented = false }

                VStack(spacing: 16) {
                    Capsule()
                        .fill(.white.opacity(0.3))
                        .frame(width: 40, height: 5)
                        .padding(.top, 8)

                    content
                        .padding()
                }
                .frame(maxWidth: .infinity)
                .glassEffect(.regular, in: RoundedRectangle(cornerRadius: 24))
                .padding()
            }
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}
```

### Pattern 6: Glass Sidebar

```swift
struct GlassSidebar: View {
    @Binding var selectedItem: String?
    let items: [(icon: String, label: String, id: String)]

    var body: some View {
        VStack(spacing: 4) {
            ForEach(items, id: \.id) { item in
                Button {
                    withAnimation(.bouncy) {
                        selectedItem = item.id
                    }
                } label: {
                    Label(item.label, systemImage: item.icon)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .foregroundStyle(
                            selectedItem == item.id ? .white : .white.opacity(0.7)
                        )
                }
                .glassEffect(
                    selectedItem == item.id
                        ? .regular.tint(.blue).interactive()
                        : .identity,
                    in: .capsule
                )
            }
        }
        .padding(12)
        .glassEffect(.regular, in: RoundedRectangle(cornerRadius: 20))
        .frame(width: 260)
    }
}
```

### Pattern 7: Glass Toolbar with Morphing Actions

```swift
struct GlassToolbar: View {
    @State private var showActions = false
    @Namespace private var namespace

    var body: some View {
        GlassEffectContainer(spacing: 30) {
            HStack(spacing: 16) {
                if showActions {
                    Button(action: {}) {
                        Image(systemName: "bold")
                            .frame(width: 36, height: 36)
                    }
                    .buttonStyle(.glass)
                    .buttonBorderShape(.circle)
                    .glassEffectID("bold", in: namespace)

                    Button(action: {}) {
                        Image(systemName: "italic")
                            .frame(width: 36, height: 36)
                    }
                    .buttonStyle(.glass)
                    .buttonBorderShape(.circle)
                    .glassEffectID("italic", in: namespace)
                }

                Button {
                    withAnimation(.bouncy) {
                        showActions.toggle()
                    }
                } label: {
                    Image(systemName: showActions ? "xmark" : "textformat")
                        .frame(width: 36, height: 36)
                }
                .buttonStyle(.glass)
                .buttonBorderShape(.circle)
                .glassEffectID("toggle", in: namespace)

                if showActions {
                    Button(action: {}) {
                        Image(systemName: "underline")
                            .frame(width: 36, height: 36)
                    }
                    .buttonStyle(.glass)
                    .buttonBorderShape(.circle)
                    .glassEffectID("underline", in: namespace)
                }
            }
        }
    }
}
```

### Pattern 8: Text and Icons on Glass

```swift
// Text automatically receives vibrant treatment on glass
Text("Glass Label")
    .font(.title)
    .bold()
    .foregroundStyle(.white)
    .padding()
    .glassEffect()

// Icons
Image(systemName: "heart.fill")
    .font(.largeTitle)
    .foregroundStyle(.white)
    .frame(width: 60, height: 60)
    .glassEffect(.regular.interactive())

// Labels
Label("Settings", systemImage: "gear")
    .labelStyle(.iconOnly)
    .padding()
    .glassEffect()

// Symbol variants (iOS 26 - use .none variant, not circle backgrounds)
Image(systemName: "checkmark")
    .symbolVariant(.none)  // clean for glass, no circle background
```

---

## D. Technical Implementation Details

### Performance Considerations

- Liquid Glass uses GPU acceleration but increases GPU demand
- Each `CABackdropLayer` requires 3 offscreen textures during rendering
- **Always use `GlassEffectContainer`** to consolidate multiple glass elements into one shared sampling region
- Reserve strongest effects for modals and primary navigation
- Scale down for lists and toolbars
- Profile your app and tweak blur radius and transparency for smoothest experience
- Older iPhones experience noticeable power drain with heavy glass usage

### Dark Mode vs Light Mode

- Material automatically adapts between light and dark environments
- Dark Mode naturally lessens Liquid Glass appearance by darkening UI backgrounds
- No additional code needed - the system handles adaptation
- Colors shift dynamically based on surroundings in both modes

### Accessibility (Auto-Handled)

No code changes required - the system automatically adapts:

- **Reduce Transparency**: Increases frosting for clarity, adds darker backgrounds
- **Increase Contrast**: Stark colors and borders for legibility
- **Reduce Motion**: Tones down animations and elastic effects
- **iOS 26.1+ Tinted Mode**: User-controlled opacity increase (Settings > Display & Brightness > Liquid Glass)
  - "Tinted" increases opacity and adds contrast
  - "Clear" provides more transparency

**Manual override (only when necessary):**
```swift
@Environment(\.accessibilityReduceTransparency) var reduceTransparency
@Environment(\.accessibilityReduceMotion) var reduceMotion

Text("Accessible")
    .glassEffect(reduceTransparency ? .identity : .regular)
```

### Shadow Behavior

Shadows are context-aware and adaptive:
- Increases shadow opacity when glass is over text (for separation/legibility)
- Decreases shadow opacity when glass is over solid light backgrounds
- No manual shadow configuration needed in most cases
- For custom overlays, use subtle shadows: `.shadow(color: .black.opacity(0.15), radius: 8, y: 4)`

### Border/Stroke Treatment

- Glass elements automatically have subtle edge definition
- For fallback (pre-iOS 26): `.stroke(.primary.opacity(0.2), lineWidth: 0.7)`
- On iOS 26: borders are built into the glass material rendering - avoid adding manual strokes

### Opacity Ranges

- For tint colors on glass: 0.6-0.9 for visible tinting
- For overlay text: use `.white` or `.primary` at full opacity - the glass handles contrast
- For secondary text on glass: `.white.opacity(0.7)`
- Custom opacity for glass tint: `.glassEffect(.regular.tint(.purple.opacity(0.8)))`

---

## E. Known Pitfalls and Workarounds

### 1. Rotation Animation Distortion
**Problem:** `rotationEffect(_:anchor:)` causes glass shape to morph unnaturally.
**Fix:** Use `UIViewRepresentable` with `UIVisualEffectView` + `UIGlassEffect` instead.

### 2. Menu Morphing Glitches (iOS 26.0-26.0.1)
**Problem:** Menu glass effects morph incorrectly.
**Fix:** Apply `.glassEffect(.regular, in: .capsule, options: .interactive)` to the outer Menu, not the label.

### 3. Menu Morphing Glitches (iOS 26.1)
**Problem:** Previous workaround breaks.
**Fix:** Create custom `ButtonStyle` and apply to Menu:
```swift
struct GlassButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .glassEffect(.regular, in: .capsule)
    }
}

Menu { /* items */ } label: {
    Image(systemName: "ellipsis")
}
.buttonStyle(GlassButtonStyle())
```
**Also:** Do NOT place Menu inside `GlassEffectContainer` on iOS 26.1.

### 4. Hit-Testing Failure
**Problem:** Only the label/icon is tappable, not the glass area.
**Fix:** Add `.contentShape(.capsule)` (or matching shape) to the button.

### 5. Glass-on-Glass Stacking
**Problem:** Visual hierarchy breaks with multiple glass layers.
**Fix:** Use `GlassEffectContainer` to group elements. Never nest glass effects.

### 6. Automatic Adoption
Simply recompiling with Xcode 26 brings the new design to standard controls automatically. No code changes needed for system components.

---

## F. Decision Tree - When to Use Which Effect

```
Is this a navigation/control element floating above content?
├── YES: Is it iOS 26+ only?
│   ├── YES: Use .glassEffect()
│   │   ├── Is it tappable? → .glassEffect(.regular.interactive())
│   │   ├── Does it convey status/meaning? → .glassEffect(.regular.tint(.color))
│   │   ├── Is it over media with bold foreground? → .glassEffect(.clear)
│   │   ├── Are there multiple glass elements nearby? → Wrap in GlassEffectContainer
│   │   └── Should they morph? → Add .glassEffectID() + @Namespace
│   └── NO: Need backward compatibility?
│       ├── YES: Use .glassedEffect(in:) wrapper (see backward compat section)
│       └── Use .background(.ultraThinMaterial) with gradient overlay
├── NO: Is this content area?
│   ├── YES: Do NOT use glass. Use opaque or standard backgrounds.
│   └── Is this a system component (TabView, NavigationStack)?
│       └── Recompile with Xcode 26 - automatic glass adoption
```

### Apple HIG Compliance Checklist

- [ ] Glass used ONLY on navigation/control layer, never on content
- [ ] No glass-on-glass stacking (use GlassEffectContainer instead)
- [ ] Interactive elements use `.interactive()` modifier
- [ ] Tint colors convey meaning, not just decoration
- [ ] Hit-testing area matches visual glass boundary (`.contentShape()`)
- [ ] Accessibility: system handles Reduce Transparency, Increase Contrast, Reduce Motion automatically
- [ ] Multiple adjacent glass elements wrapped in `GlassEffectContainer`
- [ ] Morphing transitions use `@Namespace` + `glassEffectID` + `withAnimation(.bouncy)`
- [ ] `.clear` variant only used over media-rich content with bold foreground
- [ ] Text on glass uses high-contrast foreground colors (.white, .primary)
- [ ] Fallback provided for pre-iOS 26 if needed
- [ ] Tab bars use `.tabBarMinimizeBehavior(.onScrollDown)` for content focus
- [ ] No manual shadows/borders on iOS 26 glass (material handles it)
- [ ] Concentric corner radii used where glass sits inside containers

---

## Sources

- [Apple Newsroom: Liquid Glass Announcement](https://www.apple.com/newsroom/2025/06/apple-introduces-a-delightful-and-elegant-new-software-design/)
- [Apple Developer: Applying Liquid Glass to Custom Views](https://developer.apple.com/documentation/SwiftUI/Applying-Liquid-Glass-to-custom-views)
- [Apple Developer: Glass API](https://developer.apple.com/documentation/swiftui/glass)
- [Apple Developer: glassEffect Modifier](https://developer.apple.com/documentation/swiftui/view/glasseffect(_:in:))
- [Apple Developer: glassBackgroundEffect](https://developer.apple.com/documentation/swiftui/view/glassbackgroundeffect(in:displaymode:))
- [WWDC 2025: Build a SwiftUI App with the New Design (Session 323)](https://developer.apple.com/videos/play/wwdc2025/323/)
- [WWDC 2025: Meet Liquid Glass (Session 219)](https://developer.apple.com/videos/play/wwdc2025/219/)
- [WWDC 2025: Get to Know the New Design System (Session 356)](https://developer.apple.com/videos/play/wwdc2025/356/)
- [Apple Developer: New Design Gallery](https://developer.apple.com/design/new-design-gallery/)
- [LiquidGlassReference (GitHub)](https://github.com/conorluddy/LiquidGlassReference)
- [Swift with Majid: Glassifying Custom Views](https://swiftwithmajid.com/2025/07/16/glassifying-custom-swiftui-views/)
- [Donny Wals: Designing Custom UI with Liquid Glass](https://www.donnywals.com/designing-custom-ui-with-liquid-glass-on-ios-26/)
- [SerialCoder: Transforming Glass Views with glassEffectID](https://serialcoder.dev/text-tutorials/swiftui/transforming-glass-views-with-the-glasseffectid-modifier-in-swiftui/)
- [Create with Swift: Exploring Liquid Glass](https://www.createwithswift.com/exploring-a-new-visual-language-liquid-glass/)
- [Create with Swift: Hierarchy, Harmony, Consistency](https://www.createwithswift.com/liquid-glass-redefining-design-through-hierarchy-harmony-and-consistency/)
- [Adopting Liquid Glass: Experiences and Pitfalls](https://juniperphoton.substack.com/p/adopting-liquid-glass-experiences)
- [EverydayUX: Glassmorphism vs Liquid Glass](https://www.everydayux.net/glassmorphism-apple-liquid-glass-interface-design/)
