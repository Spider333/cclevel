# Security

## Reporting a vulnerability

Please report it privately by e-mail to **cclevel.grimace562@passmail.net**, not in a public issue. Include what you found, how to reproduce it, and what an attacker could do with it.

We aim to reply within a week. Please give us a reasonable time to fix the problem before you disclose it.

## What we especially want to hear about

- A way to read or change another creature's row, or a private group you are not in.
- A token, invite code or GitHub verification code leaking: to the board in clear, into logs, or to a third party.
- The scanner sending more than [PRIVACY.md](PRIVACY.md) says, or printing text that came from the board.
- Script injection or off-site loading on the board's pages.
- A way around the rate limits, the daily cap or the growth cap that the docs do not already admit.

## Known limits (not vulnerabilities)

These are documented in [PRIVACY.md](PRIVACY.md) and [docs/scoring.md](docs/scoring.md):

- Scores are self-reported. Anyone can edit their own local files; the board ranks only XP it witnessed, at most 550 a day.
- Anyone holding a group's invite link can join that group until it is full.
- A link shown or pasted in a Claude Code conversation becomes part of that conversation's history.
- The host (Cloudflare) sees IP addresses to deliver requests.
