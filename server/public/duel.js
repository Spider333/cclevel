// The duel invite page. The code is the part of the address after "#", which browsers never send to a server.
// This page reads it and shows how to accept. It makes no request of any kind.
(function () {
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

	var code = location.hash.slice(1).toLowerCase();
	if (!/^[0-9a-f]{32}$/.test(code)) {
		el("broken").hidden = false;
		return;
	}
	el("duel-cmd").textContent = "/pet duel " + location.origin + "/duel#" + code;
	document.querySelectorAll("code[data-copy]").forEach(function (c) {
		c.after(copier(c));
	});
	el("steps").hidden = false;
})();
