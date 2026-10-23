# Running your own board

The board in `server/` is a small Cloudflare Worker with a D1 database and static pages. It fits Cloudflare's free plan. A creature only ever talks to the board it joined, so a self-hosted board is fully separate from the public one.

## What it does

- **Ranks only what it saw.** After joining, a creature gains at most 550 XP per active day on the board, without badge XP. That is its witnessed XP, and it is the only thing either list is sorted by. Whatever a creature reported when it joined (its history, its level) never ranks. On its first return it may be credited one extra day, once, to allow for time zones.
- **Two lists.** Season is the XP credited this month; All-time is everything since joining. Each lists the top 1,000. Below that the board publishes the XP needed for each "top X%" band, and `--rank` works out your place on your machine.
- **Listed by default, off in one command.** The scanner turns the world ranking on when it joins (a separate `PUT /api/world` right after the first check-in; the board itself keeps new rows off the lists until then). A creature shows once it has check-ins on two different UTC days. `--world off` and `--leave` take you off both lists in the same request.
- **Private groups.** Up to 25 friends share an invite link holding a code made on one of their machines; the board keeps only the code's hash. The invite page (`/join`) reads the code from the part after `#`, which browsers never send, and shows the group's generated name and how to join. Only members can read a group, there is no web view of its members, and being in one does not list you anywhere. One group per creature.
- **GitHub badge.** Optional. You prove a GitHub account is yours with a public gist (no password or key leaves your machine); the board then shows the login and how many of its public commits carry Claude Code's co-author line. It never changes a place or XP. Without a GitHub key on the board, it answers "not available".
- **Sus** marks a creature with at least 14 witnessed days of which 80% or more were credited at the full 550. It changes nothing else, and a script that claims a little less is not caught.
- **Totals** (creatures per level, stage, class, stat range and badge, and the sus count) count every creature with check-ins on two days, listed or not, and appear only from 100 creatures.
- **Limits.** One network can add roughly two new creatures a minute (the host's limiter is approximate), and the board takes at most 5,000 new creatures a day. Turning the world ranking on and starting or joining a group share a limit of three a day per creature; turning off and leaving are never limited. Group requests are limited to ten a minute per creature.
- The service keeps no request logs and stores no IP address. See [PRIVACY.md](../PRIVACY.md) for what that does and does not cover.

## Deploy

You need a Cloudflare account and Node.js.

```
cd server
npm install
npx wrangler d1 create cclevel-board          # copy the database_id it prints into wrangler.jsonc
npx wrangler d1 execute cclevel-board --remote --file=schema.sql
npx wrangler deploy
```

Optional, for the GitHub badge: a GitHub token with **no** permissions, stored as a secret.

```
npx wrangler secret put GITHUB_TOKEN
```

Then point the scanner at your board: `--server https://<your-worker>.<your-subdomain>.workers.dev`, or set `CCLEVEL_SERVER`. If you run a public board for others, edit the operator and contact in your copy of `PRIVACY.md` and on the page footer.

Keep these settings as they are in `wrangler.jsonc`:

- `observability.enabled: false`. The Worker keeps no request logs.
- `workers_dev: true`, with no custom route. A custom domain adds Cloudflare's sampled request logs with IP addresses. If you add one, say so in your privacy notice.
- The three rate limiters (`NEW_ROWS`, `PER_CREATURE`, `GITHUB_CALLS`). The Worker refuses those requests if a binding is missing.

## Run it locally

```
cd server
npm install
npm test
npx wrangler d1 execute cclevel-board --local --file=schema.sql
npx wrangler dev --test-scheduled
```

The public files are rebuilt by a timer (every hour) that does not fire in local development. Open `http://localhost:8787/cdn-cgi/handler/scheduled` to rebuild them by hand.

A note for self-hosters: `wrangler dev` is a development tool and keeps its own local traces of each request (method, address of the page, status, time) and its own copy of the limiter's counters under `.wrangler/`. The deployed service does neither, because `wrangler.jsonc` switches request logging off. Keep it that way.
