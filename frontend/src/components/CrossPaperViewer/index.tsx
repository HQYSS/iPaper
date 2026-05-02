import { usePaperStore } from '../../stores/paperStore'
import { PdfViewer } from '../PdfViewer'

export function CrossPaperViewer() {
  const { papers, crossPaper, setCrossPaperPdfTab } = usePaperStore()
  const { activeCrossPaperSession, activePdfTab } = crossPaper

  if (!activeCrossPaperSession) return null

  const paperIds = activeCrossPaperSession.paper_ids
  const currentTab = activePdfTab || paperIds[0]

  const getPaperTitle = (paperId: string) => {
    const paper = papers.find((p) => p.arxiv_id === paperId)
    if (!paper) return paperId
    return paper.title.length > 20 ? paper.title.slice(0, 20) + '…' : paper.title
  }

  const currentPaper = papers.find((p) => p.arxiv_id === currentTab)

  return (
    <div className="h-full flex flex-col">
      {/* Tab 栏 */}
      <div className="flex-shrink-0 border-b border-border bg-muted/30 flex items-center overflow-x-auto no-scrollbar">
        {paperIds.map((paperId) => {
          const isActive = paperId === currentTab
          return (
            <button
              key={paperId}
              onClick={() => setCrossPaperPdfTab(paperId)}
              className={`relative flex-shrink-0 px-4 py-2 text-sm transition-colors whitespace-nowrap border-b-2 ${
                isActive
                  ? 'border-purple-500 text-foreground font-medium'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-accent/50'
              }`}
              title={papers.find((p) => p.arxiv_id === paperId)?.title || paperId}
            >
              <span className="font-mono text-xs text-muted-foreground mr-1.5">{paperId}</span>
              <span>{getPaperTitle(paperId)}</span>
            </button>
          )
        })}
      </div>

      {/* PDF 内容 — 切换 tab 时通过 key 重建 PdfViewer */}
      <div className="flex-1 min-h-0">
        <PdfViewer key={currentTab} paperId={currentTab} sourceType={currentPaper?.source_type} />
      </div>
    </div>
  )
}
