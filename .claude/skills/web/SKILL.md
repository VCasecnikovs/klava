---
name: web
description: Open relevant web pages based on current context. Use when user says open website, link, or wants to navigate to a web interface
user_invocable: true
---

# Web - Open Relevant Pages

Open the most relevant web page based on what we're currently doing. Use proactively after actions that have a web counterpart.

## Proactive Triggers

Open automatically (without being asked) after:

- **git push** -> open the repo or PR on GitHub
- **gh pr create** -> open the new PR URL
- **gh repo create** -> open the new repo
- **Deploy / push to main** -> open the deployed site
- **npm publish** -> open the package on npmjs.com
- **Created a GitHub issue** -> open the issue URL
- **Editing a website** -> open localhost or production URL

## Manual Usage

`/web` - open the most relevant page based on conversation context
`/web <url>` - open a specific URL

## Behavior

1. Determine the relevant URL from context:
   - Git remote -> GitHub repo URL
   - Recent `gh` command output -> PR/issue URL
   - Project with deploy URL -> production site
   - Localhost dev server running -> localhost URL
2. Open with:
   ```bash
   open "URL"
   ```
3. Confirm briefly what was opened

## Known Projects

Configure your project URLs in MEMORY.md or config.yaml.

## Rules

- Be proactive: if an action has an obvious web counterpart, open it
- Don't open pages for minor actions (small commits without push, local edits)
- If multiple URLs are relevant, pick the most specific one (PR > repo)
- For git push: open the repo, not just github.com
