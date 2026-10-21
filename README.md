# CC level

**Claude Code, gamified. How big is your Claude Code? Measure it. Compare it. Stay nameless.**

[![License: FSL-1.1-MIT](https://img.shields.io/badge/license-FSL--1.1--MIT-d97757)](LICENSE)
[![Board](https://img.shields.io/badge/board-live-d97757)](https://cclevel.com)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-d97757)](#install)
[![Privacy](https://img.shields.io/badge/sends-9_numbers-d97757)](PRIVACY.md)

CC level (`cclevel` for short: the plugin, the script and this repository) turns your Claude Code setup into a creature that grows. It reads your local Claude Code folder, scores how well-used and well-wired the setup is, and prints a card: a level, six stats, a mood and a short list of what to fix next. If you like, you can put the creature on a public board or compare it with friends in a private group. No account, no name, nine numbers.

```
    .-^-.     Lil Guy Shipper · Lv 23
   ( o o )    XP 21,480 · 1,560 to Lv 24 · today so far +310
    \ ~ /     Mood: Vibing · Health 72 · Aura 300
    /| |\     212 days old · 94 active days (61 estimated) · streak 4

  Grind     ###########---------  55
  Appetite  #########-----------  45
  Arsenal   ##########----------  50
  Brains    ##############------  70  Big Brain
  Autonomy  #####---------------  25
  Craft     ###########---------  55

  Needs
   1. 14 own skills unused for 90 days. Skill issue: archive them (Health +11)
   2. missing: a second model doing real work (2% of replies or more) (Brains +10)

  Badges: Hooked, Skill issue: solved, Not my job, gm x7, Loadout
```

<sub>An example card with invented numbers.</sub>

**The one rule:** what is used counts far more than what is installed. Installing a hundred skills takes a minute. Using thirty of them every week takes a real setup.

## Contents

- [Install](#install)
- [What you get](#what-you-get)
- [Play with friends](#play-with-friends)
- [Privacy at a glance](#privacy-at-a-glance)
- [Commands](#commands)
- [How the score works](#how-the-score-works)
- [The board](#the-board)
- [FAQ](#faq)
- [Contributing, security, licence](#contributing-security-licence)

## Install

Needs Claude Code. Works in any editor's terminal.

Inside Claude Code:

```
/plugin marketplace add Spider333/cclevel
/plugin install cclevel@cclevel
```

or from a shell:

```
claude plugin install cclevel --marketplace Spider333/cclevel
```

Then run `/pet`. If you already have a command called `pet`, use `/cclevel:pet`.

**Updating.** Claude Code does not update plugins from this marketplace by itself until you say so. Once, in Claude Code: `/plugin` → Marketplaces → cclevel → **Enable auto-update**, and new versions arrive on their own. To update now: `/plugin` → Marketplaces → cclevel → Update marketplace, then `/reload-plugins`; or from a shell, `claude plugin marketplace update cclevel` and `claude plugin update cclevel@cclevel`. Duels and the share card need 0.4.0 or newer.

Without the plugin system, copy `skills/pet/` into `~/.claude/skills/`, or run the script directly:

```
python3 skills/pet/scripts/cclevel.py
```

It needs Python 3.9 or newer and nothing else: standard library only, no dependencies.

## What you get

| Feature | What it is | Sends anything? |
|---|---|---|
| **The card** | Level, six stats, mood, badges and the top things to fix. | No. Fully offline. |
| **The world board** | Season and all-time lists at [cclevel.com](https://cclevel.com), ranked only on XP the board watched you earn. | Only if you join, and being listed is a second choice. |
| **Private groups** | Up to 25 friends compare in private, joined with one invite link. | Only if you start or join one. |
| **Duels** | Challenge one friend: seven days, most XP the board credits wins the ♛. | Only if you start or accept one. |
| **Share card** | Your card as a picture to post, drawn in your browser. | No. The numbers stay in the link after `#`. |
| **Wrapped** | Your year in review: XP, best day and month, longest streak, level gained, badges, and how your stats moved week by week. | No. Worked out from your own ledger. |
| **Training** | Five lessons per stat that tick themselves from your logs, and opt-in tips: a how-to under each Need and one Claude Code tip a day. | No. Fully offline. |
| **GitHub badge** | Prove a GitHub account is yours and show how many of its public commits Claude co-signed. | Only if you ask for it. |

In Claude Code you can just ask: `/pet`, `/pet join the leaderboard`, `/pet rank me`, `/pet start a group`, `/pet join <invite link>`, `/pet duel`, `/pet card`, `/pet learn`, `/pet tips on`.

## Play with friends

1. **Start a group:** `/pet start a group`. You get an invite link like `https://go.cclevel.workers.dev/join#3f9a…` and a generated group name, for example *Stormy Lemur Crew*.
2. **Send the link** to friends. Opening it shows the group's name and how to join. The code after `#` stays in the browser and is never sent to the board.
3. **Friends paste it** into Claude Code: `/pet join <link>`. One yes joins the board and the group together.
4. **Compare:** `/pet show my group`. Each member sees the others' generated names, levels, XP and stats. Nobody outside the group does.

Anyone with the link can join until the group is full, so share it with friends only. If it leaks, start a new group.

**Duel one friend:** `/pet duel` gives you a link like `https://go.cclevel.workers.dev/duel#7c1e…`. The first friend to accept it with `/pet duel <link>` takes the seat. The duel starts at 00:00 UTC the next day and runs seven days. XP counts at each check-in after your first one on or after the day it was accepted, so XP saved up from before never counts; whoever the board credits with more wins the ♛. A duel sits beside your group and is never published.

**Post your card:** `/pet card` prints a link to a page that draws your card as a picture to save or copy. The numbers sit after `#`, so the page sends nothing, and the picture shows no creature name.

## Privacy at a glance

| | |
|---|---|
| **The card** | Offline. Reads your Claude Code folder, writes only `~/.claude/cclevel/`. Nothing keeps running, no telemetry. The one hook does nothing unless you turn on auto check-in. |
| **Where data goes** | Only to the board at `https://go.cclevel.workers.dev`, run by Amagi Labs LLC, and only when you use an opt-in command: joining, check-ins (also the opt-in daily auto check-in), world ranking, groups, duels and the GitHub badge. The card, `--preview`, `--card` and `--wrapped` send nothing; `--rank` only downloads the public board files. |
| **A check-in sends** | Nine numbers and a list of badge codes (`v`, `xp`, `xp_days`, six stats, `badges`), plus a random key made on your machine. The board keeps only a hash of that key. |
| **Never sent** | Your name, e-mail, prompts, code, file paths, or the names of your projects, skills or connectors. |
| **The board stores** | No account, no e-mail, no IP address, and no request logs. A creature is its score, a generated name, the key's hash and a few dates and counters. |
| **You control** | `--world off` (off the lists at once), `--group-leave`, `--duel-leave`, `--leave` (deletes your row). A row with no check-in for 180 days deletes itself. |

The word is **pseudonymous, not anonymous**: a row stays linked to the key on your machine. [PRIVACY.md](PRIVACY.md) lists every field, every request and what we cannot promise.

## Commands

In Claude Code, `/pet` runs these for you. Network commands ask first, and so does Claude Code's permission prompt.

| Command | What it does |
|---|---|
| `cclevel.py` | The card. Offline. |
| `--json` | The numbers behind the card. |
| `--no-save` | Score without touching the ledger. |
| `--preview` | Print exactly what a check-in would send. Sends and saves nothing. |
| `--rank` | Your place on the world lists, the XP to pass the next place, and how rare your badges are, worked out locally from the public files. Uploads nothing. |
| `--join` | Join the board. Shows the payload and asks first. If already joined, it sends nothing. |
| `--sync` | Check in. One accepted check-in per day. |
| `--auto on` / `--auto off` | Check in by itself once a day, in the background, when a Claude Code session starts (on asks first). Off by default; sends nothing when you switch it. |
| `--world on` / `--world off` | Be ranked on the public world lists, or not. Off at joining; on asks first; off works at once. |
| `--group-create` | Start a private group (asks first) and print its invite link. |
| `--group-join LINK` | Join a friend's group with its invite link or code (asks first). If you are not on the board yet, one yes joins the board and the group. Without LINK, type it at a hidden prompt. |
| `--group` | Show your group: names, levels, XP since joining, season XP, this week's XP with the ♛ weekly crown, Aura, sus marks. |
| `--group-leave` | Leave your group at once. |
| `--group-code` | Show your group's invite link again. Sends nothing. |
| `--duel-create` | Challenge a friend to a seven-day duel (asks first) and print its invite link. |
| `--duel-join LINK` | Accept a friend's duel with its invite link or code (asks first). If you are not on the board yet, one yes joins the board and accepts. Without LINK, type it at a hidden prompt. |
| `--duel` | Show your duel: the day, both creatures' duel XP, who leads, and the ♛ once it is over. |
| `--duel-leave` | Leave your duel at once. |
| `--duel-code` | Show your duel's invite link again. Sends nothing. |
| `--card` | Print a link to your card as a picture, to save and post. Sends nothing. |
| `--wrapped [YEAR]` | Your year in review, this year so far by default. Sends nothing. |
| `--learn` | The training path: five lessons per stat, ticked by what your logs show, with how to do the next one. Offline. |
| `--tips on` / `--tips off` | A how-to under each Need and one Claude Code tip a day on the card. Off by default; kept on this machine, sends nothing. |
| `--verify-github LOGIN` | Opt-in GitHub badge. First run: asks, then gives you a code to put in a public gist. Second run: the board checks the gist. |
| `--unverify-github` | Remove the GitHub badge and every GitHub detail at once. |
| `--leave` | Delete your row and the local token. |
| `--server URL` | Use a self-hosted board. A creature only talks to the board it joined. |
| `--claude-dir DIR` | Scan another folder. |

## How the score works

- **XP and level.** XP is earned per finished UTC day, at most 550 a day, so a level cannot be bought with one big burn. Level is `floor(sqrt(xp / 40))`, from 1 to 99.
- **Six stats, 0 to 100:**

  | Stat | What it measures |
  |---|---|
  | Grind | Days used out of the last 30, and streaks |
  | Appetite | Weighted tokens over the last 30 days |
  | Arsenal | Skills, connectors and subagent types actually used |
  | Brains | Ten checks of wiring that is in use |
  | Autonomy | Sessions that ran without you, and scheduled jobs that call Claude |
  | Craft | Edits, commits, pull requests and published pages |

  Together they add up to **Aura**.
- **Stage** follows level: Egg → Hatchling → Lil Guy → Big Guy → Gigachad → GOAT. **Class** comes from your strongest working stat: Shipper, AFK Farmer, Loot Goblin, Tokenmaxxer, Perfectly Balanced or Noob.
- **Health and mood** drop for unused skills, connectors waiting for sign-in, a heavy start-up context and failing tool calls. The Needs list tells you what to fix.

The full rules, every name and the known limits are in [docs/scoring.md](docs/scoring.md).

## The board

- **It ranks only what it saw.** After joining, a creature gains at most 550 XP per active day on the board, without badge XP. Its history and reported level never rank, so editing your local files does not get you to the top.
- **Two lists:** Season (this month) and All-time, top 1,000 each. Below that, "top X%" bands, and `--rank` works out your place on your own machine.
- **Listing is a choice.** Joining does not list you; `--world on` does, from your second day of check-ins.
- **Sus** marks a creature whose witnessed days nearly all hit the daily maximum. It changes nothing else.
- **Totals** for analysis (creatures per level, class, stat range and badge) appear once 100 creatures are counted.
- **Four reasons to come back:**
  - **Weekly crown:** ♛ marks the group member with the most XP this week. Weeks start Monday, 00:00 UTC.
  - **Rival:** `--rank` says how much XP you need to pass the next place, and names that creature when it is in the top 1,000.
  - **Badge rarity:** `--rank` and the page show how rare each badge is.
  - **Class wars:** this season's XP added up per class, on the page.

  Badge rarity and class wars start at 100 creatures, like the totals.

The board is a small Cloudflare Worker with a D1 database and static pages, in `server/`. It runs with request logging switched off. To run your own, see [docs/self-hosting.md](docs/self-hosting.md).

## FAQ

**Is it anonymous?**
Almost. It's pseudonymous: no account, no name, no e-mail, and the board never stores your IP address. Your creature is a made-up name tied to a random key on your machine. The catch: if you post your card or creature name publicly, or turn on the GitHub badge, people can match it to you.

**Can people cheat?**
On their own card, yes. It is self-reported, for fun, and not a credential. The board limits what cheating buys: it ranks only XP it watched you earn, at most 550 a day, and marks suspicious patterns as sus.

**Does it slow down Claude Code or run in the background?**
No. Nothing keeps running: it works when you call `/pet`. The one exception is opt-in: with auto check-in on (`/pet check in automatically`), a hook starts one quick check-in a day when Claude Code starts, without holding it up. While it is off, that hook sends nothing.

**Does it read my prompts?**
It reads your Claude Code folder to count things (days, tokens, tools used, prompt timestamps). Nothing from your prompts, code or file names is printed, stored or sent.

**Why are invite links shown in full inside Claude Code?**
So you can copy one. A link shown or pasted in a conversation becomes part of that chat's history. A link only grants a seat in that group, and you can always start a new group.

**How do I get off the board?**
`/pet leave the board`, or `--leave`. Your row is deleted at once; the database host's backups age out after up to 30 days (7 on the free plan).

## Contributing, security, licence

- **Contributing:** see [CONTRIBUTING.md](CONTRIBUTING.md). Tests: `python3 -m unittest discover -s tests` and `cd server && npm test`.
- **Security:** please report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md).
- **Licence:** FSL-1.1-MIT (Functional Source License). Read it, run it, change it, use it at work. What you may not do is use it in a commercial product or service that competes with CC level. Each version becomes MIT two years after it is released. See [LICENSE](LICENSE).
- **Operator:** the public board is run by Amagi Labs LLC, Sheridan, Wyoming, USA. Questions about your data: cclevel.grimace562@passmail.net.

```
repo layout
skills/pet/            the Claude Code skill (/pet) and the scanner, cclevel.py
server/                the board: Cloudflare Worker (src/), static pages (public/), schema, tests
tests/                 scanner tests
.claude-plugin/        plugin and marketplace manifests
docs/                  scoring rules and self-hosting
PRIVACY.md             every field, every request, every limit
```
