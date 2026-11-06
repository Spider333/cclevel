// The six class pages a /pet evolve post links to: static pages, the site's CSP, a same-site 1200×630 picture.
import { SELF } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import headers from "../public/_headers?raw";
import shipper from "../public/class/shipper.html?raw";
import afk from "../public/class/afk-farmer.html?raw";
import goblin from "../public/class/loot-goblin.html?raw";
import tokens from "../public/class/tokenmaxxer.html?raw";
import balanced from "../public/class/perfectly-balanced.html?raw";
import noob from "../public/class/noob.html?raw";

const PAGES = { shipper, "afk-farmer": afk, "loot-goblin": goblin, tokenmaxxer: tokens, "perfectly-balanced": balanced, noob };
const CSP = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'";

describe("class pages", () => {
	it("keeps the site's CSP as it was", () => {
		expect(headers).toContain(`Content-Security-Policy: ${CSP}`);
	});

	for (const [slug, page] of Object.entries(PAGES)) {
		it(`/class/${slug} is served with the CSP and a same-site 1200x630 og:image that exists`, async () => {
			const res = await SELF.fetch(`https://cclevel.com/class/${slug}`);
			expect(res.status).toBe(200);
			expect(res.headers.get("content-security-policy")).toBe(CSP);
			const body = await res.text();
			expect(body).toBe(page);
			const image = body.match(/<meta property="og:image" content="([^"]+)">/)[1];
			expect(new URL(image).host).toBe("cclevel.com");
			expect(body).toContain('<meta property="og:image:width" content="1200">');
			expect(body).toContain('<meta property="og:image:height" content="630">');
			expect(body).toContain('<meta name="twitter:card" content="summary_large_image">');
			expect(body).toContain(`<meta property="og:url" content="https://cclevel.com/class/${slug}">`);
			const png = new Uint8Array(await (await SELF.fetch(`https://cclevel.com${new URL(image).pathname}`)).arrayBuffer());
			const view = new DataView(png.buffer);
			expect([view.getUint32(16), view.getUint32(20)]).toEqual([1200, 630]);   // the PNG's IHDR width and height
			// Nothing on the page loads from another host, and it runs no script: it is the same for everyone.
			expect(body).not.toMatch(/<script|<img|<iframe|<video|src="https?:/);
			for (const href of body.matchAll(/<link [^>]*href="([^"]+)"/g)) expect(href[1].startsWith("/")).toBe(true);
			expect(body).toContain("What's yours?");
			expect(body).toContain("/plugin install cclevel@cclevel");
			expect(body).toContain("/pet learn");
		});
	}

	it("an unknown class is the 404 page", async () => {
		const res = await SELF.fetch("https://cclevel.com/class/wizard");
		expect(res.status).toBe(404);
	});
});
