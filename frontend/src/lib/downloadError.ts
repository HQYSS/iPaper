export function formatDownloadError(error?: string | null): string {
  if (!error) return '多数是源站限制或网络抖动，稍后重试通常可恢复。'

  if (error.includes('HTTP 403')) {
    return '源站拒绝程序下载，可以稍后重试，或改用论文页面/其他 PDF 链接添加。'
  }
  if (error.includes('HTTP 404')) {
    return 'PDF 不存在或论文 ID 有误，请检查输入链接。'
  }
  if (error.includes('HTTP 429') || error.includes('限流')) {
    return '源站暂时限流，请过一两分钟后再重试。'
  }
  if (error.includes('超时') || error.toLowerCase().includes('timeout')) {
    return 'PDF 下载超时，多数是网络或源站响应慢，稍后重试通常可恢复。'
  }
  if (error.includes('不是 PDF')) {
    return '链接返回的内容不是 PDF，请换用真正的 PDF 链接。'
  }

  return error
}
