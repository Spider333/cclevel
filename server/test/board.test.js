import { createExecutionContext, env, fetchMock, waitOnExecutionContext } from "cloudflare:test";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import schema from "../schema.sql?raw";
import worker from "../src/index.js";
import { ADJECTIVES as ADJ, ANIMALS as ANI } from "../src/names.js";
import source from "../src/index.js?raw";
import wrangler from "../wrangler.jsonc?raw";
import legacy from "../legacy/index.js";
import legacyWrangler from "../legacy/wrangler.jsonc?raw";

const TOKEN = "a".repeat(64);
const token = (n) => n.toString(16).padStart(64, "0");
const ALL_BADGES = [
	"first_hook", "first_skill", "first_subagent", "first_loop", "streak_7", "streak_30", "streak_100",
	"skills_10", "skills_50", "skills_100",
];

const score = (over = {}) => ({
	v: 1,
	xp: 1000,
	xp_days: 5,
	stats: { grind: 10, appetite: 20, arsenal: 30, brains: 60, autonomy: 5, craft: 15 },
	badges: ["first_skill"],
	...over,
});

// Each new creature comes from its own address, as real clients would.
let caller = 0;
const checkin = (body, bearer = TOKEN, ip = `10.0.${caller >> 8}.${caller++ & 255}`) => {
	const text = typeof body === "string" ? body : JSON.stringify(body);
	return worker.fetch(
		new Request("https://board.test/api/checkin", {
			method: "POST",
			headers: {
				...(bearer ? { authorization: `Bearer ${bearer}` } : {}),
				"cf-connecting-ip": ip,
				"content-length": String(new TextEncoder().encode(text).length),
			},
			body: text,
		}),
		env,
	);
};
const leave = (bearer = TOKEN) =>
	worker.fetch(
		new Request("https://board.test/api/entry", { method: "DELETE", headers: { authorization: `Bearer ${bearer}` } }),
		env,
	);
const setWorld = (on, bearer = TOKEN) => {
	const text = typeof on === "string" ? on : JSON.stringify({ on });
	return worker.fetch(
		new Request("https://board.test/api/world", {
			method: "PUT",
			headers: { authorization: `Bearer ${bearer}`, "content-length": String(text.length) },
			body: text,
		}),
		env,
	);
};
const group = (method, body, bearer = TOKEN, path = "/api/group") => {
	const text = body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body);
	return worker.fetch(
		new Request(`https://board.test${path}`, {
			method,
			headers: { authorization: `Bearer ${bearer}`, ...(text === undefined ? {} : { "content-length": String(text.length) }) },
			body: text,
		}),
		env,
	);
};
const CODE = "0123456789abcdef0123456789abcdef";
const OTHER = "fedcba9876543210fedcba9876543210";
const get = (path) => worker.fetch(new Request(`https://board.test${path}`), env).then((r) => r.json());
const files = async () => ({ board: await get("/board.json"), top: await get("/top.json") });
const rebuild = async () => {
	const ctx = createExecutionContext();
	await worker.scheduled({}, env, ctx);
	await waitOnExecutionContext(ctx);
	return get("/board.json");
};
// Two check-ins on two days and the world ranking on: listed at the next rebuild.
const listed = async (bearer, firstXp = 1000, secondXp = 1400) => {
	goTo("2026-10-13");
	await checkin(score({ xp: firstXp }), bearer);
	goTo("2026-10-14");
	await checkin(score({ xp: secondXp, xp_days: 6 }), bearer);
	await setWorld(true, bearer);
};
// Rows straight into the table, for crowds too large to build through check-ins.
const crowd = (n, { world = 1, day = "2026-10-14", from = 1 } = {}) =>
	env.DB.prepare(
		`WITH RECURSIVE k(i) AS (SELECT ?1 UNION ALL SELECT i + 1 FROM k WHERE i < ?1 + ?2 - 1)
		INSERT INTO entries (id, name, xp, xp_days, base_days, level, stage, class, grind, appetite, arsenal, brains, autonomy, craft,
			badges, first_day, last_day, days_seen, season, season_xp, witnessed_xp, capped_days, world)
		SELECT printf('%064x', i), 'Crowd Row ' || i, 1000, 20, 5, 5, 'Hatchling', 'Loot Goblin', 10, 20, 30, 60, 5, 15,
			'["first_skill"]', '2026-10-01', ?3, 2, substr(?3, 1, 7), i * 10, i * 10, CASE WHEN i % 10 = 0 THEN 15 ELSE 0 END, ?4
		FROM k`,
	)
		.bind(from, n, day, world)
		.run();
const row = (bearer = TOKEN) =>
	sha256(bearer).then((id) => env.DB.prepare("SELECT * FROM entries WHERE id = ?").bind(id).first());
const goTo = (day) => vi.setSystemTime(new Date(`${day}T12:00:00Z`));

async function sha256(text) {
	const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
	return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

beforeAll(async () => {
	const statements = schema.replace(/--.*$/gm, "").split(";").map((s) => s.trim()).filter(Boolean);
	for (const statement of statements) await env.DB.prepare(statement).run();
});
beforeEach(() => {
	vi.useFakeTimers({ toFake: ["Date"] });
	goTo("2026-10-13");
});
afterEach(() => vi.useRealTimers());

describe("check-in validation", () => {
	it("refuses requests without a well-formed token", async () => {
		expect((await checkin(score(), null)).status).toBe(401);
		expect((await checkin(score(), "abc")).status).toBe(401);
		expect((await checkin(score(), "A".repeat(64))).status).toBe(401);
	});

	it("refuses malformed, oversized and impossible bodies", async () => {
		expect((await checkin("not json")).status).toBe(400);
		expect((await checkin([1, 2])).status).toBe(400);
		expect((await checkin(score({ extra: "x" }))).status).toBe(400);
		expect((await checkin(score({ world: true }))).status).toBe(400);
		expect((await checkin(score({ v: 2 }))).status).toBe(400);
		expect((await checkin(score({ xp: "1000" }))).status).toBe(400);
		expect((await checkin(score({ stats: { ...score().stats, grind: 105 } }))).status).toBe(400);
		expect((await checkin(score({ stats: { ...score().stats, grind: 12 } }))).status).toBe(400);
		expect((await checkin(score({ stats: { ...score().stats, age: 10 } }))).status).toBe(400);
		expect((await checkin(score({ badges: ["made_up"] }))).status).toBe(400);
		expect((await checkin(score({ badges: ["first_skill", "first_skill"] }))).status).toBe(400);
		expect((await checkin(`{"pad":"${"x".repeat(3000)}"}`)).status).toBe(413);
		expect((await checkin(score({ xp: 999999 }))).status).toBe(422);
		expect((await checkin(score({ xp: 0, xp_days: 99999 }))).status).toBe(422);
		expect(await row()).toBeNull();
	});

	it("refuses a body that does not say how long it is", async () => {
		const res = await worker.fetch(
			new Request("https://board.test/api/checkin", {
				method: "POST",
				headers: { authorization: `Bearer ${TOKEN}` },
				body: JSON.stringify(score()),
			}),
			env,
		);
		expect(res.status).toBe(411);
		const odd = await worker.fetch(
			new Request("https://board.test/api/checkin", {
				method: "POST",
				headers: { authorization: `Bearer ${TOKEN}`, "content-length": "abc" },
				body: JSON.stringify(score()),
			}),
			env,
		);
		expect(odd.status).toBe(411);
	});
});

describe("joining", () => {
	it("stores a hash of the token, never the token, and nothing about the caller", async () => {
		const res = await checkin(score(), TOKEN, "203.0.113.77");
		expect(res.status).toBe(200);
		const reply = await res.json();
		// The reply carries numbers and flags only. Names stay on the board.
		expect(reply).toEqual({
			accepted: true, level: 5, season_xp: 0, witnessed_xp: 0, world: false, listed: false, sus: false, verified: false, commits: 0,
		});

		const stored = await row();
		expect(stored).toMatchObject({ stage: "Hatchling", class: "Loot Goblin" });
		expect(stored.name).toMatch(/^[A-Z][a-z]+ [A-Z][a-z]+ \d{4}$/);
		expect(stored.id).toBe(await sha256(TOKEN));
		const tables = (await env.DB.prepare("SELECT name FROM sqlite_master WHERE type = 'table'").all()).results;
		for (const { name } of tables.filter((t) => !t.name.startsWith("_"))) {
			const everything = JSON.stringify((await env.DB.prepare(`SELECT * FROM ${name}`).all()).results);
			expect(everything).not.toContain(TOKEN);
			expect(everything).not.toContain("203.0.113");
			const columns = (await env.DB.prepare(`PRAGMA table_info(${name})`).all()).results.map((c) => c.name);
			expect(columns.filter((c) => /ip|agent|token|mail/i.test(c))).toEqual([]);
		}
		expect(stored.first_day).toBe("2026-10-13");
	});

	it("lets one network add five creatures a minute, counting an IPv6 /64 as one network", async () => {
		expect(env.NEW_ROWS).toBeDefined();
		const from = (ip, n) => checkin(score(), token(n), ip).then((r) => r.status);
		for (let n = 500; n < 505; n++) expect(await from("198.51.100.9", n)).toBe(200);
		const sixth = await checkin(score(), token(505), "198.51.100.9");
		expect(sixth.status).toBe(429);
		expect((await sixth.json()).reason).toBe("network");
		for (let n = 510; n < 515; n++) expect(await from("2001:db8:1:2::" + (n - 509), n)).toBe(200);
		expect(await from("2001:db8:1:2:aaaa:bbbb:cccc:dddd", 515)).toBe(429);
		expect(await from("2001:db8:1:3::1", 516)).toBe(200);
	});

	it("refuses new creatures when spam control is not wired up", async () => {
		const res = await worker.fetch(
			new Request("https://board.test/api/checkin", {
				method: "POST",
				headers: { authorization: `Bearer ${token(600)}`, "content-length": "2" },
				body: JSON.stringify(score()),
			}),
			{ DB: env.DB },
		);
		expect(res.status).toBe(503);
		expect(await row(token(600))).toBeNull();
	});

	it("stops taking new creatures at the daily ceiling and keeps serving existing ones", async () => {
		await checkin(score());
		await env.DB.prepare("UPDATE days SET joins = 5000 WHERE day = '2026-10-13'").run();
		const refused = await checkin(score(), token(700));
		expect(refused.status).toBe(429);
		expect((await refused.json()).reason).toBe("full_today");
		expect((await checkin(score())).status).toBe(200);
		goTo("2026-10-14");
		expect((await checkin(score(), token(701))).status).toBe(200);
	});

	it("treats a repeated first check-in as one creature", async () => {
		const replies = await Promise.all([1, 2, 3].map(() => checkin(score(), token(800), "192.0.2.50")));
		expect(replies.map((r) => r.status).filter((s) => s === 500)).toEqual([]);
		const { n } = await env.DB.prepare("SELECT COUNT(*) AS n FROM entries").first();
		expect(n).toBe(1);
	});
});

describe("growth rules", () => {
	it("accepts one check-in per day", async () => {
		await checkin(score());
		const res = await checkin(score({ xp: 1500, xp_days: 6 }));
		expect((await res.json()).accepted).toBe(false);
		expect((await row()).xp).toBe(1000);
	});

	it("caps growth at 550 XP per new active day", async () => {
		await checkin(score());
		goTo("2026-10-14");
		// One day has passed. The calendar allows one new active day, plus one day of time-zone slack, once.
		const res = await checkin(score({ xp: 11000, xp_days: 30 }));
		expect(await res.json()).toMatchObject({ accepted: true, capped: true, season_xp: 1100, witnessed_xp: 1100 });
		expect(await row()).toMatchObject({ xp: 2100, xp_days: 7, days_seen: 2 });

		// The slack is not granted again. A new badge raises XP but not the season.
		goTo("2026-10-15");
		const again = await checkin(score({ xp: 11000, xp_days: 30, badges: ["first_skill", "first_loop"] }));
		expect(await again.json()).toMatchObject({ accepted: true, capped: true, season_xp: 1650, witnessed_xp: 1650 });
		expect(await row()).toMatchObject({ xp: 3150, xp_days: 8 });
	});

	it("credits an honest day in full", async () => {
		await checkin(score());
		goTo("2026-10-14");
		const res = await checkin(score({ xp: 1420, xp_days: 6 }));
		expect(await res.json()).toMatchObject({ accepted: true, capped: false, season_xp: 420, witnessed_xp: 420, listed: false });
	});

	it("refuses a score that went down", async () => {
		await checkin(score());
		goTo("2026-10-14");
		expect((await checkin(score({ xp: 900 }))).status).toBe(422);
		expect((await row()).xp).toBe(1000);
	});

	it("keeps badges held back at joining out of the season", async () => {
		await checkin(score({ badges: [] }));
		goTo("2026-10-14");
		const res = await checkin(score({ xp: 11200, xp_days: 6, badges: ALL_BADGES }));
		expect(await res.json()).toMatchObject({ accepted: true, capped: false, season_xp: 550, witnessed_xp: 550 });
		expect((await row()).xp).toBe(11200);
	});

	it("adds only the daily part of an honest badge day to the season", async () => {
		await checkin(score());
		goTo("2026-10-14");
		const res = await checkin(score({ xp: 2100, xp_days: 6, badges: ["first_skill", "streak_30"] }));
		expect(await res.json()).toMatchObject({ accepted: true, capped: false, season_xp: 100, witnessed_xp: 100 });
		expect((await row()).xp).toBe(2100);
	});

	it("never lets the season grow by more than the gain without badges, whatever is claimed", async () => {
		const BADGE_XP = { first_hook: 250, first_skill: 250, first_subagent: 250, first_loop: 500, streak_7: 200, streak_30: 1000, streak_100: 3000, skills_10: 200, skills_50: 1000, skills_100: 3000 };
		let seed = 7;
		const rand = (n) => (seed = (seed * 1103515245 + 12345) % 2147483648) % n;
		let badges = [];
		let claim = { xp: 0, xp_days: 0 };
		await checkin(score({ ...claim, badges }));
		let before = await row();
		for (let step = 1; step <= 120; step++) {
			const date = new Date(Date.UTC(2026, 9, 13 + step));
			goTo(date.toISOString().slice(0, 10));
			const fresh = ALL_BADGES.filter((b) => !badges.includes(b) && rand(8) === 0);
			badges = [...badges, ...fresh];
			claim = { xp: claim.xp + rand(3) * rand(700) + fresh.reduce((n, b) => n + BADGE_XP[b], 0), xp_days: claim.xp_days + rand(3) };
			const res = await checkin(score({ ...claim, badges }));
			if (res.status !== 200) {
				claim = { xp: before.xp, xp_days: before.xp_days };
				continue;
			}
			const after = await row();
			const badgeGain = JSON.parse(after.badges).filter((b) => !JSON.parse(before.badges).includes(b)).reduce((n, b) => n + BADGE_XP[b], 0);
			const seasonGain = after.season === before.season ? after.season_xp - before.season_xp : after.season_xp;
			expect(seasonGain).toBeLessThanOrEqual(Math.max(0, after.xp - before.xp - badgeGain));
			expect(after.witnessed_xp - before.witnessed_xp).toBeLessThanOrEqual(550 * (after.xp_days - before.xp_days));
			expect(after.witnessed_xp - before.witnessed_xp).toBeLessThanOrEqual(Math.max(0, after.xp - before.xp - badgeGain));
			expect(after.capped_days).toBeLessThanOrEqual(after.xp_days - after.base_days);
			expect(after.xp - before.xp).toBeLessThanOrEqual(550 * (after.xp_days - before.xp_days) + badgeGain);
			expect(after.season_xp).toBeLessThanOrEqual(550 * date.getUTCDate());
			before = after;
		}
	});

	it("starts a new season at zero and does not carry last month into it", async () => {
		goTo("2026-10-02");
		await checkin(score());
		goTo("2026-11-01");
		const res = await checkin(score({ xp: 16000, xp_days: 34 }));
		expect(await res.json()).toMatchObject({ accepted: true, season_xp: 550 });
		expect(await row()).toMatchObject({ xp: 16000, season: "2026-11" });
	});

	it("keeps a week's XP for the group crown and starts it again each ISO week, in the same write", async () => {
		goTo("2026-10-17"); // a Saturday
		await checkin(score());
		expect(await row()).toMatchObject({ week: "2026-W42", week_xp: 0 });
		goTo("2026-10-18"); // Sunday: same week
		await checkin(score({ xp: 1400, xp_days: 6 }));
		expect(await row()).toMatchObject({ week: "2026-W42", week_xp: 400 });
		goTo("2026-10-19"); // Monday: a new week starts from that day's credit only
		await checkin(score({ xp: 1700, xp_days: 7 }));
		expect(await row()).toMatchObject({ week: "2026-W43", week_xp: 300, season_xp: 700, witnessed_xp: 700 });
	});

	it("numbers weeks the ISO way across the turn of the year", async () => {
		const cases = [["2026-01-01", "2026-W01"], ["2025-12-29", "2026-W01"], ["2027-01-01", "2026-W53"], ["2027-01-04", "2027-W01"]];
		for (const [i, [day, week]] of cases.entries()) {
			goTo(day);
			await checkin(score(), token(900 + i));
			expect((await row(token(900 + i))).week).toBe(week);
		}
	});

	it("witnesses nothing at joining, whatever history is reported", async () => {
		const res = await checkin(score({ xp: 300000, xp_days: 590, badges: ALL_BADGES }));
		expect(await res.json()).toMatchObject({ accepted: true, level: 86, witnessed_xp: 0, season_xp: 0 });
		goTo("2026-10-14");
		const next = await checkin(score({ xp: 330000, xp_days: 595, badges: ALL_BADGES }));
		expect(await next.json()).toMatchObject({ witnessed_xp: 1100, capped: true });
	});
});

describe("stage and class", () => {
	// The same cases are asserted for the scanner in tests/test_cclevel.py.
	const cases = [
		[{ appetite: 20, arsenal: 30, autonomy: 5, craft: 15 }, 1000, "Hatchling", "Loot Goblin"],
		[{ appetite: 80, arsenal: 40, autonomy: 30, craft: 20 }, 0, "Egg", "Tokenmaxxer"],
		[{ appetite: 40, arsenal: 40, autonomy: 30, craft: 90 }, 9000, "Lil Guy", "Shipper"],
		[{ appetite: 10, arsenal: 20, autonomy: 70, craft: 30 }, 36000, "Big Guy", "AFK Farmer"],
		[{ appetite: 60, arsenal: 65, autonomy: 60, craft: 70 }, 81000, "Gigachad", "Perfectly Balanced"],
		[{ appetite: 60, arsenal: 65, autonomy: 55, craft: 70 }, 144000, "GOAT", "Shipper"],
		[{ appetite: 30, arsenal: 25, autonomy: 25, craft: 25 }, 0, "Egg", "Tokenmaxxer"],
		[{ appetite: 25, arsenal: 25, autonomy: 25, craft: 25 }, 0, "Egg", "Noob"],
		[{ appetite: 5, arsenal: 0, autonomy: 5, craft: 5 }, 0, "Egg", "Noob"],
		[{ appetite: 0, arsenal: 0, autonomy: 0, craft: 0 }, 0, "Egg", "Unhatched"],
	];
	it("names them the way the scanner does, whatever Grind and Brains say", async () => {
		let n = 3000;
		for (const [shape, xp, stage, cls] of cases) {
			for (const [grind, brains] of [[0, 0], [100, 100]]) {
				const bearer = token(n++);
				await checkin(score({ xp, xp_days: 500, stats: { grind, brains, ...shape }, badges: [] }), bearer);
				expect(await row(bearer)).toMatchObject({ stage, class: cls });
			}
		}
	});
});

describe("the world ranking", () => {
	it("is off for a new creature until its owner turns it on", async () => {
		goTo("2026-10-13");
		await checkin(score());
		goTo("2026-10-14");
		expect(await (await checkin(score({ xp: 1400, xp_days: 6 }))).json()).toMatchObject({ world: false, listed: false });
		let board = await rebuild();
		expect(board.all).toMatchObject({ ranked: 0, xp: [] });
		expect((await get("/top.json")).all).toEqual([]);

		expect(await (await setWorld(true)).json()).toEqual({ world: true, listed: true });
		board = await rebuild();
		expect(board.all).toMatchObject({ ranked: 1, xp: [400] });
		expect(board.season).toMatchObject({ ranked: 1, xp: [400] });
		expect((await get("/top.json")).all).toEqual([
			{ name: (await row()).name, stage: "Hatchling", class: "Loot Goblin", level: 5, xp: 400, power: 140, sus: false },
		]);
	});

	it("lists a creature only after check-ins on two different days", async () => {
		await checkin(score());
		expect(await (await setWorld(true)).json()).toEqual({ world: true, listed: false });
		expect((await rebuild()).all.ranked).toBe(0);
		goTo("2026-10-14");
		expect(await (await checkin(score({ xp: 1400, xp_days: 6 }))).json()).toMatchObject({ world: true, listed: true });
		expect((await rebuild()).all.xp).toEqual([400]);
	});

	it("takes a creature off both lists in the request that turns it off, and nobody else", async () => {
		await listed(token(1), 1000, 1500);
		await listed(token(2), 1000, 1200);
		await listed(token(3), 1000, 1300);
		await rebuild();
		const before = await files();
		expect(before.board.all.xp).toEqual([500, 300, 200]);
		const second = (await row(token(3))).name;
		expect(before.top.season.map((r) => r.name)).toContain(second);

		expect(await (await setWorld(false, token(3))).json()).toEqual({ world: false, listed: false });
		const after = await files();
		expect(after.board.all).toMatchObject({ ranked: 2, xp: [500, 200] });
		expect(after.board.season).toMatchObject({ ranked: 2, xp: [500, 200] });
		expect(after.top.all.map((r) => r.xp)).toEqual([500, 200]);
		expect(after.top.season.map((r) => r.name)).not.toContain(second);
		expect(after.top.all.map((r) => r.name)).toEqual([(await row(token(1))).name, (await row(token(2))).name]);
		// Turning it off again, or for a creature that is not listed, changes nothing.
		expect((await setWorld(false, token(3))).status).toBe(200);
		expect(await files()).toEqual(after);
		expect((await rebuild()).all.xp).toEqual([500, 200]);
	});

	it("can be turned on three times a UTC day; turning it off is never limited", async () => {
		await checkin(score());
		for (let n = 1; n <= 3; n++) {
			expect((await setWorld(true)).status).toBe(200);
			expect((await setWorld(true)).status).toBe(200); // already on: not a new opt-in
			expect((await setWorld(false)).status).toBe(200);
		}
		expect((await setWorld(true)).status).toBe(429);
		expect((await row()).world).toBe(0);
		for (let n = 0; n < 5; n++) expect((await setWorld(false)).status).toBe(200);
		goTo("2026-10-14");
		expect(await (await setWorld(true)).json()).toMatchObject({ world: true });
	});

	it("takes only an exact on or off, from a creature that exists", async () => {
		await checkin(score());
		for (const body of ['{"on":"yes"}', '{"on":true,"group":"x"}', "[true]", "null", "{}", "nope"]) {
			expect((await setWorld(body)).status).toBe(400);
		}
		expect((await row()).world).toBe(0);
		expect((await setWorld(true, token(9))).status).toBe(404);
		expect((await setWorld(true, "abc")).status).toBe(401);
		expect(await row(token(9))).toBeNull();
	});
});

describe("the lists", () => {
	it("rank by XP the board witnessed, never by reported XP or level", async () => {
		goTo("2026-10-13");
		await checkin(score({ xp: 300000, xp_days: 590 }), token(1)); // a big claimed history
		await checkin(score({ xp: 0, xp_days: 0 }), token(2));
		goTo("2026-10-14");
		await checkin(score({ xp: 300100, xp_days: 591 }), token(1));
		await checkin(score({ xp: 550, xp_days: 1 }), token(2));
		await setWorld(true, token(1));
		await setWorld(true, token(2));
		await rebuild();
		const { board, top } = await files();
		expect(board.all.xp).toEqual([550, 100]);
		expect(top.all.map((r) => r.level)).toEqual([3, 86]);
	});

	it("hold at most 1,000 rows each and publish band cut-offs past that", async () => {
		await crowd(999);
		let board = await rebuild();
		expect(board.all).toMatchObject({ ranked: 999, bands: null });
		await crowd(206, { from: 1000 });
		board = await rebuild();
		const top = await get("/top.json");
		expect(board.all.ranked).toBe(1205);
		expect(board.all.xp).toHaveLength(1000);
		expect(top.all).toHaveLength(1000);
		expect(board.all.xp[0]).toBe(12050);
		expect(board.all.xp[999]).toBe(2060);
		expect(board.all.xp).toEqual([...board.all.xp].sort((a, b) => b - a));
		expect(top.all.map((r) => r.xp)).toEqual(board.all.xp);
		expect(board.all.bands.map(([p]) => p)).toEqual([1, 2, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]);
		// Top 1% of 1,205 is the first 13 rows; top 100% reaches the last one.
		expect(board.all.bands[0]).toEqual([1, 12050 - 12 * 10]);
		expect(board.all.bands[12]).toEqual([100, 10]);
		expect(board.season).toMatchObject({ ranked: 1205 });
		expect(board.season.xp).toHaveLength(1000);
	});

	it("put equal XP next to each other and leave the creatures that are not listed out", async () => {
		await crowd(30);
		await crowd(5, { from: 31, world: 0 });
		await env.DB.prepare("UPDATE entries SET witnessed_xp = 777 WHERE id IN (printf('%064x', 3), printf('%064x', 7))").run();
		const board = await rebuild();
		expect(board.all.ranked).toBe(30);
		expect(board.all.xp.filter((x) => x === 777)).toHaveLength(2);
		expect(board.all.xp).toEqual([...board.all.xp].sort((a, b) => b - a));
	});
});

describe("the sus mark", () => {
	const daily = async (bearer, days, perDay) => {
		goTo("2026-10-01");
		await checkin(score({ xp: 0, xp_days: 0, badges: [] }), bearer);
		for (let d = 1; d <= days; d++) {
			goTo(`2026-10-${String(1 + d).padStart(2, "0")}`);
			const res = await checkin(score({ xp: perDay * d, xp_days: d, badges: [] }), bearer);
			if (d === 1) await setWorld(true, bearer);
			if (d === days) return res.json();
		}
	};

	it("marks 14 witnessed days or more with at least 80% of them at the full 550", async () => {
		expect((await daily(token(1), 13, 550)).sus).toBe(false);
		expect((await daily(token(2), 14, 550)).sus).toBe(true);
		expect((await daily(token(3), 20, 549)).sus).toBe(false); // a script claiming 549 is not caught, as the page says
		expect(await row(token(2))).toMatchObject({ capped_days: 14, witnessed_xp: 7700 });
	});

	it("counts days, so a weekly check-in at the full cap is marked after two weeks", async () => {
		goTo("2026-10-01");
		await checkin(score({ xp: 0, xp_days: 0, badges: [] }));
		goTo("2026-10-08");
		expect(await (await checkin(score({ xp: 3850, xp_days: 7, badges: [] }))).json()).toMatchObject({ sus: false, witnessed_xp: 3850 });
		goTo("2026-10-15");
		expect(await (await checkin(score({ xp: 7700, xp_days: 14, badges: [] }))).json()).toMatchObject({ sus: true });
		expect((await row()).capped_days).toBe(14);
	});

	it("changes nothing but the mark: XP, place and listing stay as they are", async () => {
		await daily(token(1), 15, 550);
		await daily(token(2), 15, 400);
		goTo("2026-10-16");
		await rebuild();
		const { board, top } = await files();
		expect(board.all.xp).toEqual([8250, 6000]);
		expect(top.all.map((r) => r.sus)).toEqual([true, false]);
		expect(await row(token(1))).toMatchObject({ witnessed_xp: 8250, world: 1 });
	});
});

describe("totals", () => {
	it("are published only from 100 counted creatures, listed or not, with the sus count", async () => {
		await crowd(60);
		await crowd(39, { from: 61, world: 0 });
		let board = await rebuild();
		expect(board.creatures).toBe(99);
		expect(board.totals).toBeNull();

		await crowd(1, { from: 100, world: 0 });
		goTo("2026-10-15"); // totals are worked out once a day
		board = await rebuild();
		expect(board.creatures).toBe(100);
		expect(board.all.ranked).toBe(60);
		const { totals } = board;
		expect(totals.levels).toHaveLength(100);
		expect(totals.levels[5]).toBe(100);
		expect(totals.stages).toEqual({ Egg: 0, Hatchling: 100, "Lil Guy": 0, "Big Guy": 0, Gigachad: 0, "GOAT": 0 });
		expect(totals.classes["Loot Goblin"]).toBe(100);
		expect(totals.stats.brains).toEqual([0, 0, 0, 0, 0, 0, 100, 0, 0, 0]);
		expect(totals.badges).toMatchObject({ first_skill: 100, first_hook: 0 });
		expect(totals.sus).toBe(10);
		// Class wars: this season's credited XP per class (rows 1..100 hold 10, 20 … 1,000).
		expect(totals.class_xp).toEqual({
			Shipper: 0, "AFK Farmer": 0, "Loot Goblin": 50500, Tokenmaxxer: 0, "Perfectly Balanced": 0, Noob: 0, Unhatched: 0,
		});
	});

	it("count only this season's XP in the class wars", async () => {
		await crowd(100);
		await crowd(5, { from: 101, day: "2026-09-29" }); // counted until idle, but their XP belongs to September
		goTo("2026-10-15");
		const { totals } = await rebuild();
		expect(totals.classes["Loot Goblin"]).toBe(105);
		expect(totals.class_xp["Loot Goblin"]).toBe(50500);
	});

	it("leave only numbers in board.json, apart from a date and a month", async () => {
		await crowd(1205);
		await listed(token(1));
		goTo("2026-10-15");
		const board = await rebuild();
		expect(board.totals).not.toBeNull();
		expect(board.all.bands).not.toBeNull();
		const strings = [];
		const walk = (v) => {
			if (typeof v === "string") strings.push(v);
			else if (v && typeof v === "object") Object.values(v).forEach(walk);
			else expect(["number", "boolean"]).toContain(typeof v === "object" ? "number" : typeof v);
		};
		walk(board);
		expect(strings).toEqual(["2026-10-15", "2026-10"]);
		expect(JSON.stringify(board)).not.toContain("Crowd Row");
	});
});

describe("leaving", () => {
	it("takes a listed creature off both lists at once", async () => {
		await listed(TOKEN);
		await listed(token(2), 1000, 1100);
		await rebuild();
		expect((await files()).top.all).toHaveLength(2);
		await leave();
		const { board, top } = await files();
		expect(board.all.xp).toEqual([100]);
		expect(board.season.xp).toEqual([100]);
		expect(top.all).toHaveLength(1);
		expect(top.all[0].name).toBe((await row(token(2))).name);
	});

	it("deletes the row and nobody else's", async () => {
		await checkin(score());
		await checkin(score(), token(2));
		expect(await (await leave()).json()).toEqual({ deleted: true });
		expect(await row()).toBeNull();
		expect(await row(token(2))).not.toBeNull();
		expect(await (await leave()).json()).toEqual({ deleted: false });
		expect(await (await leave(await sha256(token(2)))).json()).toEqual({ deleted: false });
		expect(await row(token(2))).not.toBeNull();
	});
});

describe("upkeep", () => {
	it("drops one-day creatures after a week, hides idle ones and later deletes them", async () => {
		await checkin(score());
		await checkin(score(), token(3));
		goTo("2026-10-14");
		await checkin(score({ xp: 1100, xp_days: 6 }));
		goTo("2026-10-19");
		await rebuild();
		expect(await row(token(3))).not.toBeNull();
		goTo("2026-10-22");
		await rebuild();
		expect(await row(token(3))).toBeNull();
		expect(await row()).not.toBeNull();

		goTo("2026-12-05");
		expect((await rebuild()).creatures).toBe(0);
		expect(await row()).not.toBeNull();
		goTo("2027-05-01");
		await rebuild();
		expect(await row()).toBeNull();
	});
});

describe("private groups", () => {
	// The per-creature limiter counts in real time across tests, so each test uses creatures of its own.
	let next = 20000;
	let token = (n) => n.toString(16).padStart(64, "0");
	let TOKEN;
	beforeEach(() => {
		const base = next;
		next += 100;
		token = (n) => (base + n).toString(16).padStart(64, "0");
		TOKEN = token(0);
	});
	const row = (bearer) => sha256(bearer).then((id) => env.DB.prepare("SELECT * FROM entries WHERE id = ?").bind(id).first());
	const members = async (bearer) => (await (await group("GET", undefined, bearer)).json()).members;

	it("start with a code made by the client, and only a creature in the group can read it", async () => {
		await checkin(score(), token(1));
		await checkin(score(), token(2));
		await checkin(score(), token(3));
		expect(await (await group("POST", { code: CODE, new: true }, token(1))).json()).toEqual({ joined: true, members: 1 });
		expect(await (await group("POST", { code: CODE }, token(2))).json()).toEqual({ joined: true, members: 2 });
		expect((await members(token(1))).filter((m) => m.you)).toHaveLength(1);
		expect(await members(token(2))).toHaveLength(2);
		// Not a member: nothing, whatever is added to the request.
		expect(await members(token(3))).toEqual([]);
		const sneaky = await group("GET", undefined, token(3), `/api/group?code=${CODE}`);
		expect((await sneaky.json()).members).toEqual([]);
		const noToken = await worker.fetch(new Request(`https://board.test/api/group?code=${CODE}`), env);
		expect(noToken.status).toBe(401);
	});

	it("keeps only the SHA-256 of the code", async () => {
		await checkin(score(), TOKEN);
		await group("POST", { code: CODE, new: true }, TOKEN);
		expect((await row(TOKEN)).grp).toBe(await sha256(CODE));
		const tables = (await env.DB.prepare("SELECT name FROM sqlite_master WHERE type = 'table'").all()).results;
		for (const { name } of tables.filter((t) => !t.name.startsWith("_"))) {
			const everything = JSON.stringify((await env.DB.prepare(`SELECT * FROM ${name}`).all()).results);
			expect(everything).not.toContain(CODE);
		}
	});

	it("reply with numbers and yes/no values only, names as three numbers", async () => {
		await checkin(score(), TOKEN);
		await group("POST", { code: CODE, new: true }, TOKEN);
		const reply = await (await group("GET", undefined, TOKEN)).json();
		const strings = [];
		const walk = (v) => {
			if (typeof v === "string") strings.push(v);
			else if (v && typeof v === "object") Object.values(v).forEach(walk);
		};
		walk(reply);
		expect(strings).toEqual([]);
		expect(reply.members[0]).toEqual({
			name: expect.any(Array), level: 5, witnessed_xp: 0, season_xp: 0, week_xp: 0, stats: [10, 20, 30, 60, 5, 15], sus: false, you: true,
		});
		const [a, b, n] = reply.members[0].name;
		expect((await row(TOKEN)).name).toBe(`${ADJ[a]} ${ANI[b]} ${String(n).padStart(4, "0")}`);
	});

	it("hold one group per creature and at most 25 members", async () => {
		await checkin(score(), token(1));
		await group("POST", { code: CODE, new: true }, token(1));
		await checkin(score(), token(99));
		await group("POST", { code: OTHER, new: true }, token(99));
		const again = await group("POST", { code: OTHER }, token(1));
		expect(again.status).toBe(409);
		expect((await again.json()).reason).toBe("in_group");
		expect((await row(token(1))).grp).toBe(await sha256(CODE));

		await crowd(24, { from: 2000 });
		await env.DB.prepare("UPDATE entries SET grp = ? WHERE name LIKE 'Crowd Row %'").bind(await sha256(CODE)).run();
		expect(await members(token(1))).toHaveLength(25);
		await checkin(score(), token(50));
		const full = await group("POST", { code: CODE }, token(50));
		expect(full.status).toBe(409);
		expect((await full.json()).reason).toBe("full");
		expect((await row(token(50))).grp).toBeNull();
		expect((await row(token(50))).opt_count).toBe(0);
		expect(await members(token(1))).toHaveLength(25);
	});

	it("refuse a creature whose generated name is already in the group", async () => {
		await checkin(score(), TOKEN);
		await checkin(score(), token(2));
		await group("POST", { code: CODE, new: true }, token(2));
		await env.DB.prepare("UPDATE entries SET name = (SELECT name FROM entries WHERE id = ?) WHERE id = ?")
			.bind(await sha256(TOKEN), await sha256(token(2)))
			.run();
		const res = await group("POST", { code: CODE }, TOKEN);
		expect(res.status).toBe(409);
		expect((await res.json()).reason).toBe("name_taken");
		expect((await row(TOKEN)).grp).toBeNull();
	});

	it("say when a code has no group, and take only a well-formed code in the body", async () => {
		await checkin(score(), TOKEN);
		const none = await group("POST", { code: CODE }, TOKEN);
		expect(none.status).toBe(404);
		expect((await none.json()).reason).toBe("no_group");
		for (const body of [{ code: CODE.toUpperCase() }, { code: CODE + "0" }, { code: CODE, new: false }, { code: CODE, x: 1 }, [CODE], "nope"]) {
			expect((await group("POST", body, TOKEN)).status).toBe(400);
		}
		expect((await group("POST", { code: CODE, new: true }, token(7))).status).toBe(404);
		expect((await row(TOKEN)).grp).toBeNull();
	});

	it("let a member leave at once, and take the creature out when it leaves the board", async () => {
		for (const n of [1, 2, 3]) await checkin(score(), token(n));
		await group("POST", { code: CODE, new: true }, token(1));
		await group("POST", { code: CODE }, token(2));
		await group("POST", { code: CODE }, token(3));
		expect(await (await group("DELETE", undefined, token(2))).json()).toEqual({ left: true });
		expect(await (await group("DELETE", undefined, token(2))).json()).toEqual({ left: false });
		await leave(token(3));
		expect(await members(token(1))).toHaveLength(1);
	});

	it("do not put anyone on a world list", async () => {
		await listed(token(1));
		await setWorld(false, token(1));
		await group("POST", { code: CODE, new: true }, token(1));
		await rebuild();
		expect((await files()).top.all).toEqual([]);
		expect((await row(token(1))).world).toBe(0);
	});

	it("share the three-a-day opt-in limit with the world ranking; leaving is never limited", async () => {
		await checkin(score(), TOKEN);
		await setWorld(true, TOKEN);
		await setWorld(false, TOKEN);
		await setWorld(true, TOKEN);
		await setWorld(false, TOKEN);
		expect((await group("POST", { code: CODE, new: true }, TOKEN)).status).toBe(200);
		expect((await group("DELETE", undefined, TOKEN)).status).toBe(200);
		const fourth = await group("POST", { code: OTHER, new: true }, TOKEN);
		expect(fourth.status).toBe(429);
		expect((await fourth.json()).reason).toBe("opt_ins");
		expect((await setWorld(true, TOKEN)).status).toBe(429);
		for (let n = 0; n < 4; n++) {
			expect((await group("DELETE", undefined, TOKEN)).status).toBe(200);
			expect((await setWorld(false, TOKEN)).status).toBe(200);
		}
		expect((await leave(TOKEN)).status).toBe(200);
		goTo("2026-10-14");
		await checkin(score(), token(4));
		expect((await group("POST", { code: OTHER, new: true }, token(4))).status).toBe(200);
	});

	it("refuse group requests when the per-creature limiter is not wired up", async () => {
		await checkin(score(), TOKEN);
		const res = await worker.fetch(
			new Request("https://board.test/api/group", { method: "GET", headers: { authorization: `Bearer ${TOKEN}` } }),
			{ DB: env.DB },
		);
		expect(res.status).toBe(503);
	});
});

describe("duels", () => {
	// The per-creature limiter counts in real time across tests, so each test uses creatures of its own.
	let next = 40000;
	let token = (n) => n.toString(16).padStart(64, "0");
	beforeEach(() => {
		const base = next;
		next += 100;
		token = (n) => (base + n).toString(16).padStart(64, "0");
	});
	const duel = (method, body, bearer) => group(method, body, bearer, "/api/duel");
	const view = async (bearer) => (await duel("GET", undefined, bearer)).json();
	const row = (bearer) => sha256(bearer).then((id) => env.DB.prepare("SELECT * FROM entries WHERE id = ?").bind(id).first());
	const reason = async (res) => [res.status, (await res.json()).reason];
	// Two creatures in a duel accepted on 13 October, so it runs from 14 to 20 October.
	const pair = async (a, b) => {
		goTo("2026-10-12");
		await checkin(score(), a);
		await checkin(score(), b);
		goTo("2026-10-13");
		await duel("POST", { code: CODE, new: true }, a);
		await duel("POST", { code: CODE }, b);
	};

	it("start with a code made by the client, take exactly one opponent, and start both clocks the next day", async () => {
		for (const n of [1, 2, 3]) await checkin(score(), token(n));
		expect(await (await duel("POST", { code: CODE, new: true }, token(1))).json()).toEqual({ joined: true, members: 1 });
		expect(await view(token(1))).toEqual({ day: null, members: [expect.objectContaining({ you: true, duel_xp: 0 })] });
		expect(await (await duel("POST", { code: CODE }, token(2))).json()).toEqual({ joined: true, members: 2 });
		expect((await row(token(1))).duel_day).toBe("2026-10-14");
		expect((await row(token(2))).duel_day).toBe("2026-10-14");
		expect(await reason(await duel("POST", { code: CODE }, token(3)))).toEqual([409, "full"]);
		expect((await row(token(3))).duel).toBeNull();
		const seen = await view(token(2));
		expect(seen.day).toBe(-1);
		expect(seen.members).toHaveLength(2);
		expect(seen.members.filter((m) => m.you)).toHaveLength(1);
		// Not in it: nothing, whatever is added to the request.
		expect(await view(token(3))).toEqual({ day: null, members: [] });
		const sneaky = await group("GET", undefined, token(3), `/api/duel?code=${CODE}`);
		expect((await sneaky.json()).members).toEqual([]);
	});

	it("count only the daily XP the board credits during its seven days", async () => {
		await pair(token(1), token(2));
		// The day it was accepted does not count, whoever checks in first.
		await checkin(score({ xp: 1500, xp_days: 6 }), token(1));
		await checkin(score(), token(2));
		expect((await row(token(1))).duel_xp).toBe(0);
		goTo("2026-10-14");
		await checkin(score({ xp: 2000, xp_days: 7 }), token(1));
		await checkin(score({ xp: 1200, xp_days: 6 }), token(2));
		goTo("2026-10-20");
		await checkin(score({ xp: 2550, xp_days: 8 }), token(1));
		expect((await view(token(1))).day).toBe(6);
		goTo("2026-10-21");
		await checkin(score({ xp: 1750, xp_days: 7 }), token(2));
		const { day, members } = await view(token(2));
		expect(day).toBe(7);
		expect(members.map((m) => [m.you, m.duel_xp])).toEqual([[false, 1050], [true, 200]]);
		// The rest of the board's numbers go on as before.
		expect((await row(token(2))).witnessed_xp).toBe(750);
	});

	it("count only check-ins after one on or after the day it was accepted, so XP held back from before never counts", async () => {
		goTo("2026-10-01");
		await checkin(score(), token(1));
		await checkin(score(), token(2));
		goTo("2026-10-13");
		await duel("POST", { code: CODE, new: true }, token(2));
		await duel("POST", { code: CODE }, token(1));
		await checkin(score(), token(2));
		// Twelve days held back and reported during the duel: the board credits them, the duel none of them,
		// however many of those days are claimed to be duel days.
		goTo("2026-10-16");
		await checkin(score({ xp: 1000 + 550 * 15, xp_days: 20 }), token(1));
		expect((await row(token(1))).witnessed_xp).toBe(8250);
		expect((await row(token(1))).duel_xp).toBe(0);
		// From then on its check-ins count.
		goTo("2026-10-17");
		await checkin(score({ xp: 1000 + 550 * 16, xp_days: 21 }), token(1));
		expect((await row(token(1))).duel_xp).toBe(550);
		// One check-in on the day of accepting, then one on the last day: all seven days count, and never more than 550 a day.
		goTo("2026-10-20");
		await checkin(score({ xp: 1000 + 550 * 7, xp_days: 12 }), token(2));
		expect((await row(token(2))).duel_xp).toBe(3850);
	});

	it("keep only the SHA-256 of the code, and reply with numbers, yes/no values and null only", async () => {
		await pair(token(1), token(2));
		expect((await row(token(1))).duel).toBe(await sha256(CODE));
		const tables = (await env.DB.prepare("SELECT name FROM sqlite_master WHERE type = 'table'").all()).results;
		for (const { name } of tables.filter((t) => !t.name.startsWith("_"))) {
			const everything = JSON.stringify((await env.DB.prepare(`SELECT * FROM ${name}`).all()).results);
			expect(everything).not.toContain(CODE);
		}
		const reply = await view(token(1));
		const strings = [];
		const walk = (v) => {
			if (typeof v === "string") strings.push(v);
			else if (v && typeof v === "object") Object.values(v).forEach(walk);
		};
		walk(reply);
		expect(strings).toEqual([]);
		expect(reply.members[0]).toEqual({
			name: expect.any(Array), level: 5, duel_xp: 0, stats: [10, 20, 30, 60, 5, 15], sus: false, you: expect.any(Boolean),
		});
	});

	it("hold one duel per creature beside its group: a waiting or finished duel can be replaced, a running one cannot", async () => {
		for (const n of [1, 2, 3]) await checkin(score(), token(n));
		await group("POST", { code: CODE, new: true }, token(1));
		await duel("POST", { code: OTHER, new: true }, token(1));
		// A new duel replaces one that waits: its old link leads nowhere.
		const third = "ab".repeat(16);
		expect((await duel("POST", { code: third, new: true }, token(1))).status).toBe(200);
		expect(await reason(await duel("POST", { code: OTHER }, token(2)))).toEqual([404, "no_duel"]);
		expect((await duel("POST", { code: third }, token(2))).status).toBe(200);
		expect((await row(token(1))).grp).toBe(await sha256(CODE));
		goTo("2026-10-20");
		expect(await reason(await duel("POST", { code: OTHER, new: true }, token(1)))).toEqual([409, "in_duel"]);
		await duel("POST", { code: OTHER, new: true }, token(3));
		expect(await reason(await duel("POST", { code: OTHER }, token(2)))).toEqual([409, "in_duel"]);
		// Over after seven days: a new duel or a rematch can start, and the other side sees it was left.
		goTo("2026-10-21");
		expect((await duel("POST", { code: OTHER }, token(1))).status).toBe(200);
		const left = await view(token(2));
		expect(left.day).toBe(7);
		expect(left.members).toHaveLength(1);
	});

	it("refuse your own duel, an unknown code, a malformed body and a creature that does not exist", async () => {
		await checkin(score(), token(1));
		await duel("POST", { code: CODE, new: true }, token(1));
		expect(await reason(await duel("POST", { code: CODE }, token(1)))).toEqual([409, "own_duel"]);
		expect(await reason(await duel("POST", { code: OTHER }, token(1)))).toEqual([404, "no_duel"]);
		for (const body of [{ code: CODE.toUpperCase() }, { code: CODE + "0" }, { code: CODE, new: false }, { code: CODE, x: 1 }, [CODE], "nope"]) {
			expect((await duel("POST", body, token(1))).status).toBe(400);
		}
		expect(await reason(await duel("POST", { code: OTHER, new: true }, token(7)))).toEqual([404, "no_creature"]);
		expect(await reason(await duel("GET", undefined, token(7)))).toEqual([404, "no_creature"]);
		expect((await row(token(1))).duel).toBe(await sha256(CODE));
	});

	it("refuse an opponent whose generated name matches the waiting creature's", async () => {
		await checkin(score(), token(1));
		await checkin(score(), token(2));
		await duel("POST", { code: CODE, new: true }, token(2));
		await env.DB.prepare("UPDATE entries SET name = (SELECT name FROM entries WHERE id = ?) WHERE id = ?")
			.bind(await sha256(token(1)), await sha256(token(2)))
			.run();
		expect(await reason(await duel("POST", { code: CODE }, token(1)))).toEqual([409, "name_taken"]);
		expect((await row(token(2))).duel_day).toBeNull();
	});

	it("let only one of two creatures accepting at the same moment in", async () => {
		for (const n of [1, 2, 3]) await checkin(score(), token(n));
		await duel("POST", { code: CODE, new: true }, token(1));
		const answers = await Promise.all([duel("POST", { code: CODE }, token(2)), duel("POST", { code: CODE }, token(3))]);
		expect(answers.map((a) => a.status).sort()).toEqual([200, 409]);
		expect((await view(token(1))).members).toHaveLength(2);
	});

	it("let a creature leave at once, and drop it when it leaves the board", async () => {
		await pair(token(1), token(2));
		expect(await (await duel("DELETE", undefined, token(2))).json()).toEqual({ left: true });
		expect(await (await duel("DELETE", undefined, token(2))).json()).toEqual({ left: false });
		expect((await row(token(2))).duel).toBeNull();
		const alone = await view(token(1));
		expect([alone.day, alone.members.length]).toEqual([-1, 1]);
		await leave(token(1));
		expect(await (await duel("DELETE", undefined, token(1))).json()).toEqual({ left: false });
	});

	it("share the three-a-day opt-in limit with the world ranking and groups; leaving is never limited", async () => {
		await checkin(score(), token(1));
		await setWorld(true, token(1));
		await group("POST", { code: CODE, new: true }, token(1));
		expect((await duel("POST", { code: CODE, new: true }, token(1))).status).toBe(200);
		expect(await reason(await duel("POST", { code: OTHER, new: true }, token(1)))).toEqual([429, "opt_ins"]);
		for (let n = 0; n < 4; n++) expect((await duel("DELETE", undefined, token(1))).status).toBe(200);
		goTo("2026-10-14");
		expect((await duel("POST", { code: OTHER, new: true }, token(1))).status).toBe(200);
	});

	it("never show on the public files or put anyone on a world list", async () => {
		await listed(token(1));
		await setWorld(false, token(1));
		await checkin(score(), token(2));
		await duel("POST", { code: CODE, new: true }, token(1));
		await duel("POST", { code: CODE }, token(2));
		await rebuild();
		const { board, top } = await files();
		expect(top.all).toEqual([]);
		expect(JSON.stringify({ board, top })).not.toMatch(/duel/);
		expect((await row(token(1))).world).toBe(0);
	});

	it("refuse duel requests when the per-creature limiter is not wired up", async () => {
		await checkin(score(), token(1));
		const res = await worker.fetch(
			new Request("https://board.test/api/duel", { method: "GET", headers: { authorization: `Bearer ${token(1)}` } }),
			{ DB: env.DB },
		);
		expect(res.status).toBe(503);
	});
});

describe("GitHub badge", () => {
	// GitHub is faked: no test reaches the real one.
	let next = 40000;
	let token;
	let TOKEN;
	const keyed = { ...env, GITHUB_TOKEN: "test-key" };
	const gh = (bearer, method, body, on = keyed) => {
		const text = body === undefined ? undefined : JSON.stringify(body);
		return worker.fetch(
			new Request("https://board.test/api/github", {
				method,
				headers: { authorization: `Bearer ${bearer}`, ...(text === undefined ? {} : { "content-length": String(text.length) }) },
				body: text,
			}),
			on,
		);
	};
	const row = (bearer) => sha256(bearer).then((id) => env.DB.prepare("SELECT * FROM entries WHERE id = ?").bind(id).first());
	const code = "a1b2c3d4e5f60718293a4b5c6d7e8f90";
	const api = () => fetchMock.get("https://api.github.com");
	const gists = (login, list) => api().intercept({ path: `/users/${login}/gists?per_page=30`, method: "GET" }).reply(200, list);
	const search = (total, incomplete = false) =>
		api()
			.intercept({ path: (p) => p.startsWith("/search/commits?"), method: "GET" })
			.reply(200, { total_count: total, incomplete_results: incomplete, items: [] });
	const gist = (login, id, description, extra = {}) => ({
		public: true, description, created_at: "2026-10-14T09:00:00Z", owner: { login, id }, ...extra,
	});
	// A creature with check-ins on 13 and 14 October; the clock is left on the 14th.
	const twoDays = async (bearer) => {
		goTo("2026-10-13");
		await checkin(score(), bearer);
		goTo("2026-10-14");
		await checkin(score({ xp: 1400, xp_days: 6 }), bearer);
	};
	const start = async (bearer, login = "octo-cat", c = code) => gh(bearer, "PUT", { login, code_hash: await sha256(c) });
	const verify = async (bearer, login = "octo-cat", id = 4242, c = code, commits = 3) => {
		await start(bearer, login, c);
		gists(login, [gist(login, id, "cclevel verify " + c)]);
		search(commits);
		return (await gh(bearer, "POST")).json();
	};
	const timer = async (on = keyed) => {
		const ctx = createExecutionContext();
		await worker.scheduled({}, on, ctx);
		await waitOnExecutionContext(ctx);
	};

	beforeAll(() => {
		fetchMock.activate();
		fetchMock.disableNetConnect();
	});
	beforeEach(() => {
		const base = next;
		next += 100;
		token = (n) => (base + n).toString(16).padStart(64, "0");
		TOKEN = token(0);
	});
	afterEach(() => fetchMock.assertNoPendingInterceptors());

	it("verifies only when the named account has a public gist carrying exactly the code", async () => {
		await twoDays(TOKEN);
		expect(await (await start(TOKEN)).json()).toEqual({ pending: true });
		expect(await row(TOKEN)).toMatchObject({ gh_login: "octo-cat", gh_id: null, gh_code: await sha256(code) });

		gists("octo-cat", [
			gist("octo-cat", 4242, "something else"),
			gist("octo-cat", 4242, "cclevel verify " + "0".repeat(32)),
			gist("octo-cat", 4242, "please cclevel verify " + code),
			gist("octo-cat", 4242, "cclevel verify " + code + " cclevel verify " + "1".repeat(32)),
		]);
		expect(await (await gh(TOKEN, "POST")).json()).toEqual({ verified: false });
		expect((await row(TOKEN)).gh_id).toBeNull();

		gists("octo-cat", [gist("Octo-Cat", 4242, "cclevel verify " + code + "\n")]);
		search(17);
		expect(await (await gh(TOKEN, "POST")).json()).toEqual({ verified: true, commits: 17 });
		expect(await row(TOKEN)).toMatchObject({
			gh_login: "Octo-Cat", gh_id: 4242, gh_commits: 17, gh_day: "2026-10-14", gh_code: await sha256(code), gh_code_day: null,
		});
	});

	it("does not accept another account's gist, a secret gist, an older gist or an expired code", async () => {
		await twoDays(TOKEN);
		await start(TOKEN);
		gists("octo-cat", [
			gist("mallory", 7, "cclevel verify " + code),
			gist("octo-cat", 4242, "cclevel verify " + code, { public: false }),
			gist("octo-cat", 4242, "cclevel verify " + code, { created_at: "2026-10-13T23:59:59Z" }),
		]);
		expect(await (await gh(TOKEN, "POST")).json()).toEqual({ verified: false });
		goTo("2026-10-16");
		const late = await gh(TOKEN, "POST");
		expect(late.status).toBe(410);
		expect((await late.json()).reason).toBe("expired");
		expect((await row(TOKEN)).gh_id).toBeNull();
	});

	it("cannot be taken with a code copied from someone else's public gist", async () => {
		await twoDays(token(1));
		await twoDays(token(2));
		expect(await verify(token(1), "alice", 1001)).toMatchObject({ verified: true });
		// The thief reads alice's gist and sends the same code: refused while alice holds it.
		const copied = await start(token(2), "alice");
		expect(copied.status).toBe(409);
		expect((await copied.json()).reason).toBe("code_taken");
		// Once alice removes her badge, the old gist is still too old for any later start.
		await gh(token(1), "DELETE");
		goTo("2026-10-20");
		await rebuild(); // the spent list has emptied by now: the gist's date is what stops the copy
		await checkin(score({ xp: 1500, xp_days: 7 }), token(2));
		expect((await start(token(2), "alice")).status).toBe(200);
		gists("alice", [gist("alice", 1001, "cclevel verify " + code)]);
		expect(await (await gh(token(2), "POST")).json()).toEqual({ verified: false });
		expect((await row(token(2))).gh_id).toBeNull();
	});

	it("cannot be taken the same day with a code its owner let go of", async () => {
		for (const n of [1, 2, 3, 4, 9]) await twoDays(token(n));
		// The owner removes the badge and leaves the gist up.
		await verify(token(1), "alice", 1001, "1".repeat(32));
		await gh(token(1), "DELETE");
		// Another owner leaves the board.
		await verify(token(2), "bob", 1002, "2".repeat(32));
		await leave(token(2));
		// A third starts again with a new code after publishing a gist with the first one.
		await start(token(3), "carol", "3".repeat(32));
		await start(token(3), "carol", "4".repeat(32));
		for (const [login, c] of [["alice", "1"], ["bob", "2"], ["carol", "3"]]) {
			const copied = await start(token(9), login, c.repeat(32));
			expect(copied.status).toBe(409);
			expect((await copied.json()).reason).toBe("code_taken");
		}
		expect((await row(token(9))).gh_login).toBeNull();
		// The spent list keeps hashes only, with no link to any creature, and empties after two days.
		const spent = (await env.DB.prepare("SELECT * FROM spent").all()).results;
		expect(Object.keys(spent[0]).sort()).toEqual(["day", "hash"]);
		expect(spent).toHaveLength(3);
		goTo("2026-10-16");
		await rebuild();
		expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM spent").first()).n).toBe(0);
	});

	it("opens only after check-ins on two different days", async () => {
		await checkin(score(), TOKEN);
		const early = await start(TOKEN);
		expect(early.status).toBe(409);
		expect((await early.json()).reason).toBe("too_new");
		expect((await row(TOKEN)).gh_login).toBeNull();
	});

	it("receives a login and a hash, never a code or a credential, and stores only the listed fields", async () => {
		await twoDays(TOKEN);
		for (const body of [{ login: "octo-cat", code }, { login: "-bad", code_hash: "a".repeat(64) }, { login: "octo-cat", code_hash: "a".repeat(64), token: "x" }]) {
			expect((await gh(TOKEN, "PUT", body)).status).toBe(400);
		}
		await start(TOKEN);
		expect(JSON.stringify(await row(TOKEN))).not.toContain(code);
		const columns = (await env.DB.prepare("PRAGMA table_info(entries)").all()).results.map((c) => c.name).filter((c) => c.startsWith("gh_"));
		expect(columns).toEqual(["gh_login", "gh_id", "gh_commits", "gh_day", "gh_code", "gh_code_day"]);
	});

	it("never changes place, XP, level or the sus mark", async () => {
		await listed(token(1), 1000, 1300);
		await listed(token(2), 1000, 1500);
		const before = await row(token(1));
		await verify(token(1), "octo-cat", 4242, code, 900);
		await rebuild();
		const { board, top } = await files();
		expect(board.all.xp).toEqual([500, 300]);
		expect(top.all[1]).toMatchObject({ xp: 300, github: "octo-cat", commits: 900, sus: false });
		expect(top.all[0].github).toBeUndefined();
		const after = await row(token(1));
		for (const k of ["xp", "level", "witnessed_xp", "season_xp", "capped_days", "world"]) expect(after[k]).toBe(before[k]);
	});

	it("is removed with every GitHub field, and the login leaves the public file at once", async () => {
		await listed(TOKEN);
		await verify(TOKEN);
		await rebuild();
		expect((await get("/top.json")).all[0]).toMatchObject({ github: "octo-cat", commits: 3 });
		expect(await (await gh(TOKEN, "DELETE")).json()).toEqual({ removed: true });
		const top = await get("/top.json");
		expect(top.all[0].github).toBeUndefined();
		expect(JSON.stringify(top)).not.toContain("octo-cat");
		expect(await row(TOKEN)).toMatchObject({ gh_login: null, gh_id: null, gh_commits: null, gh_day: null, gh_code: null, gh_code_day: null });
	});

	it("answers 'not available' without the board's key, and everything else keeps working", async () => {
		await twoDays(TOKEN);
		const startRes = await gh(TOKEN, "PUT", { login: "octo-cat", code_hash: "a".repeat(64) }, env);
		expect(startRes.status).toBe(503);
		expect((await startRes.json()).reason).toBe("unavailable");
		expect((await gh(TOKEN, "POST", undefined, env)).status).toBe(503);
		expect((await gh(TOKEN, "POST", undefined, { DB: env.DB, PER_CREATURE: env.PER_CREATURE, GITHUB_TOKEN: "k" })).status).toBe(503);
		expect((await row(TOKEN)).gh_login).toBeNull();
		goTo("2026-10-15");
		expect((await checkin(score({ xp: 1800, xp_days: 7 }), TOKEN)).status).toBe(200);
		expect((await setWorld(true, TOKEN)).status).toBe(200);
		expect((await rebuild()).all.ranked).toBe(1);
	});

	it("recounts on the timer by account number, keeping the old count when GitHub's is incomplete", async () => {
		await twoDays(TOKEN);
		await verify(TOKEN, "octo-cat", 4242, code, 5);
		goTo("2026-10-15");
		api().intercept({ path: "/user/4242", method: "GET" }).reply(200, { id: 4242, login: "renamed-cat" });
		search(99, true);
		await timer();
		expect(await row(TOKEN)).toMatchObject({ gh_login: "renamed-cat", gh_commits: 5, gh_day: "2026-10-15" });
	});

	it("drops the badge of a deleted account, and a failed lookup does not hold up the queue", async () => {
		await listed(token(1));
		await listed(token(2));
		await verify(token(1), "gone", 501, code);
		await verify(token(2), "flaky", 502, "f".repeat(32));
		await rebuild();
		goTo("2026-10-15");
		api().intercept({ path: "/user/501", method: "GET" }).reply(404, {});
		api().intercept({ path: "/user/502", method: "GET" }).reply(500, {});
		await timer();
		expect(await row(token(1))).toMatchObject({ gh_login: null, gh_id: null, gh_code: null });
		expect(JSON.stringify(await get("/top.json"))).not.toContain("gone");
		expect(await row(token(2))).toMatchObject({ gh_login: "flaky", gh_id: 502, gh_day: "2026-10-15" });
	});

	it("does not write a removed badge back when the removal lands during a recount", async () => {
		await twoDays(TOKEN);
		await verify(TOKEN, "racer", 777, code);
		goTo("2026-10-15");
		api().intercept({ path: "/user/777", method: "GET" }).reply(200, { id: 777, login: "racer" }).delay(100);
		search(2);
		const ctx = createExecutionContext();
		const running = worker.scheduled({}, keyed, ctx);
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(await (await gh(TOKEN, "DELETE")).json()).toEqual({ removed: true });
		await running;
		await waitOnExecutionContext(ctx);
		expect(await row(TOKEN)).toMatchObject({ gh_login: null, gh_id: null, gh_commits: null, gh_day: null });
	});

	it("forgets an unfinished verification and the login it named once the code has expired", async () => {
		await twoDays(TOKEN);
		await start(TOKEN, "typo-name");
		goTo("2026-10-16");
		await rebuild();
		expect(await row(TOKEN)).toMatchObject({ gh_login: null, gh_code: null, gh_code_day: null });
	});
});

describe("source and configuration hygiene", () => {
	it("logs nothing and reads the caller's address in one place only", () => {
		expect(source).not.toMatch(/console\./);
		expect(source.match(/cf-connecting-ip/g)).toHaveLength(1);
		// It sends its own user agent to GitHub, as GitHub requires, and never reads the caller's.
		expect(source).not.toMatch(/headers\.get\(\s*["'`]user-agent/i);
		expect(source.match(/user-agent/gi)).toHaveLength(1);
	});

	it("keeps request logs off and stays on the default address", () => {
		const config = JSON.parse(wrangler.replace(/^\s*\/\/.*$/gm, ""));
		expect(config.observability).toEqual({ enabled: false });
		expect(config.workers_dev).toBe(true);
		for (const key of ["routes", "route", "logpush", "tail_consumers"]) expect(config).not.toHaveProperty(key);
		expect(config.ratelimits[0]).toMatchObject({ name: "NEW_ROWS", simple: { limit: 5, period: 60 } });
		expect(config.ratelimits[1]).toMatchObject({ name: "PER_CREATURE", simple: { limit: 10, period: 60 } });
		expect(config.ratelimits[2]).toMatchObject({ name: "GITHUB_CALLS", simple: { limit: 20, period: 60 } });
	});

	it("indexes no column a check-in writes, so a check-in costs one written row", async () => {
		const indexes = (await env.DB.prepare("SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'entries'").all()).results;
		// The indexes are on the group, duel and GitHub columns, which a check-in never writes.
		expect(indexes.filter((i) => i.sql !== null).map((i) => i.name)).toEqual(["entries_grp", "entries_duel", "entries_gh", "entries_gh_code"]);
		await checkin(score(), token(5));
		await group("POST", { code: CODE, new: true }, token(5));
		await group("POST", { code: CODE, new: true }, token(5), "/api/duel");
		await checkin(score(), token(6));
		await group("POST", { code: CODE }, token(6), "/api/duel");
		await checkin(score());
		goTo("2026-10-14");
		const id = await sha256(token(5));
		// The same statement the board runs for a check-in, run here to read its cost, for a creature in a group and in a
		// running duel. The last four values take the duel's counting branch: it runs from 14 October, and the previous
		// check-in was on the day it was accepted.
		const update = source.match(/`UPDATE entries SET xp = [\s\S]*?WHERE id = \?`/)[0].slice(1, -1);
		const values = Array(update.split("?").length - 2).fill(1);
		values.splice(-4, 4, "2026-10-08", "2026-10-14", "2026-10-13", 550);
		const { meta } = await env.DB.prepare(update).bind(...values, id).run();
		expect(meta.rows_written).toBe(1);
		expect((await row(token(5))).duel_xp).toBe(550);
	});
});

describe("the board's first address", () => {
	it("passes the scanner's calls on unchanged and sends browsers to the new address", async () => {
		const seen = [];
		const board = { fetch: async (request) => (seen.push(request), new Response("ok")) };
		const post = new Request("https://cclevel-board.cclevel.workers.dev/api/checkin", { method: "POST", body: "{}" });
		expect(await (await legacy.fetch(post, { BOARD: board })).text()).toBe("ok");
		for (const path of ["/board.json", "/top.json", "/api/group"]) {
			await legacy.fetch(new Request("https://cclevel-board.cclevel.workers.dev" + path), { BOARD: board });
		}
		expect(seen.map((r) => new URL(r.url).pathname)).toEqual(["/api/checkin", "/board.json", "/top.json", "/api/group"]);
		expect(seen[0]).toBe(post);
		const page = await legacy.fetch(new Request("https://cclevel-board.cclevel.workers.dev/join?x=1"), { BOARD: board });
		expect(page.status).toBe(301);
		expect(page.headers.get("location")).toBe("https://go.cclevel.workers.dev/join?x=1");
		expect(seen).toHaveLength(4);
	});

	it("keeps no logs, holds no data and points at the board", () => {
		const config = JSON.parse(legacyWrangler.replace(/^\s*\/\/.*$/gm, ""));
		const main = JSON.parse(wrangler.replace(/^\s*\/\/.*$/gm, ""));
		expect(config.observability).toEqual({ enabled: false });
		expect(config.workers_dev).toBe(true);
		expect(config.services).toEqual([{ binding: "BOARD", service: main.name }]);
		expect(config.triggers).toEqual({ crons: [] });
		for (const key of ["routes", "route", "logpush", "tail_consumers", "d1_databases", "ratelimits"]) {
			expect(config).not.toHaveProperty(key);
		}
	});
});
