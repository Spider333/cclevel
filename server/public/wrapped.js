// The Wrapped page. The year's numbers are the part of the address after "#", which browsers never send to a server.
// This page checks them and draws five story images (1080x1920) in the browser. It makes no request of any kind:
// saving, copying and sharing hand the pictures straight to this device.
(function () {
	// These must match skills/pet/scripts/cclevel.py; a test checks them.
	var WRAPPED_VERSION = 1;
	var FIRST_YEAR = 2025;
	var DAY_CAP = 550;
	var STAT_ORDER = ["grind", "appetite", "arsenal", "brains", "autonomy", "craft"];
	var STAGES = [[60, "GOAT"], [45, "Gigachad"], [30, "Big Guy"], [15, "Lil Guy"], [5, "Hatchling"], [1, "Egg"]];
	// A class's number in the link, in this order; one past the end means no weekly snapshot this year.
	var WRAPPED_CLASSES = ["Shipper", "AFK Farmer", "Loot Goblin", "Tokenmaxxer", "Perfectly Balanced", "Noob", "Unhatched"];
	var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
	// In the scanner's BADGES order: bit i of the badge number is badge i.
	var BADGE_NAMES = {
		first_hook: "Hooked", first_skill: "Skill issue: solved", first_subagent: "Not my job", first_loop: "AFK gains",
		streak_7: "gm x7", streak_30: "No days off", streak_100: "Terminally online",
		skills_10: "Loadout", skills_50: "Full kit", skills_100: "Maxed out",
	};
	var ART = {
		Egg: ["   ___   ", "  /   \\  ", " |  .  | ", "  \\___/  "],
		Hatchling: ["   ___   ", "  /o o\\  ", " _\\_^_/_ ", "  '   '  "],
		"Lil Guy": ["  .-^-.  ", " ( o o ) ", "  \\ ~ /  ", "  /| |\\  "],
		"Big Guy": ["  .-^-.  ", " ( o o ) ", " /\\ ~ /\\ ", "  /| |\\  "],
		Gigachad: [" \\.-^-./ ", " ( o o ) ", " /\\ = /\\ ", " _/| |\\_ "],
		"GOAT": ["*\\.-^-./*", " ( @ @ ) ", "</\\ = /\\>", " _/| |\\_ "],
	};
	// The pictures always use the site's dark colours, whatever this browser's theme.
	var C = { bg: "#201f1c", surface: "#2a2926", raised: "#34322e", fg: "#f3f1ea", muted: "#b5b1a7", line: "#46433d", accent: "#d97757" };
	var CLASS_COLORS = {
		Shipper: "#7ec488", "AFK Farmer": "#8fb8f0", "Loot Goblin": "#e8c35a", Tokenmaxxer: "#e58bd0",
		"Perfectly Balanced": "#9ed9d0", Noob: "#c9c4b8", Unhatched: "#a8a49a",
	};
	var MONO = 'ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Code", Menlo, Consolas, monospace';
	var COUNT = 41;

	var el = function (id) {
		return document.getElementById(id);
	};
	var n0 = function (x) {
		return x.toLocaleString("en-US");
	};
	var plural = function (n, word) {
		return n0(n) + " " + word + (n === 1 ? "" : "s");
	};
	var stageOf = function (level) {
		return STAGES.filter(function (s) { return level >= s[0]; })[0][1];
	};
	var daysIn = function (year) {
		return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 366 : 365;
	};
	// "2 Feb" for a day of the year, the way the scanner writes a day.
	var dayName = function (year, doy) {
		var d = new Date(Date.UTC(year, 0, doy));
		return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()];
	};
	var monthOf = function (year, doy) {
		return new Date(Date.UTC(year, 0, doy)).getUTCMonth();
	};

	// A copy button for a command. Where the clipboard is refused, the command is selected instead.
	var copier = function (code) {
		var copy = document.createElement("button");
		copy.className = "copy";
		copy.type = "button";
		copy.textContent = "copy";
		copy.setAttribute("aria-label", "Copy: " + code.textContent);
		copy.addEventListener("click", function () {
			var text = code.textContent;
			var done = function () {
				copy.textContent = "copied";
				setTimeout(function () {
					copy.textContent = "copy";
				}, 1500);
			};
			var select = function () {
				var range = document.createRange();
				range.selectNodeContents(code);
				var sel = window.getSelection();
				sel.removeAllRanges();
				sel.addRange(range);
			};
			if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, select);
			else select();
		});
		return copy;
	};

	// The year from the address, or null: 41 whole numbers joined by "-", each in range and consistent with the rest.
	function read(hash) {
		var parts = hash.split("-");
		if (parts.length !== COUNT || !parts.every(function (p) { return /^\d{1,9}$/.test(p); })) return null;
		var n = parts.map(Number);
		var w = {
			year: n[1], soFar: n[2] === 1, until: n[3], xp: n[4], active: n[5], estimated: n[6], first: n[7], last: n[8],
			bestDay: n[9], bestXp: n[10], bestMonth: n[11], longest: n[12], months: n.slice(13, 25), badgeBits: n[25],
			snaps: n[26], cls: n[27], strongest: n[28], average: n[29], moves: n.slice(30, 36), stages: n.slice(36, 41),
		};
		var badges = Object.keys(BADGE_NAMES);
		var inYear = function (d) { return d >= 1 && d <= w.until; };
		var ok = n[0] === WRAPPED_VERSION && w.year >= FIRST_YEAR && w.year <= 2100 && n[2] <= 1
			&& w.until >= 1 && w.until <= daysIn(w.year) && (w.soFar || w.until === daysIn(w.year))
			&& w.active >= 1 && w.active <= w.until && w.estimated <= w.active
			&& w.xp === w.months.reduce(function (a, b) { return a + b; }, 0) && w.xp <= w.active * DAY_CAP
			&& w.first >= 1 && w.first <= w.last && w.last <= 99
			&& inYear(w.bestDay) && w.bestXp >= 1 && w.bestXp <= DAY_CAP && w.bestMonth <= 11
			&& w.months[w.bestMonth] >= w.bestXp && w.longest >= 1 && w.longest <= w.active
			&& w.months.every(function (m) { return m <= 31 * DAY_CAP; })
			&& w.badgeBits < Math.pow(2, badges.length) && w.snaps <= 53
			&& w.cls <= WRAPPED_CLASSES.length && w.strongest <= STAT_ORDER.length && w.average <= 100
			&& (w.snaps === 0) === (w.cls === WRAPPED_CLASSES.length) && (w.snaps === 0) === (w.strongest === STAT_ORDER.length)
			&& w.moves.every(function (m) { return m <= 200; })
			&& w.stages.every(function (d) { return d === 0 || inYear(d); });
		if (!ok) return null;
		w.badges = badges.filter(function (b, i) { return Math.floor(w.badgeBits / Math.pow(2, i)) % 2 === 1; })
			.map(function (b) { return BADGE_NAMES[b]; });
		w.cls = w.snaps ? WRAPPED_CLASSES[w.cls] : null;
		w.strongest = w.snaps ? STAT_ORDER[w.strongest] : null;
		w.moves = w.snaps > 1 ? w.moves.map(function (m) { return m - 100; }) : null;
		w.title = w.year + (w.soFar ? " so far" : " Wrapped");
		w.span = w.soFar ? MONTHS[0] + (monthOf(w.year, w.until) ? "–" + MONTHS[monthOf(w.year, w.until)] : "") : "";
		w.levels = "Lv " + w.first + " " + stageOf(w.first) + " → Lv " + w.last + " " + stageOf(w.last);
		return w;
	}

	var font = function (weight, size) {
		return weight + " " + size + "px " + MONO;
	};
	// Sets the largest font from `size` down to `min` at which `text` fits in `width`, and returns that size.
	function fit(ctx, text, weight, size, min, width) {
		for (; size > min; size -= 2) {
			ctx.font = font(weight, size);
			if (ctx.measureText(text).width <= width) return size;
		}
		ctx.font = font(weight, min);
		return min;
	}
	// Writes `text` at (x, y) in the given style, shrunk to fit `width` if it has to be.
	function text(ctx, s, x, y, weight, size, color, width, align) {
		ctx.textAlign = align || "left";
		ctx.fillStyle = color;
		if (width) fit(ctx, s, weight, size, 20, width);
		else ctx.font = font(weight, size);
		ctx.fillText(s, x, y);
	}

	var W = 1080;
	var H = 1920;
	var L = 96;
	var R = W - 96;
	var MID = W / 2;

	// What every image shares: the background, the frame, the header and the self-reported footer.
	function frame(ctx, w, index, heading) {
		ctx.fillStyle = C.bg;
		ctx.fillRect(0, 0, W, H);
		ctx.fillStyle = "rgba(255, 255, 255, .025)"; // the site's faint scanlines
		for (var y = 2; y < H; y += 3) ctx.fillRect(0, y, W, 1);
		ctx.strokeStyle = C.line;
		ctx.lineWidth = 3;
		ctx.strokeRect(36, 36, W - 72, H - 72);
		ctx.textBaseline = "alphabetic";
		ctx.font = font(800, 44);
		ctx.textAlign = "left";
		ctx.fillStyle = C.accent;
		ctx.fillText("CC", L, 170);
		ctx.fillStyle = C.fg;
		ctx.fillText("level", L + ctx.measureText("CC ").width, 170);
		text(ctx, w.title + " · " + index + "/5", R, 170, 400, 34, C.muted, 0, "right");
		if (heading) text(ctx, heading, L, 330, 800, 76, C.accent, R - L);
		ctx.setLineDash([8, 8]);
		ctx.beginPath();
		ctx.moveTo(L, H - 200);
		ctx.lineTo(R, H - 200);
		ctx.stroke();
		ctx.setLineDash([]);
		text(ctx, "CC level · self-reported", MID, H - 130, 400, 34, C.muted, 0, "center");
	}

	function big(ctx, value, label, y, color) {
		text(ctx, value, L, y, 800, 150, color || C.fg, R - L);
		text(ctx, label, L, y + 70, 400, 44, C.muted, R - L);
	}

	var DRAW = [
		// 1. The cover: the year, the creature as it is now, and the levels it climbed.
		function (ctx, w) {
			frame(ctx, w, 1);
			text(ctx, String(w.year), MID, 520, 800, 260, C.fg, 0, "center");
			text(ctx, w.soFar ? "so far · " + w.span : "Wrapped", MID, 640, 700, 80, C.accent, R - L, "center");
			var art = ART[stageOf(w.last)];
			ctx.fillStyle = C.surface;
			ctx.fillRect(L, 760, R - L, 560);
			ctx.strokeStyle = C.line;
			ctx.setLineDash([10, 10]);
			ctx.strokeRect(L, 760, R - L, 560);
			ctx.setLineDash([]);
			art.forEach(function (line, i) {
				text(ctx, line, MID, 760 + (560 - art.length * 110) / 2 + 85 + i * 110, 700, 100, C.accent, 0, "center");
			});
			text(ctx, w.levels, MID, 1480, 800, 64, C.fg, R - L, "center");
			text(ctx, "My year with Claude Code", MID, 1580, 400, 44, C.muted, R - L, "center");
			return w.title + (w.span ? " (" + w.span + ")" : "") + ". " + w.levels + ".";
		},
		// 2. The grind: XP, active days, the longest streak, and how many days were estimated.
		function (ctx, w) {
			frame(ctx, w, 2, "The grind");
			big(ctx, n0(w.xp), "XP this year", 620);
			big(ctx, n0(w.active), w.active === 1 ? "active day" : "active days", 960);
			big(ctx, n0(w.longest), w.longest === 1 ? "day longest streak" : "days longest streak", 1300, C.accent);
			if (w.estimated) text(ctx, "(" + w.estimated + " days estimated from prompt counts)", L, 1560, 400, 38, C.muted, R - L);
			return n0(w.xp) + " XP over " + plural(w.active, "active day")
				+ (w.estimated ? " (" + w.estimated + " estimated from prompt counts)" : "") + ". Longest streak: " + plural(w.longest, "day") + ".";
		},
		// 3. The peak: the best day, the best month and a bar for each month so far.
		function (ctx, w) {
			frame(ctx, w, 3, "The peak");
			text(ctx, "Best day", L, 470, 400, 44, C.muted);
			text(ctx, dayName(w.year, w.bestDay), L, 590, 800, 120, C.fg, R - L);
			text(ctx, n0(w.bestXp) + " XP", L, 670, 700, 56, C.accent);
			text(ctx, "Best month", L, 810, 400, 44, C.muted);
			text(ctx, MONTHS[w.bestMonth], L, 930, 800, 120, C.fg);
			text(ctx, n0(w.months[w.bestMonth]) + " XP", L, 1010, 700, 56, C.accent);
			var shown = monthOf(w.year, w.until) + 1;
			var top = Math.max.apply(null, w.months) || 1;
			var base = 1640;
			var tall = 500;
			var step = (R - L) / 12;
			for (var m = 0; m < 12; m++) {
				var x = L + m * step + 8;
				ctx.fillStyle = C.raised;
				ctx.fillRect(x, base - tall, step - 16, tall);
				if (m < shown) {
					var h = Math.round(tall * w.months[m] / top);
					ctx.fillStyle = m === w.bestMonth ? C.accent : C.muted;
					ctx.fillRect(x, base - h, step - 16, h);
				}
				text(ctx, MONTHS[m].charAt(0), x + (step - 16) / 2, base + 50, 400, 32, m < shown ? C.fg : C.line, 0, "center");
			}
			return "Best day: " + dayName(w.year, w.bestDay) + ", " + n0(w.bestXp) + " XP. Best month: " + MONTHS[w.bestMonth] + ", "
				+ n0(w.months[w.bestMonth]) + " XP. " + MONTHS.slice(0, shown).map(function (name, i) { return name + " " + n0(w.months[i]); }).join(", ") + ".";
		},
		// 4. Who you became: the stage-ups this year, the class and the strongest stat, and how the stats moved.
		function (ctx, w) {
			frame(ctx, w, 4, "Who you became");
			var said = [];
			var ups = [];
			STAGES.slice(0, -1).reverse().forEach(function (s, i) {
				if (w.stages[i]) ups.push((s[1] === "Hatchling" ? "Hatched" : s[1]) + " " + dayName(w.year, w.stages[i]));
			});
			var y = 470;
			if (!ups.length) ups.push("No new stage this year: still " + (stageOf(w.last) === "Egg" ? "an Egg" : "a " + stageOf(w.last)));
			ups.forEach(function (line) {
				text(ctx, line, L, y, 700, 60, C.fg, R - L);
				y += 90;
			});
			said.push(ups.join(" · ") + ".");
			y += 60;
			if (w.cls) {
				text(ctx, "Most weeks as", L, y, 400, 44, C.muted);
				text(ctx, w.cls, L, y + 100, 800, 90, CLASS_COLORS[w.cls], R - L);
				text(ctx, "Strongest stat", L, y + 210, 400, 44, C.muted);
				var strong = w.strongest.charAt(0).toUpperCase() + w.strongest.slice(1);
				text(ctx, strong + ", " + w.average + " on average", L, y + 290, 700, 60, C.fg, R - L);
				said.push("Most weeks as: " + w.cls + ". Strongest stat: " + strong + ", " + w.average + " on average.");
				y += 400;
				if (w.moves) {
					text(ctx, "Since the first snapshot", L, y, 400, 44, C.muted);
					STAT_ORDER.forEach(function (s, i) {
						var col = i % 2 ? MID + 20 : L;
						var row = y + 80 + Math.floor(i / 2) * 76;
						var m = w.moves[i];
						text(ctx, s.charAt(0).toUpperCase() + s.slice(1), col, row, 400, 46, C.fg);
						text(ctx, (m > 0 ? "+" : m < 0 ? "−" : "±") + Math.abs(m), col + 420, row, 800, 46, m > 0 ? C.accent : C.muted, 0, "right");
					});
					said.push("Since then: " + STAT_ORDER.map(function (s, i) {
						return s.charAt(0).toUpperCase() + s.slice(1) + " " + (w.moves[i] < 0 ? "" : "+") + w.moves[i];
					}).join(" · ") + ".");
				}
			} else {
				text(ctx, "Weekly stat snapshots start now.", L, y, 400, 44, C.muted, R - L);
				text(ctx, "Next Wrapped shows how they moved.", L, y + 64, 400, 44, C.muted, R - L);
			}
			return said.join(" ");
		},
		// 5. Badges, then the question and where to answer it.
		function (ctx, w) {
			frame(ctx, w, 5, "Badges");
			var y = 470;
			if (!w.badges.length) text(ctx, "No new badges this year", L, y, 700, 60, C.muted, R - L);
			w.badges.forEach(function (b) {
				text(ctx, "★ " + b, L, y, 700, 60, C.fg, R - L);
				y += 90;
			});
			text(ctx, "How big is your", MID, 1500, 800, 72, C.fg, R - L, "center");
			text(ctx, "Claude Code?", MID, 1590, 800, 72, C.fg, R - L, "center");
			text(ctx, "cclevel.com", MID, 1700, 800, 80, C.accent, R - L, "center");
			return (w.badges.length ? "Badges earned: " + w.badges.join(", ") : "No new badges this year") + ". How big is your Claude Code? cclevel.com";
		},
	];

	var say = function (s) {
		el("said").textContent = s;
	};
	var png = function (canvas) {
		return new Promise(function (resolve, reject) {
			canvas.toBlob(function (blob) {
				if (blob) resolve(blob);
				else reject(new Error("no image"));
			}, "image/png");
		});
	};
	var download = function (blob, name) {
		var a = document.createElement("a");
		a.href = URL.createObjectURL(blob);
		a.download = name;
		document.body.append(a);
		a.click();
		a.remove();
		setTimeout(function () {
			URL.revokeObjectURL(a.href);
		}, 10000);
	};

	document.querySelectorAll("code[data-copy]").forEach(function (c) {
		c.after(copier(c));
	});
	var w = read(location.hash.slice(1));
	if (!w) {
		el("broken").hidden = false;
		return;
	}
	var summary = w.title + ": " + n0(w.xp) + " XP over " + plural(w.active, "active day") + ". " + w.levels + ". Best day: "
		+ dayName(w.year, w.bestDay) + ", " + n0(w.bestXp) + " XP. Best month: " + MONTHS[w.bestMonth] + ", "
		+ n0(w.months[w.bestMonth]) + " XP. Longest streak: " + plural(w.longest, "day") + ". ";
	var canvases = [];
	var canClip = window.ClipboardItem && navigator.clipboard && navigator.clipboard.write;
	DRAW.forEach(function (draw, i) {
		var figure = document.createElement("figure");
		figure.className = "story";
		var canvas = document.createElement("canvas");
		canvas.className = "shot";
		canvas.width = W;
		canvas.height = H;
		canvas.setAttribute("role", "img");
		var own = draw(canvas.getContext("2d"), w);
		canvas.setAttribute("aria-label", "Image " + (i + 1) + " of 5. " + summary + own);
		var name = "cclevel-wrapped-" + w.year + "-" + (i + 1) + ".png";
		var row = document.createElement("div");
		row.className = "ctas";
		var save = document.createElement("button");
		save.className = "btn";
		save.type = "button";
		save.textContent = "Save";
		save.setAttribute("aria-label", "Save image " + (i + 1));
		save.addEventListener("click", function () {
			png(canvas).then(function (blob) {
				download(blob, name);
				say("Saved image " + (i + 1) + ".");
			}, function () {
				say("This browser could not make the image. A screenshot works too.");
			});
		});
		row.append(save);
		// Copying a picture needs the newer clipboard; where it is missing, the button is left out.
		if (canClip) {
			var copy = document.createElement("button");
			copy.className = "btn";
			copy.type = "button";
			copy.textContent = "Copy image";
			copy.setAttribute("aria-label", "Copy image " + (i + 1));
			copy.addEventListener("click", function () {
				navigator.clipboard.write([new ClipboardItem({ "image/png": png(canvas) })]).then(function () {
					say("Copied image " + (i + 1) + ". Paste it into a post.");
				}, function () {
					say("This browser would not copy the image. Save it instead.");
				});
			});
			row.append(copy);
		}
		figure.append(canvas, row);
		el("stories").append(figure);
		canvases.push({ canvas: canvas, name: name });
	});
	var caption = "My year with Claude Code: Lv " + w.first + " → Lv " + w.last + ". What's yours? cclevel.com";
	el("caption").textContent = caption;
	el("caption").nextElementSibling.setAttribute("aria-label", "Copy: " + caption);
	document.title = w.title + " · " + w.levels + " · CC level";
	el("share").hidden = false;

	var all = function () {
		return Promise.all(canvases.map(function (c) { return png(c.canvas); }));
	};
	el("save-all").addEventListener("click", function () {
		all().then(function (blobs) {
			blobs.forEach(function (blob, i) {
				setTimeout(function () {
					download(blob, canvases[i].name);
				}, i * 300);
			});
			say("Saving all 5. Your browser may ask once to allow several downloads.");
		}, function () {
			say("This browser could not make the images. Screenshots work too.");
		});
	});
	// Phones can hand files to the share sheet (and from there to a story); on a desktop the button stays hidden.
	var probe = typeof File === "function" ? [new File([""], "probe.png", { type: "image/png" })] : null;
	if (probe && navigator.canShare && navigator.canShare({ files: probe })) {
		el("share-all").hidden = false;
		el("share-all").addEventListener("click", function () {
			all().then(function (blobs) {
				var files = blobs.map(function (blob, i) { return new File([blob], canvases[i].name, { type: "image/png" }); });
				return navigator.share({ files: files, text: caption });
			}).then(function () {
				say("Shared.");
			}, function () {
				say("Not shared. Save them instead.");
			});
		});
	}
})();
