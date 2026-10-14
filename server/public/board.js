// The board page. Reads /top.json and /board.json and nothing else. Board data is only ever written as text.
(function () {
	var SHOWN = 100;
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
	var cell = function (text, cls) {
		var td = document.createElement("td");
		td.textContent = text;
		if (cls) td.className = cls;
		return td;
	};
	var say = function (title, text) {
		var b = document.createElement("b");
		b.textContent = title;
		el("state").replaceChildren(b, document.createTextNode(text || ""));
		el("wrap").hidden = true;
		el("more").hidden = true;
		el("state").hidden = false;
	};

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
		var code = document.createElement("code");
		code.textContent = "--rank";
		el("bands").replaceChildren(
			"Below the top 1,000 (" + n(section.ranked) + " ranked): " + parts.join(" · ") + ". Run ",
			code,
			" to see your band.",
		);
		el("bands").hidden = false;
	}

	function draw() {
		if (!top) return;
		var wanted = el("class").value;
		var list = top[view] || [];
		var place = places(list);
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
			say(
				view === "season" ? "Nobody on the world list has earned XP this season yet." : "Nobody is on the world list yet.",
				" A creature appears once its owner runs --world on and it has check-ins on two different days.",
			);
			return;
		}
		if (!rows.length) {
			say("No " + wanted + " creatures in the top " + n(list.length) + ".");
			return;
		}
		var shown = everything ? rows : rows.slice(0, SHOWN);
		el("rows").replaceChildren.apply(
			el("rows"),
			shown.map(function (x) {
				var r = x.r;
				var tr = document.createElement("tr");
				var name = cell(r.name, "name");
				if (r.sus === true) {
					var tag = document.createElement("span");
					tag.className = "sus";
					tag.textContent = "sus";
					tag.title = "80% or more of at least 14 witnessed days at the full 550 XP";
					name.append(" ", tag);
				}
				if (typeof r.github === "string") {
					var gh = document.createElement("a");
					gh.className = "gh";
					gh.href = "https://github.com/" + encodeURIComponent(r.github);
					gh.rel = "noopener noreferrer";
					gh.textContent = "\u2713 " + r.github + " · " + n(r.commits);
					gh.title = "Verified GitHub account · public commits co-signed by Claude";
					name.append(" ", gh);
				}
				tr.append(cell(x.place, "rank"), name, cell(r.stage + " " + r.class, "kind"), cell(r.level, "num"), cell(n(r.xp), "num"), cell(r.power, "num"));
				return tr;
			}),
		);
		el("more").hidden = everything || rows.length <= SHOWN;
		el("more").textContent = "Show all " + n(rows.length);
		el("state").hidden = true;
		el("wrap").hidden = false;
	}

	function world() {
		var items = [];
		var add = function (label, value) {
			var div = document.createElement("div");
			var dt = document.createElement("dt");
			var dd = document.createElement("dd");
			dt.textContent = label;
			dd.textContent = value;
			div.append(dt, dd);
			items.push(div);
		};
		add("Creatures", n(board.creatures));
		add("Listed all-time", n(board.all.ranked));
		add("Listed season", n(board.season.ranked));
		var t = board.totals;
		if (t) {
			var classes = Object.keys(t.classes).sort(function (a, b) {
				return t.classes[b] - t.classes[a];
			});
			add("Top class, " + Math.round((100 * t.classes[classes[0]]) / board.creatures) + "%", classes[0]);
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
			add("Median level", median);
			add("Marked sus", n(t.sus));
		} else {
			add("Totals", "appear once 100 creatures are counted");
		}
		el("world").replaceChildren.apply(el("world"), items);
	}

	["season", "all"].forEach(function (name) {
		el("tab-" + name).addEventListener("click", function () {
			view = name;
			everything = false;
			el("tab-season").setAttribute("aria-selected", String(name === "season"));
			el("tab-all").setAttribute("aria-selected", String(name === "all"));
			draw();
		});
	});
	el("class").addEventListener("change", draw);
	el("more").addEventListener("click", function () {
		everything = true;
		draw();
	});

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
			el("meta").textContent = "Season " + board.month + " · updated " + board.generated;
			world();
			draw();
		})
		.catch(function () {
			el("meta").textContent = "Board unavailable";
			el("world").replaceChildren();
			say("The board could not be loaded.", " Try again in a few minutes.");
		});
})();
