// Records screenshots and a short screen recording of the running dashboard for the README.
// Needs the API (python -m shorts_studio serve --data .data --port 8765) and the UI (npm run dev -- -p 3010) running,
// and a project called "convenience-store". It never clicks a paid action (image regeneration / render).
// Usage: node scripts/capture-media.mjs [baseUrl] [projectId]
import { mkdirSync, renameSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const base = process.argv[2] ?? "http://localhost:3010";
const project = process.argv[3] ?? "convenience-store";
const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(here, "../../docs/media");
const tmp = path.join(out, "_video");
mkdirSync(out, { recursive: true });
rmSync(tmp, { recursive: true, force: true });

// swiftshader lets headless Chromium run the landing page's WebGL background
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });

// 0. landing page: the hero, and the story one scroll later (the camera is flying through the frames)
for (const [file, vp] of [["00-landing.png", { width: 1440, height: 900 }], ["00-landing-phone.png", { width: 390, height: 844 }]]) {
  const landing = await browser.newContext({ viewport: vp, deviceScaleFactor: vp.width < 500 ? 2 : 1, isMobile: vp.width < 500, hasTouch: vp.width < 500 });
  const lp = await landing.newPage();
  await lp.goto(base + "/", { waitUntil: "networkidle" });
  await lp.locator("[data-ready]").waitFor({ timeout: 60_000 });
  await lp.waitForTimeout(3500);
  await lp.screenshot({ path: path.join(out, file) });
  if (vp.width > 500) {
    await lp.evaluate((h) => window.scrollTo(0, h * 1.3), vp.height);
    await lp.waitForTimeout(2500);
    await lp.screenshot({ path: path.join(out, "00-landing-story.png") });
  }
  await landing.close();
}

const desktop = await browser.newContext({
  viewport: { width: 1280, height: 860 },
  recordVideo: { dir: tmp, size: { width: 1280, height: 860 } },
  locale: "ko-KR",
});
const page = await desktop.newPage();
page.setDefaultTimeout(60_000);
const shot = (name, opts = {}) => page.screenshot({ path: path.join(out, name), ...opts });
const pause = (ms) => page.waitForTimeout(ms);

// 1. project list
await page.goto(base + "/projects");
await page.getByRole("heading", { name: /컵라면/ }).first().waitFor();
await pause(700);
await shot("01-home.png");

// 2. project page
await page.goto(`${base}/projects/${project}`);
await page.getByRole("heading", { level: 1 }).waitFor();
await page.getByRole("article").first().waitFor();
await pause(1500);
await shot("02-project-top.png");

// 3. storyboard cards
await page.evaluate(() => document.querySelector(".grid")?.scrollIntoView({ block: "start" }));
await pause(1200);
await shot("03-storyboard.png");

// 4. live subtitle preview: type in a line, do not save, then discard by reloading
const card = page.getByRole("article", { name: "컷 5" });
await card.scrollIntoViewIfNeeded();
const line = card.getByLabel("대사");
await line.click();
await line.press("End");
await line.pressSequentially(" 그래서 천천히 한 번 더 말했다", { delay: 45 });
await pause(900);
await card.screenshot({ path: path.join(out, "04-live-subtitles.png") });
await pause(500);
await page.reload();
await page.getByRole("article").first().waitFor();

// 5. voice recommendation
const row = page.locator(".speaker").filter({ has: page.locator("strong", { hasText: "grandpa" }) });
await row.scrollIntoViewIfNeeded();
await row.getByRole("button", { name: "grandpa 목소리 추천 받기" }).click();
await row.getByLabel("grandpa 추천 목소리").waitFor();
await pause(900);
await page.locator('section[aria-label="목소리"]').screenshot({ path: path.join(out, "05-voice-recommend.png") });

// 6. face check (local computer vision, free)
await page.getByRole("button", { name: "얼굴 일치 검사" }).click();
await page.getByText("얼굴 일치", { exact: true }).first().waitFor({ timeout: 120_000 });
// bring the first shots that feature a character (5 and onwards) under the sticky header so the badges are visible
await page.evaluate(() => {
  const card = [...document.querySelectorAll("article")].find((a) => a.getAttribute("aria-label") === "컷 5");
  window.scrollTo(0, card.getBoundingClientRect().top + window.scrollY - 125);
});
await pause(1500);
await shot("06-face-check.png");

// 7. render panel with the finished video
const panel = page.locator("#render");
await panel.scrollIntoViewIfNeeded();
await pause(1200);
await shot("07-render.png");
await desktop.close();   // finishes the video file

const video = await page.video().path();
renameSync(video, path.join(out, "dashboard-tour.webm"));
rmSync(tmp, { recursive: true, force: true });

// 8. phone width
const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const m = await phone.newPage();
m.setDefaultTimeout(60_000);
await m.goto(`${base}/projects/${project}`);
await m.getByRole("article").first().waitFor();
await m.waitForTimeout(1500);
await m.screenshot({ path: path.join(out, "08-mobile.png") });
await browser.close();
console.log("saved to", out);
