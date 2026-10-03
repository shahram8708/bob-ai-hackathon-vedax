import { chromium, request } from "playwright";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE_URL ?? "http://localhost:8080";
const PASSWORD = process.env.DEMO_USER_PASSWORD;
const OUT = path.resolve(process.env.DEMO_DIR ?? "../demo");
const RAW = path.join(OUT, "raw");
const SIZE = { width: 1440, height: 900 };
const PACE = Number(process.env.PACE ?? 1);

if (!PASSWORD) throw new Error("DEMO_USER_PASSWORD is required");
fs.rmSync(RAW, { recursive: true, force: true });
fs.mkdirSync(RAW, { recursive: true });

const OVERLAY = () => {
  const install = () => {
    if (document.getElementById("__demo_caption")) return;
    const style = document.createElement("style");
    style.textContent = `
      #__demo_caption{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:2147483647;pointer-events:none;
        max-width:880px;width:calc(100% - 64px);background:rgba(18,51,38,.94);color:#F4F2ED;border-radius:10px;padding:12px 18px 13px;
        font:400 15px/1.45 'IBM Plex Sans',system-ui,sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.28);transition:opacity .25s ease;opacity:0}
      #__demo_caption .t{font-weight:600;font-size:16px;color:#fff}
      #__demo_caption .k{font:500 11px 'IBM Plex Mono',monospace;letter-spacing:.12em;text-transform:uppercase;color:#C9E86A;margin-bottom:3px;display:flex;justify-content:space-between;gap:12px}
      #__demo_cursor{position:fixed;z-index:2147483646;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;pointer-events:none;
        background:rgba(201,232,106,.55);border:2px solid #1F4D3A;transition:transform .12s ease;left:-40px;top:-40px}
      #__demo_cursor.down{transform:scale(.7)}`;
    document.head.appendChild(style);
    const box = document.createElement("div");
    box.id = "__demo_caption";
    box.innerHTML = '<div class="k"><span class="s"></span><span class="tab"></span></div><div class="t"></div><div class="b"></div>';
    document.body.appendChild(box);
    const cur = document.createElement("div");
    cur.id = "__demo_cursor";
    document.body.appendChild(cur);
    window.addEventListener("mousemove", (e) => { cur.style.left = e.clientX + "px"; cur.style.top = e.clientY + "px"; }, true);
    window.addEventListener("mousedown", () => cur.classList.add("down"), true);
    window.addEventListener("mouseup", () => cur.classList.remove("down"), true);
    window.__caption = (step, title, body, tab) => {
      box.querySelector(".s").textContent = step || "";
      box.querySelector(".tab").textContent = tab || "";
      box.querySelector(".t").textContent = title || "";
      box.querySelector(".b").textContent = body || "";
      box.style.opacity = title ? "1" : "0";
    };
    if (window.__pendingCaption) window.__caption(...window.__pendingCaption);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
};

const T0 = Date.now();
const segments = [];
const captions = [];
const tabs = [];
let active = null;
let activeSince = 0;
let stepNo = 0;

async function prepare() {
  const ctx = await request.newContext({ baseURL: BASE, timeout: 180000 });
  const login = await ctx.post("/api/auth/login", { data: { email: "admin@chargeopt.example", password: PASSWORD } });
  if (!login.ok()) throw new Error(`Login failed: ${login.status()}`);
  const reset = await ctx.post("/api/simulation/reset", { data: { scheduler_mode: "baseline", simulation_enabled: false, history_days: 30 } });
  if (!reset.ok()) throw new Error(`Reset failed: ${await reset.text()}`);
  let fast = 0;
  for (let i = 0; i < 60 && fast < 3; i++) {
    const t = Date.now();
    await ctx.get("/api/dashboard/overview");
    fast = Date.now() - t < 1500 ? fast + 1 : 0;
    await new Promise((r) => setTimeout(r, 2000));
  }
  await ctx.post("/api/auth/logout");
  await ctx.dispose();
}

const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--disable-gpu", "--disable-extensions", "--disable-background-networking"] });
const context = await browser.newContext({ viewport: SIZE, deviceScaleFactor: 1, acceptDownloads: true });
const frames = [];
let frameNo = 0;
let castStopped = null;

async function startCast(tab) {
  if (!tab.cdp) {
    tab.cdp = await context.newCDPSession(tab.page);
    tab.cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
      if (active !== tab) return;
      const file = path.join(RAW, `f${String(frameNo++).padStart(6, "0")}.jpg`);
      fs.writeFileSync(file, Buffer.from(data, "base64"));
      frames.push({ t: Math.max(metadata.timestamp * 1000, frames.length ? frames[frames.length - 1].t + 1 : 0), file });
      await tab.cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
    });
  }
  await tab.cdp.send("Page.startScreencast", { format: "jpeg", quality: 82, maxWidth: SIZE.width, maxHeight: SIZE.height, everyNthFrame: 1 });
}

async function stopCast(tab) {
  await tab.cdp?.send("Page.stopScreencast").catch(() => {});
}
await context.addInitScript(OVERLAY);
context.setDefaultTimeout(150000);
const cuts = [];

async function waited(fn) {
  const a = Date.now();
  const result = await fn();
  const b = Date.now();
  if (b - a > 1500) cuts.push([a + 700, b - 300]);
  return result;
}
const problems = [];

async function openTab(label, url) {
  const page = await context.newPage();
  const tab = { page, label, created: Date.now() };
  tabs.push(tab);
  page.on("pageerror", (e) => problems.push(`[pageerror] ${label}: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && problems.push(`[console] ${label}: ${m.text()}`));
  page.on("response", (r) => r.status() >= 500 && problems.push(`[http ${r.status()}] ${r.url()}`));
  if (url) await page.goto(`${BASE}${url}`);
  await activate(tab);
  return tab;
}

async function activate(tab) {
  const now = Date.now();
  if (active && now > activeSince) segments.push({ tab: active, start: activeSince, end: now });
  if (active && active !== tab) await stopCast(active);
  active = tab;
  activeSince = now;
  await tab.page.bringToFront();
  await startCast(tab);
}

function tabLabel() {
  return tabs.length > 1 ? `Tab ${tabs.indexOf(active) + 1} of ${tabs.length} · ${active.label}` : "";
}

async function caption(title, body = "", hold = 3600) {
  stepNo += 1;
  const step = `Step ${String(stepNo).padStart(2, "0")}`;
  const page = active.page;
  await page.evaluate(([s, t, b, tab]) => {
    window.__pendingCaption = [s, t, b, tab];
    window.__caption?.(s, t, b, tab);
  }, [step, title, body, tabLabel()]);
  captions.push({ at: Date.now(), tab: active, title, body });
  await page.waitForTimeout(hold * PACE);
}

async function move(locator) {
  const page = active.page;
  await waited(() => locator.scrollIntoViewIfNeeded());
  const box = await locator.boundingBox();
  if (!box) return;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 18 });
  await page.waitForTimeout(250);
}

async function click(locator) {
  await waited(() => locator.waitFor({ state: "visible", timeout: 150000 }));
  await move(locator);
  await locator.click();
  await active.page.waitForTimeout(500);
}

async function type(locator, text) {
  await click(locator);
  await locator.fill("");
  await locator.pressSequentially(text, { delay: 35 });
}

async function nav(name) {
  await click(active.page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true }));
  active.label = name;
  await active.page.waitForLoadState("networkidle").catch(() => {});
  await active.page.waitForTimeout(900);
}

async function scroll(px, steps = 6) {
  for (let i = 0; i < steps; i++) {
    await active.page.mouse.wheel(0, px / steps);
    await active.page.waitForTimeout(120);
  }
  await active.page.waitForTimeout(500);
}

async function settle(ms = 1200) {
  await waited(() => active.page.waitForLoadState("networkidle").catch(() => {}));
  await active.page.waitForTimeout(ms);
}

async function signIn(email) {
  const page = active.page;
  await page.goto(`${BASE}/login`);
  await settle(800);
  await type(page.getByLabel("Email"), email);
  await type(page.getByLabel("Password"), PASSWORD);
  await click(page.getByRole("button", { name: "Sign in" }));
  await waited(() => page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 150000 }));
  await settle(1500);
}

try {
  if (process.env.SKIP_RESET !== "1") await prepare();
  const main = await openTab("Overview", "/login");
  await settle(1200);
  await caption("ChargeOpt — rule-based EV fleet charging", "A deterministic platform that keeps every vehicle ready for departure while avoiding expensive charging. No AI or ML is used.", 4200);
  await caption("Role-based sign-in", "The fleet administrator signs in. Sessions use an HTTP-only cookie and every sign-in is written to the audit log.", 2600);
  await signIn("admin@chargeopt.example");

  await caption("Live fleet overview", "100 vehicles across three depots. Readiness, charger status and energy are visible on one screen and refresh over WebSockets.", 4500);
  await move(main.page.locator("text=Static baseline schedule is active"));
  await caption("Starting point: the static baseline", "Vehicles are charged first-come-first-served, straight to maximum SoC, with no tariff, priority or load coordination.", 4500);
  await move(main.page.getByText("Departures at risk"));
  await caption("Departures at risk", "Eight departures will miss their required SoC under the static schedule — including emergency vehicle EV-042.", 4200);
  await scroll(520);
  await caption("Charger board", "Every charger by depot: status, the vehicle charging, SoC against target, and the next reservation. One charger is faulted and one is in maintenance.", 4500);
  await scroll(-520);

  const sched = await openTab("Schedule", "/schedule");
  await settle(1500);
  await caption("Second tab: the charging schedule", "A timeline of charger reservations over the next 24 hours, drawn over the tariff calendar (blue off-peak, green shoulder, orange peak).", 4800);
  await caption("Baseline behaviour", "The static plan starts charging immediately — running straight into the 18:00–22:00 peak tariff.", 3800);
  await click(sched.page.getByRole("radio", { name: "Preview rule-based" }));
  await settle(1500);
  await caption("Preview the rule-based plan", "Same fleet, same chargers: urgent vehicles charge now, flexible charging moves into the overnight off-peak window.", 4800);
  await click(sched.page.getByRole("tab", { name: "Baseline vs rule-based" }));
  await settle(2500);
  await caption("Baseline vs rule-based comparison", "Computed from the current snapshot: higher projected readiness, fewer vehicles at risk, far less peak-period energy and a lower average price.", 5200);
  await move(sched.page.getByText("Linear-programming reference"));
  await caption("Mathematical optimisation benchmark", "A HiGHS linear program gives a reference optimum, showing how close the explainable rules come on price per kWh.", 4500);

  await click(sched.page.getByRole("button", { name: "Activate rule-based scheduler" }));
  await caption("Activate the rule-based scheduler", "The fleet manager confirms. The change is audited and a new schedule run starts immediately.", 3200);
  await click(sched.page.getByRole("dialog").getByRole("button", { name: "Activate" }));
  await settle(2500);
  await click(sched.page.getByRole("tab", { name: "Timeline" }));
  await settle(1500);
  await caption("Rule-based schedule applied", "Priority rules P1–P5, charger capacity, connector compatibility and depot load limits are enforced. No charger is ever double-booked.", 4800);

  const ev027 = sched.page.locator('button[title^="EV-027 ·"]').first();
  await click(ev027);
  await settle(800);
  await caption("Explainable decision — PRD example EV-027", "42% → 72% by its 07:30 departure: flexible, so rule R4 shifts it into the off-peak window and shows the saving versus charging now.", 6000);
  await click(sched.page.getByRole("button", { name: "Close panel" }));

  await click(sched.page.getByRole("tab", { name: "Decisions & rules" }));
  await settle(1500);
  await caption("Every vehicle's decision and the rules behind it", "EV-042's emergency trip is P1 (R2): tariff optimisation is bypassed and it charges immediately. Ties break on departure, then SoC.", 5200);
  await scroll(400);
  await caption("Conflicts resolved by priority", "Where vehicles compete for a charger, rule R3 records who held the slot and where the lower-priority vehicle was placed.", 4200);
  await scroll(-400);

  await activate(main);
  await main.page.reload();
  await settle(1500);
  await caption("Back to tab 1: resume charger telemetry", "Chargers without an OCPP link are simulated. All simulated values are labelled as such.", 3600);
  await click(main.page.getByRole("button", { name: "Resume" }));
  await settle(1500);
  await click(main.page.getByRole("button", { name: "+60 min" }));
  await waited(() => main.page.waitForResponse((r) => r.url().includes("/simulation/advance"), { timeout: 150000 }).catch(() => {}));
  await settle(3000);
  await caption("One hour later", "Sessions started at their reserved slots and SoC has risen. The scheduler re-evaluated the plan as vehicles departed and charging completed (R7).", 5000);
  await scroll(520);
  await caption("Live sessions on the charger board", "Each active session shows the vehicle, power and progress towards its target SoC.", 3800);
  await scroll(-520);

  await nav("Charging ops");
  const ops = main;
  await settle(1500);
  await caption("Charging operations", "The charging operator manages charger states and live sessions. Commands go over OCPP when a charger is connected.", 4200);
  const chargingRow = ops.page.locator("tbody tr", { has: ops.page.getByText("Charging", { exact: true }) }).first();
  await click(chargingRow.getByRole("button", { name: "Status" }));
  await settle(600);
  const dialog = ops.page.getByRole("dialog");
  await dialog.getByLabel("New status").selectOption("fault");
  await type(dialog.getByLabel("Note"), "Ground-fault trip reported by depot technician");
  await caption("A charger fails mid-session", "The operator records a fault. The active session is marked interrupted and an alert is raised.", 3800);
  await click(dialog.getByRole("button", { name: "Set fault" }));
  await settle(2500);
  await caption("Automatic reassignment (R5)", "The schedule is recalculated: the interrupted vehicle and every reservation on that charger move to compatible chargers.", 4500);

  await activate(sched);
  await sched.page.reload();
  await settle(2000);
  await click(sched.page.getByRole("tab", { name: "Decisions & rules" }));
  await settle(1500);
  await caption("Schedule tab updated", "The re-planned vehicles carry rule R5 in their explanation, so operators can see why they moved.", 4000);
  await click(sched.page.getByRole("tab", { name: "Timeline" }));
  await settle(1500);
  const planned = sched.page.locator('button[title*="· P4 ·"], button[title*="· P5 ·"]').first();
  await click(planned);
  await settle(800);
  const drawer = sched.page.getByRole("dialog");
  const start = drawer.getByLabel("Start (fleet time)");
  const current = await start.inputValue();
  const [d, t] = current.split("T");
  const [hh, mm] = t.split(":").map(Number);
  const shifted = new Date(Date.UTC(...d.split("-").map((x, i) => (i === 1 ? Number(x) - 1 : Number(x))), hh, mm) + 90 * 60000);
  const later = `${shifted.toISOString().slice(0, 10)}T${shifted.toISOString().slice(11, 16)}`;
  await start.fill(later);
  await type(drawer.getByLabel("Reason (recorded in the audit log)"), "Driver delayed at loading bay — move charging 90 minutes later");
  await caption("Manual override", "An authorised operator moves a reservation. Overrides are fixed bookings; the scheduler plans every other vehicle around them (R8).", 4500);
  await click(drawer.getByRole("button", { name: "Apply override" }));
  await settle(2500);
  await caption("Override applied and audited", "Any displaced reservation raises a conflict alert and is rescheduled automatically.", 3500);
  if (await sched.page.getByRole("dialog").isVisible().catch(() => false)) await click(sched.page.getByRole("button", { name: "Close panel" }));

  await activate(main);
  await nav("Alerts");
  await caption("Alerts & exceptions", "At-risk departures, charger faults, interrupted sessions, conflicts, missed slots, peak-approaching and readiness alerts.", 4200);
  await click(main.page.getByRole("button", { name: "Acknowledge" }).first());
  await type(main.page.getByRole("dialog").getByLabel(/Note/), "Technician dispatched");
  await click(main.page.getByRole("dialog").getByRole("button", { name: "Acknowledge" }));
  await settle(1200);
  await click(main.page.getByRole("button", { name: "Resolve" }).first());
  await type(main.page.getByRole("dialog").getByLabel(/Resolution/), "Charger reset and verified; vehicle reassigned");
  await caption("Acknowledge, resolve, record", "Operators take ownership of an exception and close it with a resolution note — both actions are audited.", 3600);
  await click(main.page.getByRole("dialog").getByRole("button", { name: "Resolve" }));
  await settle(1200);

  await nav("Trips & drivers");
  await caption("Trips and departure requirements", "Operations managers enter or import trips. Each trip carries a departure time and an operator-defined required SoC.", 3800);
  await click(main.page.getByRole("button", { name: "New trip" }));
  const tripDialog = main.page.getByRole("dialog");
  const vehicleSelect = tripDialog.getByLabel("Vehicle");
  const optionValue = await vehicleSelect.locator("option", { hasText: "EV-031" }).first().getAttribute("value");
  if (optionValue) await vehicleSelect.selectOption(optionValue);
  await type(tripDialog.getByLabel("Destination"), "Electronic City hub");
  await type(tripDialog.getByLabel("Estimated distance (km)"), "120");
  await tripDialog.getByLabel("Required departure SoC %").fill("85");
  await caption("New trip triggers re-planning", "Saving the trip immediately recalculates the schedule for the assigned vehicle (step 8: recalculate on events).", 3600);
  await click(tripDialog.getByRole("button", { name: "Create trip" }));
  await settle(2000);

  await nav("Vehicles");
  await type(main.page.getByLabel("Search vehicles"), "EV-061");
  await settle(1500);
  await caption("PRD example EV-061", "75% against a 65% requirement: rule R1 — already ready, so no charging is scheduled and no energy is wasted.", 4200);
  await click(main.page.getByRole("link", { name: "EV-061" }).first());
  await settle(1500);
  await click(main.page.getByRole("tab", { name: "Contingency options" }));
  await settle(1500);
  await caption("Rule-based contingency suggestions", "If a vehicle cannot complete its route: nearest compatible depot or public charger, mobile charging and towing, with ETA and estimated cost.", 4800);

  await nav("Energy & cost");
  await caption("Energy & cost dashboard", "Energy priced at the applicable tariff period. Demand charges, solar and battery-storage effects are shown separately as estimates.", 4600);
  await scroll(700);
  await caption("Trends and vehicle-to-grid rules", "Daily energy by tariff period, and advisory V2G export opportunities that never compromise the next departure.", 4500);
  await scroll(-700);

  await nav("Reports");
  await caption("Reports and success metrics", "Readiness, missed requirements, lower-cost energy share, charger utilisation, conflicts prevented, interventions and recalculation time.", 4800);
  await click(main.page.getByRole("button", { name: "Fleet readiness report" }));
  await settle(1500);
  const download = main.page.waitForEvent("download", { timeout: 15000 }).catch(() => null);
  await click(main.page.getByRole("link", { name: /Download CSV/ }));
  const file = await download;
  if (file) await file.saveAs(path.join(OUT, "fleet-readiness-report.csv"));
  await caption("Downloadable CSV", "Every report — charging history, utilisation, cost by tariff period, scheduled vs actual and more — exports to CSV.", 3800);

  await nav("Map");
  await settle(2500);
  await caption("Multi-depot map", "Depots with free chargers, vehicles coloured by readiness, and contingency providers.", 4000);

  await nav("Tariffs");
  await caption("Tariff management", "Peak, shoulder, off-peak and custom periods with demand charges, plus dynamic utility price feeds that override static rates.", 4200);

  await nav("Rules & settings");
  await caption("Configurable deterministic rules", "Urgency window, departure buffer, tie-breakers, safety reserve, approval workflow and alert thresholds — every change is audited.", 4500);

  await nav("Audit log");
  await settle(1200);
  await caption("Complete audit trail", "Sign-ins, the scheduler activation, manual overrides, charger faults, configuration changes and resolved exceptions.", 4500);

  await click(main.page.getByRole("button", { name: "Sign out" }));
  await settle(1200);
  await caption("Driver view", "Drivers only see their own vehicle and charging instructions.", 2600);
  await signIn("driver@chargeopt.example");
  await caption("My vehicle", "EV-027's driver sees current SoC, the required SoC for tomorrow's trip and exactly when and where to plug in.", 5200);
  await caption("ChargeOpt", "Reliable fleet readiness with transparent, cost-aware charging coordination.", 3600);
  await activate(main);
} finally {
  castStopped = Date.now();
  if (active) await stopCast(active);
  for (const t of tabs) await t.page.close().catch(() => {});
  await context.close();
  await browser.close();
}

const fmt = (ms) => {
  const h = String(Math.floor(ms / 3600000)).padStart(2, "0");
  const m = String(Math.floor((ms % 3600000) / 60000)).padStart(2, "0");
  const sec = String(Math.floor((ms % 60000) / 1000)).padStart(2, "0");
  return `${h}:${m}:${sec},${String(Math.floor(ms % 1000)).padStart(3, "0")}`;
};
const origin = frames[0].t;
cuts.sort((a, b) => a[0] - b[0]);
const merged = [];
for (const [a, b] of cuts) {
  if (b <= a) continue;
  const last = merged[merged.length - 1];
  if (last && a <= last[1]) last[1] = Math.max(last[1], b);
  else merged.push([a, b]);
}
cuts.splice(0, cuts.length, ...merged);
const squeeze = (t) => t - cuts.reduce((sum, [a, b]) => sum + Math.max(0, Math.min(t, b) - a), 0);
const lines = [];
frames.forEach((f, i) => {
  const next = i + 1 < frames.length ? frames[i + 1].t : castStopped;
  const span = squeeze(next) - squeeze(f.t);
  if (span < 1) return;
  lines.push(`file '${f.file.split(path.sep).join("/")}'`, `duration ${(span / 1000).toFixed(3)}`);
});
lines.push(`file '${frames[frames.length - 1].file.split(path.sep).join("/")}'`);
fs.writeFileSync(path.join(RAW, "frames.txt"), lines.join("\n"));
const final = path.join(OUT, "ChargeOpt_demo.mp4");
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", path.join(RAW, "frames.txt"), "-vf", `scale=${SIZE.width}:${SIZE.height}:force_original_aspect_ratio=decrease,pad=${SIZE.width}:${SIZE.height}:(ow-iw)/2:(oh-ih)/2:color=0xF4F2ED,fps=25`, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", final]);
const srt = captions.map((c, i) => {
  const startMs = Math.max(0, squeeze(c.at) - squeeze(origin));
  const endMs = Math.max(startMs + 500, squeeze(i + 1 < captions.length ? captions[i + 1].at : castStopped) - squeeze(origin));
  return `${i + 1}\n${fmt(startMs)} --> ${fmt(endMs)}\n${c.title}${c.body ? `\n${c.body}` : ""}\n`;
});
fs.writeFileSync(path.join(OUT, "ChargeOpt_demo.srt"), srt.join("\n"));
console.log(JSON.stringify({ final, seconds: Math.round((squeeze(castStopped) - squeeze(origin)) / 1000), trimmed_s: Math.round(cuts.reduce((a, [x, y]) => a + y - x, 0) / 1000), frames: frames.length, captions: captions.length, elapsed_s: Math.round((Date.now() - T0) / 1000) }));
console.log(problems.length ? problems.join("\n") : "no problems");
