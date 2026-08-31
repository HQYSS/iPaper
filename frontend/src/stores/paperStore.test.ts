import { describe, expect, it } from 'vitest'
import { hasPendingPaperRefresh, isPlaceholderMetadata } from './paperStore'
import type { PaperListItem } from '../services/api'

const basePaper: PaperListItem = {
  arxiv_id: '2604.15483',
  title: 'A real paper title',
  summary: 'A real summary',
  authors: ['Author'],
  download_time: '2026-08-20T00:00:00Z',
  download_status: 'ready',
}

describe('paper metadata refresh state', () => {
  it('keeps arXiv placeholder metadata pending after the PDF is ready', () => {
    const paper = {
      ...basePaper,
      title: 'arXiv 2604.15483',
      summary: 'arXiv 元数据待补齐；PDF 下载完成后即可先阅读。',
    }

    expect(isPlaceholderMetadata(paper)).toBe(true)
    expect(hasPendingPaperRefresh([paper])).toBe(true)
  })

  it('stops refreshing once real metadata is available', () => {
    expect(isPlaceholderMetadata(basePaper)).toBe(false)
    expect(hasPendingPaperRefresh([basePaper])).toBe(false)
  })
})
