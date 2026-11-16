import { expect, test, type Page } from "@playwright/test";

// Runs against the real demo/ bundle served in demo mode: no keys, no providers, pre-built assets (npm run test:e2e:demo).
const PROJECT = "/projects/convenience-store";
// exact: with 26 shots "컷 1" would also match 컷 10 to 컷 19
const card = (page: Page, n: number) => page.getByRole("article", { name: `컷 ${n}`, exact: true });
const speaker = (page: Page, who: string) => page.locator(".speaker").filter({ has: page.locator("strong", { hasText: who }) });
const openDemo = async (page: Page) => {
  await page.goto(PROJECT);
  await expect(page.getByRole("heading", { level: 1, name: "새벽 3시, 컵라면 두 개" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(26);
};

test("the demo says what it is on every page and does not pretend services are connected", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.getByRole("note", { name: "데모 안내" })).toContainText("실제 이미지·음성 생성은 하지 않고");
  await expect(page.getByText("연결됨")).toHaveCount(0);
  await openDemo(page);
  await expect(page.getByRole("note", { name: "데모 안내" })).toBeVisible();
});

test("all 26 shot images of the bundle really load", async ({ page }) => {
  await openDemo(page);
  const loaded = async () =>
    page.locator("article img").evaluateAll((imgs) => (imgs as HTMLImageElement[]).filter((i) => i.complete && i.naturalWidth > 0).length);
  for (const n of [1, 13, 26]) await card(page, n).scrollIntoViewIfNeeded(); // thumbnails are lazy
  await page.evaluate(async () => {
    for (const a of document.querySelectorAll("article")) {
      a.scrollIntoView();
      await new Promise((r) => setTimeout(r, 40));
    }
  });
  await expect.poll(loaded, { timeout: 30_000 }).toBe(26);
});

test("edits cannot be saved: the user is told so and the line is unchanged after a reload", async ({ page }) => {
  await openDemo(page);
  const c = card(page, 1);
  const before = await c.getByLabel("대사").inputValue();
  await c.getByLabel("대사").fill("저장되면 안 되는 대사");
  await c.getByRole("button", { name: "저장", exact: true }).click();
  await expect(c.getByRole("alert")).toContainText("읽기 전용");
  await page.reload();
  await expect(card(page, 1).getByLabel("대사")).toHaveValue(before);
});

test("typing still gives a live subtitle preview and voice recommendation works", async ({ page }) => {
  await openDemo(page);
  const c = card(page, 1);
  await c.getByLabel("대사").fill("저기요, 오늘은 컵라면이 두 개네요? 무슨 날이에요?");
  await expect(c.locator(".phrases .chip")).toHaveText(["저기요 오늘은", "컵라면이 두 개네요?", "무슨 날이에요?"]);
  const row = speaker(page, "grandpa");
  await row.getByRole("button", { name: "grandpa 목소리 추천 받기" }).click();
  await expect(row.getByLabel("grandpa 추천 목소리").getByRole("button").first()).toHaveText("BongJin · 130Hz");
});

test("a voice sample plays: the pre-made mp3 is served and decodes to a real clip", async ({ page }) => {
  await openDemo(page);
  const row = speaker(page, "grandpa");
  await row.getByRole("button", { name: "들어보기" }).click();
  const audio = row.locator("audio");
  await expect(audio).toBeVisible();
  await expect.poll(() => audio.evaluate((a) => (a as HTMLAudioElement).duration), { timeout: 20_000 }).toBeGreaterThan(3);
});

test("the face check shows the pre-computed results, including the honest 'check this one' and 'no face' cases", async ({ page }) => {
  await openDemo(page);
  await page.getByRole("button", { name: "얼굴 일치 검사" }).click();
  for (const label of ["얼굴 일치", "얼굴 확인 필요", "얼굴 안 보임"]) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
  }
});

test("regenerating is replayed for free: a progress overlay, then back to normal, and no spend", async ({ page }) => {
  await openDemo(page);
  const c = card(page, 5);
  await c.getByRole("button", { name: "이미지 다시 생성" }).click();
  await expect(c.getByRole("group", { name: "비용 확인" })).toContainText("$0.000");
  await c.getByRole("button", { name: "생성", exact: true }).click();
  await expect(c.getByRole("status")).toContainText("이미지 생성 중");
  await expect(c.getByRole("status")).toBeHidden();
  await expect(page.getByText(/오늘 \$0\.00 \/ \$2\.00/)).toBeVisible();
});

test("rendering is replayed and the pre-built video plays", async ({ page }) => {
  await openDemo(page);
  const panel = page.locator("#render");
  await panel.getByRole("button", { name: "영상 렌더 시작" }).click();
  await expect(panel.getByRole("progressbar")).toBeVisible();
  const video = panel.locator("video");
  await expect(video).toHaveAttribute("src", /\/renders\/render-20261112-000000\.mp4$/);
  await expect.poll(() => video.evaluate((v) => (v as HTMLVideoElement).duration), { timeout: 30_000 }).toBeGreaterThan(60);
});

test("the new-story page explains that the demo opens the finished sample and then does so", async ({ page }) => {
  await page.goto("/projects/new");
  await expect(page.getByText("데모에서는 AI를 호출하지 않습니다")).toBeVisible();
  await page.getByLabel("이야기").fill("무엇이든 적어 보세요");
  await page.getByRole("button", { name: "스토리보드 만들기" }).click();
  await expect(page.getByRole("group", { name: "비용 확인" })).toContainText("비용 없음");
  await page.getByRole("group", { name: "비용 확인" }).getByRole("button", { name: "만들기" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "새벽 3시, 컵라면 두 개" })).toBeVisible({ timeout: 15_000 });
});
