// cclevel board: receives scores from the cclevel scanner and serves the public board.
// Privacy rules for this file: store no IP address, no user agent and no raw token, and log nothing.
import { ADJECTIVES, ANIMALS } from "./names.js";

// Scoring rules. These must match skills/pet/scripts/cclevel.py.
const RULES = 1;
const DAY_CAP = 550;
const LEVEL_DIVISOR = 40;
const LEVEL_MAX = 99;
const BADGES = {
	first_hook: 250, first_skill: 250, first_subagent: 250, first_loop: 500,
	streak_7: 200, streak_30: 1000, streak_100: 3000,
	skills_10: 200, skills_50: 1000, skills_100: 3000,
};
const STATS = ["grind", "appetite", "arsenal", "brains", "autonomy", "craft"];
const STAT_STEP = 5; // stats arrive in steps of 5
// Names are for the board page only. Clients never read them: they get numbers and name things themselves.
const STAGES = [[60, "Final Boss"], [45, "Giga"], [30, "Main Character"], [15, "Lil Guy"], [5, "Hatchling"], [1, "Egg"]];
// The class is the strongest of the four things a setup does. Grind and Brains never set it.
const CLASSES = { craft: "Shipper", autonomy: "AFK Farmer", arsenal: "Loot Goblin", appetite: "Tokenmaxxer" };
const CLASS_FLOOR = 30;
const BALANCED_SPREAD = 10;

// Board rules.
const FIRST_RELEASE = "2025-02-24"; // Claude Code's first public release: nobody has more active days than this
const MAX_BODY = 2048;
const NEW_ROWS_PER_DAY = 5000; // global ceiling, counted without any client identifier
const COUNTED_AFTER_DAYS = 2; // a creature counts, and can be listed, after check-ins on two different days
const ONE_DAY_ROWS_KEPT = 7; // days a creature that never came back is kept
const HIDDEN_AFTER_IDLE = 45; // days without a check-in before it leaves the lists and the totals
const DELETED_AFTER_IDLE = 180; // days without a check-in before the row is deleted
const LIST_SIZE = 1000; // ranked rows per list; below them only band cut-offs are published
const BANDS = [1, 2, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]; // "top X%" cut-offs
const MIN_ROWS_FOR_TOTALS = 100; // no totals for a crowd small enough to pick people out of
const OPT_INS_PER_DAY = 3; // world ranking on and group joins together, per creature and UTC day
const GROUP_MAX = 25; // members of one private group
const GROUP_CODE = /^[0-9a-f]{32}$/; // made on the user's machine
// GitHub badge. A login is 1 to 39 letters, digits and single hyphens, not starting or ending with one.
const GH_LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const GH_CODE_DAYS = 2; // a verification code is good for the day it was sent and the next
const GH_REFRESH = 10; // verified accounts recounted per timed rebuild
const GH_CLAUDE_LINE = "noreply@anthropic.com"; // ends Claude Code's co-author line in every commit it signs
// Sus: at least 14 witnessed days, and at least 80% of them credited at the full daily cap.
const SUS_MIN_DAYS = 14;
const SUS_SQL = `(xp_days - base_days >= ${SUS_MIN_DAYS} AND capped_days * 5 >= (xp_days - base_days) * 4)`;
const isSus = (row) => row.xp_days - row.base_days >= SUS_MIN_DAYS && row.capped_days * 5 >= (row.xp_days - row.base_days) * 4;

const json = (data, status = 200, headers = {}) =>
	new Response(JSON.stringify(data), {
		status,
		headers: { "content-type": "application/json; charset=utf-8", ...headers },
	});
const today = () => new Date().toISOString().slice(0, 10);
const daysBetween = (from, to) => Math.round((Date.parse(to) - Date.parse(from)) / 86400000);
const daysBefore = (day, n) => new Date(Date.parse(day) - n * 86400000).toISOString().slice(0, 10);
// ISO week in UTC, "2026-W42": weeks start on Monday, and a week belongs to the year of its Thursday.
const isoWeek = (day) => {
	const t = new Date(Date.parse(day));
	t.setUTCDate(t.getUTCDate() + 3 - ((t.getUTCDay() + 6) % 7));
	const year = t.getUTCFullYear();
	return `${year}-W${String(1 + Math.floor((t - Date.UTC(year, 0, 1)) / 604800000)).padStart(2, "0")}`;
};
const badgeXp = (list) => list.reduce((sum, b) => sum + BADGES[b], 0);
const isInt = (x, low, high) => Number.isInteger(x) && x >= low && x <= high;

async function sha256(text) {
	const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
	return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// The row key is the hash of the client's token. The token itself is never stored.
async function entryId(request) {
	const match = /^Bearer ([0-9a-f]{64})$/.exec(request.headers.get("authorization") || "");
	return match ? sha256(match[1]) : null;
}

// The spam limiter counts per network: an IPv6 customer usually holds a whole /64.
function network(address) {
	if (!address.includes(":") || address.includes(".")) return address;
	const [head, tail] = address.split("::");
	const left = head ? head.split(":") : [];
	const right = tail ? tail.split(":") : [];
	const gap = Array(Math.max(0, 8 - left.length - right.length)).fill("0");
	const groups = tail === undefined ? left : [...left, ...gap, ...right];
	return groups.slice(0, 4).map((g) => parseInt(g, 16).toString(16)).join(":");
}

// The name as three numbers. Group replies carry these, and the scanner spells the name from its own word lists.
function nameKey(id) {
	const part = (i) => parseInt(id.slice(i, i + 4), 16);
	return [part(0) % ADJECTIVES.length, part(4) % ANIMALS.length, part(8) % 10000];
}

function creatureName(id) {
	const [adjective, animal, number] = nameKey(id);
	return `${ADJECTIVES[adjective]} ${ANIMALS[animal]} ${String(number).padStart(4, "0")}`;
}

function derive(xp, stats) {
	const level = Math.max(1, Math.min(LEVEL_MAX, Math.floor(Math.sqrt(Math.floor(xp / LEVEL_DIVISOR)))));
	const stage = STAGES.find(([floor]) => level >= floor)[1];
	const shape = Object.keys(CLASSES);
	const top = shape.reduce((best, s) => (stats[s] > stats[best] ? s : best));
	const lowest = Math.min(...shape.map((s) => stats[s]));
	let cls = CLASSES[top];
	if (stats[top] === 0) cls = "Unhatched";
	else if (stats[top] < CLASS_FLOOR) cls = "Noob";
	else if (lowest >= CLASS_FLOOR && stats[top] - lowest <= BALANCED_SPREAD) cls = "Perfectly Balanced";
	return { level, stage, cls };
}

function validate(body) {
	if (!body || typeof body !== "object" || Array.isArray(body)) return "the body must be a JSON object";
	if (Object.keys(body).sort().join() !== "badges,stats,v,xp,xp_days") return "unexpected or missing fields";
	if (body.v !== RULES) return "this version of cclevel is out of date, please update it";
	if (!isInt(body.xp, 0, 10000000) || !isInt(body.xp_days, 0, 100000)) return "xp is out of range";
	const stats = body.stats;
	if (!stats || typeof stats !== "object" || Array.isArray(stats)) return "stats are malformed";
	if (Object.keys(stats).sort().join() !== [...STATS].sort().join()) return "stats are malformed";
	if (!STATS.every((s) => isInt(stats[s], 0, 100) && stats[s] % STAT_STEP === 0)) return "a stat is out of range";
	const badges = body.badges;
	if (!Array.isArray(badges) || badges.length > Object.keys(BADGES).length) return "badges are malformed";
	if (!badges.every((b) => typeof b === "string" && Object.hasOwn(BADGES, b))) return "unknown badge";
	if (new Set(badges).size !== badges.length) return "badges are malformed";
	return null;
}

// What a client gets back: numbers and flags only, never a name.
const view = (row, accepted, season) => ({
	accepted,
	level: row.level,
	season_xp: row.season === season ? row.season_xp : 0,
	witnessed_xp: row.witnessed_xp,
	world: row.world === 1,
	listed: row.world === 1 && row.days_seen >= COUNTED_AFTER_DAYS,
	sus: isSus(row),
	verified: row.gh_id != null,
	commits: row.gh_id != null ? row.gh_commits || 0 : 0,
});

// A small JSON body, or the reply that refuses it.
async function readBody(request) {
	const length = request.headers.get("content-length");
	if (length === null || !/^\d+$/.test(length)) return { refused: json({ error: "a content length is required" }, 411) };
	if (Number(length) > MAX_BODY) return { refused: json({ error: "the body is too large" }, 413) };
	const text = await request.text();
	if (text.length > MAX_BODY) return { refused: json({ error: "the body is too large" }, 413) };
	try {
		return { body: JSON.parse(text) };
	} catch {
		return { refused: json({ error: "the body is not JSON" }, 400) };
	}
}

async function checkin(request, env) {
	const id = await entryId(request);
	if (!id) return json({ error: "missing or malformed token" }, 401);
	const { body, refused } = await readBody(request);
	if (refused) return refused;
	const problem = validate(body);
	if (problem) return json({ error: problem }, 400);

	const day = today();
	const season = day.slice(0, 7);
	if (body.xp > DAY_CAP * body.xp_days + badgeXp(body.badges) || body.xp_days > daysBetween(FIRST_RELEASE, day) + 1) {
		return json({ error: "this score is not possible under the rules" }, 422);
	}

	const prev = await env.DB.prepare("SELECT * FROM entries WHERE id = ?").bind(id).first();
	if (!prev) {
		// Spam control: five new creatures a minute per network, so friends on one wifi can join together. The address becomes a counter key that
		// Cloudflare holds for up to a minute. It is never written to the database and never logged.
		if (!env.NEW_ROWS) return json({ error: "the board is not taking new creatures right now" }, 503);
		const key = await sha256(network(request.headers.get("cf-connecting-ip") || ""));
		const { success } = await env.NEW_ROWS.limit({ key });
		if (!success) return json({ error: "too many new creatures from this network, try again in a minute", reason: "network" }, 429);
		const joined = await env.DB.prepare("SELECT joins FROM days WHERE day = ?").bind(day).first();
		if (joined && joined.joins >= NEW_ROWS_PER_DAY) {
			return json({ error: "the board is full for today, try again tomorrow", reason: "full_today" }, 429);
		}
		// Witnessed XP starts at zero: nothing claimed before joining ever ranks.
		const row = {
			name: creatureName(id), ...derive(body.xp, body.stats), season, season_xp: 0, days_seen: 1,
			witnessed_xp: 0, world: 0, xp_days: body.xp_days, base_days: body.xp_days, capped_days: 0, gh_id: null,
		};
		const inserted = await env.DB.prepare(
			`INSERT OR IGNORE INTO entries (id, name, xp, xp_days, base_days, level, stage, class,
				grind, appetite, arsenal, brains, autonomy, craft, badges, first_day, last_day, days_seen, season, season_xp, week, week_xp)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 0, ?, 0)`,
		)
			.bind(
				id, row.name, body.xp, body.xp_days, body.xp_days, row.level, row.stage, row.cls,
				...STATS.map((s) => body.stats[s]), JSON.stringify(body.badges), day, day, season, isoWeek(day),
			)
			.run();
		if (inserted.meta.changes > 0) {
			await env.DB.prepare("INSERT INTO days (day, joins) VALUES (?1, 1) ON CONFLICT (day) DO UPDATE SET joins = joins + 1")
				.bind(day)
				.run();
		}
		return json(view(row, true, season));
	}

	// One accepted check-in per day.
	if (daysBetween(prev.last_day, day) <= 0) return json(view(prev, false, season));
	if (body.xp < prev.xp || body.xp_days < prev.xp_days) {
		return json({ error: "the score went down" }, 422);
	}

	// Growth cap. Active days cannot grow faster than the calendar since the row was first seen,
	// and XP cannot grow by more than the daily cap per new active day, plus newly earned badges.
	// A larger claim is not refused: the board takes what the cap allows and catches up on later days.
	const had = JSON.parse(prev.badges);
	const badges = [...new Set([...had, ...body.badges])];
	const xpDays = Math.min(body.xp_days, prev.base_days + daysBetween(prev.first_day, day) + 1);
	const earnable = DAY_CAP * Math.max(0, xpDays - prev.xp_days);
	const newBadgeXp = badgeXp(badges.filter((b) => !had.includes(b)));
	const xp = Math.min(body.xp, prev.xp + earnable + newBadgeXp);
	// Witnessed and season XP count daily XP only: badge XP is taken out of the gain first, then the
	// daily cap applies. Days from an earlier month do not buy a place on the season either.
	const daily = Math.max(0, Math.min(xp - prev.xp - newBadgeXp, earnable));
	const seasonXp = Math.min((prev.season === season ? prev.season_xp : 0) + daily, DAY_CAP * Number(day.slice(8)));
	// The group's weekly crown: the same daily XP, starting again at zero each ISO week.
	const week = isoWeek(day);
	const weekXp = (prev.week === week ? prev.week_xp : 0) + daily;
	// Every new day counts as capped when the whole cap was taken: the sus rule counts days, not check-ins.
	const cappedDays = prev.capped_days + (earnable > 0 && daily === earnable ? xpDays - prev.xp_days : 0);
	const next = {
		...prev, ...derive(xp, body.stats), xp_days: xpDays, season, season_xp: seasonXp, days_seen: prev.days_seen + 1,
		witnessed_xp: prev.witnessed_xp + daily, capped_days: cappedDays,
	};
	await env.DB.prepare(
		`UPDATE entries SET xp = ?, xp_days = ?, level = ?, stage = ?, class = ?,
			grind = ?, appetite = ?, arsenal = ?, brains = ?, autonomy = ?, craft = ?,
			badges = ?, last_day = ?, days_seen = ?, season = ?, season_xp = ?, witnessed_xp = ?, capped_days = ?, week = ?, week_xp = ?
		WHERE id = ?`,
	)
		.bind(
			xp, xpDays, next.level, next.stage, next.cls, ...STATS.map((s) => body.stats[s]),
			JSON.stringify(badges), day, next.days_seen, season, seasonXp, next.witnessed_xp, cappedDays, week, weekXp, id,
		)
		.run();
	return json({ ...view(next, true, season), capped: xp < body.xp });
}

// Statements that cut one creature out of the stored lists, in the same request that asks for it.
// The ids files hold the listed row ids back to back, 64 characters each, in list order, so the
// creature's place is found and removed inside the database at a fixed cost however long the lists are.
function cut(env, id) {
	return ["all", "season"].flatMap((list) => {
		const at = `(SELECT instr(s.body, ?1) FROM snapshot s WHERE s.id = 'ids_${list}')`;
		const index = `((${at} - 1) / 64)`;
		return [
			env.DB.prepare(
				`UPDATE snapshot SET body = json_set(json_remove(body, '$.${list}.xp[' || ${index} || ']'),
					'$.${list}.ranked', json_extract(body, '$.${list}.ranked') - 1)
				WHERE id = 'board' AND ${at} % 64 = 1`,
			).bind(id),
			env.DB.prepare(`UPDATE snapshot SET body = json_remove(body, '$.${list}[' || ${index} || ']') WHERE id = 'top' AND ${at} % 64 = 1`)
				.bind(id),
			env.DB.prepare(`UPDATE snapshot SET body = replace(body, ?1, '') WHERE id = 'ids_${list}' AND instr(body, ?1) % 64 = 1`)
				.bind(id),
		];
	});
}

async function leave(request, env) {
	const id = await entryId(request);
	if (!id) return json({ error: "missing or malformed token" }, 401);
	const [, gone] = await env.DB.batch([
		spend(env, id),
		env.DB.prepare("DELETE FROM entries WHERE id = ?").bind(id),
		...cut(env, id),
	]);
	return json({ deleted: gone.meta.changes > 0 });
}

// The owner's choice to be on the world lists. Off by default; turning it off works at once and is never limited.
async function world(request, env) {
	const id = await entryId(request);
	if (!id) return json({ error: "missing or malformed token" }, 401);
	const { body, refused } = await readBody(request);
	if (refused) return refused;
	if (!body || typeof body !== "object" || Object.keys(body).join() !== "on" || typeof body.on !== "boolean") {
		return json({ error: "the body must be {\"on\": true} or {\"on\": false}" }, 400);
	}
	const day = today();
	if (body.on) {
		await env.DB.prepare(
			`UPDATE entries SET world = 1, opt_count = CASE WHEN opt_day = ?2 THEN opt_count + 1 ELSE 1 END, opt_day = ?2
			WHERE id = ?1 AND world = 0 AND (opt_day IS NOT ?2 OR opt_count < ?3)`,
		)
			.bind(id, day, OPT_INS_PER_DAY)
			.run();
	} else {
		await env.DB.batch([env.DB.prepare("UPDATE entries SET world = 0 WHERE id = ? AND world = 1").bind(id), ...cut(env, id)]);
	}
	const row = await env.DB.prepare("SELECT world, days_seen FROM entries WHERE id = ?").bind(id).first();
	if (!row) return json({ error: "no creature has this token" }, 404);
	if (body.on && row.world !== 1) {
		return refuse(429, "opt_ins", "the world ranking and group joins can be turned on three times a day together");
	}
	return json({ world: row.world === 1, listed: row.world === 1 && row.days_seen >= COUNTED_AFTER_DAYS });
}

// Private groups. A group is nothing but the SHA-256 of its code on each member's own row: it exists
// while someone points at it, and a member who leaves the board leaves the group with the row.
// The code travels only in the body of a join; reading a group takes the member's token and nothing else.
const refuse = (status, reason, error) => json({ error, reason }, status);

async function perCreature(env, id) {
	if (!env.PER_CREATURE) return refuse(503, "unavailable", "groups are not available right now");
	const { success } = await env.PER_CREATURE.limit({ key: id });
	return success ? null : refuse(429, "busy", "too many group requests, try again in a minute");
}

async function joinGroup(request, env) {
	const id = await entryId(request);
	if (!id) return json({ error: "missing or malformed token" }, 401);
	const { body, refused } = await readBody(request);
	if (refused) return refused;
	const keys = body && typeof body === "object" && !Array.isArray(body) ? Object.keys(body).sort().join() : "";
	const fresh = keys === "code,new" && body.new === true;
	if (!(keys === "code" || fresh) || typeof body.code !== "string" || !GROUP_CODE.test(body.code)) {
		return json({ error: "the body must be {\"code\": \"<32 hex>\"}, with \"new\": true to start a group" }, 400);
	}
	const busy = await perCreature(env, id);
	if (busy) return busy;
	const grp = await sha256(body.code);
	const day = today();
	// One statement, so two people joining at once cannot make a group of 26 or share a name.
	const done = await env.DB.prepare(
		`UPDATE entries SET grp = ?2, opt_count = CASE WHEN opt_day = ?3 THEN opt_count + 1 ELSE 1 END, opt_day = ?3
		WHERE id = ?1 AND grp IS NULL AND (opt_day IS NOT ?3 OR opt_count < ?4)
			AND (SELECT COUNT(*) FROM entries g WHERE g.grp = ?2) ${fresh ? "= 0" : "BETWEEN 1 AND ?5 - 1"}
			AND NOT EXISTS (SELECT 1 FROM entries g WHERE g.grp = ?2 AND g.name = entries.name)`,
	)
		.bind(id, grp, day, OPT_INS_PER_DAY, ...(fresh ? [] : [GROUP_MAX]))
		.run();
	const row = await env.DB.prepare("SELECT grp, opt_day, opt_count FROM entries WHERE id = ?").bind(id).first();
	if (!row) return refuse(404, "no_creature", "no creature has this token");
	const { n } = await env.DB.prepare("SELECT COUNT(*) AS n FROM entries WHERE grp = ?").bind(grp).first();
	if (done.meta.changes > 0 || row.grp === grp) return json({ joined: true, members: n });
	if (row.grp) return refuse(409, "in_group", "this creature is already in a group; leave it first");
	if (fresh && n > 0) return refuse(409, "taken", "a group with this code exists");
	if (!fresh && n === 0) return refuse(404, "no_group", "no group has this code");
	if (n >= GROUP_MAX) return refuse(409, "full", "this group is full");
	if (row.opt_day === day && row.opt_count >= OPT_INS_PER_DAY) {
		return refuse(429, "opt_ins", "the world ranking and group joins can be turned on three times a day together");
	}
	return refuse(409, "name_taken", "a member of this group has the same generated name");
}

async function leaveGroup(request, env) {
	const id = await entryId(request);
	if (!id) return json({ error: "missing or malformed token" }, 401);
	const done = await env.DB.prepare("UPDATE entries SET grp = NULL WHERE id = ? AND grp IS NOT NULL").bind(id).run();
	return json({ left: done.meta.changes > 0 });
}

// A member's view of the group: numbers and yes/no values only. Names travel as three numbers.
async function readGroup(request, env) {
	const id = await entryId(request);
	if (!id) return json({ error: "missing or malformed token" }, 401);
	const busy = await perCreature(env, id);
	if (busy) return busy;
	const month = today().slice(0, 7);
	const week = isoWeek(today());
	const { results } = await env.DB.prepare(
		`SELECT m.* FROM entries me JOIN entries m ON m.grp = me.grp
		WHERE me.id = ?1 AND me.grp IS NOT NULL ORDER BY m.witnessed_xp DESC, m.id`,
	)
		.bind(id)
		.all();
	if (!results.length) {
		const row = await env.DB.prepare("SELECT 1 AS ok FROM entries WHERE id = ?").bind(id).first();
		if (!row) return refuse(404, "no_creature", "no creature has this token");
	}
	return json({
		members: results.map((r) => ({
			name: nameKey(r.id),
			level: r.level,
			witnessed_xp: r.witnessed_xp,
			season_xp: r.season === month ? r.season_xp : 0,
			week_xp: r.week === week ? r.week_xp : 0,
			stats: STATS.map((s) => r[s]),
			sus: isSus(r),
			you: r.id === id,
		})),
	});
}

// GitHub "verified" badge. It proves that the owner of a creature controls a GitHub account, and shows how many
// public commits in that account carry Claude Code's co-author line. It never changes a place, XP or the sus mark.
// The board uses its own GitHub key with no permissions; the user's machine sends only a login and the hash of a code.
// The code ends up in a public gist, so it proves the account once only: its hash stays with the first creature that
// sent it for as long as that creature holds it, and a gist made before that creature started does not count.
async function github(env, path) {
	const res = await fetch(`https://api.github.com${path}`, {
		headers: {
			accept: "application/vnd.github+json",
			authorization: `Bearer ${env.GITHUB_TOKEN}`,
			"user-agent": "cclevel-board",
			"x-github-api-version": "2022-11-28",
		},
	});
	return { status: res.status, body: res.ok ? await res.json() : null };
}

// Public commits by this account that carry the line. Null when GitHub could not give a complete count.
async function claudeCommits(env, login) {
	const q = encodeURIComponent(`author:${login} is:public ${GH_CLAUDE_LINE}`);
	const { body } = await github(env, `/search/commits?q=${q}&per_page=1`);
	if (!body || body.incomplete_results !== false || !Number.isInteger(body.total_count)) return null;
	return body.total_count;
}

// Statements that take the login off the public file in the same request.
function githubCut(env, id) {
	return ["all", "season"].map((list) => {
		const at = `(SELECT instr(s.body, ?1) FROM snapshot s WHERE s.id = 'ids_${list}')`;
		return env.DB.prepare(
			`UPDATE snapshot SET body = json_remove(body, '$.${list}[' || ((${at} - 1) / 64) || '].github',
				'$.${list}[' || ((${at} - 1) / 64) || '].commits')
			WHERE id = 'top' AND ${at} % 64 = 1`,
		).bind(id);
	});
}
const GH_CLEARED = "gh_login = NULL, gh_id = NULL, gh_commits = NULL, gh_day = NULL, gh_code = NULL, gh_code_day = NULL";

// Whenever a creature lets go of a code, its hash goes on the spent list for two days, linked to no creature.
function spend(env, id) {
	return env.DB.prepare("INSERT OR IGNORE INTO spent (hash, day) SELECT gh_code, ?2 FROM entries WHERE id = ?1 AND gh_code IS NOT NULL")
		.bind(id, today());
}

// Step 1: the scanner sends a login and the SHA-256 of a code it made. Nothing is fetched yet.
async function githubStart(request, env) {
	const id = await entryId(request);
	if (!id) return json({ error: "missing or malformed token" }, 401);
	const { body, refused } = await readBody(request);
	if (refused) return refused;
	const ok = body && typeof body === "object" && !Array.isArray(body) && Object.keys(body).sort().join() === "code_hash,login";
	if (!ok || typeof body.login !== "string" || !GH_LOGIN.test(body.login) || typeof body.code_hash !== "string" || !/^[0-9a-f]{64}$/.test(body.code_hash)) {
		return json({ error: "the body must be {\"login\": \"<GitHub login>\", \"code_hash\": \"<64 hex>\"}" }, 400);
	}
	if (!env.GITHUB_TOKEN || !env.GITHUB_CALLS) return refuse(503, "unavailable", "the GitHub badge is not available on this board");
	const busy = await perCreature(env, id);
	if (busy) return busy;
	const day = today();
	const unused = `NOT EXISTS (SELECT 1 FROM entries g WHERE g.gh_code = ?3 AND g.id <> ?1)
		AND NOT EXISTS (SELECT 1 FROM spent WHERE hash = ?3)`;
	let done = [null, { meta: { changes: 0 } }];
	try {
		done = await env.DB.batch([
			// A fresh start replaces an unfinished one: the old code is spent, since its gist may already be public.
			env.DB.prepare(
				`INSERT OR IGNORE INTO spent (hash, day) SELECT gh_code, ?2 FROM entries
				WHERE id = ?1 AND gh_id IS NULL AND gh_code IS NOT NULL AND gh_code <> ?3 AND days_seen >= ?4`,
			).bind(id, day, body.code_hash, COUNTED_AFTER_DAYS),
			env.DB.prepare(
				`UPDATE entries SET gh_login = ?2, gh_code = ?3, gh_code_day = ?4,
					opt_count = CASE WHEN opt_day = ?4 THEN opt_count + 1 ELSE 1 END, opt_day = ?4
				WHERE id = ?1 AND gh_id IS NULL AND days_seen >= ?6 AND (opt_day IS NOT ?4 OR opt_count < ?5) AND ${unused}`,
			).bind(id, body.login, body.code_hash, day, OPT_INS_PER_DAY, COUNTED_AFTER_DAYS),
		]);
	} catch {
		// The unique index caught two creatures sending the same code at the same moment: refused below.
	}
	if (done[1].meta.changes > 0) return json({ pending: true });
	const row = await env.DB.prepare(
		`SELECT gh_id, days_seen, NOT (${unused.replaceAll("?3", "?2")}) AS taken FROM entries WHERE id = ?1`,
	)
		.bind(id, body.code_hash)
		.first();
	if (!row) return refuse(404, "no_creature", "no creature has this token");
	if (row.gh_id !== null) return refuse(409, "verified", "already verified; remove the badge first to use another account");
	if (row.days_seen < COUNTED_AFTER_DAYS) return refuse(409, "too_new", "the GitHub badge opens after check-ins on two days");
	if (row.taken) return refuse(409, "code_taken", "this code has been used; start again with a new one");
	return refuse(429, "opt_ins", "the world ranking, group joins and GitHub starts are limited to three a day together");
}

// Step 2: the board looks for the code in the named account's public gists.
async function githubCheck(request, env) {
	const id = await entryId(request);
	if (!id) return json({ error: "missing or malformed token" }, 401);
	if (!env.GITHUB_TOKEN || !env.GITHUB_CALLS) return refuse(503, "unavailable", "the GitHub badge is not available on this board");
	const busy = await perCreature(env, id);
	if (busy) return busy;
	const row = await env.DB.prepare("SELECT gh_login, gh_id, gh_commits, gh_code, gh_code_day FROM entries WHERE id = ?").bind(id).first();
	if (!row) return refuse(404, "no_creature", "no creature has this token");
	if (row.gh_id !== null) return json({ verified: true, commits: row.gh_commits || 0 });
	if (!row.gh_code) return refuse(409, "not_started", "start with a login and a code first");
	if (daysBetween(row.gh_code_day, today()) >= GH_CODE_DAYS) return refuse(410, "expired", "the code has expired; start again");
	// One budget for the whole board, so a few creatures cannot use up the key and turn the badge off for everyone.
	const { success } = await env.GITHUB_CALLS.limit({ key: "github" });
	if (!success) return refuse(429, "busy", "too many GitHub checks right now, try again in a minute");
	const { body: gists } = await github(env, `/users/${encodeURIComponent(row.gh_login)}/gists?per_page=30`);
	if (!Array.isArray(gists)) return refuse(502, "github", "GitHub did not answer");
	let owner = null;
	for (const gist of gists) {
		const login = gist && gist.owner && gist.owner.login;
		if (typeof login !== "string" || login.toLowerCase() !== row.gh_login.toLowerCase() || !Number.isInteger(gist.owner.id)) continue;
		if (gist.public !== true || typeof gist.description !== "string" || typeof gist.created_at !== "string") continue;
		if (gist.created_at.slice(0, 10) < row.gh_code_day) continue; // made before this creature started
		const match = /^\s*cclevel verify ([0-9a-f]{32})\s*$/.exec(gist.description);
		if (match && (await sha256(match[1])) === row.gh_code) {
			owner = gist.owner;
			break;
		}
	}
	if (!owner || !GH_LOGIN.test(owner.login)) return json({ verified: false });
	const commits = await claudeCommits(env, owner.login);
	// Only if nothing changed meanwhile: a removal or a fresh start during the lookup wins.
	const done = await env.DB.prepare(
		`UPDATE entries SET gh_login = ?2, gh_id = ?3, gh_commits = ?4, gh_day = ?5, gh_code_day = NULL
		WHERE id = ?1 AND gh_id IS NULL AND gh_code = ?6`,
	)
		.bind(id, owner.login, owner.id, commits || 0, today(), row.gh_code)
		.run();
	if (done.meta.changes === 0) return json({ verified: false });
	return json({ verified: true, commits: commits || 0 });
}

// Removes every GitHub field, and the login from the public file, in this request.
async function githubForget(request, env) {
	const id = await entryId(request);
	if (!id) return json({ error: "missing or malformed token" }, 401);
	const [, done] = await env.DB.batch([
		spend(env, id),
		env.DB.prepare(`UPDATE entries SET ${GH_CLEARED} WHERE id = ? AND (gh_login IS NOT NULL OR gh_code IS NOT NULL)`).bind(id),
		...githubCut(env, id),
	]);
	return json({ removed: done.meta.changes > 0 });
}

// A few verified accounts are recounted at each timed rebuild, oldest count first. The login is looked up by the
// account's number first, so a renamed account keeps its badge and a reused old name never inherits it.
// A deleted account loses its badge. A failed lookup still moves the account to the back of the queue.
// At most 2 GitHub calls per account: keep GH_REFRESH low enough for the plan's limit of calls per run.
async function refreshGithub(env) {
	if (!env.GITHUB_TOKEN) return;
	const { results } = await env.DB.prepare(
		"SELECT id, gh_id FROM entries WHERE gh_id IS NOT NULL ORDER BY gh_day LIMIT ?",
	)
		.bind(GH_REFRESH)
		.all();
	for (const r of results) {
		const found = await github(env, `/user/${r.gh_id}`);
		if (found.status === 404) {
			await env.DB.batch([
				spend(env, r.id),
				env.DB.prepare(`UPDATE entries SET ${GH_CLEARED} WHERE id = ? AND gh_id = ?`).bind(r.id, r.gh_id),
				...githubCut(env, r.id),
			]);
			continue;
		}
		const account = found.body;
		const ok = account && account.id === r.gh_id && typeof account.login === "string" && GH_LOGIN.test(account.login);
		const commits = ok ? await claudeCommits(env, account.login) : null;
		// Written only while the same account still holds the badge, so a removal during the lookup stays removed.
		await env.DB.prepare(
			`UPDATE entries SET gh_login = COALESCE(?2, gh_login), gh_commits = COALESCE(?3, gh_commits), gh_day = ?4
			WHERE id = ?1 AND gh_id = ?5`,
		)
			.bind(r.id, ok ? account.login : null, commits, today(), r.gh_id)
			.run();
	}
}

// Builds the stored board files. Runs on a timer, so a page view costs one row read.
// Sorting and counting happen in the database: the Worker only shapes about a thousand rows per list.
async function rebuild(env) {
	const day = today();
	const month = day.slice(0, 7);
	await env.DB.batch([
		env.DB.prepare("DELETE FROM entries WHERE last_day < ?1 OR (last_day < ?2 AND days_seen < ?3)")
			.bind(daysBefore(day, DELETED_AFTER_IDLE), daysBefore(day, ONE_DAY_ROWS_KEPT), COUNTED_AFTER_DAYS),
		env.DB.prepare("DELETE FROM days WHERE day < ?").bind(daysBefore(day, ONE_DAY_ROWS_KEPT)),
		env.DB.prepare("DELETE FROM spent WHERE day <= ?").bind(daysBefore(day, GH_CODE_DAYS)),
		// An unfinished GitHub verification, and the login it named, is kept only while its code is good.
		env.DB.prepare(
			`UPDATE entries SET gh_login = NULL, gh_code = NULL, gh_code_day = NULL
			WHERE gh_code IS NOT NULL AND gh_id IS NULL AND gh_code_day <= ?`,
		).bind(daysBefore(day, GH_CODE_DAYS)),
	]);

	const counted = "days_seen >= ?1 AND last_day >= ?2";
	const args = [COUNTED_AFTER_DAYS, daysBefore(day, HIDDEN_AFTER_IDLE)];
	// One pass per list returns the ranked rows plus the rows that sit exactly on a band cut-off.
	const ranked = (xp, where) =>
		`SELECT * FROM (
			SELECT id, name, level, stage, class, ${xp} AS xp, ${STATS.join(" + ")} AS power, ${SUS_SQL} AS sus,
				CASE WHEN gh_id IS NOT NULL THEN gh_login END AS github, gh_commits AS commits,
				ROW_NUMBER() OVER (ORDER BY ${xp} DESC, id) AS place, COUNT(*) OVER () AS ranked
			FROM entries WHERE ${counted} AND world = 1 ${where}
		) WHERE place <= ${LIST_SIZE} OR place IN (${BANDS.map((p) => `(ranked * ${p} + 99) / 100`).join(", ")})
		ORDER BY place`;
	const [all, season] = await env.DB.batch([
		env.DB.prepare(ranked("witnessed_xp", "")).bind(...args),
		env.DB.prepare(ranked("season_xp", "AND season = ?3 AND season_xp > 0")).bind(...args, month),
	]);
	const shape = ({ results }) => {
		const count = results.length ? results[0].ranked : 0;
		const at = (p) => results.find((r) => r.place === Math.floor((count * p + 99) / 100)).xp;
		return {
			rows: results.filter((r) => r.place <= LIST_SIZE),
			count,
			bands: count > LIST_SIZE ? BANDS.map((p) => [p, at(p)]) : null,
		};
	};
	const lists = { all: shape(all), season: shape(season) };
	const { creatures, totals } = await dailyTotals(env, day, counted, args);

	// Numbers only: this is all the scanner ever reads.
	const board = JSON.stringify({
		generated: day, month, rules: RULES, creatures,
		all: { ranked: lists.all.count, xp: lists.all.rows.map((r) => r.xp), bands: lists.all.bands },
		season: { ranked: lists.season.count, xp: lists.season.rows.map((r) => r.xp), bands: lists.season.bands },
		totals,
	});
	const entry = (r) => ({
		name: r.name, stage: r.stage, class: r.class, level: r.level, xp: r.xp, power: r.power, sus: r.sus === 1,
		...(r.github ? { github: r.github, commits: r.commits || 0 } : {}),
	});
	const top = JSON.stringify({ generated: day, month, all: lists.all.rows.map(entry), season: lists.season.rows.map(entry) });
	const save = (id, body) =>
		env.DB.prepare("INSERT INTO snapshot (id, body) VALUES (?1, ?2) ON CONFLICT (id) DO UPDATE SET body = ?2").bind(id, body);
	await env.DB.batch([
		save("board", board),
		save("top", top),
		save("ids_all", lists.all.rows.map((r) => r.id).join("")),
		save("ids_season", lists.season.rows.map((r) => r.id).join("")),
	]);
	return { board, top };
}

// Totals over every counted creature, listed or not. Worked out at the first rebuild of each UTC day.
async function dailyTotals(env, day, counted, args) {
	const stored = await env.DB.prepare("SELECT body FROM snapshot WHERE id = 'daily'").first();
	const kept = stored && JSON.parse(stored.body);
	if (kept && kept.day === day) return kept;

	const buckets = STATS.flatMap((s) => [...Array(10).keys()].map((k) => `SUM(MIN(${s} / 10, 9) = ${k}) AS ${s}_${k}`));
	const badges = Object.keys(BADGES).map((b) => `SUM(instr(badges, '"${b}"') > 0) AS badge_${b}`);
	const [byLevel, sums, bySeason] = await env.DB.batch([
		env.DB.prepare(`SELECT level, class, COUNT(*) AS n FROM entries WHERE ${counted} GROUP BY level, class`).bind(...args),
		env.DB.prepare(`SELECT COUNT(*) AS n, SUM(${SUS_SQL}) AS sus, ${[...buckets, ...badges].join(", ")} FROM entries WHERE ${counted}`)
			.bind(...args),
		// Class wars: the season XP the board credited, summed per class.
		env.DB.prepare(`SELECT class, SUM(season_xp) AS xp FROM entries WHERE ${counted} AND season = ?3 GROUP BY class`)
			.bind(...args, day.slice(0, 7)),
	]);
	const s = sums.results[0];
	const creatures = s.n;
	let totals = null;
	if (creatures >= MIN_ROWS_FOR_TOTALS) {
		const levels = Array(LEVEL_MAX + 1).fill(0);
		const classes = Object.fromEntries([...Object.values(CLASSES), "Perfectly Balanced", "Noob", "Unhatched"].map((c) => [c, 0]));
		const classXp = { ...classes };
		for (const r of bySeason.results) classXp[r.class] += r.xp || 0;
		const stages = Object.fromEntries(STAGES.map(([, name]) => [name, 0]).reverse());
		for (const r of byLevel.results) {
			levels[r.level] += r.n;
			classes[r.class] += r.n;
			stages[STAGES.find(([floor]) => r.level >= floor)[1]] += r.n;
		}
		totals = {
			levels, stages, classes, class_xp: classXp,
			stats: Object.fromEntries(STATS.map((st) => [st, [...Array(10).keys()].map((k) => s[`${st}_${k}`] || 0)])),
			badges: Object.fromEntries(Object.keys(BADGES).map((b) => [b, s[`badge_${b}`] || 0])),
			sus: s.sus || 0,
		};
	}
	const result = { day, creatures, totals };
	await env.DB.prepare("INSERT INTO snapshot (id, body) VALUES ('daily', ?1) ON CONFLICT (id) DO UPDATE SET body = ?1")
		.bind(JSON.stringify(result))
		.run();
	return result;
}

// The stored files. Each costs one row read; the first ever request builds them.
async function file(env, name) {
	const row = await env.DB.prepare("SELECT body FROM snapshot WHERE id = ?").bind(name).first();
	return new Response(row ? row.body : (await rebuild(env))[name], {
		headers: {
			"content-type": "application/json; charset=utf-8",
			"access-control-allow-origin": "*",
			"cache-control": "public, max-age=60",
		},
	});
}

export default {
	async fetch(request, env) {
		const { pathname } = new URL(request.url);
		try {
			if (pathname === "/api/checkin" && request.method === "POST") return await checkin(request, env);
			if (pathname === "/api/entry" && request.method === "DELETE") return await leave(request, env);
			if (pathname === "/api/world" && request.method === "PUT") return await world(request, env);
			if (pathname === "/api/group" && request.method === "POST") return await joinGroup(request, env);
			if (pathname === "/api/group" && request.method === "GET") return await readGroup(request, env);
			if (pathname === "/api/group" && request.method === "DELETE") return await leaveGroup(request, env);
			if (pathname === "/api/github" && request.method === "PUT") return await githubStart(request, env);
			if (pathname === "/api/github" && request.method === "POST") return await githubCheck(request, env);
			if (pathname === "/api/github" && request.method === "DELETE") return await githubForget(request, env);
			if (pathname === "/board.json" && request.method === "GET") return await file(env, "board");
			if (pathname === "/top.json" && request.method === "GET") return await file(env, "top");
			return json({ error: "not found" }, 404);
		} catch {
			return json({ error: "server error" }, 500); // nothing is logged, by design
		}
	},
	async scheduled(_controller, env, ctx) {
		ctx.waitUntil(refreshGithub(env).catch(() => {}).then(() => rebuild(env)));
	},
};
