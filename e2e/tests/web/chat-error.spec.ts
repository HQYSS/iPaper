import { expect, test } from '@playwright/test'
import { installApiMocks } from './mock-api'

test('chat SSE 的部分回复和错误都会展示在 UI', async ({ page }) => {
  await installApiMocks(page, {
    withPaper: true,
    chatSse: [
      'data: {"type":"chunk","content":"这是本地 mock 的部分回复。"}',
      '',
      'data: {"type":"error","message":"模拟 SSE 上游错误"}',
      '',
    ].join('\n'),
  })

  await page.goto('/')
  await page.getByText('Deterministic E2E Paper', { exact: true }).click()

  const input = page.getByPlaceholder('输入问题...')
  await expect(input).toBeVisible()
  await input.fill('请触发确定性错误')
  await input.press('Enter')

  await expect(page.getByText('请触发确定性错误', { exact: true })).toBeVisible()
  await expect(page.getByText('这是本地 mock 的部分回复。', { exact: true })).toBeVisible()
  await expect(page.getByText('模拟 SSE 上游错误', { exact: true })).toBeVisible()
})
