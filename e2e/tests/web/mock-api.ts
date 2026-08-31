import type { Page, Route } from '@playwright/test'

export const MOCK_PAPER_ID = '2401.12345'
export const MOCK_SESSION_ID = 'session-e2e'

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })

const config = {
  llm: {
    provider: 'llm_center_gpt_responses',
    api_base: 'http://mock.invalid',
    api_key_configured: true,
    model: 'gpt-5.5',
    provider_id: '64',
    temperature: 0,
    max_tokens: 1024,
  },
  data_dir: '/tmp/ipaper-e2e',
  hjfy_cookie_configured: false,
  sync: {
    role: 'off',
    url: '',
    verify_ssl: true,
    token_configured: false,
  },
}

const paper = {
  arxiv_id: MOCK_PAPER_ID,
  source_type: 'arxiv',
  title: 'Deterministic E2E Paper',
  title_zh: '确定性端到端测试论文',
  summary: 'Local mock data only.',
  authors: ['E2E Bot'],
  download_time: '2026-01-01T00:00:00Z',
  download_status: 'ready',
}

// A minimal PDF is enough for the viewer request; the chat assertions do not
// depend on PDF rendering.
const minimalPdf = Buffer.from(
  '%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n' +
  '2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n' +
  'trailer<</Root 1 0 R>>\n%%EOF\n',
)

export async function installApiMocks(
  page: Page,
  options: { withPaper?: boolean; chatSse?: string } = {},
) {
  const { withPaper = false, chatSse } = options

  await page.addInitScript(() => {
    localStorage.clear()
    localStorage.setItem('ipaper.auth.token', 'e2e-token')
  })

  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) {
      return route.abort('blockedbyclient')
    }
    return route.fallback()
  })

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    const method = request.method()

    if (pathname === '/api/auth/me') {
      return json(route, { id: 'e2e-user', username: 'e2e', is_admin: false })
    }
    if (pathname === '/api/preferences') {
      return json(route, method === 'GET' ? {} : { ok: true })
    }
    if (pathname === '/api/papers/open-request') {
      return json(route, { paper_id: null })
    }
    if (pathname === '/api/papers' && method === 'GET') {
      return json(route, withPaper ? [paper] : [])
    }
    if (pathname === '/api/config') {
      return json(route, config)
    }
    if (pathname === `/api/papers/${MOCK_PAPER_ID}/translations`) {
      return json(route, { zh: false, bilingual: false })
    }
    if (pathname === `/api/papers/${MOCK_PAPER_ID}/pdf`) {
      return route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: minimalPdf,
      })
    }
    if (pathname === `/api/chat/${MOCK_PAPER_ID}/sessions`) {
      return json(route, {
        sessions: [{
          id: MOCK_SESSION_ID,
          title: 'E2E 对话',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }],
        last_active_session_id: MOCK_SESSION_ID,
      })
    }
    if (pathname === `/api/chat/${MOCK_PAPER_ID}/${MOCK_SESSION_ID}/history`) {
      return json(route, {
        paper_id: MOCK_PAPER_ID,
        session_id: MOCK_SESSION_ID,
        messages: [],
        forks: {},
      })
    }
    if (
      pathname === `/api/chat/${MOCK_PAPER_ID}/${MOCK_SESSION_ID}/history/draft`
      && method === 'PUT'
    ) {
      return json(route, { ok: true })
    }
    if (
      pathname === `/api/chat/${MOCK_PAPER_ID}/${MOCK_SESSION_ID}`
      && method === 'POST'
      && chatSse !== undefined
    ) {
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache' },
        body: chatSse,
      })
    }
    if (pathname === '/api/client-logs') {
      return json(route, { ok: true })
    }

    return json(route, {
      detail: `E2E mock has no handler for ${method} ${pathname}`,
    }, 501)
  })
}
