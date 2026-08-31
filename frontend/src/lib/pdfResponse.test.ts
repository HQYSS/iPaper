import { describe, expect, it } from 'vitest'
import { pdfBlobFromResponse } from './pdfResponse'

describe('pdfBlobFromResponse', () => {
  it('accepts a PDF response', async () => {
    const response = new Response('%PDF-1.7\nbody', {
      headers: { 'Content-Type': 'application/pdf' },
    })

    const blob = await pdfBlobFromResponse(response)

    expect(await blob.text()).toBe('%PDF-1.7\nbody')
  })

  it('surfaces an HTTP error instead of passing JSON to PDF.js', async () => {
    const response = new Response(JSON.stringify({ detail: '中文 PDF 不存在' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' },
    })

    await expect(pdfBlobFromResponse(response)).rejects.toThrow('中文 PDF 不存在')
  })

  it('rejects a successful non-PDF response', async () => {
    const response = new Response('<html>upstream error</html>', { status: 200 })

    await expect(pdfBlobFromResponse(response)).rejects.toThrow('不是有效 PDF')
  })
})
