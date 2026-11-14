#!/usr/bin/env bash
# Re-brand the existing GitHub releases so every page matches the current look.
set -euo pipefail
cd "$(dirname "$0")/.."

LOGO='<p align="center"><img src="https://raw.githubusercontent.com/pranrichh/spectre-mcp/main/assets/spectre-logo.png" width="132" alt="Spectre" /></p>'
TAGLINE='<p align="center"><em><strong>The fastest X/Twitter automation for AI agents.</strong></em></p>'

gh release edit v1.0.0 --title "Spectre MCP v1.0.0 — 104 tools, no browser, no API keys" --notes "${LOGO}

${TAGLINE}

## Spectre MCP v1.0.0

104 MCP tools for X/Twitter automation, talking straight to X's internal GraphQL and REST APIs. No browser. No API keys. No monthly fees.

### What's included

- **Account pool** — multiple accounts, automatic rotation on rate limits
- **Search** — full X operator syntax (\`from:\`, \`since:\`, \`#hashtag\`, \`filter:media\`, …)
- **Profiles** — user info, timelines, followers, following, likes, highlights, verified followers
- **Post & media** — post with media upload (cookie-based, no API keys)
- **Engagement** — like, retweet, bookmark (and undo all three)
- **Social** — follow, mute, block, remove follower, pin reply
- **DMs** — send, inbox, conversation, search (all/groups/people), mute, block
- **Lists** — full CRUD, members, subscribers, subscribe/unsubscribe
- **Bookmark folders** — full CRUD with timeline and search
- **Drafts & scheduled posts** — full CRUD
- **Communities** — join, leave, info, posts
- **Topics** — follow, unfollow, info
- **Community Notes** — read and rate
- **Account settings** — profile, avatar, banner
- **Notifications** — full timeline

### Install

\`\`\`bash
pipx install spectre-mcp
spectre add myaccount \"auth_token=xxx; ct0=yyy\"
\`\`\`

### MCP config

\`\`\`yaml
mcp_servers:
  spectre:
    command: uvx
    args: [spectre-mcp]
\`\`\`

---

<sub>Current release: [v2.0.0](https://github.com/pranrichh/spectre-mcp/releases/latest) — verified writes, live query ids, 111 tools.</sub>"

gh release edit v1.0.1 --title "v1.0.1 — parsing and config fixes" --notes "${LOGO}

${TAGLINE}

## v1.0.1 — parsing and config fixes

### Fixed

- **Tool count** — server docstring corrected from 105 to 104 tools
- **Config propagation** — \`get_user_tweets_and_replies\` and \`get_account_settings\` use the configured \`db_path\` and proxy instead of creating unconfigured scraper instances
- **Verified followers parsing** — \`_extract_user_info\` falls back to \`core.user_results.result.legacy\` for endpoints (BlueVerifiedFollowers and friends) that nest user data differently
- **Notification tweet parsing** — \`_extract_tweet_info\` handles notification-style responses where the author is nested in the core user chain

### Changed

- Version bumped to 1.0.1

---

<sub>Current release: [v2.0.0](https://github.com/pranrichh/spectre-mcp/releases/latest) — verified writes, live query ids, 111 tools.</sub>"

gh release edit v1.0.2 --title "v1.0.2 — fix server crash on last_used='0'" --notes "${LOGO}

${TAGLINE}

## v1.0.2 — fix server crash on last_used='0'

### Fixed

- \`set_active_account\` wrote \`last_used=0\`, which SQLite stored as the string \`'0'\` (truthy), so twscrape's \`datetime.fromisoformat('0')\` crashed the entire MCP server
- Added \`_sanitize_db()\`, which heals an already-corrupt pool on startup
- Root cause: twscrape checks \`if doc['last_used']\` — \`'0'\` is truthy but not a valid ISO datetime

### Changed

- Version bumped to 1.0.2

---

<sub>Current release: [v2.0.0](https://github.com/pranrichh/spectre-mcp/releases/latest) — verified writes, live query ids, 111 tools.</sub>"

gh release edit v1.0.3 --title "v1.0.3 — fix null usernames in verified followers" --notes "${LOGO}

${TAGLINE}

## v1.0.3 — fix null usernames in verified followers

### Fixed

- \`get_verified_followers\` returned null \`username\`/\`name\`: BlueVerifiedFollowers nests them in \`core{}\` directly, not in \`legacy{}\`
- The same fallback fixes \`get_followers_you_know\`, \`get_list_subscribers\`, and every tool that goes through \`_extract_user_info\` on standalone user-list endpoints

---

<sub>Current release: [v2.0.0](https://github.com/pranrichh/spectre-mcp/releases/latest) — verified writes, live query ids, 111 tools.</sub>"

echo "edited existing releases"
gh release list | head -6
