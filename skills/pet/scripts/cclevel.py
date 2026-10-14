#!/usr/bin/env python3
"""cclevel: score a Claude Code setup and show it as a creature that grows.

Reads the local Claude Code folder. Writes nothing except its own files in
<claude dir>/cclevel/. A score covers one machine and is self-reported.

The card is fully offline. The network is used only by --join, --sync,
--world, the --group commands, the GitHub badge commands, --leave and
--rank, and only for what payload() returns, the world choice, a group
invite code and a GitHub login with the hash of a code.
"""
import argparse
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
import sys
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
STAGES = [(60, "Final Boss"), (45, "Giga"), (30, "Main Character"), (15, "Lil Guy"), (5, "Hatchling"), (1, "Egg")]
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

ART = {
    "Egg": [r"   ___   ", r"  /   \  ", r" |  .  | ", r"  \___/  "],
    "Hatchling": [r"   ___   ", r"  /o o\  ", r" _\_^_/_ ", r"  '   '  "],
    "Lil Guy": [r"  .-^-.  ", r" ( o o ) ", r"  \ ~ /  ", r"  /| |\  "],
    "Main Character": [r"  .-^-.  ", r" ( o o ) ", r" /\ ~ /\ ", r"  /| |\  "],
    "Giga": [r" \.-^-./ ", r" ( o o ) ", r" /\ = /\ ", r" _/| |\_ "],
    "Final Boss": [r"*\.-^-./*", r" ( @ @ ) ", r"</\ = /\>", r" _/| |\_ "],
}

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GIT_COMMIT_RE = re.compile(r"\bgit\s+commit\b")
COMMAND_RE = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
HOOK_COUNT_RE = re.compile(r'"hookCount":(\d+)')


# ---------------------------------------------------------------- reading

def load_json(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except (OSError, ValueError):
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
            "edits": 0, "commits": 0, "prs": 0, "spawns": 0, "tools": 0,
            "errors": 0, "interrupts": 0, "turns": 0, "plan": 0, "hooks_ran": 0, "memory_writes": 0}


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

    ledger_path = os.path.join(cdir, "cclevel", "ledger.json")
    ledger = load_dict(ledger_path)
    # A hand-edited ledger cannot lift a day above the cap, bank a future day or hold a badge that does not exist.
    banked = {d: min(int(x), DAY_CAP) for d, x in as_dict(ledger.get("days")).items()
              if is_day(d) and d < today_s and num(x) > 0}
    badges = {b: str(when) for b, when in as_dict(ledger.get("badges")).items() if b in BADGES}
    listed = ledger.get("estimated") if isinstance(ledger.get("estimated"), list) else []
    estimated = {d for d in listed if isinstance(d, str) and d in banked}

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

    xp = sum(banked.values()) + sum(BADGES.get(b, 0) for b in badges)
    level = max(1, min(LEVEL_MAX, math.isqrt(xp // LEVEL_DIVISOR)))

    kept = {"days": banked, "estimated": sorted(estimated), "badges": badges}
    if save and (banked or badges) and any(kept[k] != ledger.get(k) for k in kept):
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
        tmp = ledger_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(kept, version=3, first_seen=ledger.get("first_seen") or today_s), f, indent=1, sort_keys=True)
        os.replace(tmp, ledger_path)

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


def render(r):
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
        out += ["   %d. %s" % (i + 1, need_text(n)) for i, n in enumerate(r["needs"][:5])]
    else:
        out.append("  Needs: nothing right now. %s." % QUIPS["no_needs"])
    if r["badges"]:
        out += ["", "  Badges: " + ", ".join(BADGE_NAMES[b] for b in r["badges"])]
    out += ["", "  This machine only, self-reported. Deep check-up: /doctor and /skill-doctor.", ""]
    return "\n".join(out)


# ------------------------------------------------------------ leaderboard
# Nothing above this line touches the network. Everything below runs only
# when the user asks for it by flag.

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
WORLD_REFUSALS = {
    401: "the board did not accept the token",
    404: "the board has no creature for this token. Check in with --sync, or join again",
    429: "the world ranking and group joins can be turned on three times a day together. Try again tomorrow",
}
# Keyed by the board's one-word reason. The word is only looked up here, never printed.
GROUP_REFUSALS = {
    "no_creature": "the board has no creature for this token. Check in with --sync, or join again",
    "no_group": "no group has this code. Check it, or start one with --group-create",
    "full": "this group is full (%d members)" % GROUP_MAX,
    "name_taken": "a member of this group has the same generated name as yours",
    "in_group": "you are already in a group. Leave it first with --group-leave",
    "opt_ins": "the world ranking and group joins can be turned on three times a day together. Try again tomorrow",
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


def load_identity(cdir):
    ident = load_dict(identity_path(cdir))
    token, server = ident.get("token"), ident.get("server")
    ok = isinstance(token, str) and TOKEN_RE.fullmatch(token) and isinstance(server, str) and SERVER_RE.match(server + "/")
    return ident if ok else {}


def save_identity(cdir, ident):
    path = identity_path(cdir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # The token is the only key to the board row: readable by its owner only, never written through a link.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    os.fchmod(fd, 0o600)   # an older file may have wider permissions: narrow them before anything is written
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(ident, f, indent=1)


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


def remember(cdir, ident, reply):
    """Keep the board's latest numbers for this creature, so --rank can work offline from the public file."""
    numbers = {k: reply[k] for k in ("witnessed_xp", "season_xp") if sane(reply.get(k))}
    if type(reply.get("world")) is bool:
        numbers["world"] = reply["world"]
    if "season_xp" in numbers:
        numbers["month"] = this_month()
    ident.update(numbers)
    save_identity(cdir, ident)


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


def name_of(key):
    """A creature's name from the three numbers the board sends, spelled with this copy's own word lists."""
    if not (isinstance(key, list) and len(key) == 3 and all(type(n) is int for n in key)):
        return None
    adjective, animal, number = key
    if not (0 <= adjective < len(ADJECTIVES) and 0 <= animal < len(ANIMALS) and 0 <= number < 10000):
        return None
    return "%s %s %04d" % (ADJECTIVES[adjective], ANIMALS[animal], number)


def member(m):
    """One member from a group reply, checked, or None."""
    m = as_dict(m)
    stats = m.get("stats")
    ok = (name_of(m.get("name")) and type(m.get("level")) is int and 1 <= m["level"] <= LEVEL_MAX
          and sane(m.get("witnessed_xp")) and sane(m.get("season_xp")) and type(m.get("sus")) is bool
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


def group_refusal(status, reply, table=GROUP_REFUSALS):
    reason = reply.get("reason")
    return (table.get(reason) if isinstance(reason, str) else None) or "it answered HTTP %d" % status


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
        ident.pop("group", None)
        save_identity(cdir, ident)
        print("Left the group." if reply["left"] else "You were not in a group.")
        return 0
    if args.group_create or args.group_join is not None:
        create = bool(args.group_create)
        text = "" if create else args.group_join
        if not create and not text.strip():
            # No link given: ask for it without echo, so it never appears on screen.
            if not sys.stdin.isatty():
                print("cclevel: pass the invite link, or run --group-join in your own terminal to type it hidden. Nothing sent.")
                return 1
            try:
                text = getpass.getpass("Invite link or code (hidden): ")
            except EOFError:
                text = ""
        code, foreign = (secrets.token_hex(16), False) if create else read_invite(text, server)
        if not code:
            print("cclevel: that is not an invite. A link ends in #, then 32 characters, 0-9 and a-f. Nothing sent.")
            return 1
        if foreign:
            print("Note: this invite names another address. cclevel uses only its code, on %s." % server)
        if not ident:
            # One yes covers both: joining the board and joining the group.
            join_terms(data, server)
            print()
            group_terms(create)
            if not confirmed(args, "Join the board and the group? [y/N] ", "Re-run with --yes to join the board and the group."):
                return 1
            rc, ident = check_in(cdir, server, {}, secrets.token_hex(32), data, result)
            if rc:
                return rc
        elif not args.yes:
            group_terms(create)
            if not confirmed(args, "Go ahead? [y/N] ", "Re-run with --yes to go ahead."):
                return 1
        token = ident["token"]
        status, reply = call(server, "POST", "/api/group", token, {"code": code, "new": True} if create else {"code": code})
        members = reply.get("members")
        if status != 200 or reply.get("joined") is not True or not sane(members) or not 1 <= members <= GROUP_MAX:
            print("cclevel: the board did not add you to the group: %s." % group_refusal(status, reply))
            return 1
        ident["group"] = code
        try:
            save_identity(cdir, ident)
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
    print("   #  %-24s %3s  %12s  %10s  %4s" % ("Creature", "Lv", "XP joined", "Season XP", "Aura"))
    place = 0
    for i, m in enumerate(checked):
        if i == 0 or m["witnessed_xp"] != checked[i - 1]["witnessed_xp"]:
            place = i + 1
        tags = (" (you)" if m["you"] else "") + (" sus" if m["sus"] else "")
        print("  %2d  %-24s %3d  %12s  %10s  %4d%s" % (place, name_of(m["name"]), m["level"], "{:,}".format(m["witnessed_xp"]),
                                                     "{:,}".format(m["season_xp"]), sum(m["stats"]), tags))
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
        ident.pop("github", None)
        save_identity(cdir, ident)
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
        ident.pop("github", None)
        save_identity(cdir, ident)
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
    ident["github"] = {"login": login, "code": code}
    save_identity(cdir, ident)
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
        print("  All-time: %s · {:,} XP the board witnessed · {:,} ranked".format(witnessed, lists["all"][0])
              % place(lists["all"], witnessed))
        if not sane(season) or ident.get("month") != this_month() or board.get("month") != this_month() or season == 0:
            print("  Season:   no XP this month yet")
        else:
            print("  Season:   %s · {:,} XP this month · {:,} ranked".format(season, lists["season"][0])
                  % place(lists["season"], season))
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
    except OSError:
        pass  # the board has the choice; the local copy only feeds --rank
    if not on:
        print("World ranking off. %s is off the public lists now." % name)
    elif reply["listed"]:
        print("World ranking on. %s shows on the public lists from the next board update (every six hours)." % name)
    else:
        print("World ranking on. %s shows once it has check-ins on two different days." % name)
    return 0


def board_command(args, cdir, result):
    data = payload(result)
    if args.preview:
        print(json.dumps(data, indent=1))
        print("\nThis is everything a check-in sends. Nothing has been sent.")
        return 0
    ident = load_identity(cdir)
    server = resolve_server(args, ident)
    if not server:
        print("cclevel: no public board is configured yet. Pass --server to use your own.")
        return 1
    if args.rank:
        return show_rank(server, ident, result)
    if args.world:
        return world_command(args, cdir, server, ident)
    if args.group or args.group_create or args.group_join is not None or args.group_leave or args.group_code:
        return group_command(args, cdir, server, ident, data, result)
    if args.verify_github or args.unverify_github:
        return github_command(args, cdir, server, ident)
    if args.leave:
        if not ident:
            print("Not on the board, nothing to leave.")
            return 0
        status, reply = call(server, "DELETE", "/api/entry", ident["token"])
        if status != 200 or type(reply.get("deleted")) is not bool:
            print("cclevel: the board did not confirm the deletion (HTTP %d). The token is kept so you can retry." % status)
            return 1
        os.remove(identity_path(cdir))
        if reply["deleted"]:
            print("Left the board. Your row is deleted and the local token is removed.")
        else:
            print("The board had no row for this token. The local token is removed.")
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
    """Send one check-in, keep the token once the board has taken the first one. Returns (exit code, identity)."""
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
        remember(cdir, ident, reply)
    except OSError as e:
        if not joined:
            print("cclevel: joined, but the token could not be saved (%s). The row will expire on its own." % e.strerror)
            return 1, ident
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
    ap.add_argument("--yes", action="store_true", help="with --join, --world on, a group start or join, or --verify-github: do not ask again")
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
    board.add_argument("--verify-github", metavar="LOGIN", help="opt-in GitHub badge: start (asks first), then run again to finish")
    board.add_argument("--unverify-github", action="store_true", help="remove the GitHub badge and every GitHub detail at once")
    board.add_argument("--leave", action="store_true", help="delete your row and the local token")
    board.add_argument("--rank", action="store_true", help="compare with the public board; uploads nothing")
    args = ap.parse_args()
    cdir = os.path.abspath(os.path.expanduser(args.claude_dir))
    if not os.path.isdir(cdir):
        sys.exit("cclevel: %s is not a folder" % cdir)
    # Machine-level sources (scheduled jobs, ~/.claude.json) belong to the real folder only.
    real = os.path.realpath(cdir) == os.path.realpath(default_dir)
    result = score(cdir, machine_jobs=real, save=not (args.no_save or args.preview))
    if (args.preview or args.join or args.sync or args.world or args.leave or args.rank or args.group or args.group_create
            or args.group_join is not None or args.group_leave or args.group_code or args.verify_github or args.unverify_github):
        sys.exit(board_command(args, cdir, result))
    print(json.dumps(result, indent=1) if args.json else render(result))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
