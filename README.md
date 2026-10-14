# cclevel

Your Claude Code setup as a creature that grows. cclevel reads your local Claude Code folder, scores how old, well-used and well-wired the setup is, and prints a card: a level, six stats, a mood and a short list of what to fix next.

Status: early. The scanner works and the board runs at https://cclevel-board.cclevel.workers.dev. The source is at https://github.com/Spider333/cclevel. The name is a working name.

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

(An example card with invented numbers.)

## The one rule

What is used counts far more than what is installed. Installing a hundred skills takes a minute. Using thirty of them every week takes a real setup.

## Install

As a Claude Code plugin, from a shell:

```
claude plugin install cclevel --marketplace Spider333/cclevel
```

or inside a session:

```
/plugin marketplace add Spider333/cclevel
/plugin install cclevel@cclevel
```

Then run `/pet` (or `/cclevel:pet` if you already have a command called `pet`).

Without the plugin system: copy `skills/pet/` into `~/.claude/skills/`, or just run the script.

```
python3 skills/pet/scripts/cclevel.py
```

It needs Python 3.9 or newer and nothing else.

## What it reads, writes, runs and sends

- **Reads** your Claude Code folder (`~/.claude`) and `~/.claude.json`: session logs, prompt history (timestamps only), settings, and the list of skills, subagents, plugins and connectors.
- **Reads** your scheduled jobs (launchd, cron, systemd user timers) to count the ones that run Claude. For that it runs `crontab -l` and opens the scripts those jobs name, wherever they are on disk, to look for a call to `claude`. Nothing from them is printed, stored or sent.
- **Writes** only `~/.claude/cclevel/ledger.json` (XP per day, badges) and, if you join the board, `~/.claude/cclevel/identity.json`.
- **Sends** nothing unless you run `--join`, `--sync`, `--world`, a `--group` command, a GitHub badge command, `--leave` or `--rank`. See [PRIVACY.md](PRIVACY.md) for the exact payload: nine numbers and a list of badge codes.

No hooks, no background process, no telemetry. As a plugin, only the offline commands are pre-approved. Network commands are left to Claude Code's normal permission rules, so with default settings each one asks first.

## Commands

| Command | What it does |
|---|---|
| `cclevel.py` | The card. Offline. |
| `--json` | The numbers behind the card. |
| `--no-save` | Score without touching the ledger. |
| `--preview` | Print exactly what a check-in would send. Sends and saves nothing. |
| `--rank` | Your place on the world lists, worked out locally from the public numbers. Uploads nothing. |
| `--join` | Join the board. Shows the payload and asks first. If already joined, it sends nothing. |
| `--sync` | Check in. One accepted check-in per day. |
| `--world on` / `--world off` | Be ranked on the public world lists, or not. Off at joining; on asks first; off works at once. |
| `--group-create` | Start a private group (asks first) and print its invite code. |
| `--group-join CODE` | Join a friend's group with its invite code (asks first). Without CODE, type it at a hidden prompt. |
| `--group` | Show your group: names, levels, XP since joining, season XP, Aura, sus marks. |
| `--group-leave` | Leave your group at once. |
| `--group-code` | Show your group's invite code again; in full only in your own terminal. Sends nothing. |
| `--verify-github LOGIN` | Opt-in GitHub badge. First run: asks, then gives you a code to put in a public gist. Second run: the board checks the gist. |
| `--unverify-github` | Remove the GitHub badge and every GitHub detail at once. |
| `--leave` | Delete your row and the local token. |
| `--server URL` | Use a self-hosted board. A creature only talks to the board it joined. |
| `--claude-dir DIR` | Scan another folder. |

## How the score works

The arithmetic is plain. The names are internet, on purpose.

- **Level (1 to 99)** comes from XP: `level = floor(sqrt(xp / 40))`. XP is earned per finished day. A finished day is priced once and is not changed afterwards. Days are UTC dates, so travelling does not move them.
- **A day with logs** earns 100 for showing up, plus up to 150 for tokens, 100 for distinct skills, connectors and subagent types used, 100 for edits, commits and pull requests, and 100 for unattended sessions. That adds up to at most 550, so a level cannot be bought with one big burn.
- **A day whose logs are gone** (Claude Code deletes them after 30 days by default) has one fixed price, the same for everyone: 100 plus up to 300 from the number of prompts written that day. One prompt is worth 145, ten are worth 256, a hundred or more 400. The card says how many days were estimated this way.
- **Badges** add one-off XP for things done: a hook that ran at the end of a turn, an own skill used, a subagent spawned, an unattended session, 7, 30 and 100 days in a row, and 10, 50 and 100 distinct skills used.
- **Six stats (0 to 100, in steps of 5)**:
  - Grind: days used out of the last 30, and streaks.
  - Appetite: weighted tokens over the last 30 days.
  - Arsenal: skills, connectors and subagent types actually used, plus a small share for what is installed.
  - Brains: ten checks of wiring that is in use (below).
  - Autonomy: sessions that ran without you, the days they ran on, the longest stretch without a human, and scheduled jobs that call Claude.
  - Craft: edits, commits, pull requests, published pages and projects touched.
  - They add up to **Aura**.
- **Brains** has ten checks worth ten points each. Eight need use: skills used within the last 90 days, and for the rest something seen in the session logs of the last 30 days. Two are things to have (an instructions file, a guardrail), so a folder of files that were never used scores 20. From 30 it earns a title: Wrinkly Brain, Big Brain from 50, Galaxy Brain from 80.
- **Health** drives the mood. It drops for own skills that are at least 90 days old and went unused in that time, connectors waiting for sign-in, a heavy start-up context, failing tool calls and interrupted turns.

## The names

| Name | Means |
|---|---|
| Egg, Hatchling, Lil Guy, Main Character, Giga, Final Boss | The stage: levels 1, 5, 15, 30, 45 and 60 |
| Shipper | Class: Craft is the strongest of the four working stats |
| AFK Farmer | Class: Autonomy is strongest. AFK farming is earning in a game while away from the keyboard |
| Loot Goblin | Class: Arsenal is strongest. A player who picks up every item in sight |
| Tokenmaxxer | Class: Appetite is strongest. Burning tokens as if that were the goal |
| Perfectly Balanced | Class: all four are 30 or more and within 10 points of each other |
| Noob | Class: none of the four has reached 30 yet |
| Unhatched | Class: all four working stats are at zero |
| Wrinkly Brain, Big Brain, Galaxy Brain | Title from the Brains stat |
| Locked in, Vibing, Cooked | Mood while in use: Health 80 or more, 50 to 79, under 50 |
| We're so back | Mood for the first three days after a break of two weeks or more |
| Touching grass, Ghosting, It's so over | Mood after 3, 14 and 60 days without a session |
| Not hatched yet | Mood of a folder with no activity |
| Aura | The six stats added up |
| Skill issue, Certified chonk, Touch grass | Asides in the Needs list: unused skills, a heavy start-up context, nothing to fix |
| gm x7, No days off, Terminally online | Badges for 7, 30 and 100 days in a row |
| Hooked, Skill issue: solved, Not my job, AFK gains | Badges for the first hook that ran at the end of a turn, own skill used, subagent spawned and unattended session |
| Loadout, Full kit, Maxed out | Badges for 10, 50 and 100 distinct skills used |

Grind and Brains never set the class. The scoring constants and the names are defined at the top of `skills/pet/scripts/cclevel.py`. The numbers are first-draft values, tuned on very few setups. The scanner never sends a name and never reads one from the board, so the names can change at any time. The board names creatures itself.

## Limits worth knowing

- A score covers one machine and is self-reported. Anyone can edit their own local files and show any level, so it is for fun and is not a credential.
- Claude Code deletes session logs after 30 days by default, so log-based numbers use a 30-day window. Days from before your first scan have no logs left, so their XP is an estimate from prompt counts. For a long-time user most of the level is such an estimate, and the card says how much.
- "Unattended" sessions are inferred from how a session was started, which is an approximation.
- A Brains check is passed by a single use inside its window. Brains shows what is wired and working, not how often it is used.
- The fixed price for a day without logs is tuned to match a typical logged day on average. For a very light day it can come out a little higher than the logs would have given.

## The board

`server/` is a small Cloudflare Worker with a D1 database and one static page.

- **It ranks only what it saw.** After joining, a creature gains at most 550 XP per active day on the board, without badge XP. That is its witnessed XP, and it is the only thing either list is sorted by. Whatever a creature reported when it joined (its history, its level) never ranks. On its first return it may be credited one extra day, once, to allow for time zones.
- **Two lists.** Season is the XP credited this month; All-time is everything since joining. Each lists the top 1,000. Below that the board publishes the XP needed for each "top X%" band, and `--rank` works out your place on your machine.
- **Listing is a choice.** Joining does not list you. `--world on` does, once you have check-ins on two different UTC days. `--world off` and `--leave` take you off both lists in the same request.
- **Private groups.** Up to 25 friends share an invite code made on one of their machines; the board keeps only its hash. Only members can read a group, there is no web view of it, and being in one does not list you anywhere. One group per creature.
- **GitHub badge.** Optional. You prove a GitHub account is yours with a public gist (no password or key leaves your machine); the board then shows the login and how many of its public commits carry Claude Code's co-author line. It never changes a place or XP. Without a GitHub key on the board, it answers "not available".
- **Sus** marks a creature with at least 14 witnessed days of which 80% or more were credited at the full 550. It changes nothing else, and a script that claims a little less is not caught.
- **Totals** (creatures per level, stage, class, stat range and badge, and the sus count) count every creature with check-ins on two days, listed or not, and appear only from 100 creatures.
- **Limits.** One network can add roughly one new creature a minute (the host's limiter is approximate), and the board takes at most 5,000 new creatures a day. Turning the world ranking on and starting or joining a group share a limit of three a day per creature; turning off and leaving are never limited. Group requests are limited to ten a minute per creature.
- The service keeps no request logs and stores no IP address. See [PRIVACY.md](PRIVACY.md) for what that does and does not cover.

Run it locally:

```
cd server
npm install
npm test
npx wrangler d1 execute cclevel-board --local --file=schema.sql
npx wrangler dev --test-scheduled
```

The public files are rebuilt by a timer that does not fire in local development. Open `http://localhost:8787/cdn-cgi/handler/scheduled` to rebuild it by hand.

A note for self-hosters: `wrangler dev` is a development tool and keeps its own local traces of each request (method, address of the page, status, time) and its own copy of the limiter's counters under `.wrangler/`. The deployed service does neither, because `wrangler.jsonc` switches request logging off. Keep it that way.

## Tests

```
python3 -m unittest discover -s tests
cd server && npm test
```

## Licence

MIT. See [LICENSE](LICENSE).
