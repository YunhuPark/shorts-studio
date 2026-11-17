import { expect, test, type Locator, type Page } from "@playwright/test";

const card = (page: Page, n: number) => page.getByRole("article", { name: `컷 ${n}` });
const chips = (c: Locator) => c.locator(".phrases .chip");
const openDemo = async (page: Page) => {
  await page.goto("/projects/demo");
  await expect(page.getByRole("heading", { level: 1, name: "데모 프로젝트" })).toBeVisible();
};

test("home lists the project and shows which services are connected", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "데모 프로젝트" })).toBeVisible();
  await expect(page.getByText("컷 4개 · 이미지 3/4")).toBeVisible();
  await expect(page.getByText("음성(Azure) 연결됨")).toBeVisible();
  await expect(page.getByText("이미지(Gemini) 연결됨")).toBeVisible();
});

test("the storyboard shows every shot and marks the one without an image", async ({ page }) => {
  await openDemo(page);
  await expect(page.getByRole("article")).toHaveCount(4);
  await expect(card(page, 4).getByText("이미지 없음")).toBeVisible();
  await expect(card(page, 1).getByRole("img")).toBeVisible();
  await expect(chips(card(page, 1))).toHaveText(["저기 오늘은 두 개네요?"]); // one chip, "두 개" kept together
});

test("typing a line updates the subtitle preview live, keeping '두 개' together, and saving persists it", async ({ page }) => {
  await openDemo(page);
  const c = card(page, 1);
  const line = c.getByLabel("대사");
  await line.fill("저기요, 오늘은 컵라면이 두 개네요? 무슨 날이에요?");
  // compare the chips themselves: getByText would also match the textarea that holds the same words
  await expect(chips(c)).toHaveText(["저기요 오늘은", "컵라면이 두 개네요?", "무슨 날이에요?"]);

  await c.getByRole("button", { name: "저장", exact: true }).click();
  await expect(c.getByRole("button", { name: "저장됨 ✓" })).toBeVisible();

  await page.reload();
  await expect(card(page, 1).getByLabel("대사")).toHaveValue("저기요, 오늘은 컵라면이 두 개네요? 무슨 날이에요?");
});

test("an empty line gives a silent shot with no subtitle", async ({ page }) => {
  await openDemo(page);
  await expect(card(page, 3).getByText("자막 없음")).toBeVisible();
});

test("regenerating asks for a cost confirmation, and cancelling spends nothing", async ({ page }) => {
  await openDemo(page);
  await expect(page.getByText(/오늘 \$0\.00 \/ \$1\.00/)).toBeVisible();
  const c = card(page, 2);
  await c.getByRole("button", { name: "이미지 다시 생성" }).click();
  const confirm = c.getByRole("group", { name: "비용 확인" });
  await expect(confirm).toContainText("약 $0.050 사용 (추정)");
  await confirm.getByRole("button", { name: "취소" }).click();
  await expect(confirm).toBeHidden();
  await page.reload();
  await expect(page.getByText(/오늘 \$0\.00 \/ \$1\.00/)).toBeVisible();
});

test("confirming a regeneration replaces the image and records the spend", async ({ page }) => {
  await openDemo(page);
  const c = card(page, 2);
  const before = await c.getByRole("img").getAttribute("src");
  await c.getByRole("button", { name: "이미지 다시 생성" }).click();
  await c.getByRole("group", { name: "비용 확인" }).getByRole("button", { name: "생성" }).click();
  await expect(c.getByText(/이미지 생성 중/)).toBeVisible();
  await expect(c.getByText(/이미지 생성 중/)).toBeHidden();
  await expect.poll(() => c.getByRole("img").getAttribute("src")).not.toBe(before);
  await expect(page.getByText(/오늘 \$0\.05 \/ \$1\.00/)).toBeVisible();
});

test("a voice sample can be generated and played", async ({ page }) => {
  await openDemo(page);
  const row = page.locator(".speaker", { hasText: "grandpa" });
  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: "들어보기" }).click();
  await expect(row.locator("audio")).toBeVisible();
  await expect(row.locator("audio")).toHaveAttribute("src", /^blob:/);
});

test("declining paid voice confirmation makes no synthesis request", async ({ page }) => {
  await openDemo(page);
  const row = page.locator(".speaker", { hasText: "grandpa" });
  const paidRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/voices/sample") && request.method() === "POST") {
      paidRequests.push(request.url());
    }
  });
  page.once("dialog", (dialog) => dialog.dismiss());
  await row.getByRole("button", { name: "들어보기" }).click();
  await expect(row.getByRole("status")).toContainText("취소");
  await expect(row.locator("audio")).toHaveCount(0);
  expect(paidRequests).toEqual([]);
});

test("an invalid speaking rate disables saving the voice", async ({ page }) => {
  await openDemo(page);
  const row = page.locator(".speaker", { hasText: "grandpa" });
  await row.getByLabel("속도").fill("fast");
  await expect(row.getByRole("button", { name: "저장" })).toBeDisabled();
  await expect(row.getByRole("button", { name: "들어보기" })).toBeDisabled();
});

test("rendering shows progress and then a playable video with a download link", async ({ page }) => {
  await openDemo(page);
  const panel = page.locator("#render");
  await panel.getByRole("button", { name: "영상 렌더 시작" }).click();
  await expect(panel.getByRole("progressbar")).toBeVisible();
  await expect(panel.locator("video")).toHaveAttribute("src", /\/api\/projects\/demo\/renders\/render-/);
  await expect(panel.getByRole("link", { name: "다운로드" })).toHaveAttribute("download", /^render-.*\.mp4$/);
});

test("an unknown project shows a clear message instead of a blank page", async ({ page }) => {
  await page.goto("/projects/does-not-exist");
  await expect(page.getByText("프로젝트를 찾을 수 없습니다.")).toBeVisible();
});

test("the image viewer opens on click and closes with Escape", async ({ page }) => {
  await openDemo(page);
  await card(page, 1).getByRole("button", { name: "컷 1 이미지 크게 보기" }).click();
  const viewer = page.getByRole("dialog", { name: "컷 1 이미지" });
  await expect(viewer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(viewer).toBeHidden();
});

test("face check badges only the shots that feature a reference character", async ({ page }) => {
  await openDemo(page);
  await expect(page.getByText("얼굴 일치", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "얼굴 일치 검사" }).click();
  await expect(card(page, 2).getByText("얼굴 일치", { exact: true })).toBeVisible();
  await expect(page.getByText("얼굴 일치", { exact: true })).toHaveCount(1); // shots 1, 3, 4 have no reference character
});

test("the background music is chosen before rendering and the choice is sent to the API", async ({ page }) => {
  await openDemo(page);
  const panel = page.locator("#render");
  const select = panel.getByLabel("배경음악");
  await expect(select.locator("option")).toHaveCount(3);
  await expect(select).toHaveValue("night_piano"); // the original score stays the default
  await select.selectOption("warm_major");
  const request = page.waitForRequest((r) => r.url().endsWith("/api/projects/demo/render") && r.method() === "POST");
  await panel.getByRole("button", { name: "영상 렌더 시작" }).click();
  expect((await request).postDataJSON()).toMatchObject({ bgm_style: "warm_major", ai_label: true });
  await expect(panel.locator("video")).toHaveAttribute("src", /render-/);
});

test("the AI-generated label is on by default, and switching it off is sent to the API", async ({ page }) => {
  await openDemo(page);
  const panel = page.locator("#render");
  const box = panel.getByLabel("영상에 “AI 생성” 표시 넣기 (권장)");
  await expect(box).toBeChecked();
  await box.uncheck();
  const request = page.waitForRequest((r) => r.url().endsWith("/api/projects/demo/render") && r.method() === "POST");
  await panel.getByRole("button", { name: "영상 렌더 시작" }).click();
  expect((await request).postDataJSON()).toMatchObject({ ai_label: false });
  await expect(panel.locator("video")).toHaveAttribute("src", /render-/);
});

const speaker = (page: Page, who: string) => page.locator(".speaker").filter({ has: page.locator("strong", { hasText: who }) });

test("voice recommendation orders candidates by the requested age and fills voice, speed and pitch without saving", async ({ page }) => {
  await openDemo(page);
  const row = speaker(page, "grandpa");
  await row.getByRole("button", { name: "grandpa 목소리 추천 받기" }).click();   // defaults: 남 / 노년
  const picks = row.getByLabel("grandpa 추천 목소리").getByRole("button");
  await expect(picks).toHaveText(["BongJin · 130Hz", "HyunsuMultilingual · 135Hz", "Hyunsu · 135Hz"]);
  await expect(row.getByText(/근사치/)).toBeVisible();   // it admits that old voices are approximated
  await picks.nth(0).click();
  await expect(row.getByLabel("속도")).toHaveValue("-15%");
  await expect(row.getByRole("button", { name: "저장", exact: true })).toBeEnabled();   // not saved until the user saves

  await row.getByLabel("grandpa 성별").selectOption("female");
  await row.getByLabel("grandpa 나이대").selectOption("young");
  await expect(row.getByLabel("grandpa 추천 목소리")).toBeHidden();   // changing the profile clears stale picks
  await row.getByRole("button", { name: "grandpa 목소리 추천 받기" }).click();
  await expect(row.getByLabel("grandpa 추천 목소리").getByRole("button").first()).toHaveText("SeoHyeon · 247Hz");
});

test("narration mode switches every other character to the narrator's voice after confirmation", async ({ page }) => {
  await openDemo(page);
  const group = page.getByRole("group", { name: "내레이션 모드" });
  await group.getByRole("button", { name: "내레이션으로 통일" }).click();
  await expect(group).toContainText("grandpa");
  await group.getByRole("button", { name: "취소" }).click();
  await expect(group.getByRole("button", { name: "내레이션으로 통일" })).toBeVisible();   // cancelling changes nothing

  await group.getByRole("button", { name: "내레이션으로 통일" }).click();
  await group.getByRole("button", { name: "바꾸기" }).click();
  await expect(group.getByRole("status")).toContainText("내레이터 목소리로 바뀌었습니다");
  await page.reload();
  const row = speaker(page, "grandpa");
  await expect(row.locator("select").first()).toHaveValue("ko-KR-InJoonNeural"); // the voice picker comes first in the row
  await expect(row.getByLabel("속도")).toHaveValue("+22%");
});


test("the landing page tells the story, links to the demo, and does not overflow on a phone", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("스토리보드 한 편이 쇼츠가 됩니다");
  for (const name of ["쓴다", "고른다", "다시 만든다", "내보낸다"]) await expect(page.getByRole("heading", { level: 2, name })).toBeAttached();
  await expect(page.getByRole("link", { name: "데모 열어 보기" }).first()).toHaveAttribute("href", "/projects/convenience-store");
  // the 3D background either starts or falls back to the CSS one; either way the page works and nothing throws
  await expect(page.locator("[data-ready], [data-fallback]").first()).toBeAttached({ timeout: 20_000 });
  for (const size of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(size);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `horizontal overflow at ${size.width}px`).toBeLessThanOrEqual(0);
  }
  expect(errors).toEqual([]);
});

test("with reduced motion the story is a plain list: every step is readable without scrolling through a pin", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  await page.goto("/");
  for (const name of ["쓴다", "고른다", "다시 만든다", "내보낸다"]) await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  await context.close();
});

test("a prompt becomes a storyboard, and one click makes every image", async ({ page }) => {
  await page.goto("/projects");
  await page.getByRole("link", { name: "새 이야기 만들기" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "새 이야기 만들기" })).toBeVisible();
  const make = page.getByRole("button", { name: "스토리보드 만들기" });
  await expect(make).toBeDisabled(); // nothing written yet
  await page.getByLabel("이야기").fill("비 오는 밤 버스 정류장에서 서로 모르는 두 사람이 만난다");
  await page.getByLabel("컷 수").selectOption("6");
  await page.getByLabel("화풍").selectOption("anime");
  await make.click();
  // the cost is shown first; nothing is spent until it is confirmed
  await expect(page.getByRole("group", { name: "비용 확인" })).toContainText("$0.010");
  await page.getByRole("group", { name: "비용 확인" }).getByRole("button", { name: "만들기" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "마지막 버스" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("article")).toHaveCount(6);
  await expect(page.getByText("이미지 없음 6")).toBeVisible();

  const panel = page.getByRole("region", { name: "이미지 만들기" });
  await panel.getByRole("button", { name: /빈 컷 이미지 모두 만들기 \(6컷\)/ }).click();
  await expect(panel.getByRole("group", { name: "비용 확인" })).toContainText("6컷, 약 $0.30");
  await panel.getByRole("button", { name: "만들기" }).click();
  await expect(page.getByRole("article").getByRole("img")).toHaveCount(6, { timeout: 60_000 });
  await expect(panel).toBeHidden(); // nothing missing any more
  await expect(page.getByText("이미지 없음")).toHaveCount(0);
});

test("a prompt that asks for something we do not make is refused with a reason and nothing is created", async ({ page }) => {
  await page.goto("/projects/new");
  await page.getByLabel("이야기").fill("야한 이야기를 만들어 줘");
  await page.getByRole("button", { name: "스토리보드 만들기" }).click();
  await page.getByRole("group", { name: "비용 확인" }).getByRole("button", { name: "만들기" }).click();
  await expect(page.locator("form").getByRole("alert")).toContainText("성적인 표현");
  await expect(page).toHaveURL(/\/projects\/new$/);
});
