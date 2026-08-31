const PDF_HEADER_BYTES = 1024

async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const body = await response.clone().json() as { detail?: unknown }
    return typeof body.detail === 'string' ? body.detail : null
  } catch {
    return null
  }
}

export async function pdfBlobFromResponse(response: Response): Promise<Blob> {
  if (!response.ok) {
    const detail = await readErrorDetail(response)
    throw new Error(detail || `PDF 加载失败（HTTP ${response.status}）`)
  }

  const blob = await response.blob()
  const header = new Uint8Array(await blob.slice(0, PDF_HEADER_BYTES).arrayBuffer())
  const signature = new TextDecoder('latin1').decode(header)
  if (!signature.includes('%PDF-')) {
    throw new Error('服务器返回的内容不是有效 PDF')
  }
  return blob
}
