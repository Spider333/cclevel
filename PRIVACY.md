# Privacy

Short version: the card is offline. The leaderboard is opt-in, takes nine numbers and a list of badge codes, and needs no account. Being listed publicly is a second, separate choice. Two more extras are optional and send one thing each: a private group's invite code, and a GitHub login for the verified badge.

## What runs where

| You run | Network | What leaves your machine |
|---|---|---|
| the card (default) | none | nothing |
| `--preview` | none | nothing; it prints what a check-in would send |
| `--rank` | one download of the public numbers file | nothing about you is uploaded |
| `--join`, `--sync` | one request to the board | the payload below, and a random token |
| `--world on`, `--world off` | one request to the board | the token, and `{"on": true}` or `{"on": false}` |
| `--group-create`, `--group-join LINK` | one request to the board (two when joining from an invite before you are on the board: the first check-in, then the group) | the token and the group's invite code (and, to start a group, `"new": true`); never the address in a link |
| `--group`, `--group-leave` | one request to the board | the token |
| `--group-code` | none | nothing; it shows the saved invite link |
| opening an invite link in a browser | one request for the invite page | nothing about you; the code after `#` stays in your browser and the page makes no request with it |
| `--verify-github LOGIN`, first run | one request to the board | the token, the GitHub login and the SHA-256 hash of a code made on your machine |
| `--verify-github LOGIN`, second run | one request to the board | the token; the board then looks at that account's public gists and counts its public commits |
| `--unverify-github` | one request to the board | the token |
| `--leave` | one request to the board | the token, to delete your row |

The plugin ships no hooks and no background process. It never runs on its own. Inside Claude Code the plugin pre-approves only the offline commands. Network commands are left to Claude Code's normal permission rules, so with default settings each one asks first.

## The whole payload

```json
{
  "v": 1,
  "xp": 21480,
  "xp_days": 94,
  "stats": { "grind": 55, "appetite": 45, "arsenal": 50, "brains": 70, "autonomy": 25, "craft": 55 },
  "badges": ["first_hook", "first_skill", "streak_7"]
}
```

(Example numbers.) `--preview` prints your own, from the same code that sends it. The function is `payload()` in `skills/pet/scripts/cclevel.py`.

- `xp` is your total XP as your scanner counts it. The board works out your level from it and checks it against the growth cap. It never ranks on it and does not publish it.
- `xp_days` is the number of active days behind that XP. The board uses it to cap growth and does not publish it.
- `stats` are the six scores from your card, each 0 to 100 in steps of 5.

## What is never sent

Names of skills, projects, files or connectors. Prompts, code and paths. Your e-mail address, Claude account ID, machine ID or hostname. Usage counts such as tokens, sessions, prompts or the number of skills you have. Those counts could fingerprint a setup; the 0 to 100 stats are coarse on purpose.

## Identity

- The first `--join` creates a random 64-character token on your machine. Once the board has accepted the first check-in, the token is stored in `~/.claude/cclevel/identity.json`, readable only by you.
- The board stores the SHA-256 hash of that token, never the token.
- A token is only ever sent to the board it joined.
- There is no account, login or e-mail address. Your name on the board is generated from the hash, for example "Mossy Falcon 4821". Your own copy works out the same name locally.
- Nothing you write is sent, with two exceptions you choose. One is a private group's invite code: 32 random characters made by `--group-create`, sent only when you start or join a group. The board keeps its SHA-256 hash, never the code. The code is saved in `identity.json` so that `--group-code` can show the invite link again.
- An invite link is the board's address, `/join#`, and the code. Browsers never send the part after `#`, so opening the invite page tells the board nothing about the group, and the page sends the code nowhere. cclevel shows the link in full, also when Claude Code runs it, so you can share it from there. That means a group code can end up in your chat history: a link shown or pasted in a Claude Code conversation becomes part of that conversation and its local transcript, and one typed on a command line is in your shell history. A link only grants a seat in that group. `--group-join` without a link asks for it at a hidden prompt. cclevel uses only the code from a link and never talks to another board because of one. A group's name (for example "Stormy Lemur Crew") is worked out from the code on each machine and is never sent.
- The other is a GitHub login, sent only if you ask for the GitHub badge with `--verify-github`. No GitHub password, key or token ever leaves your machine: you prove the account is yours by publishing a public gist with a code, and the board sees only that code's hash until it finds the code in the gist.

## What the board stores

One row per creature, with exactly these columns (`server/schema.sql`):

| Column | What it holds |
|---|---|
| `id` | the SHA-256 hash of your token |
| `name` | the name generated from that hash |
| `xp`, `xp_days` | from the payload, after the growth cap |
| `base_days` | your `xp_days` when you joined: the starting point of the growth cap |
| `level`, `stage`, `class` | worked out from the payload |
| `grind`, `appetite`, `arsenal`, `brains`, `autonomy`, `craft` | the six stats from the payload |
| `badges` | the badge codes from the payload |
| `first_day`, `last_day` | UTC dates of your first and latest check-in, no time of day |
| `days_seen` | how many different days you have checked in |
| `season`, `season_xp` | the current month and the XP the board credited you in it |
| `witnessed_xp` | the XP the board credited you since joining: what ranks |
| `capped_days` | how many of those days were credited at the full 550: the sus rule |
| `world` | whether you have the world ranking on |
| `grp` | the SHA-256 hash of your private group's invite code, if you are in a group |
| `opt_day`, `opt_count` | the UTC date of your latest opt-in (world ranking on, group start or join, GitHub badge start), and how many that day |
| `gh_login`, `gh_id` | the GitHub login you asked to verify, and that account's number once verified |
| `gh_commits`, `gh_day` | how many public commits of that account carry Claude Code's co-author line, as GitHub counted them, and the UTC date of the count |
| `gh_code`, `gh_code_day` | the SHA-256 hash of the verification code, kept while you hold the badge so the same public code cannot verify anyone else, and the UTC date it was sent, cleared once verified. An unfinished verification, with the login it named, is cleared once its code expires after two days |

Besides that the board keeps:

- one counter per day of how many creatures joined (table `days`: `day`, a UTC date, and `joins`, a number), with nothing that identifies them;
- its stored files (table `snapshot`: `id`, the file's name, and `body`, its content): the two public files below, the row ids of listed creatures in list order (so one can be cut out at once), and the day's totals;
- GitHub verification codes that stopped being used, because a badge was removed, a creature left or a new start replaced an unfinished one (table `spent`: `hash`, the code's SHA-256, and `day`, a UTC date). They are kept for two days with no link to any creature, so a code copied from a public gist cannot be used again, and then deleted.

It does not store IP addresses or user agents, and the service writes no request logs. The code is in `server/`.

## What the board publishes

- **`/top.json`**, for the board page: the creatures on the world lists, and only those. For each: generated name, stage, class, level, the XP the board witnessed (all-time list) or credited this month (season list), Aura, and whether it is marked sus; for a creature whose owner chose the GitHub badge, also that GitHub login and its count of public commits co-signed by Claude. At most 1,000 per list.
- **`/board.json`**, for `--rank`: numbers only. The XP values of the listed rows in order, the XP needed for each "top X%" band once more than 1,000 are listed, how many are listed, and the totals.
- **Totals** count every creature with check-ins on two different days, listed or not: how many there are per level, stage, class, stat range (0-9, 10-19 and so on) and badge, and how many are marked sus. They are worked out once a day and published only from 100 creatures. They are counts, not records, but a count of one still says that one such creature exists.

A creature is on the world lists only while its owner keeps the world ranking on (it starts off) and after check-ins on two different days.

**Private groups are never published.** A group is up to 25 creatures that share an invite code. Only a creature in the group can read it, with its own token; the code alone shows nothing. Members see each other's generated name, level, XP since joining, season XP, six stats and sus mark, as soon as each one checks in. Being in a group does not put anyone on the world lists. A creature is in at most one group, and two creatures with the same generated name cannot be in the same group. Anyone who has the invite link or code can join until the group is full, so share it only with friends. Nobody can remove another member. If a code leaks, or someone fills the group or takes a seat to keep a friend out, start a new group and have your friends join that one.

**The GitHub badge is opt-in and public.** It links your creature to a GitHub account you prove is yours, and shows how many of that account's public commits carry Claude Code's co-author line (`noreply@anthropic.com`). It never changes a place, XP or the sus mark. The count has known limits: it sees public default branches only, a squash merge counts once, anyone can type the line by hand, and people who switched the line off are undercounted. The board recounts a few verified accounts at each rebuild, looking the account up by its number so a renamed account keeps its badge; a deleted account loses it. A code proves an account once: only the creature that sent it first can use it, only with a gist made on or after the day that creature started, and not again for two days after it was let go, so copying a code from someone's gist does not work. The badge opens after check-ins on two different days. `--unverify-github` removes every GitHub field and takes the login off the public file at once.

## What we cannot promise

- **The host sees addresses.** The board runs on Cloudflare. Like any host, Cloudflare processes IP addresses to deliver a request, under its own privacy policy.
- **The short address keeps sampled logs.** https://cclevel.com only sends you on to the board's own address. Because it is a domain on Cloudflare, Cloudflare keeps a sample of visits to it, with IP addresses, for about 31 days. Check-ins, invite links and the board itself use the `workers.dev` address and never go through it.
- **Group requests are counted per creature.** Starting, joining and reading a group are limited to about ten a minute per creature. The counter is keyed by your row's id, which the board already holds, and Cloudflare keeps it for up to 60 seconds.
- **Spam control uses your address for a minute.** A new creature's network address (for IPv6, its /64 prefix) is turned into a counter that Cloudflare holds for up to 60 seconds, so that one network can add roughly five new creatures a minute. The host's limiter is approximate, and people behind a shared address (an office, a campus) may have to wait a minute. The address is never written to the board's database.
- **Live debugging is possible.** The service stores no logs, but its operator could watch live traffic while fixing a fault, and that view includes request details such as IP addresses. Nothing from it is kept.
- **Backups age out, they do not vanish.** `--leave` removes your row from the live database and from both public files at once (a browser may show a copy for up to a minute). The database host keeps point-in-time backups for up to 30 days (7 on the free plan), after which the row is gone for good.
- **Timing is coarse, not hidden.** The public files are rebuilt every six hours. Someone watching them could tell within six hours when a listed creature's XP changed, and at once when one left or turned the world ranking off.
- **GitHub sees the board's lookups.** To check a gist and count commits, the board asks GitHub about your login with its own key. GitHub sees those requests coming from Cloudflare, not from you. Your login and gist are public on GitHub anyway.
- **Groups see check-ins as they happen.** Members of a private group see each other's numbers change as soon as each one checks in, so a member who keeps looking can tell roughly when a friend runs `--sync`. Joining and leaving are seen at once too.
- **Pseudonymous, not anonymous.** A row stays linked to the token on your machine. If you post your card or creature name publicly, people can match it to your row.

## Your controls

- `--world off` takes you off the world lists at once, and `--group-leave` takes you out of your group at once. Neither is ever limited. Turning the world ranking on, starting or joining a group and starting the GitHub badge share a limit of three a day. `--unverify-github` is never limited.
- `--leave` deletes your row and removes the local token. The token is kept if the board does not confirm, so you can retry.
- `--join` on a machine that is already on the board sends nothing.
- A creature that never comes back after its first day is deleted after 7 days.
- A row with no check-in for 45 days leaves the lists and the totals. After 180 days it is deleted.
- To run your own board, deploy `server/` and pass `--server <address>`.

## Operator and contact

The public board at https://go.cclevel.workers.dev (earlier address https://cclevel-board.cclevel.workers.dev, which only passes requests on to it and keeps nothing; short address https://cclevel.com) is run by Amagi Labs LLC, 30 N Gould St Ste R, Sheridan, WY 82801, USA.

Questions about your data: cclevel.grimace562@passmail.net.

We hold no e-mail address or account for any creature, so we can find a row only by its creature name. If you lost your token, your row deletes itself 180 days after its last check-in (7 days if it checked in only once).
