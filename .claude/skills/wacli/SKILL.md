---
name: wacli
description: WhatsApp CLI - read messages, search, send texts and files, manage contacts and groups.
user_invocable: true
---

# wacli - WhatsApp CLI

WhatsApp CLI (v0.2.0) by steipete. Local SQLite DB at `~/.wacli/`, uses whatsmeow (Go).

**Customization:** If `PERSONAL.md` exists in this skill directory, read it for your contact-to-JID mapping table.

## Auth & Sync

```bash
wacli auth status                      # check auth
wacli sync --once                      # sync until idle, then exit
wacli sync --follow                    # keep syncing (default)
wacli sync --once --download-media     # sync + download media
wacli sync --refresh-contacts          # refresh contacts from session
wacli sync --refresh-groups            # refresh group list
wacli doctor                           # full diagnostics
```

---

## Chats

```bash
# List chats (sorted by last activity)
wacli chats list --json --limit 20

# Search chats by name
wacli chats list --query "Мама" --json

# Show specific chat
wacli chats show JID --json
```

---

## Messages

### List messages

```bash
# Last 20 messages in chat
wacli messages list --chat "<phone>@s.whatsapp.net" --limit 20 --json

# Messages after date
wacli messages list --chat "JID" --after "2026-03-01" --limit 50 --json

# Messages in date range
wacli messages list --chat "JID" --after "2026-02-01" --before "2026-03-01" --json

# Group messages
wacli messages list --chat "120363123456789@g.us" --limit 30 --json
```

### Search messages (FTS5)

```bash
# Full-text search across all chats
wacli messages search "keyword" --json

# Search in specific chat
wacli messages search "keyword" --chat "JID" --json

# Search from specific sender
wacli messages search "keyword" --from "<phone>@s.whatsapp.net" --json

# Filter by media type
wacli messages search "keyword" --type image --json    # image|video|audio|document

# Search with date filter
wacli messages search "keyword" --after "2026-01-01" --limit 100 --json
```

### Show / Context

```bash
wacli messages show MESSAGE_ID --json
wacli messages context MESSAGE_ID --json    # surrounding messages
```

---

## Send

```bash
# Text message
wacli send text --to "<phone>" --message "Привет!"

# Text to group
wacli send text --to "120363123456789@g.us" --message "Привет группе!"

# Send file (image/video/audio/document)
wacli send file --to "<phone>" --file "/path/to/photo.jpg"

# Send file with caption
wacli send file --to "<phone>" --file "/path/to/doc.pdf" --caption "Документ"

# Custom filename
wacli send file --to "<phone>" --file "/tmp/report.pdf" --filename "Q1 Report.pdf"
```

### Address format

- DM: phone number without `+` (e.g. `<phone>`)
- Group: full JID (e.g. `120363123456789@g.us`)

---

## Contacts

```bash
# Search contacts
wacli contacts search "Name" --json

# Show contact details
wacli contacts show JID --json

# Refresh contacts from WhatsApp
wacli contacts refresh

# Set alias for contact
wacli contacts alias set --jid "<phone>@s.whatsapp.net" --alias "Мама"

# Remove alias
wacli contacts alias rm --jid "<phone>@s.whatsapp.net"

# Tag contacts
wacli contacts tags add --jid "JID" --tag "vip"
wacli contacts tags rm --jid "JID" --tag "vip"
```

---

## Groups

```bash
# List groups
wacli groups list --json

# Group info (live fetch)
wacli groups info GROUP_JID --json

# Refresh group list
wacli groups refresh

# Participants
wacli groups participants list GROUP_JID --json

# Invite link
wacli groups invite get GROUP_JID

# Join by invite
wacli groups join INVITE_CODE

# Leave group
wacli groups leave GROUP_JID

# Rename group
wacli groups rename GROUP_JID "New Name"
```

---

## Media

```bash
# Download media from message
wacli media download MESSAGE_ID
```

---

## History Backfill

```bash
# Request older messages from primary device
wacli history backfill --chat "JID"
```

---

## JSON Output

All commands support `--json` for structured output.

```bash
wacli chats list --json | jq '.[].Name'
wacli messages search "deal" --json | jq '.messages[] | {sender: .SenderJID, text: .Text, time: .Timestamp}'
```

## Key JIDs

See PERSONAL.md for the contact-to-JID mapping table. Example format:

| Contact | JID |
|---------|-----|
| Self | `<phone>@s.whatsapp.net` |
| Contact Name | `<phone>@s.whatsapp.net` |

## Data

- Store: `~/.wacli/`
- Database: SQLite with FTS5 full-text search
- Replaces: WhatsApp MCP + Go Bridge
