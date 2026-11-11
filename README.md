# CC level

**Claude Code, gamified. How big is your Claude Code? Measure it. Compare it. Stay nameless.**

[![License: FSL-1.1-MIT](https://img.shields.io/badge/license-FSL--1.1--MIT-d97757)](LICENSE)
[![Board](https://img.shields.io/badge/board-live-d97757)](https://cclevel.com)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-d97757)](#install)
[![Privacy](https://img.shields.io/badge/sends-9_numbers-d97757)](PRIVACY.md)

CC level (`cclevel` for short: the plugin, the script and this repository) turns your Claude Code setup into a creature that grows. It reads your local Claude Code folder (and, if you use Claude's Cowork on the same Mac, Cowork's session logs), scores how well-used and well-wired the setup is, and prints a card: a level, six stats, a mood and a short list of what to fix next. From the next Claude Code start, the creature is on a public board under a generated name, and you can compare it with friends in a private group. No account, no name, nine numbers. That is Default mode; Privacy mode is one command, `/pet privacy on`, and then cclevel sends nothing (opening a share-card, Wrapped or invite link in a browser still loads its page from cclevel.com).

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

Then run `/pet`: your egg hatches, and the first card says what you got ("It's a Lil Guy Shipper · Lv 18"). If you already have a command called `pet`, use `/cclevel:pet`.

**Two modes.** **Default mode** is what you get: from the next Claude Code start, the plugin puts your creature on the public board under a generated name, lists it from its second day, and checks in once a day in the background: nine numbers and badge codes, no account, nothing you wrote, then reads your own private group so the Mac panel can show friends (again at later Claude Code starts, at most every 15 minutes, only with the panel installed and a group). Groups, duels, `/pet rank` and the GitHub badge come with it. **Privacy mode is one command: `/pet privacy on`**, before or after it joins. It deletes your row, if there is one, and from then on cclevel sends nothing (opening a share-card, Wrapped or invite link in a browser still loads its page from cclevel.com). The card, the creature above your prompt, the menu bar panel, tips, lessons and Wrapped all keep working; the board features wait until `/pet privacy off`. To stay on the board for groups and duels but off the public lists, use `/pet world off`.

**Updating.** Claude Code does not update plugins from this marketplace by itself until its auto-update is on. From 0.21.0, in Default mode, your first `/pet` card turns it on for you, once, and says so in one line: the same switch as `/plugin` → Marketplaces → cclevel → **Enable auto-update**. Claude Code then checks GitHub for a new cclevel once a session and installs it; `/pet autoupdate off` stops it for good. A choice you already made there stays yours, and Privacy mode turns off what the first card turned on. On an older version, update once by hand (and pick **Enable auto-update** while you are there). To update now: `/plugin` → Marketplaces → cclevel → Update marketplace, then `/reload-plugins`; or from a shell, `claude plugin marketplace update cclevel` and `claude plugin update cclevel@cclevel`. Duels and the share card need 0.4.0 or newer; Wrapped's story images need 0.19.0 or newer. From 0.7.0 the board is on by default; if you left the board under an earlier version, run `/pet privacy on` once after updating, or the next session start joins you again. From 0.13.0, a machine that left the board (`/pet leave`, or `/pet auto off` before joining) is in Privacy mode, so `/pet rank` waits until `/pet privacy off`. The menu bar panel is built once on your Mac and never rebuilds itself: after an update, run `/pet panel on` again to get the new panel (from 0.18.0 you can poke the creature; from 0.22.0 it counts Cowork work too).

Without the plugin system, copy `skills/pet/` into `~/.claude/skills/`, or run the script directly:

```
python3 skills/pet/scripts/cclevel.py
```

It needs Python 3.9 or newer and nothing else: standard library only, no dependencies.

## What you get

| Feature | What it is | Sends anything? |
|---|---|---|
| **The card** | Level, six stats, mood, badges and the top things to fix. | No. Fully offline. |
| **Creature band** | Your creature above the prompt in every Claude Code session, with a level bar, today's XP, your streak (from 2 days in a row) and its mood. While Claude works it walks (each stage its own way) and acts out the tool: writing while files are edited, sniffing around while Claude searches, lifting while a command runs, flexing when a commit lands, sweating when a tool fails. On a new machine its first appearance is a hatch: the egg wobbles, cracks, and your creature shows up with its class, once. Back after two or more days away, it shows up dusty and asleep, shakes awake and says "Welcome back!", once that day: no toast, no notification, and nothing while you are away. It sleeps when Claude is idle and bursts on a level up, and in the terminal Claude's spinner says what it is up to ("Gigachad is grinding"). `/creature off` hides it. Needs Claude Code 2.1.287 or later, in the terminal or the Desktop app. | No. Fully offline. |
| **Menu bar panel** (Mac, opt-in) | Your creature in the Mac menu bar. Click it for a small black panel of rounded cards: **Creature** (your creature as a rendered 3D loop that plays while the panel is open, in its class look: a colour and a hat per class, such as the Noob's propeller beanie or the AFK Farmer's straw hat, a still with Reduce Motion on), **Level** and **Today** (your level bar and today's XP against the 550-a-day cap), **Stats** (the six stats) and **Trend** (your XP for each of the last 14 days). Three buttons below open **Friends** (your private group: an **Invite friends** card with a **Copy invite link** button, then each friend's creature, level, stage and XP this week, with ♛ for the week's most XP; Default mode only; in a group, a **Copy invite link** card also sits beside Friends on the overview, one click away), **Fix next** (your top Needs, how to fix each, and its Claude Code docs page) and **Learn** (the lessons per stat, each one's next step, and a tip of the day), each with a way back. Hover over your creature and click to poke it: it hops and goes boing. **Free roam:** click the lock on the Creature card to let it out: it hops along the top of your screen, just under the menu bar, jumps now and then and boings when you poke it. If it sits on something you want to click, poke it and it jumps aside. Click the lock again, or right-click the creature, to call it back. It rests while you are away, stops when the screen sleeps, and stays home until you unlock it. To keep it quiet, turn off **Play user interface sound effects** in System Settings → Sound. Right-click for Refresh or Quit. It sits at the right end of your menu bar items, away from the notch; hold ⌘ and drag it to move it, and it stays where you put it. `/pet panel on` builds it on your Mac from the plugin's own source with Apple's free command line tools and starts it at login; `/pet panel off` removes it. | The panel itself, no: it never calls the board. Its Friends page shows your group as of the last daily check-in, Claude Code start (at most every 15 minutes) or `/pet group`, which read it from the board in Default mode. |
| **The world board** | Season and all-time lists at [cclevel.com](https://cclevel.com), ranked only on XP the board watched you earn. | Yes, in Default mode: nine numbers a day. Privacy mode (`/pet privacy on`) turns it off. |
| **Private groups** | Up to 25 friends compare in private, joined with one invite link. | Starting or joining one, yes. In Default mode the daily check-in also reads your own group once (the token only; an empty list when you are in none), and with the Mac panel installed later Claude Code starts read it again, at most every 15 minutes. |
| **Duels** | Challenge one friend: seven days, most XP the board credits wins the ♛. | Only if you start or accept one. |
| **Markings** | Every creature gets its own markings (eyes, mouth, crest) from a number made on your machine, and 1 in 100 is shiny. | No. The number never leaves your machine; a card link you post carries its look. |
| **Share card** | Your card as a picture to post, drawn in your browser, with your creature's markings. | No. The numbers stay in the link after `#`. |
| **Wrapped** | Your year in review: XP, best day and month, longest streak, level gained, badges, and how your stats moved week by week, and 5 story images to post, drawn in your browser. | No. Worked out from your own ledger; the images' numbers stay in the link after `#`. |
| **Our story** | A timeline of you and your creature: the day you met, each evolve, badges, your biggest day. `/pet story`. | No. Worked out from your own ledger. |
| **Evolve post** | For 7 days after your creature reaches a new stage, the card says so ("Evolved into a Big Guy on 3 Dec! Post it: /pet evolve"), and so does the band's stage-up toast. `/pet evolve` prints a link that opens X with a ready post you can edit: "My Claude Code just evolved into a Big Guy Shipper, Lv 30. What's yours?" (invented numbers). Any other day it says what your creature is now. The post links to your class's page on cclevel.com, the same page for everyone. | No, in both modes. The link is only printed. Opening it is your own visit to x.com, and the post is public. |
| **README badge** | A "Lv 42 · Gigachad" badge for your GitHub profile or any README, as one line of Markdown to paste. `/pet readme badge`. It doesn't update itself: run it again to refresh. | No. The numbers sit in the badge's address; the picture comes from shields.io, a free badge service. |
| **Timesheet** | Hours per project for a week, from your session logs, in local time: minutes with you, minutes Claude worked alone, and each project. In a background job, only what you type counts as with you. `/pet timesheet` (or `last`, or a week like `2026-W45`). Every block goes into `timesheet.csv` on your machine for a spreadsheet. Activity time, not proof you were at the desk. Outside the score. | No. Fully offline, the same in both modes. The chat sees numbered projects only; names are in the CSV on your machine. |
| **Fix** | `/pet fix` plans the top Fix next item: what is wrong, every file it would touch, the exact change, the gain and how to undo. It changes nothing until you say yes. One fix is automatic (moving own skills unused for 90 days); the others Claude makes in your session and shows you the diff first. A backup always comes first, and `/pet fix undo` puts it back. If Claude Code's sandbox blocks the fix, nothing changes and Claude asks before running it outside the sandbox. | No. Offline, the same in both modes. |
| **Leak finder** | Where your tokens went over the last 4 weeks, priced with API list prices as a yardstick (not a charge): cache written again after pauses, your start-up context, auto-compactions, and connectors you set up but never call. `/pet leaks`. With tips on, the card names the biggest leak when it is over $5 a week. Outside the score. | No. Fully offline, the same in both modes. It prints your connector names on your screen and stores nothing. |
| **Training** | Five lessons per stat that tick themselves from your logs, and opt-in tips: a how-to under each Need and one Claude Code tip a day. | No. Fully offline. |
| **GitHub badge** | Prove a GitHub account is yours and show how many of its public commits Claude co-signed. | Only if you ask for it. |

In Claude Code you can just ask: `/pet`, `/pet join the leaderboard`, `/pet rank me`, `/pet start a group`, `/pet join <invite link>`, `/pet duel`, `/pet card`, `/pet leaks`, `/pet timesheet`, `/pet fix`, `/pet learn`, `/pet tips on`.

## Play with friends

1. **Start a group:** `/pet start a group`. You get an invite link like `https://cclevel.com/join#3f9a…` and a generated group name, for example *Stormy Lemur Crew*.
2. **Send the link** to friends. Opening it shows the group's name and how to join. The code after `#` stays in the browser and is never sent to the board.
3. **Friends paste it** into Claude Code: `/pet join <link>`. One yes joins the board and the group together.
4. **Compare:** `/pet show my group`. Each member sees the others' generated names, levels, XP and stats. Nobody outside the group does.

Anyone with the link can join until the group is full, so share it with friends only. If it leaks, start a new group.

**Duel one friend:** `/pet duel` gives you a link like `https://cclevel.com/duel#7c1e…`. The first friend to accept it with `/pet duel <link>` takes the seat. The duel starts at 00:00 UTC the next day and runs seven days. XP counts at each check-in after your first one on or after the day it was accepted, so XP saved up from before never counts; whoever the board credits with more wins the ♛. A duel sits beside your group and is never published.

**Badge for your README:** `/pet readme badge` prints one line of Markdown, for example `[![CC level: Lv 42 Gigachad (5 Nov 2026)](https://img.shields.io/badge/CC_level-Lv_42_%C2%B7_Gigachad-d97757)](https://cclevel.com)` (invented numbers). Paste it into your GitHub profile README. cclevel sends nothing; anyone who views the page loads the picture from shields.io. Anyone who sees it sees your level next to your name, so if your creature is on the world lists, `/pet world off` keeps people from matching the two.

**Post your card:** `/pet card` prints a link to a page that draws your card as a picture to save or copy. The numbers sit after `#`, so the page sends nothing, and the picture shows no creature name. The link also carries your creature's look (one number), so two of your posted cards can be matched to each other.

## Privacy at a glance

| | |
|---|---|
| **The card** | Offline. Reads your Claude Code folder and, with Claude's Cowork on the same Mac, Cowork's session logs (nothing else of Cowork's); the card writes only `~/.claude/cclevel/`, with one exception: in Default mode, the first card turns on Claude Code's auto-update for this marketplace, which is one key (`autoUpdate`) on cclevel's own entry in `~/.claude/plugins/known_marketplaces.json` and, if your `~/.claude/settings.json` lists the marketplace, there too (where `/plugin`'s toggle writes it). It never changes anything else in those files, leaves a linked or read-only file alone, and `/pet autoupdate off` undoes it. `/pet fix` changes your setup only after your yes, with a backup. Nothing keeps running. |
| **The creature band** | Offline. Draws above your prompt and, when its last score is more than an hour old, rescores in the background with `--json --no-save`, which reads what the card reads (Cowork's session logs too) and writes nothing. It keeps the level, stage, mood, XP, streak, days away and time of that score in the plugin's own store, and the day it last welcomed you back. To act out Claude's work it notes which tool runs, whether it failed and whether a command is a commit; it keeps only which action it is showing, for this session, never the command itself. `/creature off` stops it. |
| **The menu bar panel** | Off until you turn it on (Mac only). It keeps a program, a copy of the scanner and the creature loops (34 of them, one per stage and per class look, about 1.7 MB, from the plugin's `mac/creatures/`, and a see-through copy of each for free roam, about 2.9 MB more) in `~/.claude/cclevel/panel/`, with one empty file, `roam`, while your creature is out for a walk, starts at login through `~/Library/LaunchAgents/com.cclevel.panel.plist` (macOS keeps where the creature sits, and where you ⌘-drag it, in the program's own preferences, `cclevel-panel`), and runs the card offline with `--json --no-save` (it reads what the card reads, Cowork's session logs too) at most once an hour (and right after `/pet panel on` updates it, or a check-in or group read saves something new), keeping the last result in `card.json` there. A docs link in the panel opens Claude Code's docs in your browser; the panel itself makes no network call. Its Friends page reads your group from `identity.json`, where the daily check-in, later Claude Code starts (at most every 15 minutes) and `/pet group` save the board's answer; a copy older than 36 hours is not shown, and in Privacy mode nothing is shown. `/pet panel off` removes all of it. |
| **Two modes** | **Default mode:** the board is on. The plugin's check-in hook joins the board at the first Claude Code start and checks in once a day, then reads your group (again at later starts, at most every 15 minutes, with the Mac panel installed and a group). **Privacy mode** (`/pet privacy on`): your row is deleted and cclevel sends nothing, not even `--rank`'s download; everything offline keeps working. Opening a share-card link loads a page from cclevel.com, whose visit (not the numbers after `#`) may be in Cloudflare's sampled visit logs. `/pet privacy off` asks first, then goes back. |
| **Where data goes** | In Default mode, cclevel sends only to the CC level board (website cclevel.com, check-in address `https://go.cclevel.workers.dev`, which stores no IP addresses), run by Amagi Labs LLC, and only for the board: joining, the daily check-in and one read of your own group after it (all on by default; with the Mac panel and a group, that read again at later Claude Code starts, at most every 15 minutes), world ranking, groups, duels and the GitHub badge. The card, `--preview`, `--card`, `--wrapped`, `--story`, `--evolve` and `--readme-badge` send nothing; `--rank` only downloads the public board files. Separately, with auto-update on (Default mode turns it on at your first card), Claude Code itself, not cclevel, fetches this marketplace from GitHub once a session to look for a new version; GitHub sees that request, and the repository's owner sees only GitHub's own clone counts. In Privacy mode, cclevel sends nothing and turns off the auto-update its first card turned on (one you turned on yourself keeps working, and Claude Code, not cclevel, does that fetching); opening a share-card or Wrapped link still loads a page from cclevel.com, and that visit may be in Cloudflare's sampled visit logs. |
| **A check-in sends** | Nine numbers and a list of badge codes (`v`, `xp`, `xp_days`, six stats, `badges`), plus a random key made on your machine. The board keeps only a hash of that key. |
| **Never sent** | Your name, e-mail, prompts, code, file paths, or the names of your projects, skills or connectors. |
| **The board stores** | No account, no e-mail, no IP address, and no request logs. A creature is its score, a generated name, the key's hash and a few dates and counters. |
| **You control** | `--privacy on` (Privacy mode: deletes your row, and cclevel sends nothing after; a share-card, Wrapped or invite link you open still loads its page from cclevel.com; `--leave` is the same), `--world off` (off the lists at once), `--auto off`, `--group-leave`, `--duel-leave`. A row with no check-in for 180 days deletes itself. |

The word is **pseudonymous, not anonymous**: a row stays linked to the key on your machine. [PRIVACY.md](PRIVACY.md) lists every field, every request and what we cannot promise.

## Commands

In Claude Code, `/pet` runs these for you. Network commands you run ask first, and so does Claude Code's permission prompt. In Default mode the session-start hook joins and checks in on its own; `--privacy on` stops it for good. The creature band has a command of its own in Claude Code: `/creature off` hides it, `/creature on` shows it again, and `/creature` switches.

| Command | What it does |
|---|---|
| `cclevel.py` | The card. Offline. |
| `--json` | The numbers behind the card, and what the menu bar panel shows. In a group this includes your invite link and friends list, so don't paste it anywhere public. |
| `--no-save` | Score without touching the ledger. |
| `--preview` | Print exactly what a check-in would send. Sends and saves nothing. |
| `--rank` | Your place on the world lists, the XP to pass the next place, and how rare your badges are, worked out locally from the public files. Uploads nothing. |
| `--join` | Join the board by hand, with the world ranking and auto check-in on (the hook usually did it already). Shows the payload and asks first. If already joined, it sends nothing. |
| `--sync` | Check in. One accepted check-in per day. |
| `--auto on` / `--auto off` | Check in by itself once a day, in the background, when a Claude Code session starts, then read your group, again at later starts at most every 15 minutes with the Mac panel installed (on asks first). On from joining; sends nothing when you switch it. Before joining, off turns Privacy mode on. |
| `--world on` / `--world off` | Be ranked on the public world lists, or not. On at joining; on asks first; off works at once. |
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
| `--wrapped [YEAR]` | Your year in review, this year so far by default, then a link to 5 story images (1080×1920) drawn in your browser from the numbers after `#`. Sends nothing, in both modes. |
| `--evolve` | A link that opens X with a ready post: your stage, class and level, and a link to your class's page (`/class/shipper` and so on). Sends nothing, in both modes. |
| `--readme-badge` | Markdown for a "Lv 42 · Gigachad" badge for a README or GitHub profile (example numbers). Offline; the picture comes from shields.io. Re-run to update it. Sends nothing, in both modes. |
| `--story` | Our story: a timeline of you and your creature, from the day you met Claude Code. Dates from before cclevel first scored you say "about". Add `--json` for the numbers. Sends nothing, in both modes. |
| `--timesheet [WEEK]` | Timesheet for `this` week (default), `last` week or a week like `2026-W45`, in local time: per day, minutes with you, minutes Claude alone and per numbered project. Writes every block to `~/.claude/cclevel/timesheet.csv` (only you can read it). `--names` shows project names, `--idle MIN` (1 to 240, default 15) sets when a block ends, `--tz Area/City` the zone. Sends nothing, in both modes. |
| `--leaks` | Leak finder: tokens per week for the last 4 weeks, the cache-read share, and the biggest leaks with how to fix each, priced as an API yardstick (prices of 2026-10-06). Add `--json` for the numbers and names. Sends and saves nothing, in both modes. |
| `--fix [CODE]` | Plans the top Fix next item (or CODE) and writes nothing. With the plan's `--plan ID --yes` it backs up the files it names into `~/.claude/cclevel/fixes/`, then moves unused own skills there, or leaves the edit to Claude. `--fix-undo` puts the latest fix back. Sends nothing, in both modes. |
| `--learn` | The training path: five lessons per stat, ticked by what your logs show, with how to do the next one. Offline. |
| `--tips on` / `--tips off` | A how-to under each Need and one Claude Code tip a day on the card. Off by default; kept on this machine, sends nothing. |
| `--autoupdate on` / `--autoupdate off` | Whether Claude Code installs new cclevel versions by itself: the `/plugin` auto-update switch for this marketplace. In Default mode the first card turns it on once; off keeps it off for good. Works only on a copy installed from a plugin marketplace. Sends nothing. |
| `--panel on` / `--panel off` | Mac only: your creature in the menu bar, with a small panel. On asks first, then builds it on this Mac with Apple's `swiftc` and starts it at login; off removes it. The panel sends nothing (its Friends page shows the group as of the last check-in, Claude Code start or `--group`). After a plugin update, run `--panel on --yes` again to update it. |
| `--verify-github LOGIN` | Opt-in GitHub badge. First run: asks, then gives you a code to put in a public gist. Second run: the board checks the gist. |
| `--unverify-github` | Remove the GitHub badge and every GitHub detail at once. |
| `--privacy on` / `--privacy off` | Privacy mode. On deletes your row and the local token, and from then on cclevel sends nothing (opening a share-card, Wrapped or invite link in a browser still loads its page from cclevel.com): the hook stays quiet and the board commands say Privacy mode is on. Off shows what Default mode sends and asks first; it sends nothing itself, and the hook joins at the next Claude Code start. A confirmed `--join` also ends Privacy mode. |
| `--leave` | The same as `--privacy on`. |
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
- **Listed by default, off in one command.** Joining lists you from your second day of check-ins; `--world off` takes you off at once, and Privacy mode (`--privacy on`) deletes the row.
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

**Does it know who I am?**
No. It's pseudonymous: no account, no name, no e-mail, and the board never stores your IP address. Your creature is a made-up name tied to a random key on your machine. The catch: if you post your card or creature name publicly, or turn on the GitHub badge, people can match it to you. Want nothing sent at all? Privacy mode: `/pet privacy on`.

**Why does the plugin talk to go.cclevel.workers.dev?**
That is the board's check-in address; the website is cclevel.com. Like every site on Cloudflare, cclevel.com keeps a sample of visits with IP addresses for at least 31 days, and we cannot switch that off. Check-ins go to the workers.dev address instead, where no such log exists, so they never sit in one.

**Can people cheat?**
On their own card, yes. It is self-reported, for fun, and not a credential. The board limits what cheating buys: it ranks only XP it watched you earn, at most 550 a day, and marks suspicious patterns as sus.

**Does it slow down Claude Code or run in the background?**
Hardly. Two things run on their own. In Default mode, a hook starts one quick check-in a day when Claude Code starts (the first one joins the board), then reads your own private group for the Mac panel (again at later starts, at most every 15 minutes, while the panel is installed and you are in a group), without holding it up; in Privacy mode, or after `/pet auto off`, it sends nothing. The creature band above your prompt rescores your setup offline, in the background, when its last score is more than an hour old (about ten seconds of work on a big setup); `/creature off` stops the band and its rescoring. If you turn on the Mac menu bar panel, it keeps running too and rescores the same way, at most once an hour (and right after `/pet panel on` updates it, or a check-in or group read saves something new); `/pet panel off` removes it. With auto-update on (Default mode turns it on at your first card), Claude Code itself checks GitHub for a new cclevel once a session and installs it; `/pet autoupdate off` stops that.

**Can I see my friends in the Mac panel?**
Yes, in Default mode. The panel's Friends page has your group's invite link with a Copy button, and each friend's creature, level and XP this week. The panel itself makes no network call: it shows the copy saved by the daily check-in, a later Claude Code start (at most every 15 minutes) or `/pet group`, and hides it after 36 hours. A friend who just left, or turned Privacy mode on, can still show on your panel until your next refresh. In Privacy mode cclevel sends nothing, and the Friends page says friends are off.

**Does it read my prompts?**
It reads your Claude Code folder to count things (days, tokens, tools used, prompt timestamps). Nothing from your prompts, code or file names is printed, stored or sent.

If you use Claude's Cowork on the same Mac, it also reads the session logs of Cowork's tasks, and nothing else of Cowork's (not its memory, settings, sign-in, uploads or outputs). Cowork work counts like Claude Code work, as one project, from the day your card first saves on version 0.22.0 and within the last 30 days. Older Cowork work is not added, so nobody's board row jumps. Nothing new is sent. In Default mode a check-in carries the same nine numbers and badge codes as before, now including Cowork work. In Privacy mode cclevel sends nothing, as always.

**Why are invite links shown in full inside Claude Code?**
So you can copy one. A link shown or pasted in a conversation becomes part of that chat's history. A link only grants a seat in that group, and you can always start a new group.

**What is Privacy mode?**
The other of the two modes. Default mode has the board on: your creature is ranked, and groups, duels and the GitHub badge work. Privacy mode, `/pet privacy on`, deletes your row and from then on cclevel sends nothing at all; a share-card, Wrapped or invite link you open in a browser still loads its page from cclevel.com, and that visit (not the numbers after `#`, which stay in your browser) may be in Cloudflare's sampled visit logs, with your IP address, for at least 31 days. You keep the card, the creature above your prompt, the menu bar panel, tips, lessons and Wrapped; you give up the board, groups, duels, `/pet rank` and the badge. If your first card turned on Claude Code's auto-update, Privacy mode turns it off again; one you turned on yourself stays. `/pet privacy off` shows what Default mode sends and asks before switching back.

**How do I opt out, or get off the board?**
`/pet privacy on` (or `/pet leave`, the same). One command, before or after the plugin joins you: your row, if there is one, is deleted at once and the plugin never joins again by itself (`/pet privacy off` or `/pet join` brings you back); the database host's backups age out after up to 30 days (7 on the free plan).

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
