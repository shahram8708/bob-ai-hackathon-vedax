import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE_URL ?? "http://localhost:8080";
const PASSWORD = process.env.DEMO_USER_PASSWORD;
const OUT = process.env.OUT_DIR ?? "shots";
const ROLE = process.env.ROLE ?? "admin";
const WIDTH = Number(process.env.WIDTH ?? 1440);
const HEIGHT = Number(process.env.HEIGHT ?? 900);
const PAGES = (process.env.PAGES ?? "/,/schedule,/schedule?tab=decisions,/schedule?tab=compare,/schedule?tab=runs,/operations,/vehicles,/vehicles/27,/trips,/alerts,/energy,/reports,/map,/infrastructure,/tariffs,/settings,/audit").split(",");

fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 });
const page = await context.newPage();
const problems = [];
page.on("console", (m) => { if (m.type() === "error") problems.push(`[console] ${page.url()} ${m.text()}`); });
page.on("pageerror", (e) => problems.push(`[pageerror] ${page.url()} ${e.message}`));
page.on("response", (r) => { if (r.status() >= 400 && r.url().includes("/api/")) problems.push(`[http ${r.status()}] ${r.request().method()} ${r.url()}`); });

await page.goto(`${BASE}/login`);
await page.getByLabel("Email").fill(`${ROLE}@chargeopt.example`);
await page.getByLabel("Password").fill(PASSWORD);
await page.getByRole("button", { name: "Sign in" }).click();
await page.waitForURL((u) => !u.pathname.startsWith("/login"));
for (const p of PAGES) {
  await page.goto(`${BASE}${p}`);
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1200);
  const name = (p === "/" ? "overview" : p.replace(/[/?=&]+/g, "_").replace(/^_/, "")) + `_${WIDTH}.png`;
  await page.screenshot({ path: path.join(OUT, name), fullPage: process.env.FULL === "1" });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 2) problems.push(`[overflow] ${p} horizontal overflow ${overflow}px`);
}
console.log(problems.length ? problems.join("\n") : "no problems");
await browser.close();
