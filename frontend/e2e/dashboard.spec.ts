import { expect, test, type Locator, type Page } from "@playwright/test";

const card = (page: Page, n: number) => page.getByRole("article", { name: `컷 ${n}` });
const chips = (c: Locator) => c.locator(".phrases .chip");
const openDemo = async (page: Page) => {
  await page.goto("/projects/demo");
  await expect(page.getByRole("heading", { level: 1, name: "데모 프로젝트" })).toBeVisible();
};

test("home lists the project and shows which services are connected", async ({ page }) => {
  await page.goto("/");
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
  await row.getByRole("button", { name: "들어보기" }).click();
  await expect(row.locator("audio")).toBeVisible();
  await expect(row.locator("audio")).toHaveAttribute("src", /^blob:/);
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
