import { useEffect, useState } from 'react'
import { ArrowLeft, ChevronRight, Compass, FileText, Loader2, Search, UserPlus, Users, X } from 'lucide-react'
import * as api from '../../services/api'
import { useToastStore } from '../../stores/toastStore'

interface SocialHubProps {
  onClose: () => void
}

function formatMessage(message: api.ChatMessage) {
  return message.content?.trim() || ''
}

type Tab = 'feed' | 'discover' | 'mine'

export function SocialHub({ onClose }: SocialHubProps) {
  const [tab, setTab] = useState<Tab>('feed')
  const [query, setQuery] = useState('')
  const [users, setUsers] = useState<api.SocialUser[]>([])
  const [feed, setFeed] = useState<api.SocialPaper[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [profile, setProfile] = useState<api.SocialUser | null>(null)
  const [paperQuery, setPaperQuery] = useState('')
  const [openingPaperId, setOpeningPaperId] = useState<string | null>(null)
  const [paperDetail, setPaperDetail] = useState<api.SocialPaperDetail | null>(null)
  const { addToast } = useToastStore()

  const load = async () => {
    setLoading(true)
    try {
      if (tab === 'feed') setFeed(await api.getFollowingFeed())
      else if (tab === 'discover') setUsers(await api.searchSocialUsers(query))
      else setUsers(await api.listFollowingUsers())
    } catch (error) {
      addToast('error', (error as Error).message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [tab])

  const search = async () => {
    setLoading(true)
    try { setUsers(await api.searchSocialUsers(query)) } catch (error) { addToast('error', (error as Error).message || '搜索失败') } finally { setLoading(false) }
  }

  const toggleFollow = async (person: api.SocialUser) => {
    setBusyId(person.id)
    try {
      if (person.is_following) await api.unfollowUser(person.id)
      else await api.followUser(person.id)
      setUsers((items) => items.map((item) => item.id === person.id ? { ...item, is_following: !person.is_following } : item))
      addToast('success', person.is_following ? '已取消关注' : `已关注 ${person.username}`)
      if (tab === 'feed') await load()
    } catch (error) { addToast('error', (error as Error).message || '操作失败') } finally { setBusyId(null) }
  }

  const openProfile = async (person: api.SocialUser) => {
    setLoading(true)
    try { setProfile(await api.getSocialUser(person.id)) } catch (error) { addToast('error', (error as Error).message || '打开用户主页失败') } finally { setLoading(false) }
  }

  const handleOpenPaper = async (userId: string, arxivId: string) => {
    setOpeningPaperId(arxivId)
    try {
      setPaperDetail(await api.getSocialPaperDetail(userId, arxivId))
    } catch (error) {
      addToast('error', (error as Error).message || '打开论文失败')
    } finally {
      setOpeningPaperId(null)
    }
  }

  if (paperDetail) {
    return <RemotePaperDetail detail={paperDetail} onBack={() => setPaperDetail(null)} onClose={onClose} />
  }

  if (profile) {
    const papers = (profile.papers || []).filter((paper) => {
      const value = `${paper.title} ${paper.arxiv_id}`.toLowerCase()
      return value.includes(paperQuery.trim().toLowerCase())
    })
    return <div className="fixed inset-0 z-50 bg-background flex flex-col"><header className="h-16 border-b border-border flex items-center px-5 gap-3 flex-shrink-0"><button onClick={() => setProfile(null)} className="p-2 rounded-lg hover:bg-accent" title="返回"><ArrowLeft className="w-5 h-5" /></button><div className="w-9 h-9 rounded-full bg-primary/10 text-primary flex items-center justify-center font-semibold">{profile.username.slice(0, 1).toUpperCase()}</div><div><p className="font-semibold">{profile.username}</p><p className="text-xs text-muted-foreground">{profile.paper_count} 篇论文 · {profile.chat_count} 个对话</p></div><button onClick={onClose} className="ml-auto p-2 rounded-lg hover:bg-accent" title="关闭"><X className="w-5 h-5" /></button></header><main className="flex-1 overflow-y-auto max-w-4xl w-full mx-auto px-5 py-8"><div className="flex items-center gap-2 border border-border rounded-xl px-3 bg-muted/30 mb-5"><Search className="w-4 h-4 text-muted-foreground" /><input value={paperQuery} onChange={(e) => setPaperQuery(e.target.value)} placeholder="在这个人的论文中搜索" className="w-full py-3 bg-transparent outline-none text-sm" /></div><p className="text-sm text-muted-foreground mb-3">全部论文（{papers.length}）</p><div className="divide-y divide-border border-y border-border">{papers.map((paper) => <button key={paper.arxiv_id} type="button" disabled={openingPaperId === paper.arxiv_id} onClick={() => void handleOpenPaper(profile.id, paper.arxiv_id)} className="w-full text-left py-4 flex items-center gap-4 hover:bg-accent/50 transition-colors disabled:opacity-60"><FileText className="w-5 h-5 text-primary flex-shrink-0" /><div className="min-w-0 flex-1"><p className="font-medium truncate">{paper.title}</p><p className="text-xs text-muted-foreground mt-1 font-mono">{paper.arxiv_id} · {paper.session_count} 个对话</p></div>{openingPaperId === paper.arxiv_id ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronRight className="w-4 h-4 text-muted-foreground" />}</button>)}</div>{papers.length === 0 && <Empty icon={<FileText className="w-8 h-8" />} text="没有匹配的论文" />}</main></div>
  }

  return (
    <div className="fixed inset-0 z-50 bg-background flex flex-col">
      <header className="h-16 border-b border-border flex items-center px-5 gap-4 flex-shrink-0">
        <button onClick={onClose} className="p-2 rounded-lg hover:bg-accent" title="返回论文库"><ArrowLeft className="w-5 h-5" /></button>
        <div className="flex items-center gap-2 font-semibold"><Users className="w-5 h-5 text-primary" />关注</div>
        <nav className="flex items-center gap-1 ml-4">
          {([['feed', '关注'], ['discover', '发现'], ['mine', '我的关注']] as [Tab, string][]).map(([key, label]) => (
            <button key={key} onClick={() => setTab(key)} className={`px-4 py-2 rounded-lg text-sm ${tab === key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent'}`}>{label}</button>
          ))}
        </nav>
        <button onClick={onClose} className="ml-auto p-2 rounded-lg hover:bg-accent" title="关闭"><X className="w-5 h-5" /></button>
      </header>

      <main className="flex-1 overflow-y-auto max-w-4xl w-full mx-auto px-5 py-8">
        {tab === 'discover' && (
          <div className="flex gap-2 mb-6">
            <div className="flex-1 flex items-center gap-2 border border-border rounded-xl px-3 bg-muted/30"><Search className="w-4 h-4 text-muted-foreground" /><input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} placeholder="搜索用户名" className="w-full py-3 bg-transparent outline-none text-sm" /></div>
            <button onClick={search} className="px-5 rounded-xl bg-primary text-primary-foreground text-sm">搜索</button>
          </div>
        )}
        {loading ? <div className="py-20 flex justify-center text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /></div> : tab === 'feed' ? (
          feed.length === 0 ? <Empty icon={<Compass className="w-8 h-8" />} text="关注用户后，他们最近阅读的论文会出现在这里" /> : <div className="space-y-3">{feed.map((item) => <PaperItem key={`${item.user_id}-${item.arxiv_id}`} item={item} onOpen={() => item.user_id && void handleOpenPaper(item.user_id, item.arxiv_id)} />)}</div>
        ) : (
          users.length === 0 ? <Empty icon={<UserPlus className="w-8 h-8" />} text={tab === 'discover' ? '没有找到用户' : '还没有关注任何人'} /> : <div className="divide-y divide-border">{users.map((person) => <UserItem key={person.id} person={person} busy={busyId === person.id} onToggle={() => toggleFollow(person)} onOpen={() => openProfile(person)} />)}</div>
        )}
      </main>
    </div>
  )
}

function UserItem({ person, busy, onToggle, onOpen }: { person: api.SocialUser; busy: boolean; onToggle: () => void; onOpen: () => void }) {
  return <div className="flex items-center gap-4 py-4"><button onClick={onOpen} className="w-11 h-11 rounded-full bg-primary/10 text-primary flex items-center justify-center font-semibold flex-shrink-0">{person.username.slice(0, 1).toUpperCase()}</button><button onClick={onOpen} className="min-w-0 flex-1 text-left"><p className="font-medium">{person.username}</p><p className="text-xs text-muted-foreground mt-1">{person.paper_count} 篇论文 · {person.chat_count} 个对话</p></button>{!person.is_self && <button onClick={onToggle} disabled={busy} className={`px-4 py-2 rounded-lg text-sm ${person.is_following ? 'border border-border text-muted-foreground' : 'bg-primary text-primary-foreground'}`}>{busy ? <Loader2 className="w-4 h-4 animate-spin" /> : person.is_following ? '已关注' : '关注'}</button>}</div>
}

function PaperItem({ item, onOpen }: { item: api.SocialPaper; onOpen: () => void }) {
  return <button type="button" onClick={onOpen} className="w-full text-left border border-border rounded-xl p-5 hover:border-primary/40 transition-colors"><div className="flex items-center gap-2 text-xs text-muted-foreground mb-3"><span className="w-7 h-7 rounded-full bg-primary/10 text-primary flex items-center justify-center font-medium">{(item.username || '?').slice(0, 1).toUpperCase()}</span><span className="font-medium text-foreground">{item.username}</span><span>最近阅读</span></div><h2 className="font-semibold leading-relaxed">{item.title}</h2><p className="text-xs text-muted-foreground mt-2 font-mono">{item.arxiv_id} · {item.session_count} 个对话</p>{item.summary && <p className="text-sm text-muted-foreground mt-3 line-clamp-2">{item.summary}</p>}{item.chat_preview && <div className="mt-3 border-l-2 border-primary/40 pl-3 text-sm text-muted-foreground line-clamp-3">“{item.chat_preview}”</div>}<div className="flex items-center gap-2 mt-4 text-xs text-muted-foreground"><FileText className="w-4 h-4" />点击在 iPaper 中打开</div></button>
}

function RemotePaperDetail({ detail, onBack, onClose }: { detail: api.SocialPaperDetail; onBack: () => void; onClose: () => void }) {
  return <div className="fixed inset-0 z-50 bg-background flex flex-col"><header className="h-16 border-b border-border flex items-center px-5 gap-3 flex-shrink-0"><button onClick={onBack} className="p-2 rounded-lg hover:bg-accent" title="返回论文列表"><ArrowLeft className="w-5 h-5" /></button><div className="min-w-0 flex-1"><p className="font-semibold truncate">{detail.paper.title}</p><p className="text-xs text-muted-foreground">{detail.username} 的论文 · {detail.sessions.length} 个对话</p></div><button onClick={onClose} className="p-2 rounded-lg hover:bg-accent" title="关闭"><X className="w-5 h-5" /></button></header><main className="flex-1 overflow-y-auto max-w-4xl w-full mx-auto px-5 py-8"><div className="border-b border-border pb-6"><p className="text-sm font-mono text-muted-foreground">{detail.paper.arxiv_id}</p>{detail.paper.summary && <p className="mt-4 text-sm leading-7 text-muted-foreground">{detail.paper.summary}</p>}</div><h2 className="font-semibold mt-7 mb-3">{detail.username} 的对话</h2>{detail.sessions.length === 0 ? <Empty icon={<Users className="w-8 h-8" />} text="这个论文还没有可查看的对话" /> : <div className="space-y-4">{detail.sessions.map((session) => <section key={session.id} className="border border-border rounded-xl p-4"><p className="text-sm font-medium mb-3">{session.title}</p>{session.messages.length === 0 ? <p className="text-sm text-muted-foreground">暂无消息</p> : <div className="space-y-3">{session.messages.map((message, index) => <div key={`${session.id}-${index}`} className={`rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${message.role === 'user' ? 'bg-muted' : 'bg-primary/5'}`}><p className="text-[11px] text-muted-foreground mb-1">{message.role === 'user' ? detail.username : 'AI'}</p>{formatMessage(message)}</div>)}</div>}</section>)}</div>}</main></div>
}

function Empty({ icon, text }: { icon: React.ReactNode; text: string }) { return <div className="py-20 flex flex-col items-center gap-3 text-muted-foreground text-sm">{icon}<p>{text}</p></div> }
