import { describe, expect, it } from 'vitest'
import { formatDownloadError } from './downloadError'

describe('formatDownloadError', () => {
  it.each([
    ['HTTP 403', '源站拒绝程序下载'],
    ['HTTP 404', 'PDF 不存在'],
    ['HTTP 429', '源站暂时限流'],
    ['请求 timeout', 'PDF 下载超时'],
    ['返回内容不是 PDF', '链接返回的内容不是 PDF'],
  ])('maps %s to a helpful message', (error, expected) => {
    expect(formatDownloadError(error)).toContain(expected)
  })

  it('uses a recovery hint for an empty error and preserves unknown errors', () => {
    expect(formatDownloadError()).toContain('稍后重试')
    expect(formatDownloadError('自定义下载错误')).toBe('自定义下载错误')
  })
})
