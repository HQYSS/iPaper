import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { PdfPreparationStatus } from './PdfPreparationStatus'

describe('PdfPreparationStatus', () => {
  it('renders determinate progress with byte totals', () => {
    render(
      <PdfPreparationStatus
        title="云端正在准备 PDF"
        downloadedBytes={1024 * 1024}
        totalBytes={2 * 1024 * 1024}
        progress={0.5}
      />
    )

    expect(screen.getByText('云端正在准备 PDF')).toBeInTheDocument()
    expect(screen.getByText('50%')).toBeInTheDocument()
    expect(screen.getByText('1.0 MB / 2.0 MB')).toBeInTheDocument()
  })

  it('renders downloaded bytes without inventing a percentage', () => {
    render(
      <PdfPreparationStatus
        title="正在下载英文 PDF"
        downloadedBytes={512 * 1024}
      />
    )

    expect(screen.getByText('已下载 512.0 KB')).toBeInTheDocument()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })
})
