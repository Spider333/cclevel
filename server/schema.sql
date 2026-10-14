-- cclevel board. One row per creature. No IP address, user agent, e-mail or raw token is stored,
-- and dates carry no time of day.
CREATE TABLE IF NOT EXISTS entries (
	id           TEXT PRIMARY KEY,           -- SHA-256 of the token made on the user's machine
	name         TEXT NOT NULL,              -- generated creature name
	xp           INTEGER NOT NULL,           -- XP as reported, after the growth cap
	xp_days      INTEGER NOT NULL,           -- active days behind the XP
	base_days    INTEGER NOT NULL,           -- xp_days at the first check-in: the anchor for the growth cap
	level        INTEGER NOT NULL,           -- level from the reported XP
	stage        TEXT NOT NULL,
	class        TEXT NOT NULL,
	grind        INTEGER NOT NULL,
	appetite     INTEGER NOT NULL,
	arsenal      INTEGER NOT NULL,
	brains       INTEGER NOT NULL,
	autonomy     INTEGER NOT NULL,
	craft        INTEGER NOT NULL,
	badges       TEXT NOT NULL,              -- JSON list of badge codes
	first_day    TEXT NOT NULL,              -- UTC date of the first check-in
	last_day     TEXT NOT NULL,              -- UTC date of the latest accepted check-in
	days_seen    INTEGER NOT NULL DEFAULT 1, -- number of different days with a check-in
	season       TEXT NOT NULL,              -- YYYY-MM that season_xp belongs to
	season_xp    INTEGER NOT NULL DEFAULT 0, -- daily XP the board credited in that season
	witnessed_xp INTEGER NOT NULL DEFAULT 0, -- daily XP the board credited since the first check-in: what ranks
	capped_days  INTEGER NOT NULL DEFAULT 0, -- credited days that hit the full daily cap: the sus rule
	world        INTEGER NOT NULL DEFAULT 0, -- 1 while the owner has the world ranking on
	grp          TEXT,                       -- SHA-256 of the private group's code, or NULL
	opt_day      TEXT,                       -- UTC date of the latest opt-in (world ranking on, group join, GitHub start)
	opt_count    INTEGER NOT NULL DEFAULT 0, -- opt-ins on that date
	gh_login     TEXT,                       -- GitHub login, only for those who chose the verified badge
	gh_id        INTEGER,                    -- that account's numeric id, once verified
	gh_commits   INTEGER,                    -- its public commits co-signed by Claude, as GitHub counted them
	gh_day       TEXT,                       -- UTC date of that count
	gh_code      TEXT,                       -- SHA-256 of the verification code, kept while the badge exists
	gh_code_day  TEXT                        -- UTC date that code was sent, cleared once verified
);
-- No index on any column a check-in changes: each one would cost an extra written row per check-in.
-- A check-in never changes grp, so members are found through this index at no cost to check-ins.
CREATE INDEX IF NOT EXISTS entries_grp ON entries (grp) WHERE grp IS NOT NULL;
-- Verified accounts, oldest count first, for the timed refresh. A check-in never writes these columns either.
CREATE INDEX IF NOT EXISTS entries_gh ON entries (gh_day) WHERE gh_id IS NOT NULL;
-- A verification code proves an account once: no two creatures can hold the same one.
CREATE UNIQUE INDEX IF NOT EXISTS entries_gh_code ON entries (gh_code) WHERE gh_code IS NOT NULL;

-- How many creatures joined on each day: the global ceiling, kept without any client identifier.
CREATE TABLE IF NOT EXISTS days (
	day   TEXT PRIMARY KEY,
	joins INTEGER NOT NULL
);

-- GitHub verification codes that stopped being used (badge removed, creature left, or replaced by a new start),
-- kept for two days with no link to any creature, so a code copied from a public gist cannot be used again.
-- After two days a gist is older than any new start, and that rule takes over.
CREATE TABLE IF NOT EXISTS spent (
	hash TEXT PRIMARY KEY, -- SHA-256 of the code
	day  TEXT NOT NULL     -- UTC date it stopped being used
);

-- Stored board files, rebuilt on a timer: 'board' (numbers), 'top' (rows with names, for the page),
-- 'ids_all' and 'ids_season' (the listed row ids in list order, so one row can be cut out at once),
-- 'daily' (the totals, worked out once a day).
CREATE TABLE IF NOT EXISTS snapshot (
	id   TEXT PRIMARY KEY,
	body TEXT NOT NULL
);
