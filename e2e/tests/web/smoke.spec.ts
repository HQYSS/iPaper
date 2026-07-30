import { expect, test } from '@playwright/test'
import { installApiMocks } from './mock-api'

test('Web 首页使用本地 mock 完成确定性启动', async ({ page }) => {
  const unexpectedExternalRequests: string[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) {
      unexpectedExternalRequests.push(request.url())
    }
  })

  await installApiMocks(page)
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '欢迎使用 iPaper' })).toBeVisible()
  await expect(page.getByText('从左侧添加论文开始阅读')).toBeVisible()
  expect(unexpectedExternalRequests).toEqual([])
})
