# klava-shared

Ship-with-the-repo defaults that setup.sh copies into per-user config paths
on first run.

## gog-credentials.json

Desktop OAuth client for Google services (Gmail, Tasks, Calendar, Drive,
Docs, etc.), consumed by the `gog` CLI. Copied by setup.sh to
`~/Library/Application Support/gogcli/credentials.json` if the user
doesn't already have one.

The `client_id` and `client_secret` here are **not real secrets** in the
security-critical sense — Google classifies Desktop OAuth clients as
"public clients" whose credentials are embedded in distributed binaries.
End users authorize with their own Google account; this file only
identifies *which OAuth application* they're granting access to (the one
registered by the Klava project).

Users who want their own OAuth application (to isolate API quota, for
example) can drop their own credentials.json into the same path and
setup.sh will not overwrite it. The wizard's Google step also exposes a
"Bring your own credentials" panel for pasting in a replacement without
touching the filesystem.
