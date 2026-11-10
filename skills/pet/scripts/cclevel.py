#!/usr/bin/env python3
"""cclevel: score a Claude Code setup and show it as a creature that grows.

Reads the local Claude Code folder. Writes nothing except its own files in
<claude dir>/cclevel/. A score covers one machine and is self-reported.

The card is fully offline, and so are --card, which only prints a link, and
the opt-in training (--learn, --tips), which is text shipped here. The
network is used only by --join, --sync, --world, the --group and --duel
commands, the GitHub badge commands, --leave and --rank, and by the
plugin's session-start hook (--auto-run): it joins the board once on a
machine that has not opted out (--leave), then checks in once a day while
auto check-in is on; and only for what payload() returns, the world
choice, a group or duel invite code and a GitHub login with the hash of a
code.
"""
import argparse
import contextlib
import csv
import errno
import fcntl
import getpass
import glob
import hashlib
import http.client
import io
import json
import math
import os
import plistlib
import re
import secrets
import shutil
import subprocess
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

# ------------------------------------------------------------------ scale
# First-draft numbers, tuned on very few setups. Every number and every name the scoring uses sits
# in this block and the next one. Nothing further down hard-codes either.

TOKEN_WEIGHT = {
    "output_tokens": 5,
    "input_tokens": 1,
    "cache_creation_input_tokens": 1.25,
    "cache_read_input_tokens": 0.1,
}

# XP for one finished day. Days are UTC dates, so travelling does not move them.
XP_SHOW = 100                # any session that day
XP_EAT_MAX = 150             # that day's weighted tokens, log scale
EAT_FULL_MTOK = 100          # million weighted tokens that earn the full eating XP
XP_ARSENAL_EACH, XP_ARSENAL_MAX = 10, 100   # per distinct skill, connector or subagent type
XP_COMMIT, XP_PR, EDITS_PER_XP, XP_SHIP_MAX = 5, 20, 10, 100
XP_LOOP_EACH, XP_LOOP_MAX = 25, 100         # per unattended session
DAY_CAP = 550                # the five parts above add up to exactly this
# A day whose logs are gone is valued from its prompt count alone, by one fixed formula that is the
# same for everyone: XP_SHOW + XP_OLD_MAX * log(1 + prompts) / log(1 + OLD_FULL_PROMPTS).
XP_OLD_MAX, OLD_FULL_PROMPTS = 300, 100
LEVEL_DIVISOR, LEVEL_MAX = 40, 99           # level = floor(sqrt(xp / 40))

# stat -> signal -> (value that earns 100, weight inside the stat[, unit])
# The legend values are meant to be the far end of what one person can reach.
# unit is the size at which a signal starts to count (default 1).
STATS = {
    "grind": {     # showing up: days out of the last 30, and streaks
        "active_days_30d": (30, 0.5), "current_streak": (100, 0.25), "longest_streak": (365, 0.25),
    },
    "appetite": {  # tokens only: sessions and prompts would count the same thing again
        "mtok_30d": (10000, 1.0, 10),
    },
    "arsenal": {   # 80% used, 20% installed
        "skills_used": (150, 0.4), "connectors_used": (40, 0.2), "agent_types_used": (25, 0.2),
        "skills_installed": (500, 0.08), "agents_installed": (50, 0.04),
        "connectors_installed": (60, 0.04), "plugins_installed": (30, 0.04),
    },
    "autonomy": {  # what runs without the owner
        "auto_sessions_30d": (1500, 0.35), "auto_days_30d": (30, 0.25),
        "longest_run": (1000, 0.25), "jobs": (40, 0.15),
    },
    "craft": {
        "edits_30d": (15000, 0.3), "commits_30d": (1500, 0.25), "prs_30d": (600, 0.2),
        "pages_30d": (500, 0.1), "projects_30d": (60, 0.15),
    },
}
LINEAR = {"active_days_30d", "auto_days_30d"}   # counts with a hard ceiling climb in a straight line
STAT_STEP = 5                # stats move in steps of 5: anything finer would be false precision
STAT_ORDER = ("grind", "appetite", "arsenal", "brains", "autonomy", "craft")

# Brains: ten checks of wiring that is in use. Each line is worded as the thing that is missing.
# Two can be passed by having a file (the first and the seventh). The other eight need activity:
# skills within USED_WINDOW_DAYS, everything else seen in the logs within RECENT_WINDOW_DAYS.
BRAINS = [
    "an instructions file (CLAUDE.md)",
    "memory written by a session in the last 30 days",
    "three own skills in use",
    "an own skill with its own scripts or references in use",
    "two or more kinds of subagent in use",
    "a checker in use (a verify, review, test or audit agent or skill)",
    "a guardrail (a deny rule, or a hook that runs before tools)",
    "a hook that ran when a turn ended",
    "a second model doing real work (2% of replies or more)",
    "plan mode in use",
]
OWN_SKILLS_IN_USE, SUBAGENT_KINDS, SECOND_MODEL_SHARE = 3, 2, 0.02
MEMORY_FOLDER = "/memory/"   # a file written under a folder of this name counts as memory
# A checker is an agent or skill with one of these words in its name.
CHECKER_WORDS = {"verify", "verifier", "verification", "review", "reviews", "reviewer", "audit", "audits", "auditor",
                 "test", "tests", "tester", "testing", "tdd", "qa", "check", "checker"}

# One-off XP: a hook that ran, an own skill used, a subagent spawned, an unattended session,
# days in a row, and distinct skills ever used.
BADGES = {
    "first_hook": 250, "first_skill": 250, "first_subagent": 250, "first_loop": 500,
    "streak_7": 200, "streak_30": 1000, "streak_100": 3000,
    "skills_10": 200, "skills_50": 1000, "skills_100": 3000,
}
BADGE_STREAKS = {"streak_7": 7, "streak_30": 30, "streak_100": 100}
BADGE_SKILLS = {"skills_10": 10, "skills_50": 50, "skills_100": 100}

# Health starts at 100 and loses points for each of these.
PENALTY_UNUSED_MAX = 40          # times the share of own skills unused for 90 days
PENALTY_SIGN_IN_EACH, PENALTY_SIGN_IN_MAX = 2, 20
CONTEXT_OK, CONTEXT_HEAVY, PENALTY_CONTEXT_MAX = 15000, 60000, 20   # start-up tokens
PENALTY_ERRORS_MAX, PENALTY_INTERRUPTS_MAX = 10, 10
ERROR_POINTS, INTERRUPT_POINTS = 100, 50     # points lost per unit of failure rate and of interruption rate
# Logs are deleted after 30 days by default, so every log-based signal uses
# 30 days for everyone. Skill use comes from Claude Code's own counters and
# can look back 90.
USED_WINDOW_DAYS, RECENT_WINDOW_DAYS = 90, 30

# ------------------------------------------------------------------ names
# The arithmetic above is plain. The names are internet, on purpose. They never travel over the
# network as text the client must understand, so any of them can be changed here at any time.
STAGES = [(60, "GOAT"), (45, "Gigachad"), (30, "Big Guy"), (15, "Lil Guy"), (5, "Hatchling"), (1, "Egg")]
# The class is the strongest of the four things a setup does. Grind and Brains never set it.
CLASSES = {"craft": "Shipper", "autonomy": "AFK Farmer", "arsenal": "Loot Goblin", "appetite": "Tokenmaxxer"}
BALANCED, NOOB, UNHATCHED = "Perfectly Balanced", "Noob", "Unhatched"
CLASS_FLOOR = 30             # below this no stat is strong enough to be a class
BALANCED_SPREAD = 10         # the four within this many points, all above the floor: Perfectly Balanced
BRAIN_TITLES = [(80, "Galaxy Brain"), (50, "Big Brain"), (30, "Wrinkly Brain")]   # Brains moves in tens; no title under 30
AURA = "Aura"                # the six stats added up
BADGE_NAMES = {
    "first_hook": "Hooked", "first_skill": "Skill issue: solved", "first_subagent": "Not my job",
    "first_loop": "AFK gains", "streak_7": "gm x7", "streak_30": "No days off", "streak_100": "Terminally online",
    "skills_10": "Loadout", "skills_50": "Full kit", "skills_100": "Maxed out",
}
# Moods. In use, Health decides; after that, the days without a session do.
HEALTH_GOOD, HEALTH_BAD = 80, 50
IDLE_GRASS, IDLE_GHOST, IDLE_OVER = 3, 14, 60
COMEBACK_GAP, COMEBACK_DAYS = 14, 3     # back after two idle weeks: the comeback mood, for three days
MOODS = {
    "good": "Locked in", "fine": "Vibing", "bad": "Cooked", "back": "We're so back",
    "grass": "Touching grass", "ghost": "Ghosting", "over": "It's so over", "none": "Not hatched yet",
}
QUIPS = {"unused_skills": "Skill issue", "heavy_context": "Certified chonk", "no_needs": "Touch grass"}

# --------------------------------------------------------------- training
# Opt-in learning: --learn shows the lessons, --tips on adds a how-to under each Need and a tip a day.
# All of it is text shipped with the scanner, and none of it is ever sent. It teaches; it never changes a score.
# Claude Code changes fast, so every line names its docs page. Facts checked against the docs on TIPS_CHECKED.
DOCS = "https://code.claude.com/docs/en/"
TIPS_CHECKED = "2026-10-21"
# How to fix each item the Needs list can show: (what to do, docs page).
HOWTO = {
    "unused_skills": ("move them out of ~/.claude/skills (or commands); moving one back restores it", "skills"),
    "sign_in": ("type /mcp to see each connector and sign in; remove the ones you never use", "mcp"),
    "heavy_context": ("type /context to see what fills it; move long how-tos from CLAUDE.md into skills", "memory"),
    "tool_errors": ("ask Claude why its last tool calls failed; /doctor checks the install", "commands"),
    "interrupts": ("agree a plan first with /plan; Esc Esc rewinds instead of stopping halfway", "common-workflows"),
    "brains_1": ("open a project and type /init: it writes a starter CLAUDE.md", "memory"),
    "brains_2": ("auto memory is on by default (check with /memory); ask Claude to remember a rule", "memory"),
    "brains_3": ("ask Claude to turn a task you repeat into a skill in ~/.claude/skills/<name>/SKILL.md", "skills"),
    "brains_4": ("put a script next to the skill's SKILL.md and say in the skill when to run it", "skills"),
    "brains_5": ("ask Claude to create a subagent (saved in ~/.claude/agents/), or to use Explore", "sub-agents"),
    "brains_6": ("ask Claude to create a code-reviewer subagent and use it after each change", "sub-agents"),
    "brains_7": ("add a deny rule such as Read(./.env) to permissions.deny; /permissions shows them", "permissions"),
    "brains_8": ("type /hooks and add a Stop hook, for example a sound when Claude finishes", "hooks-guide"),
    "brains_9": ("set model: haiku in a subagent's frontmatter so small jobs run on a smaller model", "sub-agents"),
    "brains_10": ("press Shift+Tab until the status bar says plan mode on, or type /plan", "common-workflows"),
}
# The training path: five lessons per stat, easiest first. A lesson is ticked by what the logs and the setup show,
# never by a claim (score() decides), and once ticked it stays ticked. (id, lesson, how, docs page)
LESSONS = {
    "grind": [
        ("g_days2", "Come back on a second day", "claude --continue picks up the last conversation in a folder", "sessions"),
        ("g_resume", "Reopen an older conversation", "type /resume and pick one from the list", "sessions"),
        ("g_streak7", "Use it 7 days in a row", "small jobs count: explain a file, write a commit message, review a diff", "common-workflows"),
        ("g_days15", "Use it on 15 of the last 30 days", "start the day by asking what changed in the repo since yesterday", "common-workflows"),
        ("g_streak30", "Keep a 30-day streak", "turn what you repeat into skills, so each day starts faster", "skills"),
    ],
    "appetite": [
        ("a_context", "See what fills the context", "type /context: it shows how the context window is used", "sessions"),
        ("a_compact", "Compact on your own terms", "type /compact and what to keep, e.g. /compact keep the open questions", "sessions"),
        ("a_model", "Pick the model for the job", "type /model and choose; a smaller model is fine for small edits", "commands"),
        ("a_usage", "Check your usage", "type /usage to see what you have used", "commands"),
        ("a_lean", "Keep a CLAUDE.md, and start-up context under 15k tokens",
         "keep CLAUDE.md to the rules; long how-tos go into skills, which load only when used", "memory"),
    ],
    "arsenal": [
        ("r_skill", "Use a skill", "type / to see your commands and skills, and run one", "skills"),
        ("r_connector", "Use a connector (MCP)", "add one with claude mcp add, sign in with /mcp, then ask Claude to use it", "mcp"),
        ("r_own", "Make a skill of your own and use it", "ask Claude to turn a task you repeat into a skill", "skills"),
        ("r_own_script", "Give one of your skills its own script") + HOWTO["brains_4"],
        ("r_ten", "Use 10 different skills", "type /plugin to browse plugins with skills other people made", "commands"),
    ],
    "brains": [
        ("b_claude_md", "Write a CLAUDE.md") + HOWTO["brains_1"],
        ("b_plan", "Plan before you build") + HOWTO["brains_10"],
        ("b_memory", "Let it remember") + HOWTO["brains_2"],
        ("b_guardrail", "Add a guardrail") + HOWTO["brains_7"],
        ("b_stop_hook", "Run a hook when a turn ends") + HOWTO["brains_8"],
    ],
    "autonomy": [
        ("u_subagent", "Hand a job to a subagent", "ask Claude to use the Explore subagent to search the code", "sub-agents"),
        ("u_two_kinds", "Use two kinds of subagent") + HOWTO["brains_5"],
        ("u_second_model", "Put a second model to work") + HOWTO["brains_9"],
        ("u_headless", "Run it without a chat", "claude -p \"summarise today's git log\" runs once and prints the answer", "headless"),
        ("u_scheduled", "Put it on a schedule", "call claude -p from cron or launchd for a job that runs by itself", "headless"),
    ],
    "craft": [
        ("c_edit", "Let Claude edit a file", "ask for one small change and accept the edit", "common-workflows"),
        ("c_commit", "Let Claude commit", "ask Claude to commit, with a message that says why", "common-workflows"),
        ("c_pr", "Open a pull request", "with the GitHub CLI (gh) signed in, ask Claude to open a pull request", "common-workflows"),
        ("c_checker", "Get your work checked") + HOWTO["brains_6"],
        ("c_worktree", "Work in two places at once", "claude --worktree <name> starts a session in its own git worktree",
         "common-workflows"),
    ],
}
# Tips of the day, by stat: extras the lessons do not cover. (id, tip, docs page)
TIPS = {
    "grind": [
        ("t_rewind", "Esc Esc on an empty prompt opens rewind: go back and restore the code or the chat", "checkpointing"),
        ("t_bang", "start a prompt with ! to run a shell command yourself, without a turn for Claude", "interactive-mode"),
        ("t_at", "type @ and a path to put a file or a folder straight into the conversation", "common-workflows"),
        ("t_resume_flag", "claude -r opens the list of past conversations before the session starts", "cli-reference"),
        ("t_statusline", "/statusline sets up a status line under the prompt", "commands"),
    ],
    "appetite": [
        ("t_clear", "/clear starts an empty conversation: use it between unrelated tasks", "sessions"),
        ("t_subagent_context", "a subagent works in its own context window, so a big search does not fill yours", "sub-agents"),
        ("t_skill_load", "a skill's full text loads only when it is used, so a long how-to costs less as a skill than in CLAUDE.md",
         "skills"),
        ("t_model_session", "in the /model picker, s switches the model for this session only", "commands"),
    ],
    "arsenal": [
        ("t_skill_desc", "a skill's description decides when Claude loads it: say what it does and when to use it", "skills"),
        ("t_project_skills", "skills in a repo's .claude/skills/ come with the repo, for everyone who clones it", "skills"),
        ("t_skill_slash", "every skill can also be run by hand: type / and its name", "skills"),
        ("t_mcp_http", "claude mcp add --transport http <name> <url> adds a remote connector", "mcp"),
        ("t_marketplace", "claude plugin marketplace add owner/repo adds a plugin marketplace from GitHub",
         "plugins/marketplace-reference"),
    ],
    "brains": [
        ("t_memory_cmd", "/memory shows which CLAUDE.md and memory files are loaded, and switches auto memory on or off", "memory"),
        ("t_pretool_block", "a PreToolUse hook can stop a tool call: exit code 2 blocks it", "hooks"),
        ("t_deny_first", "deny rules are checked first, so one deny line protects a file even when much else is allowed",
         "permissions"),
        ("t_init_again", "/init on a project that has a CLAUDE.md suggests changes instead of overwriting it", "commands"),
        ("t_hooks_browser", "/hooks opens a browser of every hook you have", "hooks-guide"),
    ],
    "autonomy": [
        ("t_ctrl_b", "Ctrl+B sends a running shell command to the background so you can keep working", "interactive-mode"),
        ("t_github_app", "/install-github-app lets you tag @claude in a GitHub issue or pull request", "github-actions"),
        ("t_exit_code", "claude -p exits with code 0 when it succeeds, so a script can check the result", "headless"),
        ("t_plan_flag", "claude --permission-mode plan starts a session already in plan mode", "common-workflows"),
        ("t_accept_edits", "Shift+Tab cycles modes; accept-edits mode applies file edits without asking each time",
         "interactive-mode"),
    ],
    "craft": [
        ("t_security_review", "/security-review checks your pending changes for security problems", "commands"),
        ("t_code_review", "/code-review (or /review) reviews your changes before you push", "commands"),
        ("t_bash_not_rewound", "rewind does not undo changes made by shell commands, so commit before a risky step",
         "checkpointing"),
    ],
}
WORKTREE_MARK = "-claude-worktrees-"   # a session started in <repo>/.claude/worktrees/<name> logs under a folder with this

ART = {
    "Egg": [r"   ___   ", r"  /   \  ", r" |  .  | ", r"  \___/  "],
    "Hatchling": [r"   ___   ", r"  /o o\  ", r" _\_^_/_ ", r"  '   '  "],
    "Lil Guy": [r"  .-^-.  ", r" ( o o ) ", r"  \ ~ /  ", r"  /| |\  "],
    "Big Guy": [r"  .-^-.  ", r" ( o o ) ", r" /\ ~ /\ ", r"  /| |\  "],
    "Gigachad": [r" \.-^-./ ", r" ( o o ) ", r" /\ = /\ ", r" _/| |\_ "],
    "GOAT": [r"*\.-^-./*", r" ( @ @ ) ", r"</\ = /\>", r" _/| |\_ "],
}

# Markings: each creature's own look, from a number made on this machine the first time a run saves (the seed file).
# look = seed mod 64 picks an eye style, a mouth and a crest (the Egg's shell mark); (seed / 64) mod 100 == 0 is shiny,
# 1 in 100. Look 0, not shiny, is the classic art above. Every slot swaps one character, so each line stays 9 wide.
# These must match server/public/card.js; a test checks them.
LOOKS = 64
SHINY_ODDS = 100
SEED_RE = re.compile(r"[0-9a-f]{16}")
EYES = "o.O0"                      # GOAT keeps its @ eyes
MOUTHS = "wv-"                     # after the stage's own mouth (^, ~ or =)
CRESTS = {"Egg": ".:o~", "Hatchling": "_^.~"}   # the rest: "^~='"
MARK_SLOTS = {                     # (line, column) of the eyes, the mouth and the crest
    "Egg": {"crest": (2, 4)},
    "Hatchling": {"eyes": [(1, 3), (1, 5)], "mouth": (2, 4), "crest": (0, 4)},
    "Lil Guy": {"eyes": [(1, 3), (1, 5)], "mouth": (2, 4), "crest": (0, 4)},
    "Big Guy": {"eyes": [(1, 3), (1, 5)], "mouth": (2, 4), "crest": (0, 4)},
    "Gigachad": {"eyes": [(1, 3), (1, 5)], "mouth": (2, 4), "crest": (0, 4)},
    "GOAT": {"mouth": (2, 4), "crest": (0, 4)},
}
SHINY_MARK = "\u2726 Shiny"


def marks_of(seed):
    """The look (0-63) and whether it is shiny, from the seed as a number, or the classic look for None."""
    if seed is None:
        return {"look": 0, "shiny": False}
    return {"look": seed % LOOKS, "shiny": (seed // LOOKS) % SHINY_ODDS == 0}


def marked_art(stage, look=0, shiny=False):
    """The stage's art with its markings. Shiny adds two twinkles: "*" corners, or "+" for the GOAT, which has "*" already."""
    lines = [list(line) for line in ART[stage]]
    slots = MARK_SLOTS[stage]
    eye, mouth, crest = look % 4, look // 4 % 4, look // 16 % 4
    if eye and "eyes" in slots:
        for row, col in slots["eyes"]:
            lines[row][col] = EYES[eye]
    if mouth and "mouth" in slots:
        row, col = slots["mouth"]
        lines[row][col] = MOUTHS[mouth - 1]
    if crest:
        row, col = slots["crest"]
        lines[row][col] = CRESTS.get(stage, "^~='")[crest]
    if shiny:
        for row, col in ([(3, 0), (3, 8)] if stage == "GOAT" else [(0, 8), (3, 0)]):
            lines[row][col] = "+" if stage == "GOAT" else "*"
    return ["".join(line) for line in lines]


def seed_path(cdir):
    return os.path.join(cdir, "cclevel", "seed")


def read_seed(cdir):
    """The seed as a number, or None: no file, a link, a folder or anything but 16 hex digits all mean the classic look."""
    path = seed_path(cdir)
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        with open(path, encoding="ascii") as f:
            text = f.read(64).strip()
    except (OSError, ValueError):
        return None
    return int(text, 16) if SEED_RE.fullmatch(text) else None


def creature_marks(cdir, save):
    """This creature's markings. A run that saves makes the seed once, if nothing is at its place yet; it is never
    rewritten, and a run that does not save only reads it. Kept apart from identity.json, which Privacy mode deletes."""
    seed = read_seed(cdir)
    if seed is None and save and not os.path.lexists(seed_path(cdir)):
        try:
            os.makedirs(os.path.dirname(seed_path(cdir)), exist_ok=True)
            text = secrets.token_hex(8)
            write_private(seed_path(cdir), text + "\n")
            seed = int(text, 16)
        except OSError:
            seed = None
    return marks_of(seed)


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FIRST_YEAR = 2025            # Claude Code's first public release: no Wrapped before it
THIS_YEAR = object()         # what --wrapped means without a YEAR (not a string, so argparse leaves it as it is)

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
WEEK_RE = re.compile(r"\d{4}-W(0[1-9]|[1-4]\d|5[0-3])")   # ISO weeks run 01 to 53
GIT_COMMIT_RE = re.compile(r"\bgit\s+commit\b")
COMMAND_RE = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
HOOK_COUNT_RE = re.compile(r'"hookCount":(\d+)')


# ---------------------------------------------------------------- reading

def load_json(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except (OSError, ValueError, RecursionError):   # RecursionError: a file nested too deeply to decode
        return None


def load_dict(path):
    data = load_json(path)
    return data if isinstance(data, dict) else {}


def as_dict(v):
    return v if isinstance(v, dict) else {}


def num(v):
    """A sane number from a file or a reply this script does not control, or 0."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0
    if isinstance(v, float) and not math.isfinite(v):
        return 0
    return v if abs(v) <= 1e15 else 0


def is_day(s):
    try:
        date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def read_head(path, limit=4000):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except OSError:
        return ""


def day_of(ts):
    """UTC calendar day (YYYY-MM-DD) for an ISO string or epoch milliseconds."""
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, timezone.utc).date().isoformat()
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date().isoformat()
    except (AttributeError, ValueError, OSError, OverflowError):
        return None


def frontmatter(text):
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end > 0 else text[3:]


def field(fm, name):
    """Value of a frontmatter field, including an indented continuation block."""
    m = re.search(r"^%s:[ \t]*(.*(?:\n[ \t]+.*)*)" % name, fm, re.M)
    return m.group(1).strip() if m else ""


def is_checker(name):
    """True for an agent or skill whose name says it checks work: code-reviewer, verify-impl, webapp-testing."""
    return any(part in CHECKER_WORDS for part in re.split(r"[^a-z0-9]+", str(name).lower()))


def count(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def merged_lists(a, b):
    """Two settings blocks joined, keeping only their list values (hooks per event, permission rules)."""
    out = {}
    for src in (a, b):
        for k, v in src.items() if isinstance(src, dict) else []:
            if isinstance(v, list):
                out[k] = out.get(k, []) + v
    return out


def new_day():
    return {"tok": Counter(), "models": Counter(), "skills": set(), "servers": set(), "servers_called": set(), "agents": set(),
            "auto": set(), "sessions": set(), "projects": set(), "pages": set(),
            "commands": set(), "edits": 0, "commits": 0, "prs": 0, "spawns": 0, "tools": 0,
            "errors": 0, "interrupts": 0, "turns": 0, "plan": 0, "hooks_ran": 0, "memory_writes": 0, "compacts": 0,
            "worktrees": 0}


def scan_history(cdir):
    """Prompts per day. This file outlives the 30-day log clean-up."""
    per_day = Counter()
    try:
        with open(os.path.join(cdir, "history.jsonl"), encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    day = day_of(json.loads(line).get("timestamp"))
                except (ValueError, AttributeError):
                    continue
                if day:
                    per_day[day] += 1
    except OSError:
        pass
    return per_day


def earns(name, inp):
    """What one tool call adds to its day once it has worked, as (field, value) pairs: a number adds up, a name joins
    the day's set. Small on purpose, so the call's input (a Write holds a whole file) is never kept."""
    if name == "Skill":
        return (("skills", str(inp.get("skill"))),)
    if name in ("Agent", "Task"):
        return (("spawns", 1), ("agents", str(inp.get("subagent_type") or "general-purpose")))
    if name.startswith("mcp__"):
        return (("servers", name.split("__")[1]),)
    if name in EDIT_TOOLS:
        return (("edits", 1), ("memory_writes", int(MEMORY_FOLDER in str(inp.get("file_path", "")).replace("\\", "/"))))
    if name == "Bash":
        cmd = str(inp.get("command", ""))
        return (("commits", int(bool(GIT_COMMIT_RE.search(cmd)))), ("prs", int("gh pr create" in cmd)))
    if name == "Artifact" and inp.get("file_path") and not inp.get("asset") and inp.get("action") in (None, "publish"):
        return (("pages", str(inp["file_path"])),)
    if name == "ExitPlanMode":
        return (("plan", 1),)
    if name == "EnterWorktree":
        return (("worktrees", 1),)
    return ()


def failed_ids(line):
    """The ids of the tool calls a result line marks as failed. Only Claude Code's is_error flag counts, never the
    result's text: a call that worked can still print something that starts with "Error"."""
    try:
        o = json.loads(line)
    except (ValueError, RecursionError):
        return []
    content = as_dict(as_dict(o).get("message")).get("content")
    return [str(b.get("tool_use_id")) for b in content if isinstance(b, dict) and b.get("type") == "tool_result"
            and b.get("is_error") is True] if isinstance(content, list) else []


def scan_logs(cdir, skill_names, extra=None):
    """Per-day activity from session logs. Returns (days, longest unattended run). Given a dict, `extra` also gets what
    the leak finder needs, from the same pass: each reply's usage with its time and log file, every compaction and
    Claude Code's own cost figure per log. The card's numbers do not depend on it."""
    days = defaultdict(new_day)
    best = {}            # (message id, request id) -> (output tokens, day, usage)
    when = {}            # the same key -> (time, log file), for the leak finder only
    seen_tools = set()
    pending = {}         # tool call id -> (day, what it earns once it has worked)
    failed = set()       # ids of the tool calls whose result is marked as an error
    longest = 0
    root = os.path.join(cdir, "projects")
    files = glob.glob(os.path.join(root, "*", "*.jsonl")) + \
        glob.glob(os.path.join(root, "*", "*", "subagents", "**", "*.jsonl"), recursive=True)
    for path in files:
        sub = os.sep + "subagents" + os.sep in path
        project = os.path.relpath(path, root).split(os.sep)[0]
        day, run = None, set()
        try:
            fh = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"type":"assistant"' in line:
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    m = o.get("message") if isinstance(o, dict) else None
                    if not isinstance(m, dict) or o.get("type") != "assistant":
                        continue
                    day = day_of(o.get("timestamp")) or day
                    if not day:
                        continue
                    d = days[day]
                    u = m.get("usage")
                    # The same message is written once per content block, so
                    # keep one usage record per message: the most complete one.
                    if isinstance(u, dict) and m.get("model") != "<synthetic>":
                        key = (str(m.get("id")), str(o.get("requestId")))
                        out = num(u.get("output_tokens"))
                        if key not in best or out > best[key][0]:
                            best[key] = (out, day, u, m.get("model"))
                            if extra is not None:
                                when[key] = (str(o.get("timestamp") or ""), path)
                    session = str(o.get("sessionId"))
                    if not sub:
                        run.add(str(m.get("id")))
                        d["sessions"].add(session)
                    # Unattended once Claude has really answered: Claude Code's own error reply ("Invalid API key")
                    # is written as a <synthetic> one.
                    if str(o.get("entrypoint") or "").startswith("sdk") and m.get("model") != "<synthetic>":
                        d["auto"].add(session)
                    d["projects"].add(project)
                    content = m.get("content")
                    for b in content if isinstance(content, list) else []:
                        if not isinstance(b, dict) or b.get("type") != "tool_use" or str(b.get("id")) in seen_tools:
                            continue
                        seen_tools.add(str(b.get("id")))
                        name = str(b.get("name") or "")
                        d["tools"] += 1
                        if name.startswith("mcp__"):
                            d["servers_called"].add(name.split("__")[1])   # for the leak finder: called, worked or not
                        what = earns(name, b.get("input") if isinstance(b.get("input"), dict) else {})
                        if what:
                            pending[str(b.get("id"))] = (day, what)
                elif '"type":"user"' in line:
                    if '"tool_result"' in line:
                        if '"is_error":true' in line:
                            if day:
                                days[day]["errors"] += 1
                            failed.update(failed_ids(line))
                        continue
                    if sub:
                        continue
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(o, dict) or o.get("type") != "user" or o.get("isMeta") or o.get("isSidechain"):
                        continue
                    day = day_of(o.get("timestamp")) or day
                    if not day:
                        continue
                    c = as_dict(o.get("message")).get("content")
                    if isinstance(c, list):
                        c = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
                    text = c if isinstance(c, str) else ""
                    if "[Request interrupted by user" in text:
                        days[day]["interrupts"] += 1
                        continue
                    for name in COMMAND_RE.findall(text):
                        days[day]["commands"].add(name)   # kept for the training path; never shown or sent
                        if name in skill_names or ":" in name:
                            days[day]["skills"].add(name)
                    days[day]["turns"] += 1
                    longest = max(longest, len(run))
                    run = set()
                elif day and '"type":"permission-mode"' in line and '"permissionMode":"plan"' in line:
                    days[day]["plan"] += 1
                elif day and '"subtype":"stop_hook_summary"' in line:
                    ran = HOOK_COUNT_RE.search(line)
                    days[day]["hooks_ran"] += bool(ran and int(ran.group(1)) > 0)
                elif day and '"subtype":"local_command"' in line:
                    days[day]["commands"].update(COMMAND_RE.findall(line))   # some commands are logged only here
                elif day and '"subtype":"compact_boundary"' in line:
                    days[day]["compacts"] += '"trigger":"manual"' in line   # /compact typed, not the automatic one
                if extra is not None and ('"subtype":"compact_boundary"' in line or '"type":"cost-state"' in line):
                    leak_line(extra, line, path)
        longest = max(longest, len(run))
    # A tool call earns its part only once it has worked: a result marked as an error means it earns nothing. A call
    # whose result has not come back yet counts for now; if its day is banked before the result comes, the credit stays.
    for call, (day, what) in pending.items():
        if call not in failed:
            d = days[day]
            for field_name, value in what:
                if isinstance(d[field_name], set):
                    d[field_name].add(value)
                else:
                    d[field_name] += value
    if extra is not None:
        extra["requests"] = [{"day": day, "time": when[k][0], "file": when[k][1], "model": str(model), "usage": u}
                             for k, (_, day, u, model) in best.items()]
    for _, day, u, model in best.values():
        days[day]["models"][str(model)] += 1
        for k in TOKEN_WEIGHT:
            days[day]["tok"][k] += num(u.get(k))
    return dict(days), longest


def scan_setup(cdir, cfg, settings, leak=None):
    """What is installed and how it is wired. Names stay in memory; only counts leave, except into `leak`, the leak
    finder's own dict, which gets the connector names and the parts of the start-up context."""
    skills = {}
    for base in ("commands", "skills"):
        for path in glob.glob(os.path.join(cdir, base, "*", "SKILL.md")):
            folder = os.path.dirname(path)
            desc = field(frontmatter(read_head(path)), "description")
            try:
                extra = len(os.listdir(folder)) > 1
            except OSError:
                extra = False
            try:
                age = (datetime.now().timestamp() - os.path.getmtime(path)) / 86400
            except OSError:
                age = 0
            skills[os.path.basename(folder)] = {"desc": len(desc), "extra": extra, "age_days": age}
    agents = []
    for path in glob.glob(os.path.join(cdir, "agents", "*.md")):
        fm = frontmatter(read_head(path))
        agents.append({"name": os.path.basename(path)[:-3], "model": field(fm, "model"),
                       "tools": bool(field(fm, "tools"))})
    plugins = as_dict(load_dict(os.path.join(cdir, "plugins", "installed_plugins.json")).get("plugins"))
    plugin_skills = 0
    for installs in plugins.values():
        for inst in installs if isinstance(installs, list) else [installs]:
            root = as_dict(inst).get("installPath")
            if isinstance(root, str):
                plugin_skills += len(glob.glob(os.path.join(root, "**", "SKILL.md"), recursive=True))
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    hook_events = {e: sum(len(g["hooks"]) for g in gs if isinstance(g, dict) and isinstance(g.get("hooks"), list))
                   for e, gs in hooks.items() if isinstance(gs, list)}
    hook_events = {e: n for e, n in hook_events.items() if n}
    perms = settings.get("permissions") if isinstance(settings.get("permissions"), dict) else {}
    projects = cfg.get("projects") if isinstance(cfg.get("projects"), dict) else {}
    connectors = set(as_dict(cfg.get("mcpServers")))
    ever = cfg.get("claudeAiMcpEverConnected")
    connectors |= {c for c in ever if isinstance(c, str)} if isinstance(ever, list) else set()
    for p in projects.values():
        connectors |= set(as_dict(as_dict(p).get("mcpServers")))
    memory = glob.glob(os.path.join(cdir, "projects", "*", "memory", "*.md")) + \
        glob.glob(os.path.join(cdir, "memory", "*.md"))
    index_size = max([os.path.getsize(p) for p in memory if os.path.basename(p) == "MEMORY.md"] or [0])
    claude_md = os.path.join(cdir, "CLAUDE.md")
    claude_md_size = os.path.getsize(claude_md) if os.path.isfile(claude_md) else 0
    if leak is not None:
        here = [os.path.join(os.getcwd(), n) for n in ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md"))]
        leak["context"] = {"claude_md": claude_md_size // 4, "memory_index": index_size // 4,
                            "skill_descriptions": sum(s["desc"] for s in skills.values()) // 4,
                            "project_claude_md": sum(os.path.getsize(p) for p in here if os.path.isfile(p)) // 4}
        leak["connectors"] = {c: c for c in connectors}
        for key, installs in plugins.items():
            for inst in installs if isinstance(installs, list) else [installs]:
                root = as_dict(inst).get("installPath")
                if isinstance(root, str):
                    mcp = load_dict(os.path.join(root, ".mcp.json"))
                    for server in as_dict(mcp.get("mcpServers", mcp)):
                        leak["connectors"]["plugin_%s_%s" % (str(key).split("@")[0], server)] = server
    return {
        "skills": skills,
        "commands_flat": len(glob.glob(os.path.join(cdir, "commands", "*.md"))),
        "plugin_skills": plugin_skills,
        "agents": agents,
        "plugins": len(plugins),
        "hook_events": hook_events,
        "allow": len(perms.get("allow") or []), "deny": len(perms.get("deny") or []),
        "stop_hook": bool(hook_events.get("Stop") or hook_events.get("SubagentStop")),
        "connectors": len(connectors),
        "memory_files": len(memory),
        "pre_tool_hook": bool(hook_events.get("PreToolUse")),
        "claude_md": claude_md_size > 0,
        "project_md": any(os.path.isfile(os.path.join(p, "CLAUDE.md")) or
                          os.path.isfile(os.path.join(p, ".claude", "CLAUDE.md")) for p in projects),
        "context_tokens": (claude_md_size + index_size + sum(s["desc"] for s in skills.values())) // 4,
        "context_chars": claude_md_size + index_size + sum(s["desc"] for s in skills.values()),
    }


# The claude command or its SDK, not a folder that happens to be called claude.
CLAUDE_CMD_RE = re.compile(r"(?:^|[\s/\"'=;|&(\[,])claude(?=$|[\s\"';|&)\],])|claude[_-](?:agent|code)[_-]sdk", re.M)
SCRIPT_RE = re.compile(r"(?:~|/)[^\s\"'<>]*\.(?:sh|zsh|bash|py|js|mjs|ts)\b")


def runs_claude(text, follow=True):
    """True if a job calls the claude command, directly or through a script it names."""
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    if CLAUDE_CMD_RE.search(text):
        return True
    for path in SCRIPT_RE.findall(text) if follow else []:
        if runs_claude(read_head(os.path.expanduser(path), 200000), follow=False):
            return True
    return False


def scheduled_jobs():
    """Scheduled jobs on this machine that run Claude: launchd, cron, systemd user timers."""
    home = os.path.expanduser("~")
    jobs = []
    for path in glob.glob(os.path.join(home, "Library", "LaunchAgents", "*.plist")):
        try:
            with open(path, "rb") as f:
                p = plistlib.load(f)
            jobs.append("\n".join(str(a) for a in [p.get("Program", "")] + list(p.get("ProgramArguments") or [])))
        except Exception:      # unreadable or malformed plist: not a job we can judge
            continue
    try:
        cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout
        jobs += [l for l in cron.splitlines() if l.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    for path in glob.glob(os.path.join(home, ".config", "systemd", "user", "*.timer")):
        jobs.append(read_head(path[:-len(".timer")] + ".service", 200000))
    return sum(1 for text in jobs if runs_claude(text))


# ---------------------------------------------------------------- scoring

def curve(x, legend, unit=1):
    return 100 * min(1.0, math.log1p(max(x, 0) / unit) / math.log1p(legend / unit))


def mtok(d):
    return sum(w * d["tok"][k] for k, w in TOKEN_WEIGHT.items()) / 1e6


def merge(days, since, until):
    agg = new_day()
    for day, d in days.items():
        if since <= day <= until:
            for k, v in d.items():
                if isinstance(v, Counter):
                    agg[k].update(v)
                elif isinstance(v, set):
                    agg[k] |= v
                else:
                    agg[k] += v
    return agg


def day_xp(d):
    """XP for a day that still has its logs."""
    eat = min(XP_EAT_MAX, XP_EAT_MAX * math.log1p(mtok(d)) / math.log1p(EAT_FULL_MTOK))
    arsenal = min(XP_ARSENAL_MAX, XP_ARSENAL_EACH * (len(d["skills"]) + len(d["servers"]) + len(d["agents"])))
    ship = min(XP_SHIP_MAX, XP_COMMIT * d["commits"] + XP_PR * d["prs"] + d["edits"] // EDITS_PER_XP)
    auto = min(XP_LOOP_MAX, XP_LOOP_EACH * len(d["auto"]))
    return round(min(DAY_CAP, XP_SHOW + eat + arsenal + ship + auto))


def old_day_xp(prompts):
    """XP for a day whose logs are gone: one fixed formula on its prompt count, the same for everyone."""
    if prompts <= 0:
        return 0
    return round(XP_SHOW + min(XP_OLD_MAX, XP_OLD_MAX * math.log1p(prompts) / math.log1p(OLD_FULL_PROMPTS)))


def streaks(active, today):
    """Longest run, current run, and the idle gap that came before the current run."""
    longest = cur = 0
    prev = None
    for s in sorted(active):
        dt = date.fromisoformat(s)
        cur = cur + 1 if prev and (dt - prev).days == 1 else 1
        longest, prev = max(longest, cur), dt
    dt = today if today.isoformat() in active else today - timedelta(days=1)
    current = 0
    while dt.isoformat() in active:
        current += 1
        dt -= timedelta(days=1)
    earlier = [d for d in active if d <= dt.isoformat()]
    gap = (dt - date.fromisoformat(max(earlier))).days if current and earlier else 0
    return longest, current, gap


def away_days(active, today):
    """The empty UTC days just before today: 0 when yesterday was active, None with no activity before today.
    It stays the same all day, so the band welcomes you back at most once a day."""
    before = [d for d in active if d < today.isoformat()]
    return (today - date.fromisoformat(max(before))).days - 1 if before else None


def mood_of(health, idle, current_streak=0, gap=0):
    if idle is None:
        return MOODS["none"]
    if idle >= IDLE_OVER:
        return MOODS["over"]
    if idle >= IDLE_GHOST:
        return MOODS["ghost"]
    if idle >= IDLE_GRASS:
        return MOODS["grass"]
    if gap >= COMEBACK_GAP and current_streak <= COMEBACK_DAYS:
        return MOODS["back"]
    if health < HEALTH_BAD:
        return MOODS["bad"]
    return MOODS["good"] if health >= HEALTH_GOOD else MOODS["fine"]


def class_of(stats):
    """The strongest of the four things a setup does, if any of them is strong enough to count."""
    shape = {k: stats[k] for k in CLASSES}
    top = max(shape, key=shape.get)
    lowest = min(shape.values())
    if shape[top] == 0:
        return UNHATCHED
    if shape[top] < CLASS_FLOOR:
        return NOOB
    if lowest >= CLASS_FLOOR and shape[top] - lowest <= BALANCED_SPREAD:
        return BALANCED
    return CLASSES[top]


def level_of(xp):
    return max(1, min(LEVEL_MAX, math.isqrt(xp // LEVEL_DIVISOR)))


def stage_of(level):
    return next(name for floor, name in STAGES if level >= floor)


def iso_week(day):
    """The ISO week of a date in UTC, "2026-W43", numbered the way the board numbers them."""
    year, week, _ = day.isocalendar()
    return "%04d-W%02d" % (year, week)


def ledger_file(cdir):
    return os.path.join(cdir, "cclevel", "ledger.json")


def read_ledger(cdir, today):
    """This machine's ledger, checked: (the file as read, banked days, badges, estimated days, weekly snapshots)."""
    path = ledger_file(cdir)
    today_s = today.isoformat()
    # Only a plain file is read: a pipe or a device there would block, and the daily auto check-in runs this unattended.
    ledger = load_dict(path) if os.path.isfile(path) and not os.path.islink(path) else {}
    # A hand-edited ledger cannot lift a day above the cap, bank a future day or hold a badge that does not exist.
    banked = {d: min(int(x), DAY_CAP) for d, x in as_dict(ledger.get("days")).items()
              if is_day(d) and d < today_s and num(x) > 0}
    badges = {b: str(when) for b, when in as_dict(ledger.get("badges")).items() if b in BADGES}
    listed = ledger.get("estimated") if isinstance(ledger.get("estimated"), list) else []
    estimated = {d for d in listed if isinstance(d, str) and d in banked}
    # Nor a snapshot of a week to come, or one whose numbers are out of range.
    now = iso_week(today)
    weeks = {}
    for week, snap in as_dict(ledger.get("weeks")).items():
        snap = as_dict(snap)
        stats, xp, health = snap.get("stats"), snap.get("xp"), snap.get("health")
        if (WEEK_RE.fullmatch(week) and week <= now and type(xp) is int and 0 <= xp <= 10 ** 9
                and type(health) is int and 0 <= health <= 100 and isinstance(stats, list) and len(stats) == len(STAT_ORDER)
                and all(type(v) is int and 0 <= v <= 100 for v in stats)):
            weeks[week] = {"xp": xp, "stats": stats, "health": health}
    return ledger, banked, badges, estimated, weeks


def score(cdir, machine_jobs, save, extra=None):
    today = datetime.now(timezone.utc).date()
    today_s = today.isoformat()
    home_cfg = os.path.join(os.path.expanduser("~"), ".claude.json")
    cfg = load_dict(os.path.join(cdir, ".claude.json")) or (load_dict(home_cfg) if machine_jobs else {})
    settings = load_dict(os.path.join(cdir, "settings.json"))
    local = load_dict(os.path.join(cdir, "settings.local.json"))
    for key in ("hooks", "permissions"):       # count both files together
        settings[key] = merged_lists(settings.get(key), local.get(key))

    setup = scan_setup(cdir, cfg, settings, extra)
    prompts = scan_history(cdir)
    days, longest_run = scan_logs(cdir, set(setup["skills"]), extra)
    if extra is not None:
        extra["days"] = days
    # A day counts only when Claude really answered (synthetic error replies are not in "models") or a prompt was typed:
    # a headless run that stopped at "Invalid API key" is not a day you showed up.
    days = {day: d for day, d in days.items() if d["models"] or prompts.get(day)}
    jobs = scheduled_jobs() if machine_jobs else 0

    recent_since = (today - timedelta(days=RECENT_WINDOW_DAYS - 1)).isoformat()
    used_since = (today - timedelta(days=USED_WINDOW_DAYS - 1)).isoformat()
    w30 = merge(days, recent_since, today_s)

    # Skills used: Claude Code's own counters reach back further than the logs.
    usage = cfg.get("skillUsage") if isinstance(cfg.get("skillUsage"), dict) else {}
    used_skills = set(w30["skills"])
    for name, rec in usage.items():
        if isinstance(rec, dict) and (day_of(rec.get("lastUsedAt")) or "") >= used_since:
            used_skills.add(name)
    ever_used = max(len(used_skills), sum(1 for r in usage.values() if isinstance(r, dict) and r.get("usageCount")))
    own = setup["skills"]
    own_used = [n for n in own if n in used_skills]
    # Unused means old enough to have had its chance: a skill added last week is not dead weight.
    unused = [n for n in own if n not in used_skills and own[n]["age_days"] >= USED_WINDOW_DAYS]

    ledger_path = ledger_file(cdir)
    ledger, banked, badges, estimated, weeks = read_ledger(cdir, today)

    # XP: a finished day is priced once and never touched again. With logs it gets its real figure.
    # Without them it gets the fixed estimate from its prompt count and is marked as estimated.
    for day in set(days) | set(prompts):
        if day >= today_s or day in banked:
            continue
        xp = day_xp(days[day]) if day in days else old_day_xp(prompts.get(day, 0))
        if xp:
            banked[day] = xp
            if day not in days:
                estimated.add(day)
    pending = day_xp(days[today_s]) if today_s in days else old_day_xp(prompts.get(today_s, 0))

    active = set(banked) | {d for d in set(days) | set(prompts) if d <= today_s}
    longest_streak, current_streak, gap = streaks(active, today)
    first = min([d for d in (day_of(cfg.get("firstStartTime")), min(active, default=None)) if d], default=None)
    age_days = (today - date.fromisoformat(first)).days if first else 0
    idle = (today - date.fromisoformat(max(active))).days if active else None

    waiting = [name for name, v in load_dict(os.path.join(cdir, "mcp-needs-auth-cache.json")).items()
               if isinstance(v, dict) and (day_of(v.get("timestamp")) or "") >= recent_since]
    need_sign_in = len(waiting)

    auto_sessions = len(w30["auto"])
    raw = {
        "age_days": age_days, "active_days": len(active),
        "active_days_30d": sum(1 for d in active if d >= recent_since),
        "longest_streak": longest_streak, "current_streak": current_streak,
        "mtok_30d": round(mtok(w30), 1), "sessions_30d": len(w30["sessions"]),
        "prompts_30d": sum(n for d, n in prompts.items() if recent_since <= d <= today_s),
        "skills_used": len(used_skills), "connectors_used": len(w30["servers"]),
        "agent_types_used": len(w30["agents"]),
        "skills_installed": len(own) + setup["commands_flat"] + setup["plugin_skills"],
        "agents_installed": len(setup["agents"]), "connectors_installed": setup["connectors"],
        "plugins_installed": setup["plugins"],
        "auto_sessions_30d": auto_sessions,
        "auto_days_30d": sum(1 for d, v in days.items() if recent_since <= d <= today_s and v["auto"]),
        "spawns_30d": w30["spawns"], "longest_run": longest_run, "jobs": jobs,
        "edits_30d": w30["edits"], "commits_30d": w30["commits"], "prs_30d": w30["prs"],
        "pages_30d": len(w30["pages"]), "projects_30d": len(w30["projects"]),
    }

    # Brains: one check per line of BRAINS, in the same order.
    replies = w30["models"].most_common()
    second_model = len(replies) > 1 and replies[1][1] >= SECOND_MODEL_SHARE * sum(n for _, n in replies)
    checks = [
        setup["claude_md"] or setup["project_md"],
        w30["memory_writes"] > 0,
        len(own_used) >= OWN_SKILLS_IN_USE,
        any(own[n]["extra"] for n in own_used),
        len(w30["agents"]) >= SUBAGENT_KINDS,
        any(is_checker(n) for n in used_skills | w30["agents"]),
        setup["deny"] > 0 or setup["pre_tool_hook"],
        w30["hooks_ran"] > 0,
        second_model,
        w30["plan"] > 0,
    ]

    stats = {}
    for name, signals in STATS.items():
        total = 0
        for k, (legend, weight, *unit) in signals.items():
            total += weight * (100 * min(1.0, raw[k] / legend) if k in LINEAR else curve(raw[k], legend, *unit))
        stats[name] = STAT_STEP * round(total / STAT_STEP)
    stats["brains"] = STAT_STEP * round(100 * sum(checks) / len(checks) / STAT_STEP)

    # Health and the needs list.
    needs = []
    unused_share = len(unused) / len(own) if own else 0
    context_over = min(1.0, max(0.0, (setup["context_tokens"] - CONTEXT_OK) / (CONTEXT_HEAVY - CONTEXT_OK)))
    error_rate = w30["errors"] / w30["tools"] if w30["tools"] else 0
    interrupt_rate = w30["interrupts"] / w30["turns"] if w30["turns"] else 0
    penalties = {
        "unused_skills": (PENALTY_UNUSED_MAX * unused_share, len(unused)),
        "sign_in": (min(PENALTY_SIGN_IN_MAX, PENALTY_SIGN_IN_EACH * need_sign_in), need_sign_in),
        "heavy_context": (PENALTY_CONTEXT_MAX * context_over, setup["context_tokens"]),
        "tool_errors": (min(PENALTY_ERRORS_MAX, ERROR_POINTS * error_rate), round(100 * error_rate)),
        "interrupts": (min(PENALTY_INTERRUPTS_MAX, INTERRUPT_POINTS * interrupt_rate), round(100 * interrupt_rate)),
    }
    health = round(100 - sum(p for p, _ in penalties.values()))
    # What Health would be without the unused skills: their descriptions leave the start-up context too.
    ctx_after = (setup["context_chars"] - sum(own[n]["desc"] for n in unused)) // 4
    over_after = min(1.0, max(0.0, (ctx_after - CONTEXT_OK) / (CONTEXT_HEAVY - CONTEXT_OK)))
    rest = sum(p for c, (p, _) in penalties.items() if c not in ("unused_skills", "heavy_context"))
    health_without_unused = round(100 - rest - PENALTY_CONTEXT_MAX * over_after)
    for code, (points, count) in penalties.items():
        if round(points) >= 1:
            gain = health_without_unused - health if code == "unused_skills" else round(points)
            needs.append({"code": code, "count": count, "stat": "health", "gain": gain})
            if code == "sign_in":
                needs[-1]["from_plugins"] = sum(1 for name in waiting if name.startswith("plugin:"))
    per_check = round(100 / len(checks))
    for i, ok in enumerate(checks):
        if not ok:
            needs.append({"code": "brains_%d" % (i + 1), "count": 0, "stat": "brains", "gain": per_check})
    needs.sort(key=lambda n: -n["gain"])
    if extra is not None:   # for /pet fix only: the names it may move, never in the --json or a check-in
        extra["unused_names"], extra["own_used"] = sorted(unused), sorted(own_used)
        extra["health_without_unused"] = health_without_unused

    earned = {
        "first_hook": w30["hooks_ran"] > 0, "first_skill": bool(own_used),
        "first_subagent": w30["spawns"] > 0, "first_loop": auto_sessions > 0,
    }
    earned.update({badge: longest_streak >= n for badge, n in BADGE_STREAKS.items()})
    earned.update({badge: ever_used >= n for badge, n in BADGE_SKILLS.items()})
    for badge, ok in earned.items():
        if ok:
            badges.setdefault(badge, today_s)

    # Training: which lessons the logs and the setup show as done. Only lesson ids leave score().
    used = w30["commands"]
    done = {
        "g_days2": raw["active_days_30d"] >= 2, "g_resume": "resume" in used,
        "g_streak7": longest_streak >= BADGE_STREAKS["streak_7"], "g_days15": raw["active_days_30d"] >= 15,
        "g_streak30": longest_streak >= BADGE_STREAKS["streak_30"],
        "a_context": "context" in used, "a_compact": w30["compacts"] > 0 or "compact" in used, "a_model": "model" in used,
        "a_usage": bool(used & {"usage", "cost", "stats"}), "a_lean": checks[0] and setup["context_tokens"] <= CONTEXT_OK,
        "r_skill": bool(used_skills), "r_connector": bool(w30["servers"]), "r_own": bool(own_used), "r_own_script": checks[3],
        "r_ten": ever_used >= BADGE_SKILLS["skills_10"],
        "b_claude_md": checks[0], "b_plan": checks[9], "b_memory": checks[1], "b_guardrail": checks[6], "b_stop_hook": checks[7],
        "u_subagent": w30["spawns"] > 0, "u_two_kinds": checks[4], "u_second_model": checks[8],
        "u_headless": auto_sessions > 0, "u_scheduled": jobs > 0,
        "c_edit": w30["edits"] > 0, "c_commit": w30["commits"] > 0, "c_pr": w30["prs"] > 0, "c_checker": checks[5],
        "c_worktree": w30["worktrees"] > 0 or any(WORKTREE_MARK in p for p in w30["projects"]),
    }

    xp = sum(banked.values()) + sum(BADGES.get(b, 0) for b in badges)
    level = level_of(xp)
    # One snapshot a week, from the week's latest run, so a year in review can show how the stats moved.
    weeks[iso_week(today)] = {"xp": xp, "stats": [stats[s] for s in STAT_ORDER], "health": health}

    seen = ledger.get("first_seen")
    hatched = seen if is_day(seen) and len(seen) == 10 and seen <= today_s else today_s if active or badges else None
    kept = {"days": banked, "estimated": sorted(estimated), "badges": badges, "weeks": weeks}
    # The day the card first showed the hatch, kept so it shows once (see hatch_due).
    hatch_seen = ledger.get("hatch_seen") if is_day(ledger.get("hatch_seen")) else None
    if save and (banked or badges) and any(kept[k] != ledger.get(k) for k in kept):
        try:
            os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
            # Written to a fresh private file and swapped in: never through a link, never half written.
            write_private(ledger_path, json.dumps(dict(kept, version=4, first_seen=ledger.get("first_seen") or today_s,
                                                       **({"hatch_seen": hatch_seen} if hatch_seen else {})),
                                                  indent=1, sort_keys=True))
        except OSError:
            pass   # the card still shows; the day is banked at the next run

    raw.update({
        "idle_days": idle, "away_days": away_days(active, today), "skills_own": len(own), "skills_plugin": setup["plugin_skills"],
        "commands_flat": setup["commands_flat"], "skills_unused": len(unused),
        "connectors_need_sign_in": need_sign_in, "hooks": sum(setup["hook_events"].values()),
        "hook_event_types": len(setup["hook_events"]), "memory_files": setup["memory_files"],
        "startup_context_tokens": setup["context_tokens"],
        "tokens_30d": {k: w30["tok"][k] for k in TOKEN_WEIGHT},
        "tool_calls_30d": w30["tools"], "tool_errors_30d": w30["errors"],
        "interrupts_30d": w30["interrupts"], "brains_passed": sum(checks), "brains_total": len(checks),
        "xp_days": len(banked), "xp_days_estimated": len(estimated),
        "xp_7d": sum(x for d, x in banked.items() if d >= (today - timedelta(days=7)).isoformat()),   # the last 7 finished days
        # The menu bar panel's Trend card: the last 14 UTC days, oldest first, each finished day as banked, today still pending.
        "xp_by_day": [banked.get((today - timedelta(days=back)).isoformat(), 0) for back in range(13, 0, -1)] + [pending],
    })
    return {
        "version": 1, "generated": today_s, "scope": "one machine, self-reported",
        "level": level, "xp": xp, "xp_next_level": LEVEL_DIVISOR * (level + 1) ** 2,
        "xp_level_start": 0 if level <= 1 else LEVEL_DIVISOR * level ** 2,   # where this level began, for progress bars
        "xp_today_pending": pending,
        "stage": next(name for floor, name in STAGES if level >= floor), "class": class_of(stats),
        "brain": next((name for floor, name in BRAIN_TITLES if stats["brains"] >= floor), ""),
        "mood": mood_of(health, idle, current_streak, gap), "health": health,
        "power": sum(stats.values()), "stats": stats,
        "badges": [b for b in BADGES if b in badges], "needs": needs, "raw": raw,
        "lessons": [lesson[0] for stat in STAT_ORDER for lesson in LESSONS[stat] if done[lesson[0]]],
        # Our story in short, for the panel: the day you met Claude Code, the day cclevel hatched your creature, and
        # the days in between and since (the card's "days old").
        "story": {"met": first, "hatched": hatched, "together_days": age_days},
        # The ledger's first day (null before there is a ledger), so the creature band can tell a new machine from an old one.
        "hatched": seen if is_day(seen) and len(seen) == 10 and seen <= today_s else None,
        # Card only, never in --json: the hatch block shows on a new machine's first card (see hatch_lines).
        # The newest stage reached in the last EVOLVED_DAYS days, {from, to, day}: the card's line and /pet evolve's post.
        "evolved": evolved_of(banked, badges, today),
        "hatch_due": bool(active) and not hatch_seen and not (is_day(seen) and len(seen) == 10
                                                               and seen < (today - timedelta(days=HATCH_DAYS)).isoformat()),
    }


# -------------------------------------------------------------- rendering

def need_text(n):
    c, g = n["count"], n["gain"]
    them = "it" if c == 1 else "them"
    if n["code"] == "unused_skills":
        return "%s unused for %d days. %s: archive %s (Health +%d)" % (
            count(c, "own skill"), USED_WINDOW_DAYS, QUIPS["unused_skills"], them, g)
    if n["code"] == "sign_in":
        plugins = n.get("from_plugins", 0)
        part = ", from a plugin" if plugins and c == 1 else ", %d of them from %s" % (plugins, "a plugin" if plugins == 1 else "plugins") if plugins else ""
        return "%s %s waiting for sign-in%s: connect %s or switch %s off (Health +%d)" % (
            count(c, "connector"), "is" if c == 1 else "are", part, them, them, g)
    if n["code"] == "heavy_context":
        return "start-up context is at least %dk tokens. %s: trim instructions, memory index or skill descriptions (Health +%d)" % (
            c // 1000, QUIPS["heavy_context"], g)
    if n["code"] == "tool_errors":
        return "%d%% of tool calls fail (Health +%d)" % (c, g)
    if n["code"] == "interrupts":
        return "%d%% of turns get interrupted (Health +%d)" % (c, g)
    return "missing: %s (Brains +%d)" % (BRAINS[int(n["code"].split("_")[1]) - 1], g)


HATCH_DAYS = 7   # how new a ledger may be for the hatch to show: an update never replays it for older machines


def hatch_lines(r):
    """The two lines on top of a new machine's first card: what hatched, or the egg and when it hatches."""
    if r["stage"] == "Egg":
        return ["An egg appeared!", "It hatches at Lv %d." % STAGES[-2][0]]
    who = r["stage"] if r["class"] == UNHATCHED else "%s %s" % (r["stage"], r["class"])
    shiny = (r.get("marks") or marks_of(None))["shiny"]
    return ["Your egg hatched!", "It's %s · Lv %d%s" % (a_or_an(who), r["level"], " · %s!" % SHINY_MARK if shiny else "")]


def record_hatch(cdir):
    """Notes in the ledger that the card showed the hatch, so it shows once. Every other key stays as it is."""
    today_s = datetime.now(timezone.utc).date().isoformat()
    path = ledger_file(cdir)
    ledger = load_dict(path) if os.path.isfile(path) and not os.path.islink(path) else {}
    ledger.setdefault("version", 4)
    if not is_day(ledger.get("first_seen")):
        ledger["first_seen"] = today_s
    ledger["hatch_seen"] = today_s
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_private(path, json.dumps(ledger, indent=1, sort_keys=True))
    except OSError:
        pass   # the block shows once more at the next run


def render(r, board="on", how=False, tip=None, creature=None, leak=None):
    """The card. `board` is "on" (this machine is on the board, as `creature`), "soon" (Default mode: the session-start
    hook joins it next time), "privacy" (Privacy mode: the opted-out note and no token, so cclevel sends nothing), "leaving"
    (the note, but the row is still on the board: a delete that did not go through) or "off" (a folder the hook never
    joins). Off, with XP banked in the last 7 days, the last lines say how much of it will never rank: the board counts only
    XP it sees after joining. Privacy mode never gets that nudge. Worked out here; nothing is sent.
    With tips on, `how` adds a how-to line under each Need, `tip` is the tip of the day, (stat, tip), and `leak` the
    leak finder's line when the biggest leak is large."""
    raw, level = r["raw"], r["level"]
    who = r["stage"] if r["class"] == UNHATCHED else "%s %s" % (r["stage"], r["class"])
    marks = r.get("marks") or marks_of(None)
    to_next = "top level" if level >= LEVEL_MAX else "{:,} to Lv {}".format(r["xp_next_level"] - r["xp"], level + 1)
    guessed = " (%d estimated)" % raw["xp_days_estimated"] if raw["xp_days_estimated"] else ""
    side = [
        "%s · Lv %d%s" % (who, level, " · " + SHINY_MARK if marks["shiny"] else ""),
        "XP {:,} · {} · today so far +{}".format(r["xp"], to_next, r["xp_today_pending"]),
        "Mood: %s · Health %d · %s %d" % (r["mood"], r["health"], AURA, r["power"]),
        "%s old · %s%s · streak %d" % (count(raw["age_days"], "day"), count(raw["active_days"], "active day"), guessed,
                                       raw["current_streak"]),
    ]
    out = ["", *("  " + line for line in hatch_lines(r))] if r.get("hatch_due") else []
    out += ["", *("  %s   %s" % (art, text) for art, text in zip(marked_art(r["stage"], marks["look"], marks["shiny"]), side)), ""]
    for name in STAT_ORDER:
        v = r["stats"][name]
        filled = round(v / 5)
        title = "  %s" % r["brain"] if name == "brains" and r["brain"] else ""
        out.append("  %-9s %s%s %3d%s" % (name.capitalize(), "#" * filled, "-" * (20 - filled), v, title))
    out.append("")
    if not raw["active_days"]:
        out.append("  No Claude Code activity found in this folder.")
    elif r["needs"]:
        sick = r["mood"] == MOODS["bad"] and r["needs"][0]["stat"] == "health"
        out.append("  Needs (why it is %s)" % MOODS["bad"] if sick else "  Needs")
        for i, n in enumerate(r["needs"][:5]):
            out.append("   %d. %s" % (i + 1, need_text(n)))
            if how:
                text, page = HOWTO[n["code"]]
                out.append("      How: %s  %s%s" % (text, DOCS, page))
        out.append("  Ask Claude: /pet fix")
    else:
        out.append("  Needs: nothing right now. %s." % QUIPS["no_needs"])
    if r["badges"]:
        out += ["", "  Badges: " + ", ".join(BADGE_NAMES[b] for b in r["badges"])]
    if r.get("evolved"):
        out += ["", "  Evolved into %s on %s! Post it: /pet evolve" % (a_or_an(r["evolved"]["to"]), short_day(r["evolved"]["day"]))]
    if tip:
        stat, (_, text, page) = tip
        out += ["", "  Tip of the day (%s): %s" % (stat.capitalize(), text), "  %s%s" % (DOCS, page)]
    if leak:
        out += ["", "  " + leak]
    out += ["", "  This machine only, self-reported. Deep check-up: /doctor and /skill-doctor."]
    if board == "on" and creature:
        out.append("  On the board as %s. Privacy mode: /pet privacy on deletes your row and sends nothing after." % creature)
    elif board == "soon":
        out += ["  Default mode: joins the board at the next Claude Code start (nine numbers, no names).",
                "  Privacy mode: /pet privacy on, and cclevel sends nothing."]
    elif board == "privacy":
        out.append("  Privacy mode: cclevel sends nothing. /pet privacy off for the board, groups and duels.")
    elif board == "leaving":
        out.append("  Privacy mode is on, but your row is still on the board: /pet privacy on deletes it.")
    if board == "off" and raw["xp_7d"] > 0:
        out += ["  Not on the board yet: your last 7 days earned {:,} XP that will never rank.".format(raw["xp_7d"]),
                "  Start counting: /pet join the leaderboard. Post it as an image: /pet card."]
    elif board in ("privacy", "leaving"):
        out += ["  Post it as an image: /pet card."]
    else:
        out += ["  Post it as an image: /pet card. Challenge a friend: /pet duel."]
    out += ["  Learn Claude Code step by step: /pet learn%s." % ("" if how else ". A how-to under each Need: /pet tips on"), ""]
    return "\n".join(out)


def short_day(day):
    return "%d %s" % (int(day[8:]), MONTHS[int(day[5:7]) - 1])


def xp_until(banked, badges, day):
    """XP banked up to and including a day: its banked days plus the XP of the badges earned by then."""
    return sum(x for d, x in banked.items() if d <= day) + sum(BADGES[b] for b, when in badges.items() if when <= day)


def milestones(banked, badges):
    """The first banked day and the day each stage from Hatchling up was reached, from the same XP sum as xp_until()."""
    marks = {"first": min(banked) if banked else None}
    days = sorted(set(banked) | {w for w in badges.values() if is_day(w)})
    for floor, name in sorted(STAGES[:-1]):   # Egg is where every creature starts
        marks[name] = next((d for d in days if level_of(xp_until(banked, badges, d)) >= floor), None)
    return marks


EVOLVED_DAYS = 7   # how long after the day a new stage was reached the card says so


def evolved_of(banked, badges, today):
    """The newest stage reached, {from, to, day}, if that day is one of the last EVOLVED_DAYS. From the ledger alone,
    so a stage reached while you were away still shows. None otherwise."""
    marks = milestones(banked, badges)
    for i, (_, name) in enumerate(STAGES[:-1]):   # GOAT first: only the newest stage counts
        if marks[name]:
            ago = (today - date.fromisoformat(marks[name])).days
            return {"from": STAGES[i + 1][1], "to": name, "day": marks[name]} if 0 <= ago < EVOLVED_DAYS else None
    return None


def class_slug(cls):
    """The class page's name in its address, /class/<slug>; None for Unhatched, which has no page."""
    return None if cls == UNHATCHED else cls.lower().replace(" ", "-")


def evolve_link(server, result):
    """An X post link. Only its text and the class page's address go in it: stage, class and level, no name or token."""
    who = result["stage"] if result["class"] == UNHATCHED else "%s %s" % (result["stage"], result["class"])
    ev = result.get("evolved")
    if ev and ev["from"] == "Egg":
        text = "My Claude Code just hatched: Lv %d %s. What's yours?" % (result["level"], who)
    elif ev:
        text = "My Claude Code just evolved into %s, Lv %d. What's yours?" % (a_or_an(who), result["level"])
    else:
        text = "My Claude Code is %s, Lv %d. What's yours?" % (a_or_an(who), result["level"])
    slug = class_slug(result["class"])
    page = "%s/class/%s" % (site(server), slug) if slug else site(server)
    return "https://x.com/intent/post?" + urllib.parse.urlencode({"text": text, "url": page}, quote_via=urllib.parse.quote)


def evolve_text(server, result, today):
    ev = result.get("evolved")
    who = result["stage"] if result["class"] == UNHATCHED else "%s %s" % (result["stage"], result["class"])
    if ev and ev["from"] == "Egg":
        first = "Your egg hatched into a Hatchling on %s (Lv %d)." % (story_day(ev["day"], today), result["level"])
    elif ev:
        first = "Your %s became %s on %s (Lv %d)." % (ev["from"], a_or_an(ev["to"]), story_day(ev["day"], today), result["level"])
    else:
        first = "Your creature is %s, Lv %d. No new stage in the last %d days, so the post says what it is now." % (
            a_or_an(who), result["level"], EVOLVED_DAYS)
    return "\n".join([
        "", "  " + first,
        "  Post it on X (opens a ready post you can edit): " + evolve_link(server, result),
        "  The post is public and shows your level, stage and class, nothing else. cclevel sends nothing: opening the link",
        "  is your own visit to x.com, and the link in the post opens %s%s." % (
            "your class's page on " if class_slug(result["class"]) else "",
            urllib.parse.urlsplit(site(server)).netloc or site(server)), ""])


WRAPPED_VERSION = 1          # must match the Wrapped page, server/public/wrapped.js
WRAPPED_CLASSES = (*CLASSES.values(), BALANCED, NOOB, UNHATCHED)   # a class's number in the link; one past the end is none
WRAPPED_STAGES = tuple(name for _, name in reversed(STAGES[:-1]))  # Hatchling to GOAT, the link's last five numbers


def wrapped_numbers(cdir, year, today):
    """A year in review from this machine's ledger: its banked days, badges and weekly snapshots. Offline.
    None for a year with no banked days."""
    _, banked, badges, estimated, weeks = read_ledger(cdir, today)
    start, end = "%d-01-01" % year, "%d-12-31" % year
    days = {d: x for d, x in banked.items() if start <= d <= end}
    if not days:
        return None
    months = [0] * 12
    for d, x in days.items():
        months[int(d[5:7]) - 1] += x
    longest = run = 0
    prev = None
    for d in sorted(days):
        dt = date.fromisoformat(d)
        run = run + 1 if prev and (dt - prev).days == 1 else 1
        longest, prev = max(longest, run), dt
    weeks_in = [w for w in sorted(weeks) if w.startswith(str(year))]
    snaps = [weeks[w]["stats"] for w in weeks_in]
    averages = {name: sum(s[i] for s in snaps) / len(snaps) for i, name in enumerate(STAT_ORDER)} if snaps else {}
    marks = milestones(banked, badges)
    return {
        "year": year, "so_far": year == today.year,
        "until": (today - timedelta(days=1)) if year == today.year else date(year, 12, 31),
        "xp": sum(days.values()), "active": len(days), "estimated": sum(1 for d in days if d in estimated),
        "first": level_of(xp_until(banked, badges, str(year - 1) + "-12-31")), "last": level_of(xp_until(banked, badges, end)),
        "best_day": max(sorted(days), key=lambda d: days[d]),   # the earliest of equal days
        "best_month": max(range(12), key=lambda m: months[m]), "months": months, "longest": longest, "days": days,
        "badges": [b for b in BADGES if start <= badges.get(b, "") <= end],
        "weeks": weeks_in, "snaps": snaps,
        "class": Counter(class_of(dict(zip(STAT_ORDER, s))) for s in snaps).most_common(1)[0][0] if snaps else None,
        "strongest": max(STAT_ORDER, key=lambda n: averages[n]) if snaps else None, "averages": averages,
        "moves": [snaps[-1][i] - snaps[0][i] for i in range(len(STAT_ORDER))] if len(snaps) > 1 else None,
        "stages": {name: marks[name] for name in WRAPPED_STAGES if marks[name] and start <= marks[name] <= end},
    }


def day_of_year(day):
    return date.fromisoformat(day).timetuple().tm_yday


def wrapped_link(server, w):
    """The Wrapped page's address. Its 41 numbers sit after "#", which browsers never send: the page draws the five
    story images from them. Every number is a whole number of 0 or more."""
    numbers = [WRAPPED_VERSION, w["year"], int(w["so_far"]), w["until"].timetuple().tm_yday, w["xp"], w["active"],
               w["estimated"], w["first"], w["last"], day_of_year(w["best_day"]), w["days"][w["best_day"]],
               w["best_month"], w["longest"], *w["months"], sum(1 << i for i, b in enumerate(BADGES) if b in w["badges"]),
               len(w["snaps"]), WRAPPED_CLASSES.index(w["class"]) if w["class"] else len(WRAPPED_CLASSES),
               STAT_ORDER.index(w["strongest"]) if w["strongest"] else len(STAT_ORDER),
               round(w["averages"][w["strongest"]]) if w["strongest"] else 0,
               *(100 + m for m in (w["moves"] or [0] * len(STAT_ORDER))),
               *(day_of_year(w["stages"][s]) if s in w["stages"] else 0 for s in WRAPPED_STAGES)]
    return "%s/wrapped#%s" % (site(server), "-".join(str(n) for n in numbers))


def wrapped(cdir, year, today, server=None):
    """The year in review as text. With a server, its last line is the link to the five story images."""
    w = wrapped_numbers(cdir, year, today)
    out = ["", "  CC level Wrapped %d%s · this machine only, self-reported" % (year, " so far" if year == today.year else ""), ""]
    if not w:
        return "\n".join(out + ["  No finished days banked in %d on this machine." % year, ""])
    first, last, months = w["first"], w["last"], w["months"]
    out.append("  {:,} XP over {}{}".format(w["xp"], count(w["active"], "active day"),
                                           " (%d estimated from prompt counts)" % w["estimated"] if w["estimated"] else ""))
    out.append("  Lv %d %s → Lv %d %s" % (first, stage_of(first), last, stage_of(last)))
    out.append("  Best day: {}, {:,} XP · Best month: {}, {:,} XP · Longest streak: {}".format(
        short_day(w["best_day"]), w["days"][w["best_day"]], MONTHS[w["best_month"]], months[w["best_month"]],
        count(w["longest"], "day")))
    earned = [BADGE_NAMES[b] for b in w["badges"]]
    out.append("  Badges earned: " + ", ".join(earned) if earned else "  No new badges this year.")
    out.append("")
    top = max(months)
    for m in range(today.month if year == today.year else 12):
        filled = round(20 * months[m] / top)
        out.append("  %s  %s%s  %s" % (MONTHS[m], "#" * filled, "-" * (20 - filled), "{:,}".format(months[m]).rjust(6)))
    out.append("")
    if not w["snaps"]:
        out.append("  Weekly snapshots of your stats start with this version, so a later Wrapped shows how they moved.")
    else:
        out.append("  %s, from %s · Most weeks as: %s · Strongest stat: %s, %d on average" % (
            count(len(w["snaps"]), "weekly snapshot"), w["weeks"][0], w["class"], w["strongest"].capitalize(),
            round(w["averages"][w["strongest"]])))
        if w["moves"]:
            out.append("  Since then: " + " · ".join("%s %+d" % (name.capitalize(), w["moves"][i])
                                                       for i, name in enumerate(STAT_ORDER)))
    out += ["", "  Post your card: /pet card."]
    if server:
        out.append("  Story images to post: " + wrapped_link(server, w))
    return "\n".join(out + [""])


STORY_VERSION = 1            # a field is only ever added; a change of meaning bumps this
STORY_KINDS = ("met", "hatched", "level", "stage", "badge", "class", "best_day")   # the order of events on one day
STORY_LINES = 25             # the most event lines --story prints


def story(cdir, result, today, year=None):
    """You and your creature as a timeline, worked out from this machine's ledger and the score. Offline, stores nothing.
    Levels come from the same XP sum as Wrapped, classes from the weekly snapshots, badges from their dates. Everything
    dated before cclevel first saved the ledger (and every badge dated that day) is marked "about". With a year, the
    records are that year's."""
    _, banked, badges, estimated, weeks = read_ledger(cdir, today)
    today_s = today.isoformat()
    met, hatched = result["story"]["met"], result["story"]["hatched"]
    badges = {b: when for b, when in badges.items() if is_day(when) and len(when) == 10 and when <= today_s}
    events = []
    if met:
        events.append({"day": met, "kind": "met"})
    level = level_of(xp_until(banked, badges, hatched)) if hatched else 1
    if hatched:
        snaps = [weeks[w] for w in sorted(weeks)]
        first_class = class_of(dict(zip(STAT_ORDER, snaps[0]["stats"]))) if snaps else result["class"]
        events.append({"day": hatched, "kind": "hatched", "level": level, "stage": stage_of(level), "class": first_class})
        before = None
        for w in sorted(weeks):
            now = class_of(dict(zip(STAT_ORDER, weeks[w]["stats"])))
            if before is not None and now != before:
                try:
                    monday = date.fromisocalendar(int(w[:4]), int(w[6:]), 1).isoformat()
                except ValueError:
                    continue
                events.append({"day": max(monday, hatched), "kind": "class", "class": now, "week": w})
            before = now
    # A level event on each day the level went up, a stage event on each day a stage was reached.
    level = 1
    for d in sorted(set(banked) | set(badges.values())):
        now = level_of(xp_until(banked, badges, d))
        if now > level:
            events.append({"day": d, "kind": "level", "level": now})
            for floor, name in sorted(STAGES[:-1]):
                if level < floor <= now:
                    events.append({"day": d, "kind": "stage", "stage": name, "level": floor})
            level = now
    for b in BADGES:
        if b in badges:
            events.append({"day": badges[b], "kind": "badge", "badge": b})
    best = max(sorted(banked), key=lambda d: banked[d]) if banked else None   # the earliest of equal days
    if best:
        events.append({"day": best, "kind": "best_day", "xp": banked[best]})
    for e in events:
        if hatched and (e["day"] < hatched or (e["kind"] == "badge" and e["day"] == hatched)):
            e["about"] = True
    events.sort(key=lambda e: (e["day"], STORY_KINDS.index(e["kind"])))

    days = {d: x for d, x in banked.items() if year is None or d.startswith("%d-" % year)}
    by_week = Counter()
    for d, x in days.items():
        by_week[iso_week(date.fromisoformat(d))] += x
    longest = run = 0
    span = start = None
    prev = None
    for d in sorted(days):
        dt = date.fromisoformat(d)
        if prev and (dt - prev).days == 1:
            run += 1
        else:
            run, start = 1, d
        if run > longest:
            longest, span = run, (start, d)
        prev = dt
    top = max(sorted(days), key=lambda d: days[d]) if days else None
    records = {
        "best_day": {"day": top, "xp": days[top]} if top else None,
        "best_week": {"week": w, "xp": by_week[w]} if (w := max(sorted(by_week), key=lambda k: by_week[k], default=None)) else None,
        "longest_streak": {"days": longest, "from": span[0], "to": span[1]} if span else None,
    }
    if year is not None:   # the levels a year began and ended with, as Wrapped shows them
        records["levels"] = {"from": level_of(xp_until(banked, badges, "%d-12-31" % (year - 1))),
                             "to": level_of(xp_until(banked, badges, "%d-12-31" % year))}
    early = {d: x for d, x in banked.items() if hatched and d < hatched}
    last_before = max(early, default=None)
    level_before = level_of(xp_until(banked, badges, last_before)) if last_before else 1
    return {
        "version": STORY_VERSION, "scope": "one machine, self-reported", "today": today_s,
        "met": met, "hatched": hatched, "together_days": result["story"]["together_days"],
        "active_days": result["raw"]["active_days"], "estimated_days": len(estimated),
        "before_hatch": {"days": len(early), "xp": sum(early.values()), "estimated_days": sum(1 for d in early if d in estimated),
                         "level": level_before, "stage": stage_of(level_before)} if early else None,
        "events": events, "records": records,
    }


def a_or_an(word):
    return ("an " if word[0] in "AEIOU" else "a ") + word


def story_day(day, today):
    """ "14 Oct", with the year when it is not this year."""
    return short_day(day) + ("" if day.startswith(str(today.year)) else " " + day[:4])


def story_text(s, today):
    """The story as text: at most STORY_LINES event lines, with the other level-ups folded into one line."""
    out = ["", "  Our story · this machine only, self-reported", ""]
    if not s["before_hatch"] and not any(e["kind"] in ("level", "badge", "best_day") for e in s["events"]) \
            and s["hatched"] in (None, s["today"]):
        out.append("  Your story starts today.")
    shown = [e for e in s["events"] if e["kind"] != "level" or e["level"] % 10 == 0]
    stage_days = {(e["day"], e["level"]) for e in s["events"] if e["kind"] == "stage"}
    shown = [e for e in shown if not (e["kind"] == "level" and (e["day"], e["level"]) in stage_days)]
    # Over the limit: drop level lines first, then class changes and badges, the oldest first.
    for kind in ("level", "class", "badge"):
        while len(shown) > STORY_LINES and any(e["kind"] == kind for e in shown):
            shown.remove(next(e for e in shown if e["kind"] == kind))
    folded = sum(1 for e in s["events"] if e["kind"] == "level") - sum(1 for e in shown if e["kind"] == "level")
    dated = []
    for e in shown:
        dated.append(("about " if e.get("about") else "") + story_day(e["day"], today))
    width = max((len(d) for d in dated), default=0)
    for e, when in zip(shown, dated):
        k = e["kind"]
        text = {
            "met": lambda: "You met Claude Code",
            "hatched": lambda: "cclevel hatched your creature: %s %s, Lv %d" % (e["stage"], e["class"], e["level"]),
            "level": lambda: "Lv %d" % e["level"],
            "stage": lambda: "Evolved into %s (Lv %d)" % (a_or_an(e["stage"]), e["level"]),
            "badge": lambda: "Badge: " + BADGE_NAMES[e["badge"]],
            "class": lambda: "Became %s" % a_or_an(e["class"]),
            "best_day": lambda: "Biggest day yet: {:,} XP".format(e["xp"]),
        }[k]()
        out.append("  %s  %s" % (when.ljust(width), text))
        if k == "hatched" and s["before_hatch"]:
            b = s["before_hatch"]
            out.append("  %s  Before that: %s, {:,} XP%s".format(b["xp"]) % (
                " " * width, count(b["days"], "active day"),
                " (%d estimated from prompt counts)" % b["estimated_days"] if b["estimated_days"] else ""))
    if folded:
        out.append("  %s  +%s" % (" " * width, count(folded, "other level-up")))
    if any(e.get("about") for e in shown):
        out += ["", "  \"about\": worked out from older days, some estimated from prompt counts."]
    out.append("")
    streak = s["records"]["longest_streak"]
    tail = ["Together %s" % count(s["together_days"], "day"), count(s["active_days"], "active day")]
    if streak:
        a, b = streak["from"], streak["to"]
        span = story_day(a, today) if a == b else "%d–%s" % (int(a[8:]), story_day(b, today)) if a[:7] == b[:7] \
            else "%s–%s" % (story_day(a, today) if a[:4] != b[:4] else short_day(a), story_day(b, today))
        tail.append("longest streak %s (%s)" % (count(streak["days"], "day"), span))
    out += ["  " + " · ".join(tail), "  Your year so far: /pet wrapped.", ""]
    return "\n".join(out)


def training_path(cdir):
    return os.path.join(cdir, "cclevel", "training.json")


def load_training(cdir):
    """The tips switch, the tips already shown and the lessons already ticked. Kept on this machine only."""
    path = training_path(cdir)
    # Only a plain file is read, as with the ledger; anything odd there reads as a fresh start.
    data = load_dict(path) if os.path.isfile(path) and not os.path.islink(path) else {}
    tips = {t[0] for ts in TIPS.values() for t in ts}
    lessons = {l[0] for ls in LESSONS.values() for l in ls}
    seen = data.get("seen") if isinstance(data.get("seen"), list) else []
    today = data.get("today")
    return {"tips": data.get("tips") is True,
            "seen": list(dict.fromkeys(t for t in seen if isinstance(t, str) and t in tips)),
            "day": data.get("day") if is_day(data.get("day")) else None,
            "today": today if isinstance(today, str) and today in tips else None,
            "done": {l: str(d) for l, d in as_dict(data.get("done")).items() if l in lessons}}


def save_training(cdir, change, wait=2.0):
    """Read, change and write training.json in one step, under the same folder lock as identity.json."""
    with identity_lock(cdir, wait):
        now = load_training(cdir)
        change(now)
        write_private(training_path(cdir), json.dumps(dict(now, version=1), indent=1, sort_keys=True))


def tick(now, result):
    """Lessons ticked by this scan join the ones ticked before: once learnt, a lesson stays learnt after the logs are gone."""
    for lesson in result["lessons"]:
        now["done"].setdefault(lesson, result["generated"])


def tip_of_the_day(state, result):
    """The same tip all day, a new one the next day: the first unseen tip of the weakest stat that has one.
    Once every tip has been shown, they start again. Returns ((stat, tip), new) where new means not shown before today."""
    by_id = {t[0]: (stat, t) for stat in STAT_ORDER for t in TIPS[stat]}
    if state["day"] == result["generated"] and state["today"] in by_id:
        return by_id[state["today"]], False
    seen = set(state["seen"])
    if seen >= set(by_id):
        seen = set()
    for stat in sorted(STAT_ORDER, key=lambda s: result["stats"][s]):   # sorted() keeps STAT_ORDER among equals
        for t in TIPS[stat]:
            if t[0] not in seen:
                return (stat, t), True
    return None, False


def training_extras(cdir, result, save):
    """What the card adds when tips are on: the how-to lines and the tip of the day. Nothing at all when off."""
    state = load_training(cdir)
    if not state["tips"]:
        return False, None
    tip, new = tip_of_the_day(state, result)
    if save and (new or any(l not in state["done"] for l in result["lessons"])):
        def shown(now):
            # Another run may have picked today's tip in the meantime; the first one picked stays.
            if new and not (now["day"] == result["generated"] and now["today"]):
                if set(now["seen"]) >= {t[0] for ts in TIPS.values() for t in ts}:
                    now["seen"] = []
                now["seen"].append(tip[1][0])
                now.update(day=result["generated"], today=tip[1][0])
            tick(now, result)
        try:
            save_training(cdir, shown)
        except (Busy, OSError):
            pass   # the card still shows; at worst the same tip comes again tomorrow
    return True, tip


def tips_command(args, cdir):
    """Turns tips on or off. A choice kept on this machine only: nothing is sent."""
    on = args.tips == "on"
    save_training(cdir, lambda now: now.update(tips=on))
    if on:
        print("Tips on. The card now shows how to fix each Need and one Claude Code tip a day.")
        print("They come with cclevel and are kept on this machine; nothing is sent. --tips off stops them.")
    else:
        print("Tips off. The card is back to its short form. /pet learn still shows the lessons.")
    return 0


# ---------------------------------------------------------------- menu bar panel (macOS, opt-in)
# --panel on builds a small menu bar program from the plugin's own Swift source (mac/CclevelPanel.swift) with Apple's
# swiftc, keeps it beside a copy of this scanner in <claude dir>/cclevel/panel/, and starts it at login with a LaunchAgent.
# The panel runs that copy's offline card (--json --no-save, which writes nothing) at most once an hour, and once right
# after --panel on replaces that copy or a check-in or group read saves something new in identity.json, and sends nothing.
PANEL_LABEL = "com.cclevel.panel"
PANEL_PREFS = "cclevel-panel"   # the panel program's macOS preferences: only where its menu bar item sits
PANEL_START_TRIES = 3   # starting it again right after stopping the old copy can fail once or twice while macOS catches up
PANEL_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, "mac", "CclevelPanel.swift")
PANEL_FILES = ("cclevel-panel", "cclevel-panel.building", "cclevel.py", "card.json")   # all --panel on ever puts in its folder
# The creature's rendered loops, one per stage; --panel on copies them into the panel's creatures/ folder.
PANEL_CLIPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, "mac", "creatures")
PANEL_STAGE_CLIPS = ("egg", "hatchling", "lil_guy", "big_guy", "gigachad", "goat")
PANEL_CLASS_CLIPS = ("shipper", "afk_farmer", "loot_goblin", "tokenmaxxer", "balanced", "noob")
# Every name a loop may have: one per stage, and <stage>_<class> for the class looks (the egg has no class).
PANEL_CLIP_NAMES = PANEL_STAGE_CLIPS + tuple("%s_%s" % (s, c) for s in PANEL_STAGE_CLIPS[1:] for c in PANEL_CLASS_CLIPS)


def panel_paths(cdir):
    folder = os.path.join(cdir, "cclevel", "panel")
    agent = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", PANEL_LABEL + ".plist")
    return folder, agent


def panel_stop(launchctl):
    """Stops the running panel, if there is one; quiet either way."""
    if launchctl:
        subprocess.run([launchctl, "bootout", "gui/%d/%s" % (os.getuid(), PANEL_LABEL)], capture_output=True, timeout=30)


def panel_command(args, cdir):
    """Puts the creature in the macOS menu bar (on, which asks first) or takes it out again (off)."""
    folder, agent = panel_paths(cdir)
    launchctl = shutil.which("launchctl")
    if args.panel == "off":
        panel_stop(launchctl)
        defaults = shutil.which("defaults") if sys.platform == "darwin" else None
        if defaults:   # where macOS kept the menu bar item's position: the panel program's own preferences
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run([defaults, "delete", PANEL_PREFS], capture_output=True, timeout=30)
        found = False
        clips = os.path.join(folder, "creatures")
        for path in (agent, *(os.path.join(folder, name) for name in PANEL_FILES),
                     *(os.path.join(clips, name + ext) for name in PANEL_CLIP_NAMES for ext in (".mp4", ".mp4.copying"))):
            try:
                os.remove(path)
                found = True
            except FileNotFoundError:
                pass
        for path in (clips, folder):   # only if empty: anything else in there is not the panel's
            with contextlib.suppress(OSError):
                os.rmdir(path)
        # The session-start hook's last group read for the panel, removed once the panel's program is gone and under the
        # board lock, so a hook that saw the panel a moment ago cannot write it again afterwards. A folder there stays.
        if os.path.isdir(os.path.dirname(group_read_path(cdir))):   # no lock file made on a machine without cclevel's folder
            with contextlib.suppress(Busy, OSError), board_lock(cdir, 30):
                if os.path.lexists(group_read_path(cdir)):
                    os.remove(group_read_path(cdir))
        print("Panel off: the creature has left the menu bar and no longer starts at login." if found
              else "The panel was not on. Nothing to remove.")
        return 0
    if sys.platform != "darwin":
        print("cclevel: the panel is for macOS. The card and the creature band above the prompt work everywhere.")
        return 1
    swiftc = shutil.which("swiftc")
    if not swiftc or not launchctl:
        print("cclevel: the panel is built on this Mac with Apple's free command line tools, and they are not installed.")
        print("  Install them with: xcode-select --install   Then run --panel on again.")
        return 1
    source = os.path.realpath(PANEL_SOURCE)
    if not os.path.isfile(source):
        print("cclevel: this copy of the plugin has no panel source (%s)." % source)
        return 1
    card = os.path.join(folder, "card.json")
    if not args.yes:
        print("The panel puts your creature in the Mac menu bar: click it for a small black panel with the creature and its stats.")
        print("Turning it on will:")
        print("  1. build a small program from the plugin's own source (mac/CclevelPanel.swift) with Apple's swiftc,")
        print("     into %s" % folder)
        print("  2. copy this scanner and the creature's animations (about 1.7 MB) there, so the panel keeps")
        print("     working when the plugin updates")
        print("  3. start it now and at every login, with %s" % agent)
        print("It scores your setup offline (--json --no-save, which writes nothing) at most once an hour, and again right")
        print("after an update or when a check-in or group read saves something new, keeps the last result in")
        print("%s, and sends nothing. It starts at the right end of your menu bar items; macOS keeps where it sits" % card)
        print("(and where you ⌘-drag it) in the program's own preferences, cclevel-panel. --panel off removes all of it.")
        print("Its Friends page shows your private group as the last check-in, Claude Code start (at most every 15")
        print("minutes) or --group saved it (Default mode);")
        print("in Privacy mode cclevel sends nothing and the page says friends are off.")
        print("Run again with --yes to go ahead.")
        return 0
    os.makedirs(folder, mode=0o700, exist_ok=True)
    binary, building, scanner = (os.path.join(folder, n) for n in ("cclevel-panel", "cclevel-panel.building", "cclevel.py"))
    print("Building the panel with swiftc (a minute or so the first time)...", flush=True)
    try:
        build = subprocess.run([swiftc, "-O", "-o", building, source], capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        build = None
    if build is None or build.returncode != 0 or not os.path.isfile(building):
        with contextlib.suppress(OSError):
            os.remove(building)
        print("cclevel: building the panel failed%s" % (". swiftc said:\n" + build.stderr.strip()[-2000:] if build else " (it took too long)."))
        return 1
    os.chmod(building, 0o700)
    os.replace(building, binary)
    with open(os.path.realpath(__file__), encoding="utf-8") as f:
        write_private(scanner, f.read())
    clips = os.path.join(folder, "creatures")
    os.makedirs(clips, mode=0o700, exist_ok=True)
    for name in PANEL_CLIP_NAMES:   # a clip missing from this copy of the plugin: that stage shows its text art
        src = os.path.realpath(os.path.join(PANEL_CLIPS, name + ".mp4"))
        if os.path.isfile(src):
            dst = os.path.join(clips, name + ".mp4")
            shutil.copyfile(src, dst + ".copying")
            os.chmod(dst + ".copying", 0o600)
            os.replace(dst + ".copying", dst)
    program = [binary, "--python", sys.executable, "--scanner", scanner, "--claude-dir", cdir, "--cache", card]
    os.makedirs(os.path.dirname(agent), exist_ok=True)
    write_private(agent, plistlib.dumps({"Label": PANEL_LABEL, "ProgramArguments": program, "RunAtLoad": True,
                                         "ProcessType": "Interactive", "LimitLoadToSessionType": "Aqua"}).decode("utf-8"))
    panel_stop(launchctl)   # a copy from an earlier --panel on
    # Its card was written by the scanner copy it ran, which may be an older version without what this one shows (the
    # Friends page came with 0.16.0). With no card, the new panel scores the setup as soon as it starts.
    with contextlib.suppress(OSError):   # none there, or one that cannot go: the panel still starts, as before
        os.remove(card)
    # macOS finishes stopping that copy in the background, and starting the new one before it has fails ("5:
    # Input/output error"). So a start that fails is tried again, up to three times, a second apart.
    for attempt in range(PANEL_START_TRIES):
        start = subprocess.run([launchctl, "bootstrap", "gui/%d" % os.getuid(), agent], capture_output=True, text=True,
                               timeout=30)
        if start.returncode == 0 or attempt == PANEL_START_TRIES - 1:
            break
        time.sleep(1)
    if start.returncode != 0:
        print("cclevel: the panel was built but did not start (%s). Try --panel on --yes again, or --panel off."
              % (start.stderr.strip() or "launchctl exit %d" % start.returncode))
        return 1
    print("The creature is in your menu bar. Click it for the panel; right-click it for Refresh or Quit.")
    print("It starts at every login. After a plugin update, run --panel on --yes again to update it. --panel off removes it.")
    return 0


def render_learn(result, done):
    """The training path: every lesson per stat, ticked or not, with how to do the next one."""
    total = sum(len(ls) for ls in LESSONS.values())
    out = ["", "  Training · %d of %d lessons done" % (len(done), total), ""]
    for stat in STAT_ORDER:
        lessons = LESSONS[stat]
        n = sum(1 for l in lessons if l[0] in done)
        out.append("  %s %d/%d%s" % (stat.capitalize(), n, len(lessons), " · trained" if n == len(lessons) else ""))
        nxt = next((l[0] for l in lessons if l[0] not in done), None)
        for lesson, title, how, page in lessons:
            out.append("   [%s] %s" % ("x" if lesson in done else " ", title))
            if lesson == nxt:
                out.append("       How: %s  %s%s" % (how, DOCS, page))
        out.append("")
    out += ["  A lesson ticks itself when your Claude Code logs show it done, and stays ticked.",
            "  Lessons teach; they never change your level, XP or rank. Facts checked against the docs on %s." % TIPS_CHECKED,
            "  A how-to under each Need and a tip a day on the card: /pet tips on.", ""]
    return "\n".join(out)


def panel_extras(cdir, result):
    """What the menu bar panel's Fix next and Learn cards show: the top Needs with how to fix each, the training path with
    each stat's next lesson, and the tip of the day. Worked out like the card, --learn and the tips; offline, saves nothing."""
    fix = []
    for n in result["needs"][:5]:   # every Need the card shows; the how-to and docs page where there is one
        how, page = HOWTO.get(n["code"], ("", ""))
        fix.append({"text": need_text(n), "how": how, "docs": DOCS + page if page else ""})
    state = load_training(cdir)
    done = set(state["done"]) | set(result["lessons"])
    stats = []
    for stat in STAT_ORDER:
        lessons = LESSONS[stat]
        nxt = next((l for l in lessons if l[0] not in done), None)
        stats.append({"stat": stat, "done": sum(1 for l in lessons if l[0] in done), "total": len(lessons),
                      "next": nxt and {"title": nxt[1], "how": nxt[2], "docs": DOCS + nxt[3]}})
    tip, _ = tip_of_the_day(state, result)   # read only: the panel never records a tip as shown
    return {"fix": fix,
            "learn": {"done": len(done), "total": sum(len(ls) for ls in LESSONS.values()), "stats": stats, "checked": TIPS_CHECKED},
            "tip": tip and {"stat": tip[0], "text": tip[1][1], "docs": DOCS + tip[1][2]}}


def learn_command(cdir, result, save):
    """Shows the training path. Offline: it reads the logs like the card and remembers the ticks on this machine."""
    state = load_training(cdir)
    done = set(state["done"]) | set(result["lessons"])
    if save and done - set(state["done"]):
        try:
            save_training(cdir, lambda now: tick(now, result))
        except (Busy, OSError):
            pass   # shown anyway; remembered at the next run
    print(render_learn(result, done))
    return 0


# ------------------------------------------------------------ leaderboard
# ------------------------------------------------------------------ leak finder
# Where the tokens went over the last weeks, priced with API list prices as a yardstick: never a charge, since most
# people pay a subscription. Outside the score. Reads only this machine's logs and prints; nothing is stored or sent.
PRICES_CHECKED = "2026-10-06"
PRICES_PAGE = "https://platform.claude.com/docs/en/about-claude/pricing"
# Dollars per million tokens: (input, output, cache read). A cache write is 1.25x input (5 minutes) or 2x (1 hour).
PRICES = {
    "claude-opus-5-5": (4, 20, 0.20), "claude-opus-5": (5, 25, 0.5), "claude-opus-4-8": (5, 25, 0.5),
    "claude-opus-4-7": (5, 25, 0.5), "claude-opus-4-6": (5, 25, 0.5),
    "claude-sonnet-5-5": (2, 10, 0.20), "claude-sonnet-5": (2, 10, 0.2), "claude-sonnet-4-6": (3, 15, 0.3),
    "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-haiku-4-5": (1, 5, 0.1),
    "claude-fable-5-1": (10, 50, 0.25), "claude-fable-5": (10, 50, 1),
}
FAST_PRICES = {"claude-opus-5-5": (8, 40, 0.40)}      # fast mode; any other model in fast mode has no price here
HAIKU_LONG = ("claude-haiku-5-5", 100000, (0.50, 2.50, 0.05))   # its price above 100K prompt tokens
CACHE_5M, CACHE_1H = 1.25, 2
PAUSE_5M, PAUSE_1H = 300, 3600     # seconds: a reply this long after the one before usually writes the cache again
LEAK_WEEKS = 4                     # full ISO weeks before this one; logs live 30 days
LEAK_GAP = 0.15                    # how far the yardstick may sit from Claude Code's own cost figure for a session
LEAK_NUDGE = 5                     # dollars a week (yardstick) from which the card names the biggest leak, tips on
LEAK_KINDS = (("input_tokens", "fresh input"), ("cache_creation_input_tokens", "cache writes"),
              ("cache_read_input_tokens", "cache reads"), ("output_tokens", "output"))
LEAK_HOW = {
    "pauses": "before a long break, /compact or start a new session; short pauses keep the cache.",
    "startup": "keep CLAUDE.md to the rules; move long how-tos into skills.",
    "compaction": "/compact on your own terms with what to keep, or split long jobs into sessions.",
    "connectors": "remove the ones you no longer need. /mcp shows them.",
}
LEAK_NAMES = {"pauses": "cache lost to pauses", "startup": "start-up context", "compaction": "auto-compaction"}
LOG_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")   # how Claude Code turns a server name into its mcp__<name>__ prefix


def leak_line(extra, line, path):
    """A compaction or a cost-state line, kept for the leak finder."""
    try:
        o = json.loads(line)
    except ValueError:
        return
    if not isinstance(o, dict):
        return
    if o.get("subtype") == "compact_boundary":
        meta = as_dict(o.get("compactMetadata"))
        extra.setdefault("compactions", []).append({
            "day": day_of(o.get("timestamp")), "time": str(o.get("timestamp") or ""), "file": path,
            "trigger": str(meta.get("trigger") or "unknown"), "pre": meta.get("preTokens"), "post": meta.get("postTokens")})
    elif o.get("type") == "cost-state" and isinstance(o.get("totalCostUSD"), (int, float)):
        extra.setdefault("cost_state", {})[path] = o["totalCostUSD"]


def price_of(model, usage):
    """(input, output, cache read) per million tokens for one reply, or None when this model has no price here."""
    model = re.sub(r"\[.*\]$", "", str(model))
    table = FAST_PRICES if usage.get("speed") == "fast" else PRICES
    for key in sorted(table, key=len, reverse=True):
        if model == key or model.startswith(key + "-") and model[len(key) + 1:len(key) + 2].isdigit() \
                and len(model) - len(key) > 2:
            if key == HAIKU_LONG[0] and sum(num(usage.get(k)) for k, _ in LEAK_KINDS[:3]) > HAIKU_LONG[1]:
                return HAIKU_LONG[2]
            return table[key]
    return None


def cache_split(u):
    """(5-minute, 1-hour) cache write tokens. Without the split, every write counts as a 5-minute one."""
    c = as_dict(u.get("cache_creation"))
    if "ephemeral_5m_input_tokens" in c or "ephemeral_1h_input_tokens" in c:
        return num(c.get("ephemeral_5m_input_tokens")), num(c.get("ephemeral_1h_input_tokens"))
    return num(u.get("cache_creation_input_tokens")), 0


def dollars(model, u):
    p = price_of(model, u)
    if p is None:
        return None
    w5, w1 = cache_split(u)
    return (num(u.get("input_tokens")) * p[0] + num(u.get("output_tokens")) * p[1]
            + num(u.get("cache_read_input_tokens")) * p[2] + w5 * p[0] * CACHE_5M + w1 * p[0] * CACHE_1H) / 1e6


def write_dollars(model, u, w5, w1):
    p = price_of(model, u)
    return None if p is None else (w5 * p[0] * CACHE_5M + w1 * p[0] * CACHE_1H) / 1e6


def seconds(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def session_of(path):
    """The session a log belongs to: a subagent's log counts with the session that started it."""
    parts = path.split(os.sep)
    if "subagents" in parts:
        return os.sep.join(parts[:parts.index("subagents")]) + ".jsonl"
    return path


def leaks(extra, result, today):
    """The leak report's numbers and names. Never part of the card's --json or the check-in."""
    monday = today - timedelta(days=today.weekday())
    since = monday - timedelta(weeks=LEAK_WEEKS)
    since_s, until_s, d30 = since.isoformat(), today.isoformat(), (today - timedelta(days=RECENT_WINDOW_DAYS - 1)).isoformat()
    reqs = [r for r in extra.get("requests", []) if r["day"] and since_s <= r["day"] <= until_s]
    weeks = []
    for i in range(LEAK_WEEKS + 1):
        start = since + timedelta(weeks=i)
        y, w, _ = start.isocalendar()
        weeks.append({"week": "%d-W%02d" % (y, w), "since": start.isoformat(), "so_far": i == LEAK_WEEKS,
                      "tokens": {k: 0 for k, _ in LEAK_KINDS}, "dollars": 0.0})
    totals, totals_30 = Counter(), Counter()
    unpriced = defaultdict(int)
    by_file = defaultdict(list)
    per_session = defaultdict(float)
    for r in extra.get("requests", []):
        if r["day"] and d30 <= r["day"] <= until_s:
            for k, _ in LEAK_KINDS:
                totals_30[k] += num(r["usage"].get(k))
    for r in reqs:
        u = r["usage"]
        wk = weeks[min(LEAK_WEEKS, (date.fromisoformat(r["day"]) - since).days // 7)]
        for k, _ in LEAK_KINDS:
            wk["tokens"][k] += num(u.get(k))
            totals[k] += num(u.get(k))
        cost = dollars(r["model"], u)
        if cost is None:
            unpriced[r["model"]] += sum(num(u.get(k)) for k, _ in LEAK_KINDS)
        else:
            wk["dollars"] += cost
            per_session[session_of(r["file"])] += cost
        r["sec"] = seconds(r["time"])
        if r["sec"] is not None:
            by_file[r["file"]].append(r)
    for rs in by_file.values():
        rs.sort(key=lambda r: r["sec"])
    n_weeks = max(1.0, ((today - since).days + 1) / 7)
    found = []

    # Cache written again after a pause.
    times, tokens, cost = 0, 0, 0.0
    for rs in by_file.values():
        for before, r in zip(rs, rs[1:]):
            gap = r["sec"] - before["sec"]
            w5, w1 = cache_split(r["usage"])
            w5, w1 = (w5 if gap > PAUSE_5M else 0), (w1 if gap > PAUSE_1H else 0)
            if w5 + w1:
                times += 1
                tokens += w5 + w1
                cost += write_dollars(r["model"], r["usage"], w5, w1) or 0
    found.append({"code": "pauses", "times": times, "tokens": tokens, "per_week": cost / n_weeks})

    # The start-up context, read by every request: a lower bound, priced as cache reads.
    ctx = dict(extra.get("context") or {})
    ctx_tokens = sum(ctx.values())
    cost = sum((price_of(r["model"], r["usage"]) or (0, 0, 0))[2] for r in reqs) * ctx_tokens / 1e6
    found.append({"code": "startup", "tokens": ctx_tokens, "parts": ctx, "requests_per_week": round(len(reqs) / n_weeks),
                  "per_week": cost / n_weeks})

    # Auto-compaction, and the cache the next reply in that log writes again.
    comps = [c for c in extra.get("compactions", []) if c["day"] and since_s <= c["day"] <= until_s]
    auto = [c for c in comps if c["trigger"] == "auto"]
    rewrite, cost = 0, 0.0
    for c in auto:
        t = seconds(c["time"])
        nxt = next((r for r in by_file.get(c["file"], []) if t is not None and r["sec"] > t), None)
        if nxt:
            w5, w1 = cache_split(nxt["usage"])
            rewrite += w5 + w1
            cost += write_dollars(nxt["model"], nxt["usage"], w5, w1) or 0
    sizes = [c["pre"] for c in auto if isinstance(c["pre"], (int, float))]
    sessions = {session_of(r["file"]) for r in reqs}
    found.append({"code": "compaction", "times": len(auto), "manual": len(comps) - len(auto),
                  "sessions": len({session_of(c["file"]) for c in auto}), "of_sessions": len(sessions),
                  "average_before": round(sum(sizes) / len(sizes)) if sizes else None,
                  "tokens_written_again": rewrite, "per_week": cost / n_weeks})

    # Connectors set up but not called in 30 days: no dollar figure, since tool search keeps idle ones small.
    called = set()
    for day, d in (extra.get("days") or {}).items():
        if d30 <= day <= until_s:
            called |= {LOG_NAME_RE.sub("_", s) for s in d["servers_called"]}
    idle = sorted({shown for name, shown in (extra.get("connectors") or {}).items()
                   if LOG_NAME_RE.sub("_", name) not in called}, key=str.lower)
    found.sort(key=lambda f: -f["per_week"])
    checks = [{"session": os.path.basename(f)[:-6], "yardstick": round(per_session[f], 4), "claude_code": c,
               "close": abs(per_session[f] - c) <= LEAK_GAP * c}
              for f, c in sorted((extra.get("cost_state") or {}).items()) if f in per_session]
    return {"since": since_s, "until": until_s, "prices_checked": PRICES_CHECKED, "prices_page": PRICES_PAGE,
            "weeks": weeks, "totals": dict(totals), "totals_30d": {k: totals_30[k] for k, _ in LEAK_KINDS},
            "cache_read_share": (totals["cache_read_input_tokens"] / sum(totals[k] for k, _ in LEAK_KINDS[:3])
                                 if sum(totals[k] for k, _ in LEAK_KINDS[:3]) else None),
            "unpriced": dict(unpriced), "leaks": found,
            "compactions": {"auto": len(auto), "manual": len(comps) - len(auto)},
            "unused_connectors": idle, "unused_skills": result["raw"].get("skills_unused", 0),
            "cost_state": checks, "requests": len(reqs)}


def tok_short(n):
    return "%.1fM" % (n / 1e6) if n >= 100000 else "%dk" % round(n / 1000) if n >= 1000 else str(int(n))


def money(x):
    return "$%d" % round(x) if x >= 10 else "$%.2f" % x


def leak_card_line(report):
    """The card's one line about the biggest leak, or None while every leak is small."""
    top = report["leaks"][0] if report["leaks"] else None
    if not top or top["per_week"] < LEAK_NUDGE:
        return None
    return "Leaks: about %s a week in %s (yardstick). /pet leaks" % (money(top["per_week"]), LEAK_NAMES[top["code"]])


def leaks_text(report):
    if not report["requests"] and not report["compactions"]["auto"] + report["compactions"]["manual"]:
        return "\n  No session logs in the last 30 days, so no leaks to measure.\n"
    out = ["", "  Leaks · last %d weeks · this machine only" % LEAK_WEEKS,
           "  API-price yardstick, not a charge. Prices of %s." % PRICES_CHECKED, ""]
    labels = [w["week"][-3:] + (" so far" if w["so_far"] else "") for w in report["weeks"]]
    out.append("  %-18s" % "Where tokens went" + "".join("%12s" % l for l in labels))
    for k, name in LEAK_KINDS:
        out.append("   %-17s" % name + "".join("%12s" % tok_short(w["tokens"][k]) for w in report["weeks"]))
    out.append("   %-17s" % "yardstick" + "".join("%12s" % money(w["dollars"]) for w in report["weeks"]))
    if report["cache_read_share"] is not None:
        out.append("  Cache reads: %d%% of all input." % round(100 * report["cache_read_share"]))
    for model, n in sorted(report["unpriced"].items()):
        out.append("  %s: %s tokens, no price for this model." % (model, tok_short(n)))
    out.append("")
    i = 0
    for f in report["leaks"]:
        i += 1
        if f["code"] == "pauses":
            if not f["times"]:
                i -= 1
                continue
            out.append("   %d. Cache written again after pauses: %s, %s tokens, about %s a week (yardstick)."
                       % (i, count(f["times"], "time"), tok_short(f["tokens"]), money(f["per_week"])))
        elif f["code"] == "startup":
            p = f["parts"]
            parts = ", ".join("%s %s" % (name, tok_short(p.get(k, 0))) for k, name in (
                ("claude_md", "CLAUDE.md"), ("memory_index", "memory index"), ("skill_descriptions", "skill descriptions"),
                ("project_claude_md", "this folder's CLAUDE.md")) if p.get(k))
            out.append("   %d. Start-up context about %s tokens (estimate%s)," % (i, tok_short(f["tokens"]),
                                                                              ": " + parts if parts else ""))
            out.append("      read by about {:,} requests a week: at least {} a week (yardstick).".format(
                f["requests_per_week"], money(f["per_week"])))
        else:
            if not f["times"]:
                out.append("   %d. Auto-compaction: none seen in %d weeks%s." % (
                    i, LEAK_WEEKS, " (%s typed)" % count(f["manual"], "/compact") if f["manual"] else ""))
            else:
                size = ", average %s tokens before" % tok_short(f["average_before"]) if f["average_before"] else ""
                typed = " (and %s typed)" % count(f["manual"], "/compact") if f["manual"] else ""
                out.append("   %d. Auto-compaction: %s in %d weeks%s, in %d of %s%s." % (
                    i, count(f["times"], "time"), LEAK_WEEKS, typed, f["sessions"], count(f["of_sessions"], "session"), size))
                out.append("      The next reply wrote %s tokens of cache again: about %s a week (yardstick)." % (
                    tok_short(f["tokens_written_again"]), money(f["per_week"])))
        out.append("      How: " + LEAK_HOW[f["code"]])
    idle = report["unused_connectors"]
    i += 1
    if idle:
        shown = ", ".join(idle[:10]) + (", and %d more" % (len(idle) - 10) if len(idle) > 10 else "")
        out += ["   %d. Connectors set up but not called in %d days: %d:" % (i, RECENT_WINDOW_DAYS, len(idle)),
                "      %s." % shown,
                "      No dollar figure: with tool search (the default) an idle connector costs little context.",
                "      Still worth removing: slower start-up and sign-in prompts. /mcp shows them."]
    else:
        out.append("   %d. Connectors: every one set up was called in the last %d days." % (i, RECENT_WINDOW_DAYS))
    if report["unused_skills"]:
        i += 1
        out.append("   %d. Own skills unused for %d days: %d (also under Needs on the card)." % (
            i, USED_WINDOW_DAYS, report["unused_skills"]))
    checks = report["cost_state"]
    if checks:
        off = [c for c in checks if not c["close"]]
        out += ["", "  Checked against Claude Code's own cost figure in %s: %d within %d%%." % (
            count(len(checks), "session"), len(checks) - len(off), round(100 * LEAK_GAP))]
        out += ["   %s: yardstick %s, Claude Code %s." % (c["session"][:8], money(c["yardstick"]), money(c["claude_code"]))
                for c in off[:5]]
    out += ["", "  Exact view of this session: /context. Plan use: /usage.", ""]
    return "\n".join(out)


# ------------------------------------------------------------------ timesheet
# Hours per project from the session logs, in local time. Outside the score. Reads only this machine's logs; the
# printed view numbers the projects, so names stay out of the conversation. Names and every block go only into
# timesheet.csv on this machine. Nothing is sent.
TS_IDLE = 15                       # minutes without activity that end a block (--idle changes it)
TS_COLUMNS = 5                     # numbered project columns in the printed view; the rest share "others"
TS_HOME = "(home)"
TS_HEADER = ["date", "weekday", "start", "end", "minutes", "kind", "project", "project_no", "sessions", "prompts",
             "tz", "utc_offset"]


def idle_minutes(v):
    try:
        n = int(v)
    except ValueError:
        n = 0
    if not 1 <= n <= 240:
        raise argparse.ArgumentTypeError("takes whole minutes from 1 to 240")
    return n


def ts_zone(name):
    """(tzinfo or None for this machine's zone, the zone's name, a warning or None)."""
    def machine():
        tz = os.environ.get("TZ", "")
        if "/" in tz:
            return tz.lstrip(":")
        try:
            link = os.path.realpath("/etc/localtime")
            if "zoneinfo" + os.sep in link:
                return link.split("zoneinfo" + os.sep, 1)[1]
        except OSError:
            pass
        return datetime.now().astimezone().tzname() or "local time"
    if not name:
        return None, machine(), None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name), name, None
    except Exception:   # an unknown name, or no zone database on this machine
        here = machine()
        return None, here, "Unknown time zone '%s'. Using this machine's zone (%s)." % (name, here)


def ts_local(t, tz):
    return datetime.fromtimestamp(t, tz) if tz else datetime.fromtimestamp(t).astimezone()


def ts_root(cwd, cache, home):
    """The project a working folder belongs to: the nearest folder at or above it that holds .git, or the folder
    itself. A worktree under <repo>/.claude/worktrees/<name> counts as <repo>. The home folder and / are (home)."""
    if cwd in cache:
        return cache[cwd]
    path = os.path.normpath(cwd)
    parts = path.split(os.sep)
    if ".claude" in parts and parts.index(".claude") + 1 < len(parts) and parts[parts.index(".claude") + 1] == "worktrees":
        path = os.sep.join(parts[:parts.index(".claude")]) or os.sep
    if path in (home, os.sep) or re.fullmatch(r"/(Users|home)/[^/]+", path):
        cache[cwd] = TS_HOME
        return TS_HOME
    root, probe = path, path
    while probe not in (home, os.sep, ""):
        if os.path.exists(os.path.join(probe, ".git")):
            root = probe
            break
        probe = os.path.dirname(probe)
    cache[cwd] = root
    return root


def ts_scan(cdir):
    """Every log line's time, working folder and whether a person typed it, grouped by session (a subagent's log
    counts with the session that started it). Returns ({session: {"events", "alone"}}, earliest time)."""
    root = os.path.join(cdir, "projects")
    files = glob.glob(os.path.join(root, "*", "*.jsonl")) + \
        glob.glob(os.path.join(root, "*", "*", "subagents", "**", "*.jsonl"), recursive=True)
    sessions = defaultdict(lambda: {"events": [], "alone": False})
    first = None
    for path in files:
        sub = os.sep + "subagents" + os.sep in path
        s = sessions[session_of(path)]
        rows, cwd0 = [], None
        try:
            fh = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"timestamp"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict) or o.get("type") not in ("user", "assistant", "system", "attachment"):
                    continue
                t = seconds(o.get("timestamp"))
                if t is None:
                    continue
                if str(o.get("entrypoint") or "").startswith("sdk"):
                    s["alone"] = True
                cwd = o.get("cwd") if isinstance(o.get("cwd"), str) and o.get("cwd") else None
                cwd0 = cwd0 or cwd
                prompt = False
                if o.get("type") == "user" and not sub and not o.get("isMeta") and not o.get("isSidechain"):
                    c = as_dict(o.get("message")).get("content")
                    prompt = not (isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                                              for b in c))
                    if o.get("sessionKind") == "bg":   # a background job: only what a person typed, not notices or peers
                        prompt = prompt and as_dict(o.get("origin")).get("kind") == "human"
                rows.append([t, cwd, prompt])
        for r in rows:
            if r[1] is None:
                r[1] = cwd0   # a line without its folder belongs where the log started
            if r[1] is not None:
                s["events"].append(tuple(r))
                first = r[0] if first is None else min(first, r[0])
    return {k: v for k, v in sessions.items() if v["events"]}, first


def ts_blocks(sessions, idle, tz, home):
    """The CSV rows: one per block, per session and project. A block runs from its first event to its last, start
    rounded down and end up to the minute, at least 1 minute; a gap longer than `idle` minutes ends it. Each block is
    split at local midnight and where the UTC offset changes, so every row has one date and one offset."""
    cache, rows = {}, []
    for key in sorted(sessions):
        s = sessions[key]
        by_project = defaultdict(list)
        for t, cwd, prompt in s["events"]:
            by_project[ts_root(cwd, cache, home)].append((t, prompt))
        for project, evs in by_project.items():
            evs.sort()
            blocks = [[evs[0][0], evs[0][0], int(evs[0][1])]]
            for t, prompt in evs[1:]:
                if t - blocks[-1][1] > idle * 60:
                    blocks.append([t, t, 0])
                blocks[-1][1] = t
                blocks[-1][2] += prompt
            for start, end, prompts in blocks:
                a = int(start // 60)
                b = max(a + 1, int(-(-end // 60)))
                kind = "you" if prompts and not s["alone"] else "alone"
                pieces = []
                for m in range(a, b):
                    loc = ts_local(m * 60, tz)
                    tag = (loc.date(), loc.utcoffset())
                    if pieces and pieces[-1]["tag"] == tag:
                        pieces[-1]["b"] = m + 1
                    else:
                        pieces.append({"tag": tag, "a": m, "b": m + 1, "project": project, "kind": kind,
                                       "session": key, "prompts": 0})
                pieces[0]["prompts"] = prompts   # a block's prompt count sits on its first row
                rows += pieces
    return rows


def ts_union(spans):
    """Minutes covered by a set of (start, end) minute spans."""
    total, reach = 0, None
    for a, b in sorted(spans):
        if reach is None or a > reach:
            total += b - a
            reach = b
        elif b > reach:
            total += b - reach
            reach = b
    return total


def ts_week(arg, today):
    """The Monday of the week asked for: this, last or YYYY-Www."""
    if arg in (None, "this"):
        return today - timedelta(days=today.weekday())
    if arg == "last":
        return today - timedelta(days=today.weekday() + 7)
    m = re.fullmatch(r"(\d{4})-W(\d{1,2})", arg or "")
    if m:
        try:
            return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            pass
    return None


def hm(minutes):
    if not minutes:
        return "-"
    h, m = divmod(int(minutes), 60)
    return "%dh %02dm" % (h, m) if h else "%dm" % m


def ts_offset(delta):
    mins = int(delta.total_seconds() // 60)
    return "%s%02d:%02d" % ("-" if mins < 0 else "+", abs(mins) // 60, abs(mins) % 60)


def ts_hhmm(m, off, day):
    """A row's start or end as local HH:MM, in the row's own UTC offset; a row ending at midnight ends at 24:00."""
    loc = datetime.fromtimestamp(m * 60, timezone(off))
    return "24:00" if loc.date() > day else loc.strftime("%H:%M")


def timesheet(cdir, week=None, idle=TS_IDLE, tz_name=None, names=False, now=None):
    """The printed view, and timesheet.csv beside the ledger. Returns the text to print."""
    tz, zone, warning = ts_zone(tz_name)
    now = now if now is not None else time.time()
    today = ts_local(now, tz).date()
    monday = ts_week(week, today)
    if monday is None:
        return "cclevel: --timesheet takes this, last or a week like 2026-W45."
    head = [warning] if warning else []
    sessions, first = ts_scan(cdir)
    if not sessions:
        return "\n".join(head + ["", "  No session logs in the last 30 days, so no timesheet.", ""])
    home = os.path.normpath(os.path.expanduser("~"))
    rows = ts_blocks(sessions, idle, tz, home)
    # Numbers: projects with the most time in the week shown first, then the rest by all their time.
    days = [monday + timedelta(days=i) for i in range(7)]
    in_week = [r for r in rows if monday <= r["tag"][0] <= days[-1]]
    def time_of(rs, p):
        return ts_union((r["a"], r["b"]) for r in rs if r["project"] == p)
    projects = sorted({r["project"] for r in rows if r["project"] != TS_HOME},
                      key=lambda p: (-time_of(in_week, p), -time_of(rows, p), p))
    number = {p: i + 1 for i, p in enumerate(projects)}
    base = defaultdict(set)
    for p in projects:
        base[os.path.basename(p) or p].add(p)
    def label(p):
        if p == TS_HOME:
            return TS_HOME
        name = os.path.basename(p) or p
        return "%s/%s" % (os.path.basename(os.path.dirname(p)), name) if len(base[name]) > 1 else name
    csv_text = ts_csv(rows, zone, number, label)
    path = os.path.join(cdir, "cclevel", "timesheet.csv")
    try:
        if os.path.islink(path) or (os.path.exists(path) and not os.path.isfile(path)):
            saved = "Not written: %s is a link or not a plain file. Remove it and run again." % path
        else:
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            write_private(path, csv_text)
            saved = "Project names and every block: %s (on this machine only)." % path
    except OSError as e:
        saved = "Could not write %s (%s)." % (path, e.strerror or type(e).__name__)

    y, w, _ = monday.isocalendar()
    out = head + ["", "  Timesheet · week %d-W%02d · %s · this machine only" % (y, w, zone),
                  "  A block ends after %d min without activity. Activity, not proof you were at the desk." % idle, ""]
    shown = [p for p in projects if time_of(in_week, p)]
    cols = shown[:TS_COLUMNS]
    others = shown[TS_COLUMNS:]
    has_home = any(r["project"] == TS_HOME for r in in_week)
    heads = ["P%d" % number[p] for p in cols] + (["others"] if others else []) + ([TS_HOME] if has_home else [])
    out.append("  %-11s%10s%15s" % ("", "with you", "Claude alone") + "".join("%9s" % h for h in heads))
    week_rows = []
    for d in days:
        rs = [r for r in in_week if r["tag"][0] == d]
        if rs:
            week_rows.append(("%s %d %s" % (d.strftime("%a"), d.day, d.strftime("%b")), rs))
    if not week_rows:
        out.append("   No activity in this week.")
    total_line = ("Week", in_week)
    sums = None
    for title, rs in week_rows + ([total_line] if week_rows else []):
        if title == "Week":
            vals = sums
        else:
            you = ts_union((r["a"], r["b"]) for r in rs if r["kind"] == "you")
            alone = ts_union((r["a"], r["b"]) for r in rs) - you
            vals = [you, alone] + [time_of(rs, p) for p in cols]
            if others:
                vals.append(ts_union((r["a"], r["b"]) for r in rs if r["project"] in others))
            if has_home:
                vals.append(time_of(rs, TS_HOME))
            sums = vals if sums is None else [a + b for a, b in zip(sums, vals)]
        out.append("   %-10s%10s%15s" % (title, hm(vals[0]), hm(vals[1])) + "".join("%9s" % hm(v) for v in vals[2:]))
    out.append("")
    if sums and sum(sums[2:]) > sums[0] + sums[1]:
        out.append("  Projects can add up to more than the day when sessions ran side by side.")
    if sums and has_home and sums[-1]:
        out.append("  %s was in sessions started from your home folder: start Claude Code inside a project to split it."
                   % hm(sums[-1]))
    if names and shown:
        out += ["  %-8s%s" % ("P%d" % number[p], label(p)) for p in shown] + [""]
    elif others:
        n = [number[p] for p in others]
        out.append("  others: P%d." % n[0] if len(n) == 1 else "  others: P%d–P%d (%d projects)." % (min(n), max(n), len(n)))
    out.append("  Logs reach back to %s (Claude Code deletes them after 30 days unless cleanupPeriodDays says otherwise)."
               % "{d.day} {d:%b} {d.year}".format(d=ts_local(first, tz).date()))
    out += ["  " + saved, ""]
    return "\n".join(out)


def ts_csv(rows, zone, number, label):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(TS_HEADER)
    for r in sorted(rows, key=lambda r: (r["a"], r["b"], r["project"])):
        day, off = r["tag"]
        w.writerow([day.isoformat(), day.strftime("%a"), ts_hhmm(r["a"], off, day), ts_hhmm(r["b"], off, day),
                    r["b"] - r["a"], r["kind"], label(r["project"]), number.get(r["project"], ""), 1, r["prompts"],
                    zone, ts_offset(off)])
    return buf.getvalue()


# Nothing above this line touches the network. Everything below runs only
# when the user asks for it by flag, or from the plugin's session-start hook
# after the user turned auto check-in on with --auto on.

DEFAULT_SERVER = "https://go.cclevel.workers.dev"   # the public board's check-in address; --server or $CCLEVEL_SERVER picks another
# The public board's website, for the links people open. Check-ins never go there: a custom domain keeps sampled
# visit logs with IP addresses, the workers.dev address keeps none (PRIVACY.md), and the board refuses /api/* there.
PUBLIC_SITE = "https://cclevel.com"
MOVED_FROM = ("https://cclevel-board.cclevel.workers.dev", PUBLIC_SITE, "https://www.cclevel.com")   # the public board's other addresses: same board
RULES_VERSION = 1        # must match RULES in server/src/index.js
MAX_REPLY = 256 * 1024
MAX_COUNT = 10 ** 9      # no honest number from the board is larger than this
LIST_SIZE = 1000         # ranked rows per world list; must match the board
BANDS = (1, 2, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)   # "top X%" cut-offs below them
TOKEN_RE = re.compile(r"[0-9a-f]{64}")
GROUP_RE = re.compile(r"[0-9a-f]{32}")   # a group invite code, made by --group-create
# An invite link carries the code after "#", which browsers never send to a server.
INVITE_LINK_RE = re.compile(r"https?://([^/\s#?]+)\S*?#([0-9a-f]{32})(?![0-9a-f])")
INVITE_CODE_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")
GROUP_MAX = 25           # must match the board
DUEL_DAYS = 7            # must match the board
CARD_VERSION = 2         # must match the card page, server/public/card.js
GH_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")   # GitHub's rule for a login


def server_ok(server):
    """https to any host, or plain http to this machine only. Checked on the parsed address, and an address with a
    name@ part is refused, since the text before the @ can look like a host it is not."""
    try:
        parts = urllib.parse.urlsplit(server)
        parts.port   # an out-of-range or non-numeric port raises
    except ValueError:
        return False
    if "@" in parts.netloc or not parts.hostname:
        return False
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1"))


# Word lists for creature names. They must match server/src/names.js.
ADJECTIVES = [
    "Amber", "Brave", "Bright", "Calm", "Clever", "Cosmic", "Crisp", "Curious", "Dapper", "Daring",
    "Dusty", "Eager", "Early", "Fabled", "Fuzzy", "Gentle", "Giddy", "Golden", "Grand", "Hardy",
    "Hazel", "Humble", "Ivory", "Jolly", "Keen", "Kind", "Lively", "Lucky", "Lunar", "Mellow", "Merry",
    "Mighty", "Misty", "Mossy", "Nimble", "Noble", "Patient", "Plucky", "Polar", "Proud", "Quick",
    "Quiet", "Rapid", "Rustic", "Rusty", "Sandy", "Silent", "Silver", "Sleepy", "Snowy", "Solar",
    "Speedy", "Spry", "Steady", "Stormy", "Sunny", "Swift", "Tidy", "Velvet", "Vivid", "Wandering",
    "Wise", "Witty", "Zesty",
]
ANIMALS = [
    "Axolotl", "Badger", "Bat", "Bear", "Beaver", "Bison", "Capybara", "Cat", "Crane", "Crow", "Deer",
    "Dolphin", "Dragon", "Duck", "Eagle", "Falcon", "Ferret", "Finch", "Fox", "Frog", "Gecko", "Goose",
    "Hare", "Hawk", "Hedgehog", "Heron", "Ibex", "Jackal", "Koala", "Lemur", "Lynx", "Magpie", "Marten",
    "Mole", "Moose", "Moth", "Newt", "Octopus", "Otter", "Owl", "Panda", "Penguin", "Pika", "Puffin",
    "Quail", "Rabbit", "Raccoon", "Raven", "Robin", "Seal", "Shrew", "Sloth", "Snail", "Sparrow",
    "Squid", "Stoat", "Swan", "Tapir", "Toad", "Turtle", "Vole", "Walrus", "Wombat", "Wren",
]
# Text from the board is never printed: it would land in front of the user, or of an agent.
REFUSALS = {
    400: "the board did not accept the data. This copy of cclevel may be out of date",
    401: "the board did not accept the token",
    413: "the board did not accept the data",
    422: "the score does not fit the board's rules. If you reset your ledger, leave the board and join again",
    429: "the board is taking no new creatures right now. Try again in a minute, or tomorrow",
}
# A refused first check-in says which limit it hit. The word is only looked up here, never printed.
JOIN_LIMITS = {
    "network": "too many new creatures from your network this minute. Try again in a minute",
    "full_today": "the board is full for today. Try again tomorrow",
}
OPT_INS = "the world ranking, group and duel joins and GitHub starts can be turned on three times a day together. Try again tomorrow"
WORLD_REFUSALS = {
    401: "the board did not accept the token",
    404: "the board has no creature for this token. Check in with --sync, or join again",
    429: OPT_INS,
}
# Keyed by the board's one-word reason. The word is only looked up here, never printed.
GROUP_REFUSALS = {
    "no_creature": "the board has no creature for this token. Check in with --sync, or join again",
    "no_group": "no group has this code. Check it, or start one with --group-create",
    "full": "this group is full (%d members)" % GROUP_MAX,
    "name_taken": "a member of this group has the same generated name as yours",
    "in_group": "you are already in a group. Leave it first with --group-leave",
    "opt_ins": OPT_INS,
    "busy": "too many group requests. Try again in a minute",
    "unavailable": "groups are not available on this board right now",
    "taken": "that code is already in use. Run --group-create again",
    "not_started": "there is no code to look for. Run --verify-github LOGIN to get one",
    "expired": "the code has expired. Run --verify-github LOGIN again for a new one",
    "verified": "this creature is already verified. Run --unverify-github first to use another account",
    "github": "GitHub did not answer. Try again in a few minutes",
}
GITHUB_REFUSALS = dict(GROUP_REFUSALS, unavailable="the GitHub badge is not available on this board",
                       busy="too many requests. Try again in a minute",
                       too_new="the GitHub badge opens after check-ins on two different days. Check in again tomorrow",
                       code_taken="that code has been used. Run --verify-github LOGIN again for a new one")
DUEL_REFUSALS = {
    "no_creature": GROUP_REFUSALS["no_creature"],
    "no_duel": "no duel has this code. Check it, or start one with --duel-create",
    "full": "this duel already has its two creatures",
    "own_duel": "that is your own duel. Send the link to the friend you challenge",
    "in_duel": "you are in a duel that has not ended. Leave it first with --duel-leave",
    "name_taken": "the creature that started this duel has the same generated name as yours",
    "opt_ins": OPT_INS,
    "busy": "too many duel requests. Try again in a minute",
    "unavailable": "duels are not available on this board right now",
    "taken": "that code is already in use. Run --duel-create again",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A request goes to the address it was made for and is never passed on."""

    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)
# A board on this machine (testing, self-hosting) is reached directly, never through a proxy.
LOCAL_OPENER = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))


def creature_name(token):
    """The generated name for a token, worked out here so that no name from the board is ever shown."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    first, second, number = (int(digest[i:i + 4], 16) for i in (0, 4, 8))
    return "%s %s %04d" % (ADJECTIVES[first % len(ADJECTIVES)], ANIMALS[second % len(ANIMALS)], number % 10000)


def payload(result):
    """Everything a check-in sends, as --preview shows it. Keep in step with PRIVACY.md."""
    return {"v": RULES_VERSION, "xp": result["xp"], "xp_days": result["raw"]["xp_days"],
            "stats": result["stats"], "badges": result["badges"]}


def identity_path(cdir):
    return os.path.join(cdir, "cclevel", "identity.json")


def left_path(cdir):
    return os.path.join(os.path.dirname(identity_path(cdir)), "left")


def off_path(cdir):
    return os.path.join(os.path.dirname(identity_path(cdir)), "opted-out")


def opted_out(cdir):
    """True once --leave (or --auto off before joining) has kept this machine off the board. Anything at the path counts."""
    return os.path.lexists(off_path(cdir))


def opt_out(cdir):
    """Keeps the session-start hook from ever joining this machine. Written under the board lock."""
    os.makedirs(os.path.dirname(off_path(cdir)), exist_ok=True)
    write_private(off_path(cdir), "off\n")


def opt_back_in(cdir):
    """A join by hand, or --privacy off: the hook may check in again. A note that cannot be removed keeps Privacy mode on
    (the hook stays quiet, token or not), so this fails closed."""
    try:
        os.remove(off_path(cdir))
    except FileNotFoundError:
        pass
    except OSError:
        clear_odd(off_path(cdir))


# The two modes. Default mode: the board is on (the hook joins, then checks in once a day). Privacy mode: the opted-out
# note is on this machine and there is no token, so cclevel sends nothing until the user confirms a join or --privacy off.
# "Leaving" is the note with a token still here (a delete that did not go through, or an opt-out that crossed the first
# join): nothing is sent then either, except the requests that remove data from the board.
PRIVACY_ON = "Privacy mode is on: cclevel sends nothing. /pet privacy off to use the board."
STILL_LISTED = "Your row is still on the board: /pet privacy on deletes it."
PRIVACY_NOW = ("Privacy mode is on: cclevel sends nothing from now on (a share-card, Wrapped or invite link you open in a browser"
               " still loads its page from the board's website, cclevel.com for the public board). /pet privacy off goes"
               " back to Default mode.")


def only_removes(args):
    """What a machine that is leaving may still run: requests that only take data off the board, and the two commands
    that only show a saved invite link again and send nothing."""
    return bool(args.world == "off" or args.group_leave or args.duel_leave or args.unverify_github
                or args.group_code or args.duel_code)


def privacy_state(cdir, ident=None):
    """"privacy", "leaving" or None (Default mode). Read from this machine's own files; nothing is sent."""
    if not opted_out(cdir):
        return None
    ident = load_identity(cdir) if ident is None else ident
    return "leaving" if ident.get("token") else "privacy"


def write_private(path, text):
    """A small private file, replaced in one step: readers see the old one or the new one, never half of it."""
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            clear_odd(path)   # only cclevel's own file belongs here; a folder or link in the way would stop the swap
    except OSError:
        pass
    for _ in range(5):
        tmp = "%s-%s.tmp" % (path, secrets.token_hex(8))   # a fresh name each time: nothing can sit in its way
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError(path)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def has_left(cdir, token):
    """True once --leave has deleted this token's row: the note is written right after the board confirms it."""
    try:
        if not stat.S_ISREG(os.lstat(left_path(cdir)).st_mode):
            return False
        with open(left_path(cdir), encoding="utf-8") as f:
            return f.read(200).strip() == token
    except OSError:
        return False


def load_identity(cdir):
    try:
        if not stat.S_ISREG(os.stat(identity_path(cdir)).st_mode):
            return {}   # a pipe, a device or a folder is not an identity, and reading one could block
    except OSError:
        return {}
    ident = load_dict(identity_path(cdir))
    token, server = ident.get("token"), ident.get("server")
    ok = isinstance(token, str) and TOKEN_RE.fullmatch(token) and isinstance(server, str) and server_ok(server)
    return ident if ok and not has_left(cdir, token) else {}


def save_identity(cdir, ident):
    path = identity_path(cdir)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    # The token is the only key to the board row: readable by its owner only, never written through a link. A new file
    # replaces the old one in one step, so a reader sees the old copy or the new one, never a half-written one.
    write_private(path, json.dumps(ident, indent=1))


def tidy_left(cdir):
    """Under the settings lock: once --leave has noted a token as gone, remove it and the note."""
    if not os.path.lexists(left_path(cdir)):
        return
    raw = load_dict(identity_path(cdir)) if os.path.isfile(identity_path(cdir)) else {}
    if isinstance(raw.get("token"), str) and has_left(cdir, raw["token"]):
        os.remove(identity_path(cdir))
    try:
        os.remove(left_path(cdir))   # done with: the left token is gone, or the machine has joined again since
    except OSError:
        clear_odd(left_path(cdir))


def update_identity(cdir, token, change, create=False, require=None, wait=10.0):
    """The one way identity.json is changed: under the lock, from the copy on disk now, never from an older copy.
    `change(ident)` edits it in place. Nothing is written, and None returned, when the file no longer holds this token
    (its owner left or joined again) or when `require(ident)` is false. `create` writes a new file for a first join
    when there is none."""
    with identity_lock(cdir, wait):
        tidy_left(cdir)
        ident = load_identity(cdir)
        if not ident and create:
            ident = {}
        elif ident.get("token") != token:
            return None
        if require is not None and not require(ident):
            return None
        change(ident)
        save_identity(cdir, ident)
        return ident


def moved(server):
    """The public board's check-in address for any form of one of its addresses (case, a trailing slash, a trailing dot
    or :443 on the host). Any other address is left as it is."""
    s = re.sub(r"^(https://[^/:]+?)\.?(?::443)?$", r"\1", server.strip().rstrip("/").lower())
    return DEFAULT_SERVER if s == DEFAULT_SERVER or s in MOVED_FROM else server


def public(server):
    return moved(server) == DEFAULT_SERVER


def send_to(server):
    """Where joining sends its numbers, as the join terms and --privacy off say it. Ends with a comma."""
    if public(server):
        return "the CC level board (cclevel.com) at its check-in address %s, which stores no IP addresses," % DEFAULT_SERVER
    return server.rstrip("/") + ","


def site(server):
    """Where people open this board's links: the public board's website, or a self-hosted board's own address."""
    return PUBLIC_SITE if public(server) else server.rstrip("/")


def board_name(server):
    """How messages name a board: the public one by its website, any other by its address."""
    return "the CC level board (cclevel.com)" if public(server) else "the board at %s" % server.rstrip("/")


def resolve_server(args, ident):
    """The board to talk to. A creature only ever talks to the board it joined."""
    asked = moved(args.server or os.environ.get("CCLEVEL_SERVER") or "")
    home = moved(ident.get("server") or "")
    if home and asked and asked.rstrip("/") != home.rstrip("/"):
        sys.exit("cclevel: this creature lives on %s. Leave that board first, or drop --server and CCLEVEL_SERVER." % board_name(home))
    server = (home or asked or DEFAULT_SERVER).rstrip("/")
    if server and not server_ok(server):
        sys.exit("cclevel: the server address must start with https:// (http:// only for localhost), with no name@ part")
    return server


def parse_reply(raw):
    """A reply from the board as a dict. Anything oversized or odd becomes an empty one."""
    def reject(_):
        raise ValueError

    try:
        return as_dict(json.loads(raw, parse_constant=reject)) if len(raw) <= MAX_REPLY else {}
    except (ValueError, RecursionError):
        return {}


def call(server, method, path, token=None, body=None, timeout=15):
    """One request to the board. Returns (status, reply dict). `timeout` is in seconds, per socket operation."""
    req = urllib.request.Request(server + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "cclevel"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with (LOCAL_OPENER if server.startswith("http://") else OPENER).open(req, timeout=timeout) as resp:
            return resp.status, parse_reply(resp.read(MAX_REPLY + 1))
    except urllib.error.HTTPError as e:
        # A refusal's body goes through the same checks. Only its one-word reason is ever looked up, never printed.
        try:
            return e.code, parse_reply(e.read(MAX_REPLY + 1))
        except (OSError, ValueError, http.client.HTTPException):
            return e.code, {}
    except (OSError, ValueError, http.client.HTTPException) as e:
        # Only the kind of failure is shown: the wording of the error can come from the other end.
        sys.exit("cclevel: could not reach the board (%s)" % type(getattr(e, "reason", e)).__name__)


def counts(value, length):
    """True for a list of that many non-negative whole numbers."""
    return isinstance(value, list) and len(value) == length and all(type(n) is int and 0 <= n <= MAX_COUNT for n in value)


def sane(n):
    return type(n) is int and 0 <= n <= MAX_COUNT


def this_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def board_numbers(reply):
    """The board's latest numbers for this creature, kept so --rank can work offline from the public file."""
    numbers = {k: reply[k] for k in ("witnessed_xp", "season_xp") if sane(reply.get(k))}
    if type(reply.get("world")) is bool:
        numbers["world"] = reply["world"]
    if "season_xp" in numbers:
        numbers["month"] = this_month()
    return numbers


def remember(cdir, ident, reply, create=False):
    """Keep the board's latest numbers, merged into the identity on disk now. `ident` is brought up to date too.
    Returns None when nothing was written: the owner left or joined again meanwhile."""
    numbers = board_numbers(reply)

    def change(now):
        if not now.get("token"):
            now.update(ident)   # a first join: the new token, its board, and auto check-in on
        now.update(numbers)
    saved = update_identity(cdir, ident["token"], change, create=create)
    if saved is not None:
        ident.clear()
        ident.update(saved)
    return saved


def ranking(section):
    """One world list from the board file, checked: (how many are ranked, their XP, band cut-offs), or None."""
    s = as_dict(section)
    ranked, xp, bands = s.get("ranked"), s.get("xp"), s.get("bands")
    if not sane(ranked) or not isinstance(xp, list) or len(xp) > min(ranked, LIST_SIZE) or not counts(xp, len(xp)):
        return None
    if any(a < b for a, b in zip(xp, xp[1:])):
        return None
    if bands is not None:
        ok = isinstance(bands, list) and all(isinstance(b, list) and len(b) == 2 and type(b[0]) is int and b[0] in BANDS
                                             and sane(b[1]) for b in bands)
        bands = bands if ok else None
    return ranked, xp, bands or []


def place(listing, mine):
    """'rank 212' among the ranked rows, or 'top 10%' from the cut-offs. Equal XP shares a place."""
    ranked, xp, bands = listing
    if len(xp) >= ranked or (xp and mine >= xp[-1]):
        return "rank {:,}".format(1 + sum(1 for x in xp if x > mine))
    for percent, cut in sorted(bands):
        if mine >= cut:
            return "top %d%%" % percent
    return "below the top {:,}".format(len(xp))


def rival(listing, mine):
    """The next place up, from the board file alone: (XP needed, its place, its index in the list), or None when nobody is ahead.
    Below the published rows the place is unknown, so it is the gap to the last of them: (XP needed, None, None)."""
    ranked, xp, _ = listing
    if len(xp) < ranked and xp and mine < xp[-1]:
        return xp[-1] - mine, None, None
    above = [x for x in xp if x > mine]
    if not above:
        return None
    target = min(above)
    return target - mine + 1, 1 + sum(1 for x in xp if x > target), xp.index(target)


def spelled(text):
    """A name from the public list, taken only when this copy's own word lists can spell it, and then spelled by them."""
    m = re.fullmatch(r"([A-Za-z]+) ([A-Za-z]+) ([0-9]{4})", text) if isinstance(text, str) else None
    if not m or m.group(1) not in ADJECTIVES or m.group(2) not in ANIMALS:
        return None
    return name_of([ADJECTIVES.index(m.group(1)), ANIMALS.index(m.group(2)), int(m.group(3))])


def rival_line(listing, mine, rows):
    """'1,240 XP to pass #12 (Mossy Falcon 4821)'. The name comes from the public list only when its row has that XP."""
    found = rival(listing, mine)
    if found is None:
        return "    Nobody is ahead of you." if listing[0] else None
    need, at, index = found
    if at is None:
        return "    {:,} XP to reach the top {:,}".format(need, len(listing[1]))
    row = as_dict(rows[index]) if isinstance(rows, list) and index < len(rows) else {}
    name = spelled(row.get("name")) if row.get("xp") == listing[1][index] else None
    return "    {:,} XP to pass #{:,}{}".format(need, at, " (%s)" % name if name else "")


def name_of(key):
    """A creature's name from the three numbers the board sends, spelled with this copy's own word lists."""
    if not (isinstance(key, list) and len(key) == 3 and all(type(n) is int for n in key)):
        return None
    adjective, animal, number = key
    if not (0 <= adjective < len(ADJECTIVES) and 0 <= animal < len(ANIMALS) and 0 <= number < 10000):
        return None
    return "%s %s %04d" % (ADJECTIVES[adjective], ANIMALS[animal], number)


def member(m, xp=("witnessed_xp", "season_xp", "week_xp")):
    """One member from a group reply (or, with xp=("duel_xp",), from a duel reply), checked, or None."""
    m = as_dict(m)
    stats = m.get("stats")
    ok = (name_of(m.get("name")) and type(m.get("level")) is int and 1 <= m["level"] <= LEVEL_MAX
          and all(sane(m.get(k)) for k in xp) and type(m.get("sus")) is bool
          and type(m.get("you")) is bool and isinstance(stats, list) and len(stats) == len(STAT_ORDER)
          and all(type(n) is int and 0 <= n <= 100 for n in stats))
    return m if ok else None


def group_name(code):
    """The group's generated name, worked out from its code on each member's machine. It is never sent."""
    digest = hashlib.sha256(("cclevel-group:" + code).encode()).hexdigest()
    first, second = (int(digest[i:i + 4], 16) for i in (0, 4))
    return "%s %s Crew" % (ADJECTIVES[first % len(ADJECTIVES)], ANIMALS[second % len(ANIMALS)])


# The menu bar panel's Friends page. The panel itself never calls the board: the daily check-in, later session starts
# (see FRIENDS_REREAD) and /pet group save the group's reply in identity.json, and --json shows it from there. A friend who left stays in an older copy only until the
# next read, and no copy older than FRIENDS_FRESH is shown at all.
FRIENDS_FRESH = 36 * 3600   # seconds
# The hook's group read: skipped when the score and check-in already took this long, with a short socket timeout and a
# short wait to save it, so the hook lets go of the board lock soon after its check-in (--leave and --privacy on wait 30 s).
GROUP_READ_AFTER, GROUP_READ_TIMEOUT, GROUP_SAVE_WAIT = 15, 5, 2
# Later session starts the same day read the group again, so a friend who joins shows the same day: only with the panel
# installed (the only thing that shows the saved copy) and a group saved, at most once every FRIENDS_REREAD seconds counted
# from the last attempt (kept in the group-read file, so a board that is down is not asked at every start). Its request
# gets REREAD_LIMIT seconds in all, name lookup included, and its save GROUP_SAVE_WAIT more, so the board lock is held for
# well under the 30 s --leave and --privacy on wait for it. An unchanged group is saved again only once its copy is
# FRIENDS_RESAVE old, so the copy never ages out (FRIENDS_DAILY, FRIENDS_FRESH) while the reads keep finding it.
FRIENDS_REREAD, REREAD_LIMIT, FRIENDS_RESAVE = 15 * 60, 6, 13 * 3600
# The footer promises an update when Claude Code starts only while the saved copy is about a day old or newer; a copy
# older than this (a slow setup whose read was skipped, a few days without Claude Code) says to run /pet group instead.
FRIENDS_DAILY = 26 * 3600
FRIEND_FIELDS = ("name", "level", "witnessed_xp", "week_xp", "stats", "sus", "you")   # what a saved copy keeps
FRIEND_XP = ("witnessed_xp", "week_xp")


def friends_snapshot(reply):
    """A group reply as it is saved for the panel: the checked members and when they were read, or None for a reply this
    copy does not understand. An empty list means the board has this creature in no group."""
    members = reply.get("members")
    if not isinstance(members, list) or len(members) > GROUP_MAX:
        return None
    checked = [member(m) for m in members]
    if None in checked:
        return None
    # Only the fields the Friends page shows from: anything else a board sends never reaches identity.json.
    keep = FRIEND_FIELDS
    return {"fetched": int(time.time()), "members": [{k: m[k] for k in keep} for m in checked]}


def save_friends(cdir, token, status, reply, wait=10.0, only_if_changed=False):
    """Keeps the group's numbers for the panel, or drops them when the board says there is no group (an empty list) or no
    such creature (a 404 with that reason). Any other answer, a bare 404 from a misrouted address included, leaves the saved
    copy and the group code alone (the code is the only copy of the invite), and FRIENDS_FRESH hides the copy in time.
    With `only_if_changed` (a later session start's read) identity.json is left as it is when nothing in the group changed,
    so the panel does not score again for nothing; the daily read always saves, which keeps the copy fresh. Never fails."""
    no_creature = status == 404 and reply.get("reason") == "no_creature"
    if status != 200 and not no_creature:
        return
    snap = friends_snapshot(reply) if status == 200 else {"members": []}
    if snap is None:
        return

    def differs(now):
        saved = as_dict(now.get("friends"))
        if snap["members"]:
            fetched = saved.get("fetched")
            aged = type(fetched) is not int or not 0 <= time.time() - fetched < FRIENDS_RESAVE
            return aged or snap["members"] != saved.get("members")
        return "friends" in now or "group" in now

    def change(now):
        if snap["members"]:
            now["friends"] = snap
        else:
            # The board says this creature is in no group: its members go, and so does a saved code for that group,
            # so the panel never offers an invite to a group this creature is not in.
            now.pop("friends", None)
            now.pop("group", None)
    try:
        update_identity(cdir, token, change, wait=wait,
                        require=lambda now: not opted_out(cdir) and (not only_if_changed or differs(now)))
    except (Busy, OSError):
        pass


def group_read_path(cdir):
    return os.path.join(os.path.dirname(identity_path(cdir)), "group-read")


def reread_due(cdir, now=None):
    """True when the last group re-read was tried FRIENDS_REREAD seconds ago or more. No stamp, one that cannot be read,
    or a time in the future counts as due. None when something other than a plain file is at its path: the hook stops."""
    path = group_read_path(cdir)
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
    except FileNotFoundError:
        return True
    except OSError:
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, encoding="utf-8") as f:
            last = float(f.read(40).strip())
    except (OSError, ValueError):
        return True
    now = time.time() if now is None else now
    return not 0 <= now - last < FRIENDS_REREAD


def panel_installed(cdir):
    return os.path.isfile(os.path.join(panel_paths(cdir)[0], "cclevel-panel"))


def stamp_group_read(cdir):
    """Notes the time of a group read the hook is about to send, on a machine with the panel. True once noted. Never
    written over something planted at its path (reread_due says None), and never fails."""
    if not panel_installed(cdir) or reread_due(cdir) is None:
        return False
    try:
        write_private(group_read_path(cdir), "%d\n" % int(time.time()))
        return True
    except OSError:
        return False


def reread_wanted(cdir, ident):
    """A later session start the same day may read the group again: Default mode, auto check-in on and already checked in
    today, a group saved, the panel installed, and the last try FRIENDS_REREAD or more ago. Reads files only."""
    if opted_out(cdir) or ident.get("auto") is not True or ident.get("auto_day") != today_utc():
        return False
    code, members = ident.get("group"), as_dict(ident.get("friends")).get("members")
    if not ((isinstance(code, str) and GROUP_RE.fullmatch(code)) or (isinstance(members, list) and members)):
        return False
    if not panel_installed(cdir):
        return False
    fetched = as_dict(ident.get("friends")).get("fetched")
    if type(fetched) is int and 0 <= time.time() - fetched < FRIENDS_REREAD:
        return False   # read a moment ago: by the daily check-in, /pet group or a re-read that found a change
    return reread_due(cdir) is True


def friends_view(cdir, result, now=None):
    """What the Friends page shows, from this machine's own files; sends nothing. In Privacy mode (or while leaving) it
    shows nothing at all, whatever is still on disk."""
    ident = load_identity(cdir)
    if privacy_state(cdir, ident):
        return {"friends": {"state": "privacy"}, "invite": None}
    invite = None
    code = ident.get("group")
    server = moved(ident.get("server") or "")
    if isinstance(code, str) and GROUP_RE.fullmatch(code) and server_ok(server):
        invite = {"name": group_name(code), "link": invite_link(server, code), "max": GROUP_MAX}
    auto = ident.get("auto") is True
    snap = as_dict(ident.get("friends"))
    fetched, members = snap.get("fetched"), snap.get("members")
    now = time.time() if now is None else now
    checked = ([member(m, xp=FRIEND_XP) for m in members]
               if isinstance(members, list) and 0 < len(members) <= GROUP_MAX else [None])
    if type(fetched) is not int or fetched > now + 300 or None in checked:
        return {"friends": {"state": "none", "auto": auto}, "invite": invite}
    if now - fetched > FRIENDS_FRESH:
        return {"friends": {"state": "stale", "auto": auto}, "invite": invite}
    # The board zeroes a week's XP only when it is read: a copy from last week shows nobody's XP this week.
    this_week = iso_week(datetime.fromtimestamp(fetched, timezone.utc).date()) == iso_week(datetime.fromtimestamp(now, timezone.utc).date())
    rows = []
    place = 0
    for i, m in enumerate(checked):
        # Places as /pet group gives them: the board's order, most XP since joining first, and equal XP shares a place.
        if i == 0 or m["witnessed_xp"] != checked[i - 1]["witnessed_xp"]:
            place = i + 1
        stats = dict(zip(STAT_ORDER, m["stats"]))
        level, stage, cls = m["level"], stage_of(m["level"]), class_of(stats)
        if m["you"]:   # this machine's own creature: its live numbers, not the board's copy from the last check-in
            level, stage, cls = result["level"], result["stage"], result["class"]
        rows.append({"place": place, "name": name_of(m["name"]), "level": level, "stage": stage, "class": cls,
                     "xp": m["witnessed_xp"], "week_xp": m["week_xp"] if this_week else 0,
                     "you": m["you"], "sus": m["sus"]})
    best = max(r["week_xp"] for r in rows)
    for r in rows:
        r["crown"] = best > 0 and r["week_xp"] == best
    # "auto" is what the footer goes by: it says the daily check-in updates the list only while that has been happening.
    daily = auto and now - fetched <= FRIENDS_DAILY
    return {"friends": {"state": "ok", "auto": daily, "fetched": fetched, "members": rows}, "invite": invite}


def invite_link(server, code):
    """The link friends open or paste. Shown in full: it can land in a chat transcript, and it only grants a seat."""
    return "%s/join#%s" % (site(server), code)


def duel_link(server, code):
    """The link a challenged friend opens or pastes. Shown in full, like a group's: it only grants the second seat."""
    return "%s/duel#%s" % (site(server), code)


def card_link(server, result):
    """The share card's address. Its numbers sit after "#", which browsers never send: the page draws the picture from
    them. XP, the six stats, the mood, the streak and the badges as bits; the page works out the rest the way this file does.
    The last number is the creature's look, plus 64 if it is shiny."""
    marks = result.get("marks") or marks_of(None)
    numbers = [CARD_VERSION, result["xp"], *(result["stats"][s] for s in STAT_ORDER),
               list(MOODS.values()).index(result["mood"]), result["raw"]["current_streak"],
               sum(1 << i for i, b in enumerate(BADGES) if b in result["badges"]),
               marks["look"] + (LOOKS if marks["shiny"] else 0)]
    return "%s/card#%s" % (site(server), "-".join(str(n) for n in numbers))


BADGE_COLOUR = "d97757"   # the brand colour of the README's own badges


def badge_part(text):
    """One part of a shields.io static badge path: "-" and "_" doubled, spaces as "_", then percent-encoded."""
    return urllib.parse.quote(text.replace("-", "--").replace("_", "__").replace(" ", "_"), safe="_")


def readme_badge(server, result, today):
    """Markdown for a "Lv 42 · Gigachad" badge. The numbers sit in the image address, so nothing looks anything up."""
    when = "%d %s %d" % (today.day, MONTHS[today.month - 1], today.year)
    image = "https://img.shields.io/badge/%s-%s-%s" % (
        badge_part("CC level"), badge_part("Lv %d · %s" % (result["level"], result["stage"])), BADGE_COLOUR)
    return "[![CC level: Lv %d %s (%s)](%s)](%s)" % (result["level"], result["stage"], when, image, site(server))


def readme_badge_text(server, result, today):
    when = "%d %s %d" % (today.day, MONTHS[today.month - 1], today.year)
    return "\n".join([
        "", readme_badge(server, result, today), "",
        "Paste this into a README. For your GitHub profile, that's the repository named after your login.",
        "It shows Lv %d as of %s and doesn't update itself. Run /pet readme badge again to refresh it." % (result["level"], when),
        "Anyone who sees it sees your level next to your name. If your creature is on the world lists, people may be able to "
        "match the two: /pet world off takes it off the lists. The picture comes from shields.io, a free badge service; "
        "cclevel sends nothing."])


def read_invite(text, server):
    """(code, foreign) from an invite link, a bare code or a message holding one; (None, False) if there is none.
    Only the code is ever used: a link never chooses the board, so it cannot send a token anywhere else."""
    text = text.strip().lower()
    if not re.search(r"[\s#]", text):
        return (text, False) if GROUP_RE.fullmatch(text) else (None, False)
    # Every code in the text counts, in links or not: two different ones are refused, never guessed between.
    found = set(INVITE_CODE_RE.findall(text))
    if len(found) != 1:
        return None, False
    home = urllib.parse.urlsplit(server).netloc.lower()
    return found.pop(), any(host != home and moved("https://" + host) != server
                            for host, _ in INVITE_LINK_RE.findall(text))


def confirmed(args, prompt, retry):
    """A yes from --yes or from the user's own terminal. Anything else sends nothing."""
    if args.yes:
        return True
    try:
        answer = input(prompt) if sys.stdin.isatty() else ""
    except EOFError:
        answer = ""
    if answer.strip().lower() in ("y", "yes"):
        return True
    print("Nothing sent. " + retry)
    return False


def join_terms(data, server, privacy=False):
    """What joining the board sends and means, shown before the first check-in. From Privacy mode, it says the yes ends it."""
    print(json.dumps(data, indent=1))
    print("\nJoining sends exactly this to %s with a random token made on this machine." % send_to(server))
    print("It also turns on the world ranking (your generated name, stage, class, level, Aura and witnessed XP on the public")
    print("lists) and a quiet check-in once a day when a Claude Code session starts. Opt out any time: --world off, --auto off,")
    print("or --leave, which turns Privacy mode on: your row is deleted and cclevel sends nothing after. Every creature with")
    print("check-ins on two different days is counted in the board's public totals (how many creatures per level, stat range,")
    print("class, stage and badge), listed or not. After each daily check-in it also reads your private group once (the")
    print("token only), for the Mac menu bar panel's Friends page; with the panel installed and a group, again at later")
    print("Claude Code starts, at most every 15 minutes.")
    if privacy:
        print("This turns Privacy mode off: back in Default mode, this machine checks in by itself. --privacy on goes back.")


def group_terms(create):
    print("%s a private group. Its members, up to %d, see each other's generated name, level, XP since joining,"
          % ("Starting" if create else "Joining", GROUP_MAX))
    print("season XP, six stats and sus mark, as soon as each one checks in. No other creature can see the group.")
    print("Being in a group does not change your world ranking. --group-leave leaves at once.")


START_COUNTING = "Check in today (--sync), or turn on --auto on: duel XP counts only after a check-in from today on."


def duel_terms(create):
    print("%s a duel: you and one friend, %d days, and whoever the board credits with more XP in them wins the ♛."
          % ("Starting" if create else "Accepting", DUEL_DAYS))
    print("It starts at 00:00 UTC the day after it is accepted. Duel XP counts from each side's first check-in on or after")
    print("the day it is accepted. The two of you see each other's generated name, level, duel XP, six stats and sus mark.")
    print("Nobody else can see the duel, and it does not change your world ranking.")
    print("A duel sits beside your group, if you have one. --duel-leave leaves at once.")


def group_refusal(status, reply, table=GROUP_REFUSALS):
    reason = reply.get("reason")
    return (table.get(reason) if isinstance(reason, str) else None) or "it answered HTTP %d" % status


def invite_seat(args, cdir, server, ident, data, result, create, text, flag, terms, both):
    """The code to send for a group or a duel, after a yes: a new one, or the one in an invite. Accepting an invite before
    this machine is on the board joins the board first, with the same yes. Returns (exit code, code, identity); the exit
    code is None when the code should be sent."""
    if not create and not text.strip():
        # No link given: ask for it without echo, so it never appears on screen.
        if not sys.stdin.isatty():
            print("cclevel: pass the invite link, or run %s in your own terminal to type it hidden. Nothing sent." % flag)
            return 1, None, ident
        try:
            text = getpass.getpass("Invite link or code (hidden): ")
        except EOFError:
            text = ""
    code, foreign = (secrets.token_hex(16), False) if create else read_invite(text, server)
    if not code:
        print("cclevel: that is not an invite. A link ends in #, then 32 characters, 0-9 and a-f. Nothing sent.")
        return 1, None, ident
    if foreign:
        print("Note: this invite names another address. cclevel uses only its code, on %s." % board_name(server))
    if not ident:
        # One yes covers both: joining the board and taking the seat.
        join_terms(data, server, privacy=opted_out(cdir))
        print()
        terms(create)
        if not confirmed(args, "Join the board and the %s? [y/N] " % both, "Re-run with --yes to join the board and the %s." % both):
            return 1, None, ident
        rc, ident = check_in(cdir, server, {}, secrets.token_hex(32), data, result)
        if rc:
            return rc, None, ident
    elif not args.yes:
        terms(create)
        if not confirmed(args, "Go ahead? [y/N] ", "Re-run with --yes to go ahead."):
            return 1, None, ident
    return None, code, ident


def group_command(args, cdir, server, ident, data, result):
    """One private group per creature: start, join, show, leave. Joining from an invite can also join the board."""
    if not ident and args.group_join is None:
        print("Not joined. Run with --join first, or join a friend's group with --group-join LINK.")
        return 1
    if args.group_code:
        code = ident.get("group")
        if not (isinstance(code, str) and GROUP_RE.fullmatch(code)):
            print("No group invite is saved on this machine.")
            return 0
        print("%s · invite link, for friends only (anyone with it can join, up to %d):" % (group_name(code), GROUP_MAX))
        print("  " + invite_link(server, code))
        return 0
    if args.group_leave:
        status, reply = call(server, "DELETE", "/api/group", ident["token"])
        if status != 200 or type(reply.get("left")) is not bool:
            print("cclevel: the board did not confirm: %s." % group_refusal(status, reply))
            return 1
        keep_local(cdir, ident["token"], lambda now: (now.pop("group", None), now.pop("friends", None)))
        print("Left the group." if reply["left"] else "You were not in a group.")
        return 0
    if args.group_create or args.group_join is not None:
        create = bool(args.group_create)
        rc, code, ident = invite_seat(args, cdir, server, ident, data, result, create, "" if create else args.group_join,
                                      "--group-join", group_terms, "group")
        if rc is not None:
            return rc
        token = ident["token"]
        status, reply = call(server, "POST", "/api/group", token, {"code": code, "new": True} if create else {"code": code})
        members = reply.get("members")
        if status != 200 or reply.get("joined") is not True or not sane(members) or not 1 <= members <= GROUP_MAX:
            print("cclevel: the board did not add you to the group: %s." % group_refusal(status, reply))
            return 1
        try:
            # A new group: the panel's copy of the old one's members goes, and the next read fills in this one's.
            keep_local(cdir, token, lambda now: (now.update(group=code), now.pop("friends", None)))
        except OSError:
            pass  # the board has the membership; the local copy only lets --group-code print the code again
        if create:
            print("Group started: %s. Invite link, for friends only (anyone with it can join, up to %d):"
                  % (group_name(code), GROUP_MAX))
            print("  " + invite_link(server, code))
            print("Friends open it, or paste it into Claude Code: /pet join <link>. --group-code shows it again.")
        else:
            print("Joined %s: %d members. --group shows them." % (group_name(code), members))
        return 0
    status, reply = call(server, "GET", "/api/group", ident["token"])
    save_friends(cdir, ident["token"], status, reply)   # the panel's Friends page shows this read until the next one
    members = reply.get("members")
    if status != 200 or not isinstance(members, list) or len(members) > GROUP_MAX:
        print("cclevel: the board did not show the group: %s." % group_refusal(status, reply))
        return 1
    checked = [member(m) for m in members]
    if None in checked:
        print("cclevel: the board sent a group this copy of cclevel does not understand.")
        return 1
    if not checked:
        print("You are not in a group. Start one with --group-create, or join one with --group-join LINK.")
        return 0
    code = ident.get("group")
    title = group_name(code) if isinstance(code, str) and GROUP_RE.fullmatch(code) else "Your group"
    print("%s · %d member%s · ranked by XP since joining" % (title, len(checked), "" if len(checked) == 1 else "s"))
    print("   #  %-24s %3s  %12s  %10s  %8s  %4s" % ("Creature", "Lv", "XP joined", "Season XP", "Week XP", "Aura"))
    # The weekly crown: most XP the board credited this ISO week (Monday 00:00 UTC on). Ties share it; nobody wears it at zero.
    best = max(m["week_xp"] for m in checked)
    place = 0
    for i, m in enumerate(checked):
        if i == 0 or m["witnessed_xp"] != checked[i - 1]["witnessed_xp"]:
            place = i + 1
        tags = (" ♛" if best > 0 and m["week_xp"] == best else "") + (" (you)" if m["you"] else "") + (" sus" if m["sus"] else "")
        print("  %2d  %-24s %3d  %12s  %10s  %8s  %4d%s" % (place, name_of(m["name"]), m["level"], "{:,}".format(m["witnessed_xp"]),
                                                          "{:,}".format(m["season_xp"]), "{:,}".format(m["week_xp"]), sum(m["stats"]), tags))
    if best > 0:
        print("♛ most XP this week. Weeks start Monday, 00:00 UTC.")
    return 0


def duel_command(args, cdir, server, ident, data, result):
    """One duel per creature, beside its group: start, accept, show, leave. Accepting from an invite can also join the board."""
    if not ident and args.duel_join is None:
        print("Not joined. Run with --join first, or accept a friend's duel with --duel-join LINK.")
        return 1
    if args.duel_code:
        code = ident.get("duel")
        if not (isinstance(code, str) and GROUP_RE.fullmatch(code)):
            print("No duel invite is saved on this machine.")
            return 0
        print("Duel invite link, for the friend you challenge (the first to accept takes the seat):")
        print("  " + duel_link(server, code))
        return 0
    if args.duel_leave:
        status, reply = call(server, "DELETE", "/api/duel", ident["token"])
        if status != 200 or type(reply.get("left")) is not bool:
            print("cclevel: the board did not confirm: %s." % group_refusal(status, reply, DUEL_REFUSALS))
            return 1
        keep_local(cdir, ident["token"], lambda now: now.pop("duel", None))
        print("Left the duel." if reply["left"] else "You were not in a duel.")
        return 0
    if args.duel_create or args.duel_join is not None:
        create = bool(args.duel_create)
        rc, code, ident = invite_seat(args, cdir, server, ident, data, result, create, "" if create else args.duel_join,
                                      "--duel-join", duel_terms, "duel")
        if rc is not None:
            return rc
        token = ident["token"]
        status, reply = call(server, "POST", "/api/duel", token, {"code": code, "new": True} if create else {"code": code})
        members = reply.get("members")
        if status != 200 or reply.get("joined") is not True or not sane(members) or members != (1 if create else 2):
            print("cclevel: the board did not %s the duel: %s." % ("start" if create else "accept", group_refusal(status, reply, DUEL_REFUSALS)))
            return 1
        try:
            # Only a duel that waits has a link worth showing again; an accepted one replaced any duel of this creature's.
            keep_local(cdir, token, (lambda now: now.update(duel=code)) if create else (lambda now: now.pop("duel", None)))
        except OSError:
            pass  # the board has the seat; the local copy only lets --duel-code print the link again
        if create:
            print("Duel started. Send this link to the friend you challenge (the first to accept takes the seat):")
            print("  " + duel_link(server, code))
            print("They open it, or paste it into Claude Code: /pet duel <link>. --duel-code shows it again.")
        else:
            print("Duel accepted. It starts at 00:00 UTC tomorrow and runs %d days. --duel shows the score." % DUEL_DAYS)
            print(START_COUNTING)
        return 0
    status, reply = call(server, "GET", "/api/duel", ident["token"])
    members, day = reply.get("members"), reply.get("day")
    if status != 200 or not isinstance(members, list) or not (day is None or (type(day) is int and -1 <= day <= MAX_COUNT)):
        print("cclevel: the board did not show the duel: %s." % group_refusal(status, reply, DUEL_REFUSALS))
        return 1
    checked = [member(m, ("duel_xp",)) for m in members]
    if None in checked or len(checked) > 2 or (checked and sum(m["you"] for m in checked) != 1):
        print("cclevel: the board sent a duel this copy of cclevel does not understand.")
        return 1
    if not checked:
        print("You are not in a duel. Start one with --duel-create, or accept one with --duel-join LINK.")
        return 0
    me = next(m for m in checked if m["you"])
    rival = next((m for m in checked if not m["you"]), None)
    over = day is not None and day >= DUEL_DAYS
    winner = max(checked, key=lambda m: m["duel_xp"]) if over and rival and me["duel_xp"] != rival["duel_xp"] else None
    if day is None:
        print("Your duel waits for an opponent. --duel-code shows the invite link to send.")
    elif rival is None:
        print("Your opponent left this duel. %s" % ("--duel-create starts a new one." if over else
                                                    "--duel-leave ends it; then --duel-create starts a new one."))
    elif day < 0:
        print("Duel accepted. It starts at 00:00 UTC tomorrow and runs %d days. %s" % (DUEL_DAYS, START_COUNTING))
    elif not over:
        print("Duel · day %d of %d · ends in %s, at 00:00 UTC" % (day + 1, DUEL_DAYS, count(DUEL_DAYS - day, "day")))
    else:
        print("Duel over.")
    print("     %-24s %3s  %10s  %4s" % ("Creature", "Lv", "Duel XP", "Aura"))
    for m in checked:
        tags = (" (you)" if m["you"] else "") + (" sus" if m["sus"] else "")
        print("  %s  %-24s %3d  %10s  %4d%s" % ("♛" if m is winner else " ", name_of(m["name"]), m["level"],
                                               "{:,}".format(m["duel_xp"]), sum(m["stats"]), tags))
    if rival and day is not None and day >= 0:
        gap = me["duel_xp"] - rival["duel_xp"]
        if over:
            print("You won by {:,} XP.".format(gap) if gap > 0 else "You lost by {:,} XP.".format(-gap) if gap < 0 else "A draw.")
            print("Rematch: --duel-create, then send the new link.")
        else:
            print("You lead by {:,} XP.".format(gap) if gap > 0 else "You trail by {:,} XP.".format(-gap) if gap < 0 else "Neck and neck.")
            print("Duel XP grows when you check in: --sync, or --auto on to check in once a day by itself.")
    return 0


def badge_line(verified, commits):
    """The GitHub badge as this copy prints it: a tick and a number, never a login from the board."""
    if verified is True and sane(commits):
        return "GitHub: \u2713 verified · {:,} public commit{} co-signed by Claude".format(commits, "" if commits == 1 else "s")
    return None


def github_command(args, cdir, server, ident):
    """The opt-in GitHub badge: prove control of an account with a public gist. No GitHub password, key or GitHub token is used: the board
    gets this creature's token, the login and the code's hash."""
    if not ident:
        print("Not joined. Run with --join first.")
        return 1
    token = ident["token"]
    if args.unverify_github:
        status, reply = call(server, "DELETE", "/api/github", token)
        if status != 200 or type(reply.get("removed")) is not bool:
            print("cclevel: the board did not confirm: %s." % group_refusal(status, reply, GITHUB_REFUSALS))
            return 1
        keep_local(cdir, token, lambda now: now.pop("github", None))
        print("GitHub badge removed. The board keeps no GitHub detail for this creature." if reply["removed"]
              else "There was no GitHub badge to remove.")
        return 0
    login = args.verify_github.strip()
    if not GH_LOGIN_RE.fullmatch(login):
        print("cclevel: that is not a GitHub login. Nothing sent.")
        return 1
    pending = as_dict(ident.get("github"))
    code = pending.get("code")
    if pending.get("login", "").lower() == login.lower() and isinstance(code, str) and GROUP_RE.fullmatch(code):
        # Second run: the board looks for the code in the account's public gists.
        status, reply = call(server, "POST", "/api/github", token)
        if status != 200 or type(reply.get("verified")) is not bool:
            print("cclevel: the board could not check: %s." % group_refusal(status, reply, GITHUB_REFUSALS))
            return 1
        if not reply["verified"]:
            print("No public gist of that account has the code in its description yet. Its description must be:")
            print("  cclevel verify " + code)
            print("Publish it at https://gist.github.com (public, any file content), then run this again.")
            return 1
        keep_local(cdir, token, lambda now: now.pop("github", None))
        print(badge_line(True, reply.get("commits") if sane(reply.get("commits")) else 0))
        print("You can delete the gist now. --unverify-github removes the badge and the login from the board at once.")
        return 0
    if not args.yes:
        print("The GitHub badge shows, next to your creature on the public lists, the GitHub login you prove is yours")
        print("and how many of its public commits carry Claude Code's co-author line. It never changes your place or XP.")
        print("To prove it, you publish a public gist with a code this machine makes. No GitHub password or key is used.")
        try:
            answer = input("Start? [y/N] ") if sys.stdin.isatty() else ""
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing sent. Re-run with --yes to start.")
            return 1
    code = secrets.token_hex(16)
    status, reply = call(server, "PUT", "/api/github", token,
                         {"login": login, "code_hash": hashlib.sha256(code.encode()).hexdigest()})
    if status != 200 or reply.get("pending") is not True:
        print("cclevel: the board did not start the check: %s." % group_refusal(status, reply, GITHUB_REFUSALS))
        return 1
    keep_local(cdir, token, lambda now: now.update(github={"login": login, "code": code}))
    print("Step 1 done. Now publish a new public gist at https://gist.github.com, signed in as that account,")
    print("with any file content and exactly this description, nothing else:")
    print("  cclevel verify " + code)
    print("Then run --verify-github with the same login again, today or tomorrow.")
    return 0


def show_rank(server, ident, result):
    """Where this creature stands, worked out here from the public board file. Uploads nothing."""
    status, board = call(server, "GET", "/board.json")
    if status != 200:
        print("cclevel: the board did not answer (HTTP %d)." % status)
        return 1
    lists = {name: ranking(board.get(name)) for name in ("all", "season")}
    if None in lists.values():
        print("cclevel: the board file did not make sense, so no ranking is shown. Nothing was uploaded.")
        return 1
    witnessed, season = ident.get("witnessed_xp"), ident.get("season_xp")
    if not ident or not sane(witnessed):
        print("World list: {:,} creatures ranked.".format(lists["all"][0]))
        print("Ranks count only the XP the board saw you earn after joining. Join with --join and check in.")
    else:
        listed = ident.get("world") is True
        if not listed:
            print("You are not on the world lists (turn them on with --world on). With your numbers you would be:")
        in_season = sane(season) and ident.get("month") == this_month() and board.get("month") == this_month() and season > 0
        mine = [("all", witnessed)] + ([("season", season)] if in_season else [])
        top_lists = {}
        if any((rival(lists[name], xp) or (0, None))[1] is not None for name, xp in mine):
            # Only to name the creature ahead: the public list, downloaded without the token, used only if built with the board file.
            status, top = call(server, "GET", "/top.json")
            if status == 200 and top.get("generated") == board.get("generated"):
                top_lists = top
        print("  All-time: %s · {:,} XP the board witnessed · {:,} ranked".format(witnessed, lists["all"][0])
              % place(lists["all"], witnessed))
        line = rival_line(lists["all"], witnessed, top_lists.get("all"))
        if line:
            print(line)
        if not in_season:
            print("  Season:   no XP this month yet")
        else:
            print("  Season:   %s · {:,} XP this month · {:,} ranked".format(season, lists["season"][0])
                  % place(lists["season"], season))
            line = rival_line(lists["season"], season, top_lists.get("season"))
            if line:
                print(line)
        if listed:
            print("  As of the board's last update; it updates every hour.")
    total, totals = board.get("creatures"), as_dict(board.get("totals"))
    levels = totals.get("levels")
    if sane(total) and total > 0 and counts(levels, LEVEL_MAX + 1):
        def ahead(below):
            return max(0, min(100, round(100 * below / total)))
        print("Level %d: ahead of %d%% of {:,} creatures.".format(total) % (result["level"], ahead(sum(levels[:result["level"]]))))
        for name in STAT_ORDER:
            buckets = as_dict(totals.get("stats")).get(name)
            if counts(buckets, 10):
                print("  %-9s ahead of %d%%" % (name.capitalize(), ahead(sum(buckets[:min(result["stats"][name] // 10, 9)]))))
        # Badge rarity: how many of the counted creatures hold each of this creature's badges, rarest first.
        held = as_dict(totals.get("badges"))
        badges = [b for b in result["badges"] if b in BADGE_NAMES and sane(held.get(b))]
        if badges:
            print("Your badges, rarest first (share of creatures that hold each):")
            for b in sorted(badges, key=lambda b: (held[b], BADGE_NAMES[b])):
                print("  %-20s %d%%" % (BADGE_NAMES[b], ahead(held[b])))
    else:
        print("Not enough creatures on the board yet for totals.")
    print("Nothing was uploaded.")
    return 0


def world_command(args, cdir, server, ident):
    """Turn the world ranking on (asks first) or off (at once, never limited)."""
    if not ident:
        print("Not joined. Run with --join first.")
        return 1
    on = args.world == "on"
    name = creature_name(ident["token"])
    if on and not args.yes:
        print("Turning the world ranking on lists %s on %s:" % (name, board_name(server)))
        print("its generated name, stage, class, level, Aura, the XP the board witnessed and a sus mark if it applies.")
        print("A creature shows once it has check-ins on two different days; the lists update every hour.")
        print("--world off takes it off the lists at once.")
        try:
            answer = input("Turn it on? [y/N] ") if sys.stdin.isatty() else ""
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing sent. Re-run with --yes to turn it on.")
            return 1
    status, reply = call(server, "PUT", "/api/world", ident["token"], {"on": on})
    if status != 200 or type(reply.get("world")) is not bool or type(reply.get("listed")) is not bool or reply["world"] is not on:
        print("cclevel: the board did not confirm: %s." % WORLD_REFUSALS.get(status, "it answered HTTP %d" % status))
        return 1
    try:
        remember(cdir, ident, reply)
    except (OSError, Busy):
        pass  # the board has the choice; the local copy only feeds --rank and catches up at the next check-in
    if not on:
        print("World ranking off. %s is off the public lists now." % name)
    elif reply["listed"]:
        print("World ranking on. %s shows on the public lists from the next board update (every hour)." % name)
    else:
        print("World ranking on. %s shows once it has check-ins on two different days." % name)
    return 0


def auto_command(args, cdir, ident):
    """Turn the daily auto check-in on (asks first) or off. A choice kept on this machine only: nothing is sent."""
    if not ident and args.auto == "off":
        # Before joining, off means the session-start hook never joins this machine. Under the board lock, so a hook
        # already joining finishes first; if it did, its auto check-in is turned off below.
        with board_lock(cdir, 30):
            opt_out(cdir)
            ident = load_identity(cdir)
        if not ident:
            print("Auto check-in off. This machine will not join the board by itself; --join joins by hand.")
            print(PRIVACY_NOW)
            return 0
    if not ident:
        print("Not joined. Run with --join first.")
        return 1
    if args.auto == "off":
        def off(now):
            now.pop("auto", None)
            now.pop("auto_day", None)
        if update_identity(cdir, ident["token"], off) is None:
            print("Not joined. Nothing to turn off.")
            return 1
        if opted_out(cdir):   # the note is here with a token: an opt-out that crossed the first join, or a failed delete
            print("Auto check-in off. Privacy mode is on, but your row is still on the board: /pet privacy on deletes it.")
            return 0
        print("Auto check-in off. No check-in is sent unless you run --sync.")
        return 0
    if not args.yes:
        print("Auto check-in runs --sync for you once a day, in the background, when a Claude Code session starts.")
        print("It sends the same nine numbers and badge codes as --sync, to the same board, and prints nothing.")
        print("Then it reads your private group once (the same token, nothing else) for the Mac panel's Friends page,")
        print("and with the panel installed and a group, again at later session starts, at most every 15 minutes.")
        print("It is kept on this machine only; --auto off stops it.")
        try:
            answer = input("Turn it on? [y/N] ") if sys.stdin.isatty() else ""
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing changed. Re-run with --yes to turn it on.")
            return 1
    if update_identity(cdir, ident["token"], lambda now: now.update(auto=True)) is None:
        print("This machine is not on the board. Nothing changed.")
        return 1
    print("Auto check-in on. %s checks in once a day when a Claude Code session starts." % creature_name(ident["token"]))
    return 0


class Busy(Exception):
    """Another cclevel run holds a lock and did not let go in time, or something in the way stops it being taken."""

    def __init__(self, blocked=None):
        super().__init__(blocked)
        self.blocked = blocked   # a path that is in the way, when that is the reason


LOCAL_LATER = "The board has the change; this machine's copy could not be updated now (another cclevel run is busy)."


def keep_local(cdir, token, change):
    """Saves a change the board has already made. When the settings are busy, says so instead of claiming nothing changed."""
    try:
        update_identity(cdir, token, change)
    except Busy:
        print(LOCAL_LATER)


def busy_text(e):
    if e.blocked:
        return "cclevel: %s is in the way and could not be cleared; remove it and try again. Nothing changed." % e.blocked
    return "cclevel: another cclevel run on this machine is still busy. Nothing changed; try again in a moment."


def clear_odd(path):
    """Removes whatever is in the way at one of cclevel's own file paths (a pipe, a link, a folder, an unreadable file):
    only cclevel's own small file belongs there. Never given any other path. True if it was removed."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    try:
        if stat.S_ISDIR(st.st_mode):
            for root, dirs, files in os.walk(path, topdown=False):
                for name in files + dirs:
                    full = os.path.join(root, name)
                    (os.rmdir if os.path.isdir(full) and not os.path.islink(full) else os.unlink)(full)
            os.rmdir(path)
        else:
            os.unlink(path)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def file_lock(path, wait, folder=False):
    """An operating-system lock (flock) on `path`, a file or, with `folder`, a folder: one holder at a time, released
    when the holder ends, even if it is killed, so none is ever left over. Raises Busy when another holder keeps it
    beyond `wait` seconds, or when something at the path cannot be locked or cleared; nobody goes on without it."""
    try:
        os.makedirs(path if folder else os.path.dirname(path), exist_ok=True)
    except OSError:
        raise Busy(path if folder else os.path.dirname(path))
    flags = os.O_RDONLY if folder else os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    deadline = time.time() + wait
    repaired = folder
    while True:
        fd = None
        try:
            fd = os.open(path, flags, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            os.close(fd)
            if time.time() >= deadline:
                raise Busy()
            time.sleep(0.05)
        except OSError:
            if fd is not None:
                os.close(fd)
            if not repaired and clear_odd(path):
                repaired = True
                continue
            raise Busy(path)
    try:
        yield
    finally:
        os.close(fd)   # closing the file releases the lock


HELD = set()   # board locks this run already holds


@contextlib.contextmanager
def board_lock(cdir, wait):
    """Everything that sends this machine's token to the board (check-ins, the background check-in, leaving, and the
    world, group and GitHub commands) runs one at a time under this lock, together with saving what the board answered.
    So --leave waits for any of them still running, and none of them uses the token after it. (A run killed with its
    request still on the way frees the lock at once; the board may apply that request later. A check-in made that way
    gives a row with one day of check-ins, which the board deletes after 7 days.)"""
    path = os.path.join(os.path.dirname(identity_path(cdir)), "board.lock")
    if path in HELD:
        yield
        return
    with file_lock(path, wait):
        HELD.add(path)
        try:
            yield
        finally:
            HELD.discard(path)


def identity_lock(cdir, wait=10.0):
    """Changes to identity.json one at a time. The lock is on cclevel's own folder, so nothing left at a lock-file
    path can ever block it."""
    return file_lock(os.path.dirname(identity_path(cdir)), wait, folder=True)


def today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def auto_wanted(cdir, token):
    """The identity on disk right now, if it still has this token and auto check-in on; otherwise None."""
    ident = load_identity(cdir)
    return ident if ident.get("token") == token and ident.get("auto") is True else None


def auto_run(cdir, args, default_dir):
    """The plugin's session-start hook. On a machine that has not joined and has not opted out, it joins the board with
    the defaults (world ranking and auto check-in on); with auto check-in on, one quiet check-in a UTC day. Otherwise it
    reads a file or two and stops."""
    # Privacy mode, or a leave that has not gone through yet: the opted-out note stops this hook, token or not.
    if opted_out(cdir):
        return 0
    ident = load_identity(cdir)
    token = ident.get("token")
    reread = False
    if token and (ident.get("auto") is not True or ident.get("auto_day") == today_utc()):
        # Checked in today already: at most a read of the group for the panel (see reread_wanted), or nothing.
        if not reread_wanted(cdir, ident):
            return 0
        reread = True
    # Nothing reaches the screen or Claude's context: the hook runs in the background and its output is discarded here too.
    sys.stdout = sys.stderr = open(os.devnull, "w")
    server = resolve_server(args, ident)
    if not server:
        return 0
    # One board write at a time: when a check-in or a leave from this machine is under way, this session stops at once.
    try:
        with board_lock(cdir, 0):
            if reread:
                return auto_reread(cdir, token, server)
            return auto_once(cdir, token, server, default_dir) if token else auto_join(cdir, server, default_dir)
    except Busy:
        return 0


def auto_join(cdir, server, default_dir):
    """The first session start on a machine that is not on the board: one join, as --join --yes would make it."""
    # Read again now that this hook holds the lock: the owner may have opted out, or another session joined, meanwhile.
    if opted_out(cdir) or load_identity(cdir):
        return 0
    real = os.path.realpath(cdir) == os.path.realpath(default_dir)
    result = score(cdir, machine_jobs=real, save=True)
    token = secrets.token_hex(32)
    try:
        rc, _ = checked_in(cdir, server, {}, token, payload(result), result)
    except SystemExit:
        return 0   # the board could not be reached: the next session start tries again
    if rc == 0:   # the join was today's check-in
        update_identity(cdir, token, lambda now: now.update(auto_day=today_utc()), require=lambda now: now.get("auto") is True)
    return 0


def auto_once(cdir, token, server, default_dir):
    """One background check-in, run while holding the board lock."""
    started = time.monotonic()
    # Read again now that this hook holds the lock: another session may have checked in, or the owner left, meanwhile.
    fresh = auto_wanted(cdir, token)
    if fresh is None or opted_out(cdir) or fresh.get("auto_day") == today_utc():
        return 0
    real = os.path.realpath(cdir) == os.path.realpath(default_dir)
    result = score(cdir, machine_jobs=real, save=True)
    if not auto_wanted(cdir, token) or opted_out(cdir):
        return 0
    try:
        status, reply = call(server, "POST", "/api/checkin", token, payload(result))
    except SystemExit:
        return 0   # not marked: the next session start tries again
    level = reply.get("level")
    if status == 200 and type(level) is int and 1 <= level <= LEVEL_MAX:
        # Kept only while auto check-in is still on: --auto off in the meantime stays off.
        numbers = dict(board_numbers(reply), auto_day=today_utc())
        update_identity(cdir, token, lambda now: now.update(numbers), require=lambda now: now.get("auto") is True)
        # Then, with the day already marked (so a slow or killed read never repeats the check-in), one read of the
        # group for the menu bar panel's Friends page. It sends the same token and nothing else. It is short, and skipped
        # on a slow day, so the hook always lets go of the board lock well within the time --leave waits for it.
        if not auto_wanted(cdir, token) or opted_out(cdir) or time.monotonic() - started > GROUP_READ_AFTER:
            return 0
        stamp_group_read(cdir)   # with the panel, this read counts toward FRIENDS_REREAD too, answered or not
        try:
            status, reply = call(server, "GET", "/api/group", token, timeout=GROUP_READ_TIMEOUT)
        except SystemExit:
            return 0
        save_friends(cdir, token, status, reply, wait=GROUP_SAVE_WAIT)
    return 0


def auto_reread(cdir, token, server):
    """A later session start the same day: one read of the group for the panel's Friends page, run while holding the board
    lock. It sends the same token and nothing else, as the daily read does."""
    # Read everything again now that this hook holds the lock: Privacy mode (written under this lock), a leave, --auto off
    # or another session's read may all have happened since the first look.
    fresh = auto_wanted(cdir, token)
    if fresh is None or not reread_wanted(cdir, fresh):
        return 0
    if not stamp_group_read(cdir):   # the try counts, whatever the board answers; no stamp, no read
        return 0
    # The request runs on its own thread so that nothing (a slow board, a name lookup that hangs) holds the lock for more
    # than REREAD_LIMIT seconds: past it this run stops waiting and lets go. The thread only reads; it never writes a file.
    answer = []

    def read():
        try:
            answer.append(call(server, "GET", "/api/group", token, timeout=GROUP_READ_TIMEOUT))
        except BaseException:
            pass
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(REREAD_LIMIT)
    if reader.is_alive():
        # Still waiting: end the whole run here, inside the lock, so no new request of this run starts after the lock is
        # freed (one already sent may still arrive, and it only reads). Nothing is being written at this point.
        os._exit(0)
    if not answer or opted_out(cdir):
        return 0
    status, reply = answer[0]
    save_friends(cdir, token, status, reply, wait=GROUP_SAVE_WAIT, only_if_changed=True)
    return 0


def privacy_off(args, cdir, ident, data, state):
    """Back to Default mode, after a yes. Sends nothing itself: the session-start hook joins at the next Claude Code start."""
    if not state:
        print("Privacy mode is not on: this machine is in Default mode. Nothing changed.")
        return 0
    if state == "leaving":
        print(json.dumps(data, indent=1))
        print("\nThis machine is still on the board as %s. In Default mode it checks in by itself again, sending exactly"
              " this once a day when auto check-in is on, then reading its private group (again at later starts, at most every"
              " 15 minutes, with the panel installed)." % creature_name(ident["token"]))
    else:
        # The board the session-start hook will use: it runs without --server, so a --server given here is not it.
        hook_board = resolve_server(argparse.Namespace(server=None), ident)
        print(json.dumps(data, indent=1))
        print("\nIn Default mode the session-start hook joins the board at the next Claude Code start and sends exactly this")
        print("to %s with a random token made on this machine. It also turns on the world ranking and a quiet" % send_to(hook_board))
        print("check-in once a day, followed by one read of your private group (again at later starts, at most every 15")
        print("minutes, with the menu bar panel installed). --privacy on goes back at any time.")
    if not confirmed(args, "Turn Privacy mode off? [y/N] ", "Privacy mode stays on. Re-run with --yes to turn it off."):
        return 1
    with board_lock(cdir, 30):
        opt_back_in(cdir)
    if opted_out(cdir):
        print("cclevel: %s could not be removed, so Privacy mode stays on. Remove it yourself to turn it off." % off_path(cdir))
        return 1
    if state == "leaving":
        print("Default mode: this machine checks in by itself again.")
    else:
        print("Default mode: joins the board at the next Claude Code start. Join now: /pet join.")
    return 0


def board_command(args, cdir, result):
    data = payload(result)
    if args.preview:
        print(json.dumps(data, indent=1))
        print("\nThis is everything a check-in sends. Nothing has been sent.")
        return 0
    if args.card:
        print("Your card as a picture: open this link, then save or copy the image.")
        server = resolve_server(args, load_identity(cdir))
        print("  " + card_link(server, result))
        print("The numbers after # stay in your browser: the page sends nothing, and the picture shows no creature name.")
        if public(server):
            print("Opening the link is a visit to cclevel.com, which Cloudflare's sampled visit logs may keep with your IP address"
                  " for at least 31 days.")
        return 0
    try:
        with identity_lock(cdir, 0):
            tidy_left(cdir)
    except (Busy, OSError):
        pass
    ident = load_identity(cdir)
    state = privacy_state(cdir, ident)
    if args.privacy == "off":
        return privacy_off(args, cdir, ident, data, state)
    if args.auto == "on" and state:
        print(PRIVACY_ON)   # the hook stays quiet while the note is here, so turning it on would promise nothing
        if state == "leaving":
            print(STILL_LISTED)
        return 1
    if args.auto:
        return auto_command(args, cdir, ident)
    # Privacy mode sends nothing. Only a confirmed join ends it (the terms say so first). Leaving sends only what removes
    # data from the board; the delete itself is --privacy on (or --leave), below.
    leaving = args.leave or args.privacy == "on"
    if state == "privacy" and not (leaving or args.join or args.group_join is not None or args.duel_join is not None):
        print(PRIVACY_ON)
        return 1
    if state == "leaving" and not (leaving or only_removes(args)):
        print(PRIVACY_ON)
        print(STILL_LISTED)
        return 1
    server = resolve_server(args, ident)
    if not server:
        print("cclevel: no public board is configured yet. Pass --server to use your own.")
        return 1
    if args.rank:
        return show_rank(server, ident, result)
    duel = args.duel or args.duel_create or args.duel_join is not None or args.duel_leave or args.duel_code
    if args.world or args.group or args.group_create or args.group_join is not None or args.group_leave \
            or args.group_code or args.verify_github or args.unverify_github or duel:
        with board_lock(cdir, 30):
            if ident and load_identity(cdir).get("token") != ident["token"]:
                print("Not joined. Run with --join first.")   # left the board while this command waited
                return 1
            if ident and opted_out(cdir) and not only_removes(args):
                print(PRIVACY_ON)   # Privacy mode began while this command waited, and the row is still there
                print(STILL_LISTED)
                return 1
            if args.world:
                return world_command(args, cdir, server, ident)
            if args.verify_github or args.unverify_github:
                return github_command(args, cdir, server, ident)
            if duel:
                return duel_command(args, cdir, server, ident, data, result)
            return group_command(args, cdir, server, ident, data, result)
    if leaving:
        # --privacy on and --leave are the same: Privacy mode starts here.
        # Under the board lock: a check-in from this machine already on its way (the session-start hook's first join too)
        # finishes first, and none starts until the row and the token are gone. If this run is stopped half way, nothing
        # is left half done.
        with board_lock(cdir, 30):
            # The opt-out comes first, so the session-start hook never joins this machine again, whatever happens next.
            opt_out(cdir)
            with contextlib.suppress(OSError):
                os.remove(group_read_path(cdir))   # the hook's last group read time: no use once Privacy mode is on
            ident = load_identity(cdir)
            if not ident:
                print("Opted out. This machine is not on the board and will not join it by itself; --join joins by hand.")
                print(PRIVACY_NOW)
                return 0
            token = ident["token"]
            server = resolve_server(args, ident)
            try:
                status, reply = call(server, "DELETE", "/api/entry", token)
            except SystemExit:   # the board could not be reached at all: say where this leaves the machine, then stop
                print("Privacy mode is on all the same: this machine sends nothing by itself. " + STILL_LISTED)
                raise
            if status != 200 or type(reply.get("deleted")) is not bool:
                print("cclevel: the board did not confirm the deletion (HTTP %d). The token is kept so you can retry." % status)
                print("Privacy mode is on all the same: this machine sends nothing by itself. " + STILL_LISTED)
                return 1
            # The row is gone. Said on disk at once, without waiting for any lock, so nothing uses this token again;
            # the token itself goes as soon as the settings are free (now, or at the next command that changes them).
            try:
                write_private(left_path(cdir), token)
                noted = True
            except OSError:
                noted = False
            tidied = False
            try:
                with identity_lock(cdir, 10):
                    if noted:
                        tidy_left(cdir)
                    elif load_identity(cdir).get("token") == token:
                        os.remove(identity_path(cdir))
                        noted = True
                    tidied = True
            except (Busy, OSError):
                pass
            if not noted:
                first = "Your row on the board is deleted" if reply["deleted"] else "The board had no row for this token"
                print("%s, but this machine's token could not be removed: something in %s is in the way. Remove the file"
                      " identity.json there yourself." % (first, os.path.dirname(identity_path(cdir))))
                return 1
        token_line = ("the local token is removed" if tidied else "this machine no longer uses the token; its file is"
                      " removed by the next cclevel command that talks to the board")
        if reply["deleted"]:
            print("Left the board. Your row is deleted and %s." % token_line)
        else:
            print("The board had no row for this token. %s%s." % (token_line[0].upper(), token_line[1:]))
        print("This machine will not join again by itself; --join joins by hand.")
        print(PRIVACY_NOW)
        return 0
    if ident and args.join:
        print("Already on the board as %s. Use --sync to check in. Nothing sent." % creature_name(ident["token"]))
        return 0
    token = ident.get("token")
    if not token:
        if args.sync:
            print("Not joined. Run with --join first.")
            return 1
        # First join: show the payload and get a yes before anything is sent.
        join_terms(data, server, privacy=opted_out(cdir))
        if not confirmed(args, "Send it? [y/N] ", "Re-run with --yes to join."):
            return 1
        token = secrets.token_hex(32)
    return check_in(cdir, server, ident, token, data, result)[0]


def check_in(cdir, server, ident, token, data, result):
    """Send one check-in, keep the token once the board has taken the first one. Returns (exit code, identity).
    Runs under the board lock, so a --leave from this machine cannot cross it."""
    with board_lock(cdir, 30):
        if ident and load_identity(cdir).get("token") != token:
            print("Not joined. Run with --join first.")
            return 1, {}
        if ident and opted_out(cdir):   # Privacy mode began while this waited; a first join (no ident) is what ends it
            print(PRIVACY_ON)
            print(STILL_LISTED)
            return 1, ident
        return checked_in(cdir, server, ident, token, data, result)


def checked_in(cdir, server, ident, token, data, result):
    status, reply = call(server, "POST", "/api/checkin", token, data)
    if status != 200:
        reason = reply.get("reason")
        said = JOIN_LIMITS.get(reason) if status == 429 and not ident and isinstance(reason, str) else None
        print("cclevel: check-in refused: %s." % (said or REFUSALS.get(status, "the board answered HTTP %d" % status)))
        return 1, ident
    # No text from the board is ever shown. The only thing taken from the reply here is the level,
    # which must be a sane number; the name, the stage and the class are worked out on this machine.
    level = reply.get("level")
    name = creature_name(token)
    if type(level) is not int or not 1 <= level <= LEVEL_MAX:
        print("cclevel: the board sent a reply this copy of cclevel does not understand. Nothing was saved.")
        return 1, ident
    # The token is kept only once the board has taken the first check-in. A first join turns on auto check-in.
    joined = bool(ident)
    ident = ident or {"token": token, "server": server, "name": name, "auto": True}
    try:
        saved = remember(cdir, ident, reply, create=not joined)
    except (OSError, Busy) as e:
        if not joined:
            print("cclevel: joined, but the token could not be saved. The row will expire on its own.")
            return 1, ident
        print("The board took the check-in; this machine's copy of the numbers catches up next time.")
        saved = ident
    if saved is None:
        print("cclevel: this machine's board settings changed while checking in. Run it again.")
        return 1, load_identity(cdir)
    if not joined:
        opt_back_in(cdir)
        # ...and the world ranking. Still under the board lock, so a --leave cannot cross it.
        try:
            status, listing = call(server, "PUT", "/api/world", token, {"on": True})
        except SystemExit:
            status, listing = 0, {}   # joined all the same; the line below says how to turn it on
        if status == 200 and listing.get("world") is True and type(listing.get("listed")) is bool:
            reply = dict(reply, world=True, listed=listing["listed"])
            try:
                remember(cdir, ident, listing)
            except (OSError, Busy):
                pass   # the board has the choice; the local copy catches up at the next check-in
    stage = next(s for floor, s in STAGES if level >= floor)
    print("You are %s · %s %s · Lv %d" % (name, stage, result["class"], level))
    witnessed, season = reply.get("witnessed_xp"), reply.get("season_xp")
    print("Witnessed XP: {:,} · Season XP: {:,}".format(witnessed if sane(witnessed) else 0, season if sane(season) else 0))
    if reply.get("accepted") is False:
        print("Already checked in today; the board keeps the earlier numbers.")
    if reply.get("capped") is True:
        print("The board credits at most %d XP per active day; the rest catches up over the next check-ins." % DAY_CAP)
    if reply.get("world") is not True:
        print("World ranking: off. Run --world on to be ranked (ranks count only XP the board witnessed).")
    elif reply.get("listed") is True:
        print("World ranking: on, listed.")
    else:
        print("World ranking: on. You show once you have check-ins on two different days.")
    if not joined:
        print("Auto check-in: on, once a day when a Claude Code session starts. Opt out any time: --leave (Privacy mode).")
    line = badge_line(reply.get("verified"), reply.get("commits"))
    if line:
        print(line)
    if reply.get("sus") is True:
        print("Sus: 80%% or more of your witnessed days took the full %d XP. The mark changes nothing else." % DAY_CAP)
    return 0, ident


# ------------------------------------------------------------------ fix
# /pet fix: the top Fix next item, done after a yes. The plan (--fix) reads and writes nothing. With --yes the scanner
# backs up every file the plan names into ~/.claude/cclevel/fixes/<time>-<code>/ first. Only one fix is automatic: moving
# unused own skills (a plain, local, exactly reversible move). The rest are made by Claude in the user's session, so
# Claude Code shows the diff, or are advice only. Never run from the hook, the band or the panel. Nothing is sent.
FIX_CLASS = {"unused_skills": "auto", "heavy_context": "assisted", "brains_1": "assisted", "brains_3": "assisted",
             "brains_4": "assisted", "brains_5": "assisted", "brains_6": "assisted", "brains_7": "assisted",
             "brains_8": "assisted", "brains_9": "assisted"}
FIX_DENY_RULE = "Read(./.env)"
FIX_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
CLASS_TEXT = {"auto": "automatic, after your yes. Reversible.",
              "assisted": "Claude makes this change and shows you the diff first. Backup first, reversible."}


def tilde(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


def tree_hash(path):
    """SHA-256 of a file, or of a folder's names and bytes in order. A link is hashed as its target text, never followed."""
    h = hashlib.sha256()
    if os.path.islink(path):
        h.update(b"link:" + os.readlink(path).encode())
    elif os.path.isfile(path):
        with open(path, "rb") as f:
            h.update(f.read())
    elif os.path.isdir(path):
        for top, dirs, files in os.walk(path):
            dirs.sort()
            for name in sorted(dirs + files):
                full = os.path.join(top, name)
                h.update(os.path.relpath(full, path).encode() + b"\0")
                if os.path.islink(full):
                    h.update(b"link:" + os.readlink(full).encode())
                elif os.path.isfile(full):
                    with open(full, "rb") as f:
                        h.update(f.read())
    else:
        return None
    return h.hexdigest()


def fingerprint(path):
    """A quick identity for a plan: each name under `path` with its size and change time. Reads no file contents."""
    out = []
    for top, dirs, files in os.walk(path) if os.path.isdir(path) and not os.path.islink(path) else [("", [], [path])]:
        dirs.sort()
        for name in sorted(files + dirs):
            full = os.path.join(top, name)
            try:
                st = os.lstat(full)
                out.append((os.path.relpath(full, path) if top else "", st.st_size, st.st_mtime_ns, st.st_ctime_ns))
            except OSError:
                out.append((full, None))
    return out


def in_git(path):
    """True if `path` sits in a git work tree (a .git anywhere above it). Read from the folders only; git is not run."""
    path = os.path.realpath(path)
    while True:
        if os.path.lexists(os.path.join(path, ".git")):
            return True
        up = os.path.dirname(path)
        if up == path:
            return False
        path = up


def fixes_dir(cdir):
    return os.path.join(cdir, "cclevel", "fixes")


def settings_refusal(path):
    if os.path.islink(path):
        return "Your settings.json is a link, so cclevel will not change it. Add the change yourself:"
    if os.path.exists(path) and not isinstance(load_json(path), dict):
        return "Your settings.json does not parse, so cclevel will not touch it. Fix it first (claude /doctor), then try again."
    if not os.access(path if os.path.exists(path) else os.path.dirname(path), os.W_OK):
        return "Your settings.json is write-protected, so cclevel will not change it. Add the change yourself:"
    return None


def linked_into(moves):
    """The first folder in moves that a link in a kept sibling (or its direct children) points into, else None."""
    real = [(m, os.path.realpath(m) + os.sep) for m in moves]
    for base in sorted({os.path.dirname(m) for m in moves}):
        try:
            kept = [os.path.join(base, e) for e in os.listdir(base) if os.path.join(base, e) not in moves]
        except OSError:
            continue
        for k in kept:
            links = [k]
            if os.path.isdir(k) and not os.path.islink(k):
                try:
                    links += [os.path.join(k, e) for e in os.listdir(k)]
                except OSError:
                    pass
            for link in links:
                if os.path.islink(link):
                    target = os.path.realpath(link) + os.sep
                    for m, r in real:
                        if target.startswith(r):
                            return m
    return None


def fix_plan(cdir, result, extra, code, name=None):
    """What a fix would do: {code, need, cls, targets [(path, action)], change [lines], when, refusal, id}. Reads only."""
    need = next((n for n in result["needs"] if n["code"] == code), None)
    plan = {"code": code, "need": need, "cls": FIX_CLASS.get(code, "advice"), "targets": [], "change": [],
            "when": "", "refusal": None}
    if need is None:
        return plan
    gain = "%s +%d" % (need["stat"].capitalize(), need["gain"])
    plan["when"] = "%s now" % gain
    how = HOWTO.get(code, ("", ""))[0]
    agents = os.path.join(cdir, "agents")
    name = name or ""
    if name and not FIX_NAME.match(name):
        plan["refusal"] = "A name is lower-case letters, digits and dashes, up to 40 characters."
    if code == "unused_skills":
        moves = []
        for skill in extra.get("unused_names", []):
            for base in ("skills", "commands"):
                folder = os.path.join(cdir, base, skill)
                if os.path.isfile(os.path.join(folder, "SKILL.md")):
                    moves.append(folder)
        bases = {os.path.dirname(m) for m in moves}
        git = [b for b in sorted(bases) if in_git(b)]
        try:
            dev = os.stat(cdir).st_dev
            far = [m for m in moves if os.lstat(m).st_dev != dev]
        except OSError:
            far = moves
        if git:
            plan["refusal"] = ("Your %s folder is a git repository, so cclevel will not move folders in it. Move them yourself:"
                               % os.path.basename(git[0]))
        elif linked_into(moves):
            plan["refusal"] = ("A skill you keep links into %s, so moving it would break that skill. Move them yourself:"
                               % os.path.basename(linked_into(moves)))
        elif any(os.path.islink(m) for m in moves):
            plan["refusal"] = "One of these skill folders is a link, so cclevel will not move it. Move them yourself:"
        elif far:
            plan["refusal"] = "One of these folders is on another disk, so cclevel will not move it. Move them yourself:"
        plan["targets"] = [(m, "move") for m in moves]
        if "health_without_unused" in extra:
            plan["when"] = "Health +%d now" % (extra["health_without_unused"] - result["health"])
        where = sorted({tilde(b) for b in bases}) or [tilde(os.path.join(cdir, "skills"))]
        plan["change"] = ["Moves these folders out of %s into %s:" % (" and ".join(where),
                                                                     tilde(os.path.join(fixes_dir(cdir), "<time>-unused_skills")) + "/"),
                          "  " + ", ".join(os.path.basename(m) for m in moves)]
    elif code in ("brains_7", "brains_8"):
        path = os.path.join(cdir, "settings.json")
        plan["refusal"] = plan["refusal"] or settings_refusal(path)
        plan["targets"] = [(path, "edit" if os.path.exists(path) else "create")]
        if code == "brains_7":
            plan["change"] = ["Adds to permissions.deny in %s: \"%s\"" % (tilde(path), FIX_DENY_RULE)]
        else:
            plan["change"] = ["Adds a Stop hook to %s, with a command you pick (for example a sound when Claude finishes)."
                              % tilde(path)]
            plan["when"] = "%s after the hook runs once" % gain
    elif code == "brains_9":
        files = sorted(glob.glob(os.path.join(agents, "*.md")))
        bare = [p for p in files if not field(frontmatter(read_head(p)), "model") and not os.path.islink(p)]
        if not bare:
            plan["cls"] = "advice"
            how = "ask Claude to create a subagent first, then give it model: haiku in its frontmatter"
        else:
            plan["targets"] = [(bare[0], "edit")]
            plan["change"] = ["Adds model: haiku to the frontmatter of %s." % tilde(bare[0])]
            plan["when"] = "%s after it does real work" % gain
    elif code in ("brains_5", "brains_6"):
        path = os.path.join(agents, "%s.md" % (name or ("code-reviewer" if code == "brains_6" else "researcher")))
        if os.path.lexists(path):
            plan["cls"] = "advice"
            how = "you have %s already: ask Claude to use it" % tilde(path)
        else:
            plan["targets"] = [(path, "create")]
            plan["change"] = ["Creates a new subagent %s (%s)." % (
                tilde(path), "a code reviewer to run after each change" if code == "brains_6" else "for research and reading")]
            plan["when"] = "%s after you use it" % gain
    elif code == "brains_3":
        path = os.path.join(cdir, "skills", name or "my-task", "SKILL.md")
        if os.path.lexists(os.path.dirname(path)):
            plan["refusal"] = plan["refusal"] or "A skill with that name exists. Pick another name: /pet fix brains_3 NAME"
        plan["targets"] = [(path, "create")]
        plan["change"] = ["Creates a new skill %s from a task you name (rename it: /pet fix brains_3 NAME)." % tilde(path)]
        plan["when"] = "%s after you use 3 own skills" % gain
    elif code == "brains_4":
        used = [s for s in sorted(extra.get("own_used", []))
                if os.path.isfile(os.path.join(cdir, "skills", s, "SKILL.md"))]
        if not used:
            plan["cls"] = "advice"
            how = "use one of your own skills first, then put a script next to its SKILL.md"
        else:
            path = os.path.join(cdir, "skills", used[0], "scripts", "%s.py" % (name or "helper"))
            plan["refusal"] = plan["refusal"] or ("That script exists. Pick another name." if os.path.lexists(path) else None)
            plan["targets"] = [(path, "create"), (os.path.join(cdir, "skills", used[0], "SKILL.md"), "edit")]
            plan["change"] = ["Creates %s and adds one line to that skill's SKILL.md saying when to run it." % tilde(path)]
            plan["when"] = "%s after you use the skill" % gain
    elif code == "heavy_context":
        path = os.path.join(cdir, "CLAUDE.md")
        if not os.path.isfile(path) or os.path.islink(path):
            plan["cls"] = "advice"
        else:
            skill = os.path.join(cdir, "skills", name or "claude-md-howtos", "SKILL.md")
            plan["targets"] = [(path, "edit"), (skill, "create")]
            plan["change"] = ["Moves long how-tos out of %s into a new skill %s." % (tilde(path), tilde(skill)),
                              "Claude shows the trim as a diff before writing."]
            plan["when"] = "Health up to +%d now, by how much is moved" % need["gain"]
    elif code == "brains_1":
        path = os.path.join(os.getcwd(), "CLAUDE.md")
        if os.path.lexists(path):
            plan["cls"] = "advice"
            how = "this folder has a CLAUDE.md already: open Claude Code here once so it counts"
        else:
            plan["targets"] = [(path, "create")]
            plan["change"] = ["Creates a starter CLAUDE.md for this folder: %s" % tilde(path)]
            plan["when"] = "%s after your next session in this folder" % gain
    plan["how"] = how
    if plan["cls"] == "advice":
        plan["targets"], plan["change"] = [], []
    for path, action in plan["targets"]:
        if action == "edit" and os.path.islink(path):
            plan["refusal"] = plan["refusal"] or "%s is a link, so cclevel will not touch it." % tilde(path)
    ident = json.dumps([code, name, [(p, a, fingerprint(p)) for p, a in plan["targets"]]])
    plan["id"] = hashlib.sha256(ident.encode()).hexdigest()[:8]
    return plan


def fix_plan_text(plan, rank, name=None):
    need = plan["need"]
    out = ["  Fix next #%d: %s" % (rank, need_text(need))]
    if plan["cls"] == "advice":
        kind = "a habit, not a setting" if plan["code"] in ("interrupts", "brains_10", "brains_2") else "for you, not a file"
        out.append("  This one is %s: %s." % (kind, plan["how"]))
        return out
    if plan["refusal"]:
        out.append("  " + plan["refusal"])
        out += ["  " + line for line in plan["change"]] if "yourself" in plan["refusal"] else []
        return out
    out.append("  Class: " + CLASS_TEXT[plan["cls"]])
    out += ["  " + line for line in plan["change"]]
    out.append("  Gain: %s." % plan["when"])
    out.append("  Undo: /pet fix undo puts %s back." % ("them" if len(plan["targets"]) > 1 else "it"))
    out.append("  To apply: --fix %s%s --plan %s --yes" % (plan["code"], " --fix-name " + name if name else "", plan["id"]))
    return out


def fix_command(args, cdir, result, extra, real=False):
    """--fix [CODE] prints the plan; with --plan ID --yes it backs up and, for the automatic fix, applies it."""
    needs = result["needs"]
    code = args.fix
    if code and code not in (n["code"] for n in needs):
        print("  %s is not on your Needs list right now, so there is nothing to fix." % code)
        return 0
    if not needs:
        print("  Needs: nothing right now. Nothing to fix.")
        return 0
    if not code:
        out = []
        for i, n in enumerate(needs):
            plan = fix_plan(cdir, result, extra, n["code"], args.fix_name)
            if plan["cls"] != "advice":
                if i:
                    out.append("  The next one I can fix:")
                print("\n".join(out + fix_plan_text(plan, i + 1, args.fix_name)))
                return 0
            out += fix_plan_text(plan, i + 1)
        print("\n".join(out + ["  None of your Needs is a setting cclevel can change. The How lines above say what to do."]))
        return 0
    rank = [n["code"] for n in needs].index(code) + 1
    plan = fix_plan(cdir, result, extra, code, args.fix_name)
    if not args.yes or plan["cls"] == "advice" or plan["refusal"]:
        print("\n".join(fix_plan_text(plan, rank, args.fix_name)))
        if args.yes and plan["cls"] == "advice":
            print("  Nothing was changed.")
        return 1 if args.yes and plan["refusal"] else 0
    if args.plan != plan["id"]:
        print("  The plan changed since you saw it (or no --plan was given). Nothing was changed. Run /pet fix again.")
        return 1
    return fix_apply(cdir, plan, result, real)


def write_refused(err):
    """True when the system said no (permissions, or Claude Code's sandbox), not that something is in the way."""
    return isinstance(err, PermissionError) or err.errno == errno.EROFS


def fix_refused(where):
    print("  Claude Code's sandbox or the folder's permissions stopped cclevel from writing in %s. Nothing was changed."
          " Once you agree, you can run it again outside the sandbox." % tilde(where))
    return 1


def private_dir(path):
    """Makes a 700 folder for cclevel, refusing a link or a file in the way. True if it is a plain folder now."""
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as err:
        if write_refused(err):
            raise
        return False
    st = os.lstat(path)
    return stat.S_ISDIR(st.st_mode)


def fix_apply(cdir, plan, result, real=False):
    base = os.path.join(cdir, "cclevel")
    try:
        plain = private_dir(base) and private_dir(fixes_dir(cdir))
    except OSError:
        return fix_refused(fixes_dir(cdir))
    if not plain:
        print("  %s is not a plain folder, so cclevel will not save a backup there. Nothing was changed." % tilde(fixes_dir(cdir)))
        return 1
    fid = "%s-%s" % (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ"), plan["code"])
    folder = os.path.join(fixes_dir(cdir), fid)
    try:
        os.mkdir(folder, 0o700)
        os.mkdir(os.path.join(folder, "files"), 0o700)
    except OSError as err:
        if write_refused(err):
            return fix_refused(fixes_dir(cdir))
        print("  Something is in the way at %s, so cclevel will not save a backup there. Nothing was changed." % tilde(folder))
        return 1
    entries = []
    for i, (path, action) in enumerate(plan["targets"]):
        e = {"path": path, "action": action, "backup": os.path.join("files", str(i)), "sha256_before": tree_hash(path)}
        if action == "edit":
            e["mode"] = stat.S_IMODE(os.lstat(path).st_mode)
            shutil.copy2(path, os.path.join(folder, e["backup"]), follow_symlinks=False)
            os.chmod(os.path.join(folder, e["backup"]), 0o600)
        entries.append(e)
    manifest = {"version": 1, "id": fid, "code": plan["code"], "class": plan["cls"], "made": fid[:18], "entries": entries}
    mpath = os.path.join(folder, "manifest.json")
    write_private(mpath, json.dumps(manifest, indent=1))
    if plan["cls"] != "auto":
        print("  Backup saved in %s/. Claude now makes this change:" % tilde(folder))
        print("\n".join("  " + line for line in plan["change"]))
        print("  Then run /pet to confirm. Undo: /pet fix undo.")
        return 0
    done = []
    try:
        for e in entries:
            os.rename(e["path"], os.path.join(folder, e["backup"]))
            done.append(e)
    except OSError as err:
        for e in reversed(done):
            os.rename(os.path.join(folder, e["backup"]), e["path"])
        manifest["undone"] = True
        write_private(mpath, json.dumps(manifest, indent=1))
        if write_refused(err):
            return fix_refused(os.path.dirname(e["path"]))
        print("  Could not move %s (%s). Everything is back as it was." % (tilde(e["path"]), err.strerror or type(err).__name__))
        return 1
    manifest["applied"] = True
    write_private(mpath, json.dumps(manifest, indent=1))
    after = score(cdir, machine_jobs=real, save=False)
    print("  Moved %s into %s/." % (count(len(entries), "folder"), tilde(folder)))
    print("  Health %d → %d. Undo: /pet fix undo puts them back." % (result["health"], after["health"]))
    return 0


def fix_undo(cdir):
    """Puts the latest fix back from its manifest. The current versions go into the fix folder; nothing is deleted."""
    root = fixes_dir(cdir)
    if os.path.islink(root) or os.path.islink(os.path.join(cdir, "cclevel")):
        print("  %s is a link, so cclevel will not undo from it." % tilde(root))
        return 1
    manifests = []
    for name in sorted(os.listdir(root), reverse=True) if os.path.isdir(root) else []:
        folder = os.path.join(root, name)
        m = load_dict(os.path.join(folder, "manifest.json"))
        if not os.path.islink(folder) and isinstance(m.get("entries"), list) and not m.get("undone"):
            manifests.append((folder, m))
    if not manifests:
        print("  Nothing to undo.")
        return 0
    folder, m = manifests[0]
    for e in m["entries"]:
        path, backup = e.get("path"), os.path.join(folder, str(e.get("backup")))
        if not isinstance(path, str) or not os.path.isabs(path):
            print("  The fix list in %s is not one cclevel wrote. Nothing was changed." % tilde(folder))
            return 1
        if os.path.islink(path) or os.path.islink(os.path.dirname(path)):
            print("  %s is now a link, so cclevel will not put the backup there. Nothing was changed." % tilde(path))
            return 1
        moved = e.get("action") == "move" and m.get("applied")
        if e.get("action") == "edit" or moved:
            if os.path.islink(backup) or tree_hash(backup) != e.get("sha256_before"):
                print("  The backup of %s is missing or changed, so cclevel will not restore it. Nothing was changed."
                      % tilde(path))
                return 1
    replaced = os.path.join(folder, "replaced")
    try:
        os.mkdir(replaced, 0o700)
    except FileExistsError:
        pass
    except OSError as err:
        if write_refused(err):
            return fix_refused(root)
        print("  Something is in the way at %s, so cclevel will not undo from there. Nothing was changed." % tilde(replaced))
        return 1
    back = 0
    for i, e in enumerate(m["entries"]):
        path, backup = e["path"], os.path.join(folder, e["backup"])
        if e["action"] == "move" and not m.get("applied"):
            continue
        if os.path.lexists(path):
            os.rename(path, os.path.join(replaced, str(i)))
        if e["action"] in ("move", "edit"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            os.rename(backup, path)
            if "mode" in e:
                os.chmod(path, e["mode"])
            back += 1
    m["undone"] = True
    write_private(os.path.join(folder, "manifest.json"), json.dumps(m, indent=1))
    what = "folder" if m.get("code") == "unused_skills" else "file"
    print("  Put back %s from %s. The versions they replaced are in that folder." % (count(back, what), m.get("id")))
    return 0


def main():
    default_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    # Whole flag names only: an abbreviation such as --ye would otherwise count as --yes.
    ap = argparse.ArgumentParser(description="Score a Claude Code setup and show it as a creature.", allow_abbrev=False)
    ap.add_argument("--claude-dir", default=default_dir, help="Claude Code folder to scan (default: %(default)s)")
    ap.add_argument("--json", action="store_true", help="print numbers only, as JSON")
    ap.add_argument("--no-save", action="store_true", help="do not write the ledger")
    ap.add_argument("--server", help="leaderboard address (default: the public board, or $CCLEVEL_SERVER)")
    ap.add_argument("--yes", action="store_true",
                    help="with --join, --world on, --auto on, --panel on, --privacy off, a group or duel start or join, or --verify-github: "
                         "do not ask again")
    ap.add_argument("--names", action="store_true", help="with --timesheet: show project names (for your own terminal)")
    ap.add_argument("--idle", metavar="MIN", type=idle_minutes, default=TS_IDLE,
                    help="with --timesheet: minutes without activity that end a block, 1 to 240 (default: %(default)s)")
    ap.add_argument("--tz", metavar="AREA/CITY", help="with --timesheet: the time zone (default: this machine's)")
    board = ap.add_mutually_exclusive_group()
    board.add_argument("--preview", action="store_true", help="print exactly what a check-in would send; sends and saves nothing")
    board.add_argument("--join", action="store_true", help="join the leaderboard (asks first)")
    board.add_argument("--sync", action="store_true", help="check in: update your row on the leaderboard")
    board.add_argument("--world", choices=("on", "off"), help="be ranked on the public world lists (on asks first) or not")
    board.add_argument("--group", action="store_true", help="show your private group")
    board.add_argument("--group-create", action="store_true", help="start a private group (asks first) and print its invite link")
    board.add_argument("--group-join", metavar="LINK", nargs="?", const="",
                       help="join a private group with its invite link or code (asks first; joins the board too if needed); "
                            "without LINK, type it hidden")
    board.add_argument("--group-leave", action="store_true", help="leave your private group")
    board.add_argument("--group-code", action="store_true", help="show your group's invite link again; sends nothing")
    board.add_argument("--duel", action="store_true", help="show your duel")
    board.add_argument("--duel-create", action="store_true", help="challenge a friend to a %d-day duel (asks first) and print its invite link"
                       % DUEL_DAYS)
    board.add_argument("--duel-join", metavar="LINK", nargs="?", const="",
                       help="accept a friend's duel with its invite link or code (asks first; joins the board too if needed); "
                            "without LINK, type it hidden")
    board.add_argument("--duel-leave", action="store_true", help="leave your duel")
    board.add_argument("--duel-code", action="store_true", help="show your duel's invite link again; sends nothing")
    board.add_argument("--card", action="store_true", help="print a link that draws your card as a picture to save and post; sends nothing")
    board.add_argument("--wrapped", metavar="YEAR", nargs="?", type=int, const=THIS_YEAR,
                       help="your year in review from this machine's ledger (default: this year); sends nothing")
    board.add_argument("--story", action="store_true",
                       help="our story: a timeline of you and your creature from this machine's ledger; sends nothing")
    board.add_argument("--readme-badge", action="store_true",
                       help="Markdown for a \"Lv 42 · Gigachad\" badge for a README or GitHub profile; the picture comes from "
                            "shields.io; sends nothing")
    board.add_argument("--evolve", action="store_true",
                       help="a ready X post with your stage, class and level and a link to your class's page; sends nothing")
    board.add_argument("--learn", action="store_true",
                       help="the training path: five lessons per stat, ticked by what your logs show; sends nothing")
    board.add_argument("--leaks", action="store_true",
                       help="leak finder: where your tokens went over the last weeks, priced as an API yardstick; sends and "
                            "saves nothing")
    board.add_argument("--timesheet", metavar="WEEK", nargs="?", const="this",
                       help="hours per project from your session logs, in local time: this (default), last or 2026-W45; "
                            "projects are numbered, names go only to timesheet.csv on this machine; sends nothing")
    board.add_argument("--fix", metavar="CODE", nargs="?", const="",
                       help="plan the top Fix next item (or CODE); writes nothing. With --plan ID --yes: backs up, then applies")
    board.add_argument("--fix-undo", action="store_true", help="put back the latest fix from its backup")
    ap.add_argument("--plan", metavar="ID", help=argparse.SUPPRESS)
    ap.add_argument("--fix-name", metavar="NAME", help="a name for a new skill, subagent or script a fix creates")
    board.add_argument("--tips", choices=("on", "off"),
                       help="a how-to under each Need and one Claude Code tip a day on the card; kept on this machine, sends nothing")
    board.add_argument("--panel", choices=("on", "off"),
                       help="macOS: your creature in the menu bar, with a small panel (on asks first; builds it on this Mac and "
                            "starts it at login); sends nothing")
    board.add_argument("--verify-github", metavar="LOGIN", help="opt-in GitHub badge: start (asks first), then run again to finish")
    board.add_argument("--unverify-github", action="store_true", help="remove the GitHub badge and every GitHub detail at once")
    board.add_argument("--privacy", choices=("on", "off"),
                       help="Privacy mode: on deletes your row and the local token, and cclevel sends nothing after;"
                            " off (asks first) goes back to Default mode, where the board is on")
    board.add_argument("--leave", action="store_true", help="the same as --privacy on")
    board.add_argument("--rank", action="store_true", help="compare with the public board; uploads nothing")
    board.add_argument("--auto", choices=("on", "off"),
                       help="check in once a day by itself when a Claude Code session starts, then read your group (again at"
                            " later starts, at most every 15 minutes, with the panel installed); on asks first; sends nothing now")
    board.add_argument("--auto-run", action="store_true", help=argparse.SUPPRESS)   # the plugin's session-start hook
    args = ap.parse_args()
    cdir = os.path.abspath(os.path.expanduser(args.claude_dir))
    if args.auto_run:
        # Silent in every case: a hook's failure must never reach the user's session.
        try:
            auto_run(cdir, args, default_dir) if os.path.isdir(cdir) else None
        except (Exception, SystemExit):
            pass
        sys.exit(0)
    if not os.path.isdir(cdir):
        sys.exit("cclevel: %s is not a folder" % cdir)
    if args.tips:
        try:
            sys.exit(tips_command(args, cdir))
        except Busy as e:
            print(busy_text(e))
        except OSError as e:
            print("cclevel: could not save the tips setting (%s)." % (e.strerror or type(e).__name__))
        sys.exit(1)
    if args.panel:
        try:
            sys.exit(panel_command(args, cdir))
        except (OSError, subprocess.SubprocessError) as e:
            print("cclevel: could not set up the panel (%s)." % (getattr(e, "strerror", None) or type(e).__name__))
        sys.exit(1)
    if args.timesheet is not None:
        text = timesheet(cdir, args.timesheet, args.idle, args.tz, args.names)
        print(text)
        sys.exit(1 if text.startswith("cclevel:") else 0)
    if args.fix_undo:
        sys.exit(fix_undo(cdir))
    # Machine-level sources (scheduled jobs, ~/.claude.json) belong to the real folder only.
    real = os.path.realpath(cdir) == os.path.realpath(default_dir)
    extra = {}   # the leak finder's names and numbers: never in the card's --json or a check-in
    quiet = args.no_save or args.preview or args.readme_badge or args.evolve or args.leaks or args.fix is not None
    result = score(cdir, machine_jobs=real, save=not quiet, extra=extra)
    if args.fix is not None:
        sys.exit(fix_command(args, cdir, result, extra, real))
    if args.leaks:
        report = leaks(extra, result, datetime.now(timezone.utc).date())
        print(json.dumps(report, indent=1) if args.json else leaks_text(report))
        return
    # A folder with no Claude Code activity has no creature yet, so it gets no seed either.
    result["marks"] = creature_marks(cdir, save=result["raw"]["active_days"] > 0 and not quiet)
    if args.wrapped is not None:
        today = datetime.now(timezone.utc).date()
        year = today.year if args.wrapped is THIS_YEAR else args.wrapped
        if not FIRST_YEAR <= year <= today.year:
            sys.exit("cclevel: --wrapped takes a year from %d to %d" % (FIRST_YEAR, today.year))
        print(wrapped(cdir, year, today, resolve_server(args, load_identity(cdir))))
        return
    if args.story:
        today = datetime.now(timezone.utc).date()
        s = story(cdir, result, today)
        print(json.dumps(s, indent=1) if args.json else story_text(s, today))
        return
    if args.readme_badge:
        print(readme_badge_text(resolve_server(args, load_identity(cdir)), result, datetime.now(timezone.utc).date()))
        return
    if args.evolve:
        print(evolve_text(resolve_server(args, load_identity(cdir)), result, datetime.now(timezone.utc).date()))
        return
    if args.learn:
        sys.exit(learn_command(cdir, result, save=not args.no_save))
    if (args.preview or args.join or args.sync or args.world or args.leave or args.rank or args.group or args.group_create
            or args.group_join is not None or args.group_leave or args.group_code or args.verify_github or args.unverify_github
            or args.auto or args.duel or args.duel_create or args.duel_join is not None or args.duel_leave or args.duel_code
            or args.card or args.privacy):
        try:
            sys.exit(board_command(args, cdir, result))
        except Busy as e:
            print(busy_text(e))
            sys.exit(1)
        except OSError as e:
            print("cclevel: could not save this machine's board settings (%s)." % (e.strerror or type(e).__name__))
            sys.exit(1)
    if args.json:
        # The numbers behind the card, and what the menu bar panel shows: the creature's art, the top Needs with how to fix
        # them, the training path and the tip of the day. The ticked lesson ids themselves are --learn's to show.
        marks = result["marks"]
        print(json.dumps(dict({k: v for k, v in result.items() if k not in ("lessons", "hatch_due")},
                              art=marked_art(result["stage"], marks["look"], marks["shiny"]),
                              **panel_extras(cdir, result), **friends_view(cdir, result)), indent=1))
    else:
        how, tip = training_extras(cdir, result, save=not args.no_save)
        # Whether this machine is on the board is read from its own files; nothing is sent. Only the folder Claude Code
        # itself uses gets the session-start hook, so only that one joins by itself.
        token = load_identity(cdir).get("token")
        board = privacy_state(cdir) or ("on" if token else "soon" if real else "off")
        leak = leak_card_line(leaks(extra, result, datetime.now(timezone.utc).date())) if how else None
        print(render(result, board=board, how=how, tip=tip, creature=token and creature_name(token), leak=leak))
        if result["hatch_due"] and not args.no_save:
            record_hatch(cdir)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
