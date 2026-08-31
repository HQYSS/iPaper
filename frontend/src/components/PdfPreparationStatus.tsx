import { Loader2 } from 'lucide-react'

interface PdfPreparationStatusProps {
  title: string
  downloadedBytes?: number | null
  totalBytes?: number | null
  progress?: number | null
  compact?: boolean
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

export function PdfPreparationStatus({
  title,
  downloadedBytes = 0,
  totalBytes,
  progress,
  compact = false,
}: PdfPreparationStatusProps) {
  const normalizedProgress = typeof progress === 'number'
    ? Math.max(0, Math.min(1, progress))
    : null
  const percent = normalizedProgress === null ? null : Math.round(normalizedProgress * 100)
  const sizeLabel = totalBytes
    ? `${formatBytes(downloadedBytes || 0)} / ${formatBytes(totalBytes)}`
    : downloadedBytes
      ? `已下载 ${formatBytes(downloadedBytes)}`
      : '正在连接下载源'

  return (
    <div className={compact ? 'mt-1.5' : 'w-full max-w-sm'}>
      <div className="flex items-center gap-2 text-sm text-foreground">
        <Loader2 className="w-4 h-4 flex-shrink-0 animate-spin text-indigo-500" />
        <span className="min-w-0 truncate">{title}</span>
        {percent !== null && <span className="ml-auto tabular-nums text-muted-foreground">{percent}%</span>}
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={normalizedProgress === null
            ? 'h-full w-1/3 animate-pulse rounded-full bg-indigo-500'
            : 'h-full rounded-full bg-indigo-500 transition-[width] duration-300'}
          style={normalizedProgress === null ? undefined : { width: `${percent}%` }}
        />
      </div>
      <p className="mt-1 text-xs tabular-nums text-muted-foreground">{sizeLabel}</p>
    </div>
  )
}
