// The invite page. The code is the part of the address after "#", which browsers never send to a server.
// This page reads it, names the group and shows how to join. It makes no request of any kind.
(function () {
	// The same word lists as server/src/names.js and the scanner: a group's name is worked out on each machine.
	var ADJECTIVES = [
		"Amber", "Brave", "Bright", "Calm", "Clever", "Cosmic", "Crisp", "Curious",
		"Dapper", "Daring", "Dusty", "Eager", "Early", "Fabled", "Fuzzy", "Gentle",
		"Giddy", "Golden", "Grand", "Hardy", "Hazel", "Humble", "Ivory", "Jolly",
		"Keen", "Kind", "Lively", "Lucky", "Lunar", "Mellow", "Merry", "Mighty",
		"Misty", "Mossy", "Nimble", "Noble", "Patient", "Plucky", "Polar", "Proud",
		"Quick", "Quiet", "Rapid", "Rustic", "Rusty", "Sandy", "Silent", "Silver",
		"Sleepy", "Snowy", "Solar", "Speedy", "Spry", "Steady", "Stormy", "Sunny",
		"Swift", "Tidy", "Velvet", "Vivid", "Wandering", "Wise", "Witty", "Zesty",
	];
	var ANIMALS = [
		"Axolotl", "Badger", "Bat", "Bear", "Beaver", "Bison", "Capybara", "Cat",
		"Crane", "Crow", "Deer", "Dolphin", "Dragon", "Duck", "Eagle", "Falcon",
		"Ferret", "Finch", "Fox", "Frog", "Gecko", "Goose", "Hare", "Hawk",
		"Hedgehog", "Heron", "Ibex", "Jackal", "Koala", "Lemur", "Lynx", "Magpie",
		"Marten", "Mole", "Moose", "Moth", "Newt", "Octopus", "Otter", "Owl",
		"Panda", "Penguin", "Pika", "Puffin", "Quail", "Rabbit", "Raccoon", "Raven",
		"Robin", "Seal", "Shrew", "Sloth", "Snail", "Sparrow", "Squid", "Stoat",
		"Swan", "Tapir", "Toad", "Turtle", "Vole", "Walrus", "Wombat", "Wren",
	];
	var el = function (id) {
		return document.getElementById(id);
	};

	// A copy button for a command. Where the clipboard is refused, the command is selected instead.
	var copier = function (code) {
		var copy = document.createElement("button");
		copy.className = "copy";
		copy.type = "button";
		copy.textContent = "copy";
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

	// Same rule as the scanner: SHA-256 of "cclevel-group:" + code, first two 4-hex-digit numbers.
	function groupName(code) {
		var bytes = new TextEncoder().encode("cclevel-group:" + code);
		return crypto.subtle.digest("SHA-256", bytes).then(function (buf) {
			var hex = Array.prototype.map
				.call(new Uint8Array(buf), function (b) {
					return ("0" + b.toString(16)).slice(-2);
				})
				.join("");
			return ADJECTIVES[parseInt(hex.slice(0, 4), 16) % ADJECTIVES.length] + " " + ANIMALS[parseInt(hex.slice(4, 8), 16) % ANIMALS.length] + " Crew";
		});
	}

	var code = location.hash.slice(1).toLowerCase();
	if (!/^[0-9a-f]{32}$/.test(code)) {
		el("broken").hidden = false;
		return;
	}
	var link = location.origin + "/join#" + code;
	el("join-cmd").textContent = "/pet join " + link;
	document.querySelectorAll("code[data-copy]").forEach(function (c) {
		c.after(copier(c));
	});
	el("steps").hidden = false;
	groupName(code).then(
		function (name) {
			var em = document.createElement("span");
			em.className = "dot";
			em.textContent = ".";
			el("title").replaceChildren("Join " + name, em);
			document.title = "Join " + name + " · cclevel board";
		},
		function () {
			// No Web Crypto (a very old browser): the page still works without the name.
		},
	);
})();
