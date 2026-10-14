// The board page. Reads /top.json and /board.json and nothing else. Board data is only ever written as text.
(function () {
	var SHOWN = 100;
	var TOTALS_FLOOR = 100;
	// The same drawings as the /pet card (ART in skills/pet/scripts/cclevel.py).
	var ART = {
		Egg: ["   ___   ", "  /   \\  ", " |  .  | ", "  \\___/  "],
		Hatchling: ["   ___   ", "  /o o\\  ", " _\\_^_/_ ", "  '   '  "],
		"Lil Guy": ["  .-^-.  ", " ( o o ) ", "  \\ ~ /  ", "  /| |\\  "],
		"Main Character": ["  .-^-.  ", " ( o o ) ", " /\\ ~ /\\ ", "  /| |\\  "],
		Giga: [" \\.-^-./ ", " ( o o ) ", " /\\ = /\\ ", " _/| |\\_ "],
		"Final Boss": ["*\\.-^-./*", " ( @ @ ) ", "</\\ = /\\>", " _/| |\\_ "],
	};
	var JOIN = [
		["1", "/pet join the leaderboard"],
		["2", "/pet put me on the world list"],
	];
	var top = null;
	var board = null;
	var view = "season";
	var everything = false;
	var el = function (id) {
		return document.getElementById(id);
	};
	var n = function (x) {
		return Number(x).toLocaleString("en");
	};
	var make = function (tag, cls, text) {
		var node = document.createElement(tag);
		if (cls) node.className = cls;
		if (text !== undefined) node.textContent = text;
		return node;
	};
	var cell = function (content, cls) {
		var td = make("td", cls);
		if (typeof content === "object") td.append(content);
		else td.textContent = content;
		return td;
	};
	var art = function (stage, cls) {
		var pre = make("pre", cls, (Object.prototype.hasOwnProperty.call(ART, stage) ? ART[stage] : ART.Egg).join("\n"));
		pre.setAttribute("aria-hidden", "true");
		return pre;
	};
	var chip = function (cls) {
		var span = make("span", "chip", cls);
		span.dataset.class = cls;
		return span;
	};
	var tags = function (r, into) {
		if (r.sus === true) {
			var sus = make("span", "sus", "sus");
			sus.title = "80% or more of at least 14 witnessed days at the full 550 XP";
			into.append(" ", sus);
		}
		if (typeof r.github === "string") {
			var gh = make("a", "gh", "\u2713 " + r.github + " · " + n(r.commits));
			gh.href = "https://github.com/" + encodeURIComponent(r.github);
			gh.rel = "noopener noreferrer";
			gh.title = "Verified GitHub account · public commits co-signed by Claude";
			into.append(" ", gh);
		}
	};
	var hideAll = function () {
		el("podium").hidden = true;
		el("wrap").hidden = true;
		el("more").hidden = true;
	};
	var say = function (title, text) {
		hideAll();
		var b = make("b", null, title);
		el("state").className = "state";
		el("state").replaceChildren(b, document.createTextNode(text || ""));
		el("state").hidden = false;
	};

	// A copy button for a command. Where the clipboard is refused, the command is selected instead.
	var copier = function (code) {
		var text = code.textContent;
		var copy = make("button", "copy", "copy");
		copy.type = "button";
		copy.setAttribute("aria-label", "Copy: " + text);
		copy.addEventListener("click", function () {
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
	document.querySelectorAll("code[data-copy]").forEach(function (code) {
		code.after(copier(code));
	});

	// Nobody listed yet: a wobbling egg and the two steps to get on the list.
	function empty(title) {
		hideAll();
		var list = make("ol", "cmds");
		JOIN.forEach(function (step) {
			var li = make("li");
			var code = make("code", null, step[1]);
			li.append(make("span", "step", step[0] + "."), code, copier(code));
			list.append(li);
		});
		el("state").className = "state empty";
		el("state").replaceChildren(
			art("Egg", "egg"),
			make("b", null, title),
			(function () {
				var p = make("p", null, "Be the first. Install the plugin (");
				var a = make("a", null, "how it works");
				a.href = "/how#install";
				p.append(a, "), then in Claude Code:");
				return p;
			})(),
			list,
			make("p", null, "You show up after check-ins on two different days."),
		);
		el("state").hidden = false;
	}

	// Equal XP shares a place: 1, 2, 2, 4.
	function places(list) {
		var place = 0;
		return list.map(function (r, i) {
			if (i === 0 || r.xp !== list[i - 1].xp) place = i + 1;
			return place;
		});
	}

	function bands() {
		var section = board && board[view];
		var cuts = section && section.bands;
		if (!cuts || !cuts.length) {
			el("bands").hidden = true;
			return;
		}
		var wanted = [1, 5, 10, 20, 50];
		var parts = cuts
			.filter(function (b) {
				return wanted.indexOf(b[0]) >= 0;
			})
			.map(function (b) {
				return "top " + b[0] + "% from " + n(b[1]) + " XP";
			});
		el("bands").replaceChildren(
			"Below the top 1,000 (" + n(section.ranked) + " ranked): " + parts.join(" · ") + ". Run ",
			make("code", null, "--rank"),
			" to see your band.",
		);
		el("bands").hidden = false;
	}

	function podium(rows) {
		el("podium").replaceChildren.apply(
			el("podium"),
			rows.map(function (x, i) {
				var r = x.r;
				var li = make("li", "p" + (i + 1));
				var who = make("div", "who", r.name);
				var tagline = make("div", "tags");
				tagline.append(chip(r.class));
				tags(r, tagline);
				var xp = make("div", "xp", n(r.xp));
				xp.append(" ", make("small", null, "XP"));
				li.append(
					make("div", "place", (x.place === 1 ? "\u265B " : "") + "#" + x.place),
					art(r.stage),
					who,
					xp,
					make("div", "sub", r.stage + " · Lv " + r.level + " · Aura " + r.power),
					tagline,
				);
				return li;
			}),
		);
		el("podium").hidden = false;
	}

	function draw() {
		if (!top) return;
		var wanted = el("class").value;
		var list = top[view] || [];
		var place = places(list);
		var lead = list.length ? Math.max(Number(list[0].xp) || 0, 1) : 1;
		var rows = list
			.map(function (r, i) {
				return { r: r, place: place[i] };
			})
			.filter(function (x) {
				return !wanted || x.r.class === wanted;
			});
		el("xp-head").textContent = view === "season" ? "Season XP" : "XP since joining";
		el("panel").setAttribute("aria-labelledby", "tab-" + view);
		bands();
		if (!list.length) {
			empty(view === "season" && (top.all || []).length ? "Nobody has earned XP this season yet." : "The world list is empty. For now.");
			return;
		}
		if (!rows.length) {
			say("No " + wanted + " creatures in the top " + n(list.length) + ".", " Try another class.");
			return;
		}
		podium(rows.slice(0, 3));
		var rest = rows.slice(3);
		var shown = everything ? rest : rest.slice(0, SHOWN);
		el("rows").replaceChildren.apply(
			el("rows"),
			shown.map(function (x) {
				var r = x.r;
				var tr = make("tr");
				var name = make("td", "name");
				var creature = make("div", "creature");
				var label = make("span", null, r.name);
				tags(r, label);
				creature.append(art(r.stage, "mini"), label);
				name.append(creature);
				var kind = make("td");
				kind.append(make("span", "stage", r.stage), chip(r.class));
				var xp = make("td", "num", n(r.xp));
				var bar = make("span", "bar");
				bar.style.width = Math.max(0, Math.min(100, (100 * (Number(r.xp) || 0)) / lead)) + "%";
				xp.append(bar);
				tr.append(cell(x.place, "rank"), name, kind, cell(r.level, "num"), xp, cell(r.power, "num"));
				return tr;
			}),
		);
		el("wrap").hidden = !rest.length;
		el("more").hidden = everything || rest.length <= SHOWN;
		el("more").textContent = "Show " + n(rest.length - shown.length) + " more";
		el("state").hidden = true;
	}

	function world() {
		var items = [];
		var add = function (label, value, cls) {
			var div = make("div", cls);
			var dd = make("dd");
			if (typeof value === "object") dd.append.apply(dd, value);
			else dd.textContent = value;
			div.append(make("dt", null, label), dd);
			items.push(div);
		};
		add("creatures", n(board.creatures));
		add("listed all-time", n(board.all.ranked));
		add("listed season", n(board.season.ranked));
		var t = board.totals;
		if (t) {
			var classes = Object.keys(t.classes).sort(function (a, b) {
				return t.classes[b] - t.classes[a];
			});
			add("top class " + Math.round((100 * t.classes[classes[0]]) / board.creatures) + "%", classes[0]);
			var half = board.creatures / 2;
			var seen = 0;
			var median = 1;
			for (var lv = 1; lv < t.levels.length; lv++) {
				seen += t.levels[lv];
				if (seen >= half) {
					median = lv;
					break;
				}
			}
			add("median level", median);
			add("marked sus", n(t.sus));
		} else {
			var have = Math.max(0, Math.min(TOTALS_FLOOR, Number(board.creatures) || 0));
			var meter = make("span", "meter");
			var fill = make("span");
			fill.style.width = have + "%";
			meter.append(fill);
			meter.setAttribute("role", "img");
			meter.setAttribute("aria-label", have + " of " + TOTALS_FLOOR + " creatures counted");
			add("world totals", [make("span", null, "unlock at " + TOTALS_FLOOR + " creatures (" + have + "/" + TOTALS_FLOOR + ")"), meter], "unlock");
		}
		el("world").replaceChildren.apply(el("world"), items);
	}

	var pick = function (name) {
		view = name;
		everything = false;
		el("tab-season").setAttribute("aria-selected", String(name === "season"));
		el("tab-all").setAttribute("aria-selected", String(name === "all"));
		draw();
	};
	["season", "all"].forEach(function (name) {
		el("tab-" + name).addEventListener("click", function () {
			pick(name);
		});
	});
	// Arrow keys move between the two tabs, as tabs do.
	document.querySelector(".tabs").addEventListener("keydown", function (e) {
		if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
		var name = view === "season" ? "all" : "season";
		pick(name);
		el("tab-" + name).focus();
		e.preventDefault();
	});
	el("class").addEventListener("change", draw);
	el("more").addEventListener("click", function () {
		everything = true;
		draw();
		// The button is gone now: keep the keyboard where the new rows start.
		var first = el("rows").children[SHOWN];
		if (first) {
			first.tabIndex = -1;
			first.focus();
		}
	});

	// The hero creature evolves from Egg to Final Boss while its level counts up, then hatches again.
	// Under reduced motion it stays as written in the page: one still Final Boss.
	(function evolve() {
		var pre = el("evo-art");
		if (!pre || (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) return;
		var stages = [["Egg", 1], ["Hatchling", 5], ["Lil Guy", 15], ["Main Character", 30], ["Giga", 45], ["Final Boss", 60]];
		var max = stages[stages.length - 1][1];
		var i = 0;
		var level = 1;
		var show = function () {
			pre.textContent = ART[stages[i][0]].join("\n");
			el("evo-stage").textContent = stages[i][0];
			pre.classList.remove("pop");
			void pre.offsetWidth; // restart the pop animation
			pre.classList.add("pop");
		};
		var paint = function () {
			el("evo-level").textContent = "Lv " + level;
			el("evo-bar").style.width = (100 * level) / max + "%";
		};
		var step = function () {
			if (level >= max) {
				setTimeout(restart, 2200);
				return;
			}
			level += 1;
			if (i + 1 < stages.length && level >= stages[i + 1][1]) {
				i += 1;
				show();
			}
			paint();
			setTimeout(step, 70);
		};
		var restart = function () {
			i = 0;
			level = 1;
			show();
			paint();
			setTimeout(step, 900);
		};
		restart();
	})();

	var load = function (path) {
		return fetch(path).then(function (res) {
			if (!res.ok) throw new Error(res.status);
			return res.json();
		});
	};
	Promise.all([load("/top.json"), load("/board.json")])
		.then(function (data) {
			top = data[0];
			board = data[1];
			el("meta").textContent = "season " + board.month + " · built " + board.generated;
			world();
			draw();
		})
		.catch(function () {
			el("meta").textContent = "board offline";
			el("world").replaceChildren();
			say("The board could not be loaded.", " Try again in a few minutes.");
		});
})();
