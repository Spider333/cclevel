# Contributing

Thanks for helping. cclevel is small on purpose; the most useful contributions are bug reports with a clear repro, scoring ideas backed by real setups, and fixes that keep the privacy promises intact.

## Setup

```
git clone https://github.com/Spider333/cclevel
cd cclevel
python3 skills/pet/scripts/cclevel.py        # the card, offline
python3 -m unittest discover -s tests        # scanner tests
cd server && npm install && npm test         # board tests
cd .. && claude plugin validate . --strict   # plugin manifests
```

The scanner needs Python 3.9 or newer and uses the standard library only. The board needs Node.js; see [docs/self-hosting.md](docs/self-hosting.md) to run it locally.

## House rules

These are the promises users rely on. A change that breaks one needs a very good reason and an update to [PRIVACY.md](PRIVACY.md) in the same pull request.

1. **The card stays offline.** Nothing above the `leaderboard` line in `cclevel.py` touches the network. Network commands run only when the user asks for them by flag. The one exception is the session-start hook: it joins the board once on a machine that has not opted out, then checks in once a day while auto check-in is on, followed by one read of the user's own group for the menu bar panel (and, with the panel installed and a group, the same read at later session starts, at most every 15 minutes). Opting out stays one command (`--leave`), works before or after joining, and stops the hook for good.
2. **The payload is five fields.** `payload()` in `cclevel.py` is everything a check-in sends. Adding to it changes PRIVACY.md and the board's validation.
3. **No text from the board is ever printed.** The scanner prints only numbers and yes/no values from replies and spells names from its own word lists. Refusals are looked up by a one-word reason, never shown.
4. **Every stored column is documented.** A test fails if `server/schema.sql` has a column PRIVACY.md does not name.
5. **Pages load only their own files.** The CSP is `default-src 'self'`. No outside fonts, scripts or images, and board data is written with `textContent`, never as HTML.
6. **Word lists stay in sync.** Creature and group names come from the same lists in `cclevel.py`, `server/src/names.js` and `server/public/join.js`; a test checks them.
7. **No request logs, no IP addresses stored.** Keep `observability` off and check-ins on the board's `workers.dev` address. `cclevel.com` serves the website only: a custom domain keeps Cloudflare's sampled visit logs with IP addresses, so the Worker refuses `/api/*` there and the scanner's API calls never use it. Links people open (invites, duels, cards) may point at cclevel.com.
8. **Fixes only after a yes, backup first.** `/pet fix` is the only command that changes files outside `~/.claude/cclevel/`. It plans first and writes nothing; it changes anything only with the plan's id and `--yes`, after a backup and a manifest in `~/.claude/cclevel/fixes/`. Undo never deletes. It never removes a user's config, never touches an MCP server, and never runs from the hook, the band or the panel.

## Pull requests

- Keep changes focused, and add or update tests for behaviour you change.
- Both test suites and plugin validation must pass.
- Write user-facing text in plain language. The names (Tokenmaxxer, GOAT, gm x7) are internet on purpose; the explanations are not.

## Issues

Bugs and ideas are welcome. Please do not paste your `identity.json`, a group invite link or code, or anything from your prompts into an issue. To report a vulnerability, see [SECURITY.md](SECURITY.md) instead.
