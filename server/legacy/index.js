// The board's first address, cclevel-board.cclevel.workers.dev, kept for older copies of the scanner and for
// invite links shared before the move. The scanner's calls go on to the board unchanged, through a service binding;
// pages send the browser to the new address (it keeps the invite code after "#"). Nothing is logged or stored here.
const BOARD = "https://go.cclevel.workers.dev";
const CALLS = /^\/(api\/|board\.json$|top\.json$)/;

export default {
	fetch(request, env) {
		const url = new URL(request.url);
		if (CALLS.test(url.pathname)) return env.BOARD.fetch(request);
		return Response.redirect(BOARD + url.pathname + url.search, 301);
	},
};
