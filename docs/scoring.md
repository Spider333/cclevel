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
- **Streak.** A day counts when it has any session or prompt, as a UTC date. The current streak counts the days in a row through yesterday until today is active, so the morning never shows 0. One empty UTC day ends it. There is no freeze and no repair, and nothing warns you about it. The card shows it, and the creature band shows "streak N" from 2. `--json` also gives `raw.away_days`: the empty UTC days just before today (0 when yesterday was active, null with no activity before today).
- **A new stage.** The day each stage was reached is worked out from the ledger: the first day the banked XP, plus the XP of badges earned by then, reaches the stage's level. For 7 days from that day (the day itself and the six after it) the card says "Evolved into a Big Guy on 3 Dec!" and `--json` gives `evolved: {from, to, day}`; otherwise `evolved` is null. Only the newest stage counts. `--evolve` turns it into a ready X post that links to the class's page, `/class/<class>` on the website (Unhatched links to the home page).
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
| Welcome back | The creature band, at your first session of a UTC day after two or more empty UTC days: your creature shows dusty and asleep, shakes awake and says "Welcome back!", once that day. No toast and no notification; nothing happens while you are away |
| Aura | The six stats added up |
| Markings | Each creature's own eyes, mouth and crest (an Egg: its shell mark), from a number made once on your machine (`~/.claude/cclevel/seed`). 64 looks; look 0 is the classic art. They never change the score and are never sent to the board |
| ✦ Shiny | 1 in 100 creatures. Two twinkles on the art and "✦ Shiny" on the card and the share card. Just for fun: it changes no number |
| Skill issue, Certified chonk, Touch grass | Asides in the Needs list: unused skills, a heavy start-up context, nothing to fix |
| gm x7, No days off, Terminally online | Badges for 7, 30 and 100 days in a row |
| Hooked, Skill issue: solved, Not my job, AFK gains | Badges for the first hook that ran at the end of a turn, own skill used, subagent spawned and unattended session |
| Loadout, Full kit, Maxed out | Badges for 10, 50 and 100 distinct skills used |

## Timesheet: outside the score

`/pet timesheet` (`--timesheet`) turns the session logs into hours per project. It never changes XP, level, a stat or a rank, and it sends nothing.

- **Blocks.** Every `user`, `assistant`, `system` and `attachment` line has a time. Per session (a subagent's log counts with its session) and per project, the times are sorted; events at most 15 minutes apart (`--idle MIN`, 1 to 240) are one block. A block runs from its first event to its last, the start rounded down and the end up to the whole minute, at least 1 minute.
- **With you or Claude alone.** A block with a prompt you typed (not a tool result, not a subagent's) counts as with you. Blocks from `claude -p` and SDK runs, background sessions, or with no prompt count as Claude alone. Claude alone in the view is time when no block with you ran. It is activity time, not proof you were at the desk.
- **Project.** The nearest folder at or above the session's working folder that holds `.git`, or that folder itself. A worktree in `<repo>/.claude/worktrees/` counts as the repo. Sessions started in your home folder or `/` are `(home)`.
- **Overlap.** Per project and per day, minutes are the union of its blocks, so side-by-side sessions count once. Project columns can add up to more than the day.
- **Local time.** The card's days stay UTC. The timesheet uses this machine's zone, or `--tz Area/City`; each time is converted on its own, so summer time is right. Rows are split at local midnight and where the UTC offset changes. Weeks run Monday to Sunday.
- **The CSV** (`timesheet.csv`): `date,weekday,start,end,minutes,kind,project,project_no,sessions,prompts,tz,utc_offset`, one row per block piece, for every day the logs hold. `project_no` matches P1, P2… in the printed view. Claude Code deletes logs after 30 days unless its `cleanupPeriodDays` setting says otherwise.

## Leak finder: outside the score

`/pet leaks` (`--leaks`) shows where your tokens went over the last 4 full ISO weeks plus this week so far. It never changes XP, level, a stat or a rank, and nothing about it is stored or sent. Claude Code keeps logs for 30 days, so that is as far back as it can see.

- **Tokens per week**, per kind: fresh input, cache writes, cache reads and output, from each reply's `usage` in the session logs. A reply is written once per content block, so it counts once (by message id and request id, keeping the most complete line).
- **Dollars are a yardstick, not a charge.** Each reply is priced with the API list price of its model, so token counts can be compared. Most people pay a subscription and are never charged this. Prices were checked on 2026-10-06 (`PRICES_CHECKED`, from https://platform.claude.com/docs/en/about-claude/pricing). A cache read is 0.1x input unless the model has its own price, a 5-minute cache write 1.25x input and a 1-hour one 2x. Opus 5.5 in fast mode is $8 / $40 per million. A model with no price in the table shows its tokens and "no price for this model", never $0.
- **Cache written again after pauses:** a reply more than 5 minutes after the one before it in the same log counts its 5-minute cache writes; more than 60 minutes, its 1-hour writes too. An estimate: the log does not say why a write happened.
- **Start-up context:** the same estimate the score uses (bytes / 4): your CLAUDE.md, the largest memory index, your own skills' descriptions, plus this folder's CLAUDE.md. Priced as a cache read for every reply in the window, so it is a lower bound.
- **Auto-compaction:** each `compact_boundary` line with trigger `auto`, the sessions it hit, the average size before, and the cache the next reply wrote again.
- **Connectors set up but not called in 30 days:** your configured servers (user, project and plugin ones) minus the ones a tool call named. No dollar figure: with tool search, the default, an idle connector costs little context.
- **A check:** for each log with Claude Code's own cost figure (a `cost-state` line), the report says how many sessions are within 15% and lists the rest with both figures.
- `/context` is the exact live view of the session you are in; the leak finder is a pattern over weeks.

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
- Our story (`/pet story`) is worked out from the ledger: the level on a day is the XP of the days banked up to it plus the badges dated by then, the same sum Wrapped uses. Dates from before your first scan are estimates and say "about". Badges you already had at the first scan are dated that day, so they say "about" too.
- "Unattended" sessions are inferred from how a session was started, which is an approximation.
- A Brains check is passed by a single use inside its window. Brains shows what is wired and working, not how often it is used.
- The fixed price for a day without logs is tuned to match a typical logged day on average. For a very light day it can come out a little higher than the logs would have given.
