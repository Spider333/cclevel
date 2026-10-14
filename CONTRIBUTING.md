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

1. **The card stays offline.** Nothing above the `leaderboard` line in `cclevel.py` touches the network. Network commands run only when the user asks for them by flag.
2. **The payload is five fields.** `payload()` in `cclevel.py` is everything a check-in sends. Adding to it changes PRIVACY.md and the board's validation.
3. **No text from the board is ever printed.** The scanner prints only numbers and yes/no values from replies and spells names from its own word lists. Refusals are looked up by a one-word reason, never shown.
4. **Every stored column is documented.** A test fails if `server/schema.sql` has a column PRIVACY.md does not name.
5. **Pages load only their own files.** The CSP is `default-src 'self'`. No outside fonts, scripts or images, and board data is written with `textContent`, never as HTML.
6. **Word lists stay in sync.** Creature and group names come from the same lists in `cclevel.py`, `server/src/names.js` and `server/public/join.js`; a test checks them.
7. **No request logs, no IP addresses stored.** Keep `observability` off and the board on `workers.dev`.

## Pull requests

- Keep changes focused, and add or update tests for behaviour you change.
- Both test suites and plugin validation must pass.
- Write user-facing text in plain language. The names (Tokenmaxxer, Final Boss, gm x7) are internet on purpose; the explanations are not.

## Issues

Bugs and ideas are welcome. Please do not paste your `identity.json`, a group invite link or code, or anything from your prompts into an issue. To report a vulnerability, see [SECURITY.md](SECURITY.md) instead.
