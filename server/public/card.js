// The share card page. The card's numbers are the part of the address after "#", which browsers never send to a server.
// This page checks them, works out the rest the way the scanner does, and draws the picture in the browser. It makes no
// request of any kind: saving and copying hand the picture straight to this device.
(function () {
	// These must match skills/pet/scripts/cclevel.py; a test checks them.
	var CARD_VERSION = 2;   // version 1 links (no look) still draw, with the classic look
	var LEVEL_DIVISOR = 40;
	var LEVEL_MAX = 99;
	var STAT_ORDER = ["grind", "appetite", "arsenal", "brains", "autonomy", "craft"];
	var STAGES = [[60, "GOAT"], [45, "Gigachad"], [30, "Big Guy"], [15, "Lil Guy"], [5, "Hatchling"], [1, "Egg"]];
	var CLASSES = { craft: "Shipper", autonomy: "AFK Farmer", arsenal: "Loot Goblin", appetite: "Tokenmaxxer" };
	var CLASS_FLOOR = 30;
	var BALANCED_SPREAD = 10;
	var BRAIN_TITLES = [[80, "Galaxy Brain"], [50, "Big Brain"], [30, "Wrinkly Brain"]];
	var MOODS = ["Locked in", "Vibing", "Cooked", "We're so back", "Touching grass", "Ghosting", "It's so over", "Not hatched yet"];
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
	// Markings: the look after the link's last "-" picks an eye style, a mouth and a crest; 64 more means shiny.
	var LOOKS = 64;
	var EYES = "o.O0";
	var MOUTHS = "wv-";
	var CRESTS = { Egg: ".:o~", Hatchling: "_^.~" };
	var MARK_SLOTS = {
		Egg: { crest: [2, 4] },
		Hatchling: { eyes: [[1, 3], [1, 5]], mouth: [2, 4], crest: [0, 4] },
		"Lil Guy": { eyes: [[1, 3], [1, 5]], mouth: [2, 4], crest: [0, 4] },
		"Big Guy": { eyes: [[1, 3], [1, 5]], mouth: [2, 4], crest: [0, 4] },
		Gigachad: { eyes: [[1, 3], [1, 5]], mouth: [2, 4], crest: [0, 4] },
		"GOAT": { mouth: [2, 4], crest: [0, 4] },
	};
	var SHINY_MARK = "\u2726 Shiny";
	// The picture always uses the site's dark colours, whatever this browser's theme.
	var C = { bg: "#201f1c", surface: "#2a2926", raised: "#34322e", fg: "#f3f1ea", muted: "#b5b1a7", line: "#46433d", accent: "#d97757" };
	var CLASS_COLORS = {
		Shipper: "#7ec488", "AFK Farmer": "#8fb8f0", "Loot Goblin": "#e8c35a", Tokenmaxxer: "#e58bd0",
		"Perfectly Balanced": "#9ed9d0", Noob: "#c9c4b8", Unhatched: "#a8a49a",
	};
	var MONO = 'ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Code", Menlo, Consolas, monospace';

	var el = function (id) {
		return document.getElementById(id);
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

	// The stage's art with its markings, the way the scanner's marked_art() draws it.
	function markedArt(stage, look, shiny) {
		var lines = ART[stage].map(function (line) { return line.split(""); });
		var slots = MARK_SLOTS[stage];
		var eye = look % 4;
		var mouth = Math.floor(look / 4) % 4;
		var crest = Math.floor(look / 16) % 4;
		if (eye && slots.eyes) slots.eyes.forEach(function (at) { lines[at[0]][at[1]] = EYES[eye]; });
		if (mouth && slots.mouth) lines[slots.mouth[0]][slots.mouth[1]] = MOUTHS[mouth - 1];
		if (crest) lines[slots.crest[0]][slots.crest[1]] = (CRESTS[stage] || "^~='")[crest];
		if (shiny) {
			(stage === "GOAT" ? [[3, 0], [3, 8]] : [[0, 8], [3, 0]]).forEach(function (at) {
				lines[at[0]][at[1]] = stage === "GOAT" ? "+" : "*";
			});
		}
		return lines.map(function (line) { return line.join(""); });
	}

	// The card from the address, or null: whole numbers joined by "-", each in range. The version, XP, the six stats,
	// the mood, the streak, the badges as bits and, from version 2, the look (plus 64 if shiny). Version 1 has eleven
	// numbers and the classic look; version 2 has twelve.
	function read(hash) {
		var parts = hash.split("-");
		if (!parts.every(function (p) { return /^\d{1,9}$/.test(p); })) return null;
		var n = parts.map(Number);
		if (!(n[0] === 1 && n.length === 11) && !(n[0] === CARD_VERSION && n.length === 12 && n[11] < LOOKS * 2)) return null;
		var look = n.length === 12 ? n[11] : 0;
		var stats = n.slice(2, 8);
		var badges = Object.keys(BADGE_NAMES);
		var ok = n[1] <= 10000000 && n[8] < MOODS.length && n[9] <= 100000 && n[10] < Math.pow(2, badges.length)
			&& stats.every(function (s) { return s <= 100 && s % 5 === 0; });
		if (!ok) return null;
		var card = { xp: n[1], stats: {}, mood: MOODS[n[8]], streak: n[9] };
		STAT_ORDER.forEach(function (s, i) {
			card.stats[s] = stats[i];
		});
		card.badges = badges.filter(function (b, i) { return Math.floor(n[10] / Math.pow(2, i)) % 2 === 1; }).map(function (b) { return BADGE_NAMES[b]; });
		card.level = Math.max(1, Math.min(LEVEL_MAX, Math.floor(Math.sqrt(Math.floor(card.xp / LEVEL_DIVISOR)))));
		card.stage = STAGES.filter(function (s) { return card.level >= s[0]; })[0][1];
		card.cls = classOf(card.stats);
		card.who = card.cls === "Unhatched" ? card.stage : card.stage + " " + card.cls;
		card.brain = (BRAIN_TITLES.filter(function (b) { return card.stats.brains >= b[0]; })[0] || [0, ""])[1];
		card.aura = stats.reduce(function (a, b) { return a + b; }, 0);
		card.shiny = look >= LOOKS;
		card.art = markedArt(card.stage, look % LOOKS, card.shiny);
		return card;
	}

	// The strongest of the four things a setup does, if any of them is strong enough to count. Ties go to the first.
	function classOf(stats) {
		var shape = Object.keys(CLASSES);
		var top = shape.reduce(function (best, s) { return stats[s] > stats[best] ? s : best; });
		var lowest = Math.min.apply(null, shape.map(function (s) { return stats[s]; }));
		if (stats[top] === 0) return "Unhatched";
		if (stats[top] < CLASS_FLOOR) return "Noob";
		if (lowest >= CLASS_FLOOR && stats[top] - lowest <= BALANCED_SPREAD) return "Perfectly Balanced";
		return CLASSES[top];
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

	function draw(canvas, card) {
		var ctx = canvas.getContext("2d");
		var W = canvas.width;
		var H = canvas.height;
		var left = 64;
		var right = W - 64;
		ctx.fillStyle = C.bg;
		ctx.fillRect(0, 0, W, H);
		ctx.fillStyle = "rgba(255, 255, 255, .025)"; // the site's faint scanlines
		for (var y = 2; y < H; y += 3) ctx.fillRect(0, y, W, 1);
		ctx.strokeStyle = C.line;
		ctx.lineWidth = 2;
		ctx.strokeRect(24, 24, W - 48, H - 48);
		ctx.textBaseline = "alphabetic";

		// Header: the name of the thing, and what it is.
		ctx.textAlign = "left";
		ctx.font = font(800, 30);
		ctx.fillStyle = C.accent;
		ctx.fillText("CC", left, 84);
		ctx.fillStyle = C.fg;
		ctx.fillText("level", left + ctx.measureText("CC ").width, 84);
		ctx.textAlign = "right";
		ctx.font = font(400, 22);
		ctx.fillStyle = C.muted;
		ctx.fillText("Claude Code, gamified", right, 84);

		// Left: the creature in its box, then the level and XP.
		ctx.fillStyle = C.surface;
		ctx.fillRect(left, 112, 360, 280);
		ctx.setLineDash([6, 6]);
		ctx.strokeRect(left, 112, 360, 280);
		ctx.setLineDash([]);
		var art = card.art;
		ctx.textAlign = "center";
		ctx.font = font(700, 44);
		ctx.fillStyle = C.accent;
		art.forEach(function (line, i) {
			ctx.fillText(line, left + 180, 112 + (280 - art.length * 52) / 2 + 40 + i * 52);
		});
		if (card.shiny) {
			// A few twinkles around the shiny creature, inside its box.
			ctx.font = font(700, 30);
			ctx.fillStyle = C.fg;
			[[left + 34, 150], [left + 326, 190], [left + 46, 360], [left + 312, 372]].forEach(function (at, i) {
				ctx.fillText(i % 2 ? "+" : "\u2726", at[0], at[1]);
			});
		}
		ctx.textAlign = "left";
		ctx.fillStyle = C.fg;
		ctx.font = font(800, 60);
		ctx.fillText("Lv " + card.level, left, 462);
		ctx.font = font(400, 24);
		ctx.fillStyle = C.muted;
		ctx.fillText(card.xp.toLocaleString("en-US") + " XP", left, 500);

		// Right: who it is, its mood, the six stats, Aura and badges.
		var x = 470;
		var width = right - x;
		var shiny = card.shiny ? " · " + SHINY_MARK : "";
		fit(ctx, card.who + shiny, 800, 52, 26, width);
		ctx.fillStyle = C.fg;
		ctx.fillText(card.stage, x, 150);
		if (card.who !== card.stage) {
			ctx.fillStyle = CLASS_COLORS[card.cls];
			ctx.fillText(card.cls, x + ctx.measureText(card.stage + " ").width, 150);
		}
		if (shiny) {
			// Not in gold, Loot Goblin's colour: the text colour, so it reads as a mark, not a class.
			ctx.fillStyle = C.fg;
			ctx.fillText(shiny, x + ctx.measureText(card.who).width, 150);
		}
		var mood = ["Mood: " + card.mood];
		if (card.streak) mood.push("streak " + card.streak);
		if (card.brain) mood.push(card.brain);
		fit(ctx, mood.join(" · "), 400, 24, 16, width);
		ctx.fillStyle = C.muted;
		ctx.fillText(mood.join(" · "), x, 192);
		var bar = x + 150;
		var barWidth = width - 150 - 70;
		var gap = 3;
		var segment = (barWidth - gap * 19) / 20;
		STAT_ORDER.forEach(function (s, i) {
			var middle = 236 + i * 42;
			ctx.textAlign = "left";
			ctx.font = font(400, 22);
			ctx.fillStyle = C.fg;
			ctx.fillText(s.charAt(0).toUpperCase() + s.slice(1), x, middle + 8);
			for (var k = 0; k < 20; k++) {
				ctx.fillStyle = k < Math.round(card.stats[s] / 5) ? C.accent : C.raised;
				ctx.fillRect(bar + k * (segment + gap), middle - 9, segment, 18);
			}
			ctx.textAlign = "right";
			ctx.font = font(700, 22);
			ctx.fillStyle = C.fg;
			ctx.fillText(String(card.stats[s]), right, middle + 8);
		});
		ctx.textAlign = "left";
		ctx.font = font(700, 24);
		ctx.fillStyle = C.fg;
		var aura = "Aura " + card.aura;
		ctx.fillText(aura, x, 500);
		if (card.badges.length) {
			var start = x + ctx.measureText(aura + " ").width;
			ctx.font = font(400, 22);
			ctx.fillStyle = C.muted;
			// As many badge names as fit, then how many more.
			var shown = card.badges.length;
			var text = "· " + card.badges.join(", ");
			while (shown > 0 && ctx.measureText(text).width > right - start) {
				shown -= 1;
				text = "· " + card.badges.slice(0, shown).join(", ") + (shown ? ", +" + (card.badges.length - shown) + " more"
					: card.badges.length + " badges");
			}
			ctx.fillText(text, start, 500);
		}

		// Footer: the question, and where to answer it.
		ctx.strokeStyle = C.line;
		ctx.setLineDash([6, 6]);
		ctx.beginPath();
		ctx.moveTo(left, 530);
		ctx.lineTo(right, 530);
		ctx.stroke();
		ctx.setLineDash([]);
		ctx.font = font(700, 26);
		ctx.fillStyle = C.fg;
		ctx.fillText("How big is your Claude Code?", left, 578);
		ctx.textAlign = "right";
		ctx.font = font(800, 28);
		ctx.fillStyle = C.accent;
		ctx.fillText("cclevel.com", right, 578);
	}

	var say = function (text) {
		el("said").textContent = text;
	};

	document.querySelectorAll("code[data-copy]").forEach(function (c) {
		c.after(copier(c));
	});
	var card = read(location.hash.slice(1));
	if (!card) {
		el("broken").hidden = false;
		return;
	}
	var canvas = el("shot");
	draw(canvas, card);
	canvas.dataset.art = card.art.join("\n");   // the creature as drawn, for tests
	canvas.setAttribute("aria-label", (card.shiny ? "Shiny " : "") + card.who + ", level " + card.level + ", " + card.xp.toLocaleString("en-US") + " XP. "
		+ STAT_ORDER.map(function (s) { return s + " " + card.stats[s]; }).join(", ") + ". Mood: " + card.mood + ".");
	var title = el("title");
	var dot = title.lastElementChild;
	title.replaceChildren(card.who + (card.shiny ? " · " + SHINY_MARK : ""), dot);
	document.title = card.who + " · Lv " + card.level + " · CC level";
	var caption = "My Claude Code is " + (card.shiny ? "a shiny " : /^[AEIOU]/.test(card.who) ? "an " : "a ") + card.who + ", Lv " + card.level + ". What's yours? cclevel.com";
	el("caption").textContent = caption;
	el("caption").nextElementSibling.setAttribute("aria-label", "Copy: " + caption);
	el("share").hidden = false;

	var png = function () {
		return new Promise(function (resolve, reject) {
			canvas.toBlob(function (blob) {
				if (blob) resolve(blob);
				else reject(new Error("no image"));
			}, "image/png");
		});
	};
	el("save").addEventListener("click", function () {
		png().then(function (blob) {
			var a = document.createElement("a");
			a.href = URL.createObjectURL(blob);
			a.download = "cclevel-" + card.who.toLowerCase().replace(/[^a-z]+/g, "-") + ".png";
			document.body.append(a);
			a.click();
			a.remove();
			setTimeout(function () {
				URL.revokeObjectURL(a.href);
			}, 10000);
			say("Saved. Post it with the line below.");
		}, function () {
			say("This browser could not make the image. A screenshot of the card works too.");
		});
	});
	// Copying a picture needs the newer clipboard; where it is missing, the button stays hidden.
	if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
		el("copy-image").hidden = false;
		el("copy-image").addEventListener("click", function () {
			navigator.clipboard.write([new ClipboardItem({ "image/png": png() })]).then(function () {
				say("Copied. Paste it into a post, with the line below.");
			}, function () {
				say("This browser would not copy the image. Save it instead.");
			});
		});
	}
})();
