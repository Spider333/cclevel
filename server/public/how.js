// The "How it works" page: copy buttons, and the example card typed out once it scrolls into view.
// It reads nothing from the board and makes no request.
(function () {
	// A copy button for a command. Where the clipboard is refused, the command is selected instead.
	var copier = function (code) {
		var copy = document.createElement("button");
		copy.className = "copy";
		copy.type = "button";
		copy.textContent = "copy";
		copy.setAttribute("aria-label", "Copy: " + code.textContent);
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
			if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(code.textContent).then(done, select);
			else select();
		});
		return copy;
	};
	document.querySelectorAll("code[data-copy]").forEach(function (code) {
		code.after(copier(code));
	});

	// The card prints line by line, like the terminal does. Without motion, or without the observer, it stays as written.
	var card = document.getElementById("card-demo");
	var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
	if (!card || still || !("IntersectionObserver" in window)) return;
	var lines = card.textContent.split("\n");
	var watch = new IntersectionObserver(function (entries) {
		if (!entries[0].isIntersecting) return;
		watch.disconnect();
		// Cleared only now, so a card that never comes into view keeps its text.
		card.style.minHeight = card.offsetHeight + "px";
		card.textContent = "";
		var i = 0;
		var tick = setInterval(function () {
			card.textContent += (i ? "\n" : "") + lines[i];
			i += 1;
			if (i >= lines.length) clearInterval(tick);
		}, 70);
	});
	watch.observe(card);
})();
