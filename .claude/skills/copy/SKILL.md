---
name: copy
description: Copy text to macOS clipboard using pbcopy. Use when user says copy, clipboard, or скопируй
user_invocable: true
---

# Copy to Clipboard

Copy the most recent relevant text from the conversation to the macOS clipboard.

## Behavior

1. Look at the conversation context to identify the text the user wants copied
2. Common cases:
   - User just asked to draft a message - copy the drafted message
   - User says "скопируй" / "в буфер" / "copy" after a response - copy the key output
   - User specifies what to copy - copy exactly that
3. Use `pbcopy` to place the text in clipboard:
   ```bash
   printf '%s' "TEXT_HERE" | pbcopy
   ```
4. Confirm briefly: "Скопировано в буфер"

## Rules

- Copy ONLY the useful content, not meta-commentary or explanations
- For messages/drafts: copy just the message text, no headers like "Draft:" or formatting artifacts
- Use `printf '%s'` instead of `echo` to avoid trailing newline issues
- For multiline text, use heredoc:
  ```bash
  pbcopy <<'EOF'
  line 1
  line 2
  EOF
  ```
- Keep confirmation minimal - one line
