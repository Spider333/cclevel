# How the score works

The arithmetic is plain. The names are internet, on purpose. Everything here is defined at the top of [`skills/pet/scripts/cclevel.py`](../skills/pet/scripts/cclevel.py).

## The rules

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
| Egg, Hatchling, Lil Guy, Big Guy, Gigachad, GOAT | The stage: levels 1, 5, 15, 30, 45 and 60 |
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

## Training and tips

Opt-in learning, offline, outside the score. It never changes XP, level, a stat or a rank, and nothing about it is sent.

- **`/pet learn`** shows five lessons per stat, easiest first: for example *See what fills the context* (`/context`), *Plan before you build*, *Hand a job to a subagent*, *Let Claude commit*. A lesson ticks itself when the logs or the setup show it done, never because you say so, and stays ticked after the logs are gone. The next lesson in each stat says how to do it and links its page in the Claude Code docs.
- **`/pet tips on`** adds a how-to line, with its docs page, under each item on the card's Needs list, and one tip a day. The tip comes from your weakest stat, stays the same all UTC day, and no tip comes round again until all of them have been shown. `/pet tips off` turns both off.
- Ticked lessons, the tips switch and the tips already shown are kept in `~/.claude/cclevel/training.json`.
- Every tip and how-to was checked against the Claude Code docs on the date in `TIPS_CHECKED`. Claude Code changes fast: if one is out of date, please open an issue.

Grind and Brains never set the class. The scoring constants and the names are defined at the top of `skills/pet/scripts/cclevel.py`. The numbers are first-draft values, tuned on very few setups. The scanner never sends a name and never reads one from the board, so the names can change at any time. The board names creatures itself.

## Limits worth knowing

- A score covers one machine and is self-reported. Anyone can edit their own local files and show any level, so it is for fun and is not a credential.
- Claude Code deletes session logs after 30 days by default, so log-based numbers use a 30-day window. Days from before your first scan have no logs left, so their XP is an estimate from prompt counts. For a long-time user most of the level is such an estimate, and the card says how much.
- "Unattended" sessions are inferred from how a session was started, which is an approximation.
- A Brains check is passed by a single use inside its window. Brains shows what is wired and working, not how often it is used.
- The fixed price for a day without logs is tuned to match a typical logged day on average. For a very light day it can come out a little higher than the logs would have given.
