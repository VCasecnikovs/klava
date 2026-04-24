---
user_invocable: true
name: peekaboo
description: macOS GUI automation with screenshot annotation. Use when automating UI interactions, taking annotated screenshots, or controlling Mac apps
---

# Peekaboo - macOS GUI Automation

Use this skill for desktop GUI automation - clicking buttons, typing text, taking screenshots with element annotations.

## When to Use

- User asks to interact with desktop apps (not browser)
- Need to click buttons, fill forms in native macOS apps
- Take annotated screenshots showing clickable elements
- Automate repetitive GUI tasks

## Prerequisites

```bash
brew install steipete/tap/peekaboo
```

Then grant permissions in System Settings:
- Privacy & Security → Screen Recording → Enable for Terminal/iTerm
- Privacy & Security → Accessibility → Enable for Terminal/iTerm

## Commands

### Take Screenshot with Element Annotations
```bash
# Annotated screenshot with element IDs (e1, e2, e3...)
peekaboo see --annotate

# Save to specific file
peekaboo see --annotate --output /tmp/screen.png

# Capture specific app only
peekaboo see --annotate --app "Safari"
```

### Click Elements
```bash
# Click by element ID from annotated screenshot
peekaboo click --on e1

# Click by coordinates
peekaboo click --at 100,200

# Double-click
peekaboo click --on e1 --double
```

### Type Text
```bash
# Type text at current cursor
peekaboo type "Hello World"

# Type with enter at end
peekaboo type "search query" --enter
```

### Keyboard Shortcuts
```bash
peekaboo hotkey cmd+shift+4      # Screenshot shortcut
peekaboo hotkey cmd+c            # Copy
peekaboo hotkey cmd+v            # Paste
peekaboo hotkey cmd+tab          # App switcher
```

### Window Management
```bash
# List all windows
peekaboo window list

# Focus specific app
peekaboo window focus "Safari"
peekaboo window focus "Finder"

# Get window info
peekaboo window info "Safari"
```

## Workflow Example

1. Take annotated screenshot to see available elements
2. Identify the element ID you need to click
3. Click the element
4. Type text if needed
5. Take another screenshot to verify

```bash
# Example: Search in Spotlight
peekaboo hotkey cmd+space        # Open Spotlight
sleep 0.5
peekaboo type "Calculator"       # Type search
sleep 0.5
peekaboo hotkey return           # Press Enter
```

## Tips

- Always take `see --annotate` first to identify elements
- Element IDs (e1, e2...) are assigned top-to-bottom, left-to-right
- Some elements may not be clickable (decorative)
- Use `--app` flag to focus on specific application
- Add `sleep` between commands for UI to settle
