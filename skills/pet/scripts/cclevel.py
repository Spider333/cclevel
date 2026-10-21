#!/usr/bin/env python3
"""cclevel: score a Claude Code setup and show it as a creature that grows.

Reads the local Claude Code folder. Writes nothing except its own files in
<claude dir>/cclevel/. A score covers one machine and is self-reported.

The card is fully offline, and so are --card, which only prints a link, and
the opt-in training (--learn, --tips), which is text shipped here. The
network is used only by --join, --sync, --world, the --group and --duel
commands, the GitHub badge commands, --leave and --rank, and by the
plugin's session-start hook (--auto-run) once a day after the user turned
it on with --auto on; and only for what payload() returns, the world
choice, a group or duel invite code and a GitHub login with the hash of a
code.
"""
import argparse
import contextlib
import fcntl
import getpass
import glob
import hashlib
import http.client
import json
import math
import os
import plistlib
import re
import secrets
import subprocess
import stat
import sys
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
    return {"tok": Counter(), "models": Counter(), "skills": set(), "servers": set(), "agents": set(),
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


def scan_logs(cdir, skill_names):
    """Per-day activity from session logs. Returns (days, longest unattended run)."""
    days = defaultdict(new_day)
    best = {}            # (message id, request id) -> (output tokens, day, usage)
    seen_tools = set()
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
                    session = str(o.get("sessionId"))
                    if not sub:
                        run.add(str(m.get("id")))
                        d["sessions"].add(session)
                    if str(o.get("entrypoint") or "").startswith("sdk"):
                        d["auto"].add(session)
                    d["projects"].add(project)
                    content = m.get("content")
                    for b in content if isinstance(content, list) else []:
                        if not isinstance(b, dict) or b.get("type") != "tool_use" or str(b.get("id")) in seen_tools:
                            continue
                        seen_tools.add(str(b.get("id")))
                        name = str(b.get("name") or "")
                        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                        d["tools"] += 1
                        if name == "Skill":
                            d["skills"].add(str(inp.get("skill")))
                        elif name in ("Agent", "Task"):
                            d["spawns"] += 1
                            d["agents"].add(str(inp.get("subagent_type") or "general-purpose"))
                        elif name.startswith("mcp__"):
                            d["servers"].add(name.split("__")[1])
                        elif name in EDIT_TOOLS:
                            d["edits"] += 1
                            d["memory_writes"] += MEMORY_FOLDER in str(inp.get("file_path", "")).replace("\\", "/")
                        elif name == "Bash":
                            cmd = str(inp.get("command", ""))
                            d["commits"] += bool(GIT_COMMIT_RE.search(cmd))
                            d["prs"] += "gh pr create" in cmd
                        elif name == "Artifact":
                            if inp.get("file_path") and not inp.get("asset") and inp.get("action") in (None, "publish"):
                                d["pages"].add(str(inp["file_path"]))
                        elif name == "ExitPlanMode":
                            d["plan"] += 1
                        elif name == "EnterWorktree":
                            d["worktrees"] += 1
                elif '"type":"user"' in line:
                    if '"tool_result"' in line:
                        if day and '"is_error":true' in line:
                            days[day]["errors"] += 1
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
        longest = max(longest, len(run))
    for _, day, u, model in best.values():
        days[day]["models"][str(model)] += 1
        for k in TOKEN_WEIGHT:
            days[day]["tok"][k] += num(u.get(k))
    return dict(days), longest


def scan_setup(cdir, cfg, settings):
    """What is installed and how it is wired. Names stay in memory; only counts leave."""
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


def score(cdir, machine_jobs, save):
    today = datetime.now(timezone.utc).date()
    today_s = today.isoformat()
    home_cfg = os.path.join(os.path.expanduser("~"), ".claude.json")
    cfg = load_dict(os.path.join(cdir, ".claude.json")) or (load_dict(home_cfg) if machine_jobs else {})
    settings = load_dict(os.path.join(cdir, "settings.json"))
    local = load_dict(os.path.join(cdir, "settings.local.json"))
    for key in ("hooks", "permissions"):       # count both files together
        settings[key] = merged_lists(settings.get(key), local.get(key))

    setup = scan_setup(cdir, cfg, settings)
    prompts = scan_history(cdir)
    days, longest_run = scan_logs(cdir, set(setup["skills"]))
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
    for code, (points, count) in penalties.items():
        if round(points) >= 1:
            needs.append({"code": code, "count": count, "stat": "health", "gain": round(points)})
            if code == "sign_in":
                needs[-1]["from_plugins"] = sum(1 for name in waiting if name.startswith("plugin:"))
    per_check = round(100 / len(checks))
    for i, ok in enumerate(checks):
        if not ok:
            needs.append({"code": "brains_%d" % (i + 1), "count": 0, "stat": "brains", "gain": per_check})
    needs.sort(key=lambda n: -n["gain"])

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

    kept = {"days": banked, "estimated": sorted(estimated), "badges": badges, "weeks": weeks}
    if save and (banked or badges) and any(kept[k] != ledger.get(k) for k in kept):
        try:
            os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
            # Written to a fresh private file and swapped in: never through a link, never half written.
            write_private(ledger_path, json.dumps(dict(kept, version=4, first_seen=ledger.get("first_seen") or today_s),
                                                  indent=1, sort_keys=True))
        except OSError:
            pass   # the card still shows; the day is banked at the next run

    raw.update({
        "idle_days": idle, "skills_own": len(own), "skills_plugin": setup["plugin_skills"],
        "commands_flat": setup["commands_flat"], "skills_unused": len(unused),
        "connectors_need_sign_in": need_sign_in, "hooks": sum(setup["hook_events"].values()),
        "hook_event_types": len(setup["hook_events"]), "memory_files": setup["memory_files"],
        "startup_context_tokens": setup["context_tokens"],
        "tokens_30d": {k: w30["tok"][k] for k in TOKEN_WEIGHT},
        "tool_calls_30d": w30["tools"], "tool_errors_30d": w30["errors"],
        "interrupts_30d": w30["interrupts"], "brains_passed": sum(checks), "brains_total": len(checks),
        "xp_days": len(banked), "xp_days_estimated": len(estimated),
        "xp_7d": sum(x for d, x in banked.items() if d >= (today - timedelta(days=7)).isoformat()),   # the last 7 finished days
    })
    return {
        "version": 1, "generated": today_s, "scope": "one machine, self-reported",
        "level": level, "xp": xp, "xp_next_level": LEVEL_DIVISOR * (level + 1) ** 2,
        "xp_today_pending": pending,
        "stage": next(name for floor, name in STAGES if level >= floor), "class": class_of(stats),
        "brain": next((name for floor, name in BRAIN_TITLES if stats["brains"] >= floor), ""),
        "mood": mood_of(health, idle, current_streak, gap), "health": health,
        "power": sum(stats.values()), "stats": stats,
        "badges": [b for b in BADGES if b in badges], "needs": needs, "raw": raw,
        "lessons": [lesson[0] for stat in STAT_ORDER for lesson in LESSONS[stat] if done[lesson[0]]],
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


def render(r, joined=True, how=False, tip=None):
    """The card. On a machine that is not on the board (`joined` false) with XP banked in the last 7 days, the last lines
    say how much of it will never rank: the board counts only XP it sees after joining. Worked out here; nothing is sent.
    With tips on, `how` adds a how-to line under each Need and `tip` is the tip of the day, (stat, tip)."""
    raw, level = r["raw"], r["level"]
    who = r["stage"] if r["class"] == UNHATCHED else "%s %s" % (r["stage"], r["class"])
    to_next = "top level" if level >= LEVEL_MAX else "{:,} to Lv {}".format(r["xp_next_level"] - r["xp"], level + 1)
    guessed = " (%d estimated)" % raw["xp_days_estimated"] if raw["xp_days_estimated"] else ""
    side = [
        "%s · Lv %d" % (who, level),
        "XP {:,} · {} · today so far +{}".format(r["xp"], to_next, r["xp_today_pending"]),
        "Mood: %s · Health %d · %s %d" % (r["mood"], r["health"], AURA, r["power"]),
        "%s old · %s%s · streak %d" % (count(raw["age_days"], "day"), count(raw["active_days"], "active day"), guessed,
                                       raw["current_streak"]),
    ]
    out = ["", *("  %s   %s" % (art, text) for art, text in zip(ART[r["stage"]], side)), ""]
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
    else:
        out.append("  Needs: nothing right now. %s." % QUIPS["no_needs"])
    if r["badges"]:
        out += ["", "  Badges: " + ", ".join(BADGE_NAMES[b] for b in r["badges"])]
    if tip:
        stat, (_, text, page) = tip
        out += ["", "  Tip of the day (%s): %s" % (stat.capitalize(), text), "  %s%s" % (DOCS, page)]
    out += ["", "  This machine only, self-reported. Deep check-up: /doctor and /skill-doctor."]
    if not joined and raw["xp_7d"] > 0:
        out += ["  Not on the board yet: your last 7 days earned {:,} XP that will never rank.".format(raw["xp_7d"]),
                "  Start counting: /pet join the leaderboard. Post it as an image: /pet card."]
    else:
        out += ["  Post it as an image: /pet card. Challenge a friend: /pet duel."]
    out += ["  Learn Claude Code step by step: /pet learn%s." % ("" if how else ". A how-to under each Need: /pet tips on"), ""]
    return "\n".join(out)


def short_day(day):
    return "%d %s" % (int(day[8:]), MONTHS[int(day[5:7]) - 1])


def wrapped(cdir, year, today):
    """A year in review from this machine's ledger: its banked days, badges and weekly snapshots. Offline."""
    _, banked, badges, estimated, weeks = read_ledger(cdir, today)
    start, end = "%d-01-01" % year, "%d-12-31" % year
    days = {d: x for d, x in banked.items() if start <= d <= end}
    out = ["", "  CC level Wrapped %d%s · this machine only, self-reported" % (year, " so far" if year == today.year else ""), ""]
    if not days:
        return "\n".join(out + ["  No finished days banked in %d on this machine." % year, ""])

    def xp_until(day):
        return sum(x for d, x in banked.items() if d <= day) + sum(BADGES[b] for b, when in badges.items() if when <= day)
    first, last = level_of(xp_until(str(year - 1) + "-12-31")), level_of(xp_until(end))
    guessed = sum(1 for d in days if d in estimated)
    out.append("  {:,} XP over {}{}".format(sum(days.values()), count(len(days), "active day"),
                                           " (%d estimated from prompt counts)" % guessed if guessed else ""))
    out.append("  Lv %d %s → Lv %d %s" % (first, stage_of(first), last, stage_of(last)))
    months = [0] * 12
    for d, x in days.items():
        months[int(d[5:7]) - 1] += x
    best_day = max(sorted(days), key=lambda d: days[d])   # the earliest of equal days
    best_month = max(range(12), key=lambda m: months[m])
    longest = run = 0
    prev = None
    for d in sorted(days):
        dt = date.fromisoformat(d)
        run = run + 1 if prev and (dt - prev).days == 1 else 1
        longest, prev = max(longest, run), dt
    out.append("  Best day: {}, {:,} XP · Best month: {}, {:,} XP · Longest streak: {}".format(
        short_day(best_day), days[best_day], MONTHS[best_month], months[best_month], count(longest, "day")))
    earned = [BADGE_NAMES[b] for b in BADGES if start <= badges.get(b, "") <= end]
    out.append("  Badges earned: " + ", ".join(earned) if earned else "  No new badges this year.")
    out.append("")
    top = max(months)
    for m in range(today.month if year == today.year else 12):
        filled = round(20 * months[m] / top)
        out.append("  %s  %s%s  %s" % (MONTHS[m], "#" * filled, "-" * (20 - filled), "{:,}".format(months[m]).rjust(6)))
    out.append("")
    snaps = [weeks[w]["stats"] for w in sorted(weeks) if w.startswith(str(year))]
    if not snaps:
        out.append("  Weekly snapshots of your stats start with this version, so a later Wrapped shows how they moved.")
    else:
        weeks_in = [w for w in sorted(weeks) if w.startswith(str(year))]
        classes = Counter(class_of(dict(zip(STAT_ORDER, s))) for s in snaps)
        averages = {name: sum(s[i] for s in snaps) / len(snaps) for i, name in enumerate(STAT_ORDER)}
        strongest = max(STAT_ORDER, key=lambda n: averages[n])
        out.append("  %s, from %s · Most weeks as: %s · Strongest stat: %s, %d on average" % (
            count(len(snaps), "weekly snapshot"), weeks_in[0], classes.most_common(1)[0][0], strongest.capitalize(),
            round(averages[strongest])))
        if len(snaps) > 1:
            out.append("  Since then: " + " · ".join("%s %+d" % (name.capitalize(), snaps[-1][i] - snaps[0][i])
                                                       for i, name in enumerate(STAT_ORDER)))
    out += ["", "  Post your card: /pet card.", ""]
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
# Nothing above this line touches the network. Everything below runs only
# when the user asks for it by flag, or from the plugin's session-start hook
# after the user turned auto check-in on with --auto on.

DEFAULT_SERVER = "https://go.cclevel.workers.dev"   # the public board; --server or $CCLEVEL_SERVER picks another
MOVED_FROM = ("https://cclevel-board.cclevel.workers.dev",)   # the public board's earlier addresses: same board
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
CARD_VERSION = 1         # must match the card page, server/public/card.js
GH_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")   # GitHub's rule for a login
SERVER_RE = re.compile(r"https://|http://(localhost|127\.0\.0\.1)[:/]")
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
    """Everything that ever leaves this machine. Keep in step with PRIVACY.md."""
    return {"v": RULES_VERSION, "xp": result["xp"], "xp_days": result["raw"]["xp_days"],
            "stats": result["stats"], "badges": result["badges"]}


def identity_path(cdir):
    return os.path.join(cdir, "cclevel", "identity.json")


def left_path(cdir):
    return os.path.join(os.path.dirname(identity_path(cdir)), "left")


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
    ok = isinstance(token, str) and TOKEN_RE.fullmatch(token) and isinstance(server, str) and SERVER_RE.match(server + "/")
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
    """The public board's address for one of its earlier ones. Any other address is left as it is."""
    return DEFAULT_SERVER if server.rstrip("/").lower() in MOVED_FROM else server


def resolve_server(args, ident):
    """The board to talk to. A creature only ever talks to the board it joined."""
    asked = moved(args.server or os.environ.get("CCLEVEL_SERVER") or "")
    home = moved(ident.get("server") or "")
    if home and asked and asked.rstrip("/") != home.rstrip("/"):
        sys.exit("cclevel: this creature lives on %s. Leave that board first, or drop --server and CCLEVEL_SERVER." % home)
    server = (home or asked or DEFAULT_SERVER).rstrip("/")
    if server and not SERVER_RE.match(server + "/"):
        sys.exit("cclevel: the server address must start with https://")
    return server


def parse_reply(raw):
    """A reply from the board as a dict. Anything oversized or odd becomes an empty one."""
    def reject(_):
        raise ValueError

    try:
        return as_dict(json.loads(raw, parse_constant=reject)) if len(raw) <= MAX_REPLY else {}
    except (ValueError, RecursionError):
        return {}


def call(server, method, path, token=None, body=None):
    """One request to the board. Returns (status, reply dict)."""
    req = urllib.request.Request(server + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "cclevel"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with (LOCAL_OPENER if server.startswith("http://") else OPENER).open(req, timeout=15) as resp:
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
            now.update(token=ident["token"], server=ident["server"], name=ident["name"])
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


def invite_link(server, code):
    """The link friends open or paste. Shown in full: it can land in a chat transcript, and it only grants a seat."""
    return "%s/join#%s" % (server, code)


def duel_link(server, code):
    """The link a challenged friend opens or pastes. Shown in full, like a group's: it only grants the second seat."""
    return "%s/duel#%s" % (server, code)


def card_link(server, result):
    """The share card's address. Its numbers sit after "#", which browsers never send: the page draws the picture from
    them. XP, the six stats, the mood, the streak and the badges as bits; the page works out the rest the way this file does."""
    numbers = [CARD_VERSION, result["xp"], *(result["stats"][s] for s in STAT_ORDER),
               list(MOODS.values()).index(result["mood"]), result["raw"]["current_streak"],
               sum(1 << i for i, b in enumerate(BADGES) if b in result["badges"])]
    return "%s/card#%s" % (server, "-".join(str(n) for n in numbers))


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


def join_terms(data, server):
    """What joining the board sends and means, shown before the first check-in."""
    print(json.dumps(data, indent=1))
    print("\nJoining sends exactly this to %s, with a random token made on this machine." % server)
    print("It does not put you on the public lists: the world ranking stays off until you run --world on.")
    print("Every creature with check-ins on two different days is counted in the board's public totals")
    print("(how many creatures per level, stat range, class, stage and badge), listed or not.")


def group_terms(create):
    print("%s a private group. Its members, up to %d, see each other's generated name, level, XP since joining,"
          % ("Starting" if create else "Joining", GROUP_MAX))
    print("season XP, six stats and sus mark, as soon as each one checks in. No other creature can see the group.")
    print("Being in a group does not put you on the world lists. --group-leave leaves at once.")


START_COUNTING = "Check in today (--sync), or turn on --auto on: duel XP counts only after a check-in from today on."


def duel_terms(create):
    print("%s a duel: you and one friend, %d days, and whoever the board credits with more XP in them wins the ♛."
          % ("Starting" if create else "Accepting", DUEL_DAYS))
    print("It starts at 00:00 UTC the day after it is accepted. Duel XP counts from each side's first check-in on or after")
    print("the day it is accepted. The two of you see each other's generated name, level, duel XP, six stats and sus mark.")
    print("Nobody else can see the duel, and it does not put you on the world lists.")
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
        print("Note: this invite names another address. cclevel uses only its code, on %s." % server)
    if not ident:
        # One yes covers both: joining the board and taking the seat.
        join_terms(data, server)
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
        keep_local(cdir, ident["token"], lambda now: now.pop("group", None))
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
            keep_local(cdir, token, lambda now: now.update(group=code))
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
    """The opt-in GitHub badge: prove control of an account with a public gist. Nothing GitHub-side leaves this machine."""
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
        print("Ranks count only the XP the board saw you earn after joining. Join with --join, check in, then --world on.")
    else:
        listed = ident.get("world") is True
        if not listed:
            print("You are not on the world lists (turn them on with --world on). With your numbers you would be:")
        in_season = sane(season) and ident.get("month") == this_month() and board.get("month") == this_month() and season > 0
        mine = [("all", witnessed)] + ([("season", season)] if in_season else [])
        public = {}
        if any((rival(lists[name], xp) or (0, None))[1] is not None for name, xp in mine):
            # Only to name the creature ahead: the public list, downloaded without the token, used only if built with the board file.
            status, top = call(server, "GET", "/top.json")
            if status == 200 and top.get("generated") == board.get("generated"):
                public = top
        print("  All-time: %s · {:,} XP the board witnessed · {:,} ranked".format(witnessed, lists["all"][0])
              % place(lists["all"], witnessed))
        line = rival_line(lists["all"], witnessed, public.get("all"))
        if line:
            print(line)
        if not in_season:
            print("  Season:   no XP this month yet")
        else:
            print("  Season:   %s · {:,} XP this month · {:,} ranked".format(season, lists["season"][0])
                  % place(lists["season"], season))
            line = rival_line(lists["season"], season, public.get("season"))
            if line:
                print(line)
        if listed:
            print("  As of the board's last update; it updates every six hours.")
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
        print("Turning the world ranking on lists %s on the public board at %s:" % (name, server))
        print("its generated name, stage, class, level, Aura, the XP the board witnessed and a sus mark if it applies.")
        print("A creature shows once it has check-ins on two different days; the lists update every six hours.")
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
        print("World ranking on. %s shows on the public lists from the next board update (every six hours)." % name)
    else:
        print("World ranking on. %s shows once it has check-ins on two different days." % name)
    return 0


def auto_command(args, cdir, ident):
    """Turn the daily auto check-in on (asks first) or off. A choice kept on this machine only: nothing is sent."""
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
        print("Auto check-in off. No check-in is sent unless you run --sync.")
        return 0
    if not args.yes:
        print("Auto check-in runs --sync for you once a day, in the background, when a Claude Code session starts.")
        print("It sends the same nine numbers and badge codes as --sync, to the same board, and prints nothing.")
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
    """The plugin's session-start hook. Without --auto on it reads one file and stops; with it, one quiet check-in a UTC day."""
    ident = load_identity(cdir)
    token = ident.get("token")
    if not token or ident.get("auto") is not True or ident.get("auto_day") == today_utc():
        return 0
    # Nothing reaches the screen or Claude's context: the hook runs in the background and its output is discarded here too.
    sys.stdout = sys.stderr = open(os.devnull, "w")
    server = resolve_server(args, ident)
    if not server:
        return 0
    # One board write at a time: when a check-in or a leave from this machine is under way, this session stops at once.
    try:
        with board_lock(cdir, 0):
            return auto_once(cdir, token, server, default_dir)
    except Busy:
        return 0


def auto_once(cdir, token, server, default_dir):
    """One background check-in, run while holding the board lock."""
    # Read again now that this hook holds the lock: another session may have checked in, or the owner left, meanwhile.
    fresh = auto_wanted(cdir, token)
    if fresh is None or fresh.get("auto_day") == today_utc():
        return 0
    real = os.path.realpath(cdir) == os.path.realpath(default_dir)
    result = score(cdir, machine_jobs=real, save=True)
    if not auto_wanted(cdir, token):
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
    return 0


def board_command(args, cdir, result):
    data = payload(result)
    if args.preview:
        print(json.dumps(data, indent=1))
        print("\nThis is everything a check-in sends. Nothing has been sent.")
        return 0
    if args.card:
        print("Your card as a picture: open this link, then save or copy the image.")
        print("  " + card_link(resolve_server(args, load_identity(cdir)), result))
        print("The numbers after # stay in your browser: the page sends nothing, and the picture shows no creature name.")
        return 0
    try:
        with identity_lock(cdir, 0):
            tidy_left(cdir)
    except (Busy, OSError):
        pass
    ident = load_identity(cdir)
    if args.auto:
        return auto_command(args, cdir, ident)
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
            if args.world:
                return world_command(args, cdir, server, ident)
            if args.verify_github or args.unverify_github:
                return github_command(args, cdir, server, ident)
            if duel:
                return duel_command(args, cdir, server, ident, data, result)
            return group_command(args, cdir, server, ident, data, result)
    if args.leave:
        if not ident:
            print("Not on the board, nothing to leave.")
            return 0
        # Under the board lock: a check-in from this machine already on its way finishes first, and none starts until the
        # row and the token are gone. If this run is stopped half way, nothing is left half done.
        token = ident["token"]
        with board_lock(cdir, 30):
            if load_identity(cdir).get("token") != token:
                print("Not on the board, nothing to leave.")
                return 0
            status, reply = call(server, "DELETE", "/api/entry", token)
            if status != 200 or type(reply.get("deleted")) is not bool:
                print("cclevel: the board did not confirm the deletion (HTTP %d). The token is kept so you can retry." % status)
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
        join_terms(data, server)
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
    # The token is kept only once the board has taken the first check-in.
    joined = bool(ident)
    ident = ident or {"token": token, "server": server, "name": name}
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
    line = badge_line(reply.get("verified"), reply.get("commits"))
    if line:
        print(line)
    if reply.get("sus") is True:
        print("Sus: 80%% or more of your witnessed days took the full %d XP. The mark changes nothing else." % DAY_CAP)
    return 0, ident


def main():
    default_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    ap = argparse.ArgumentParser(description="Score a Claude Code setup and show it as a creature.")
    ap.add_argument("--claude-dir", default=default_dir, help="Claude Code folder to scan (default: %(default)s)")
    ap.add_argument("--json", action="store_true", help="print numbers only, as JSON")
    ap.add_argument("--no-save", action="store_true", help="do not write the ledger")
    ap.add_argument("--server", help="leaderboard address (default: the public board, or $CCLEVEL_SERVER)")
    ap.add_argument("--yes", action="store_true",
                    help="with --join, --world on, --auto on, a group or duel start or join, or --verify-github: do not ask again")
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
    board.add_argument("--learn", action="store_true",
                       help="the training path: five lessons per stat, ticked by what your logs show; sends nothing")
    board.add_argument("--tips", choices=("on", "off"),
                       help="a how-to under each Need and one Claude Code tip a day on the card; kept on this machine, sends nothing")
    board.add_argument("--verify-github", metavar="LOGIN", help="opt-in GitHub badge: start (asks first), then run again to finish")
    board.add_argument("--unverify-github", action="store_true", help="remove the GitHub badge and every GitHub detail at once")
    board.add_argument("--leave", action="store_true", help="delete your row and the local token")
    board.add_argument("--rank", action="store_true", help="compare with the public board; uploads nothing")
    board.add_argument("--auto", choices=("on", "off"),
                       help="check in once a day by itself when a Claude Code session starts (on asks first); sends nothing now")
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
    # Machine-level sources (scheduled jobs, ~/.claude.json) belong to the real folder only.
    real = os.path.realpath(cdir) == os.path.realpath(default_dir)
    result = score(cdir, machine_jobs=real, save=not (args.no_save or args.preview))
    if args.wrapped is not None:
        today = datetime.now(timezone.utc).date()
        year = today.year if args.wrapped is THIS_YEAR else args.wrapped
        if not FIRST_YEAR <= year <= today.year:
            sys.exit("cclevel: --wrapped takes a year from %d to %d" % (FIRST_YEAR, today.year))
        print(wrapped(cdir, year, today))
        return
    if args.learn:
        sys.exit(learn_command(cdir, result, save=not args.no_save))
    if (args.preview or args.join or args.sync or args.world or args.leave or args.rank or args.group or args.group_create
            or args.group_join is not None or args.group_leave or args.group_code or args.verify_github or args.unverify_github
            or args.auto or args.duel or args.duel_create or args.duel_join is not None or args.duel_leave or args.duel_code
            or args.card):
        try:
            sys.exit(board_command(args, cdir, result))
        except Busy as e:
            print(busy_text(e))
            sys.exit(1)
        except OSError as e:
            print("cclevel: could not save this machine's board settings (%s)." % (e.strerror or type(e).__name__))
            sys.exit(1)
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        how, tip = training_extras(cdir, result, save=not args.no_save)
        # Whether this machine is on the board is read from its own token file; nothing is sent.
        print(render(result, joined=bool(load_identity(cdir)), how=how, tip=tip))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
