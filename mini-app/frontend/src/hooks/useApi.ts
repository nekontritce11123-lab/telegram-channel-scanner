import { useState, useCallback, useEffect } from 'react'

export const API_BASE = import.meta.env.VITE_API_BASE || 'https://ads-api.factchain-traker.online'

// Types
export interface Recommendation {
  type: 'cpm' | 'tip' | 'warning' | 'success'
  icon: string
  text: string
}

export interface Channel {
  username: string
  title?: string  // v58.2: Название канала (отображается вместо username)
  score: number
  verdict: string
  trust_factor: number
  members: number
  category: string | null
  category_secondary: string | null
  category_percent: number | null  // v20.0: процент основной категории
  scanned_at: string | null
  cpm_min: number | null
  cpm_max: number | null
  photo_url: string | null
  is_verified: boolean  // v34.0: Telegram верификация
  ad_status: number | null  // v69.0: 0=нельзя, 1=возможно, 2=можно купить
  contact_info?: string | null  // v94.0: Ad contact
}

// v7.0: Detailed breakdown structure
// v22.2: Added disabled flag for reactions/comments off
// v23.1: Added status for Info Metrics
// v39.0: Added bot_info for comments metric (AI-detected bots)
export interface BotInfo {
  value: string  // e.g. "22% боты"
  status: 'good' | 'warning' | 'bad'
  llm_source?: boolean
}

export interface MetricItem {
  score: number
  max: number
  label: string
  value?: string    // Optional human-readable value (e.g., "2 года", "откл.")
  disabled?: boolean  // v22.2: True when metric is disabled (floating weights)
  status?: 'good' | 'warning' | 'bad'  // v23.1: Info Metric status
  bot_info?: BotInfo  // v39.0: Bot info integrated into comments
}

// v24.0: Info Metric with bar_percent for progress bar
export interface InfoMetricItem {
  score: number  // Always 0 for info metrics
  max: number    // Always 0 for info metrics
  label: string
  value: string  // e.g. "15%", "3.2 п/д"
  status: 'good' | 'warning' | 'bad'
  bar_percent: number  // 100 for good, 60 for warning, 20 for bad
}

export interface BreakdownCategory {
  total: number
  max: number
  items: Record<string, MetricItem>
  info_metrics?: Record<string, InfoMetricItem>  // v23.1: Info Metrics (ad_load, regularity, etc.)
}

export interface Breakdown {
  quality: BreakdownCategory
  engagement: BreakdownCategory
  reputation: BreakdownCategory
  // v51.0: Flags for channel features
  comments_enabled?: boolean
  reactions_enabled?: boolean
  floating_weights?: boolean
}

// v51.0: BreakdownItem removed (legacy, not used anywhere)

export interface TrustPenalty {
  name: string
  multiplier: number
  description: string
}

export interface PriceEstimate {
  min: number
  max: number
  base_price: number
  size_mult: number
  quality_mult: number
  engagement_mult?: number    // v13.0
  reputation_mult?: number    // v13.0
  trust_mult: number
  demand_mult?: number        // v13.0
  total_mult?: number         // v13.0
}

export interface CategoryRank {
  position: number
  total: number
  avg_score: number
}

// v38.0: LLM Analysis types
// v39.0: Simplified - LLM data now integrated into breakdown metrics
// Only tier info is passed separately for status banner
export interface LLMAnalysis {
  tier: 'PREMIUM' | 'STANDARD' | 'LIMITED' | 'RESTRICTED' | 'EXCLUDED'
  tier_cap: number
}

// v54.0: QuickStats interface
export interface QuickStats {
  reach: number
  err: number
  comments_avg: number
}

export interface ChannelDetail extends Channel {
  recommendations: Recommendation[]
  status?: string
  source?: string
  breakdown?: Breakdown
  trust_penalties?: TrustPenalty[]
  price_estimate?: PriceEstimate
  category_rank?: CategoryRank
  llm_analysis?: LLMAnalysis  // v38.0
  quick_stats?: QuickStats  // v54.0
  ai_summary?: string | null  // v69.0: AI описание канала (500+ символов)
}

export interface ChannelListResponse {
  channels: Channel[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export interface Stats {
  total: number
  good: number
  bad: number
  waiting: number
  error: number
}

export interface CategoryStat {
  category: string
  count: number
  cpm_min: number
  cpm_max: number
}

export interface CategoryStatsResponse {
  categories: CategoryStat[]
  total_categorized: number
  uncategorized: number
}

// v51.0: ScanResponse removed (live scan disabled v59.5)

// v49.0: History/Watchlist stored channel
export interface StoredChannel {
  username: string
  score: number
  verdict: string
  members: number
  category: string | null
  viewedAt?: string  // For history
  addedAt?: string   // For watchlist
}

export interface ChannelFilters {
  categories?: string[]  // v71.0: multiselect
  min_score?: number
  max_score?: number
  min_members?: number
  max_members?: number
  min_trust?: number  // v6.0: min Trust Factor (0.0-1.0)
  verdict?: 'good_plus' | null  // v6.0: good_plus = EXCELLENT + GOOD only
  ad_statuses?: number[]  // v71.0: multiselect [0, 1, 2]
  sort_by?: 'score' | 'members' | 'scanned_at' | 'trust_factor'
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

// API functions
async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string>),
  }

  // v62.0: Добавляем Telegram initData для user tracking
  const tg = window.Telegram?.WebApp
  if (tg?.initData) {
    headers['X-Telegram-Init-Data'] = tg.initData
  }
  if (tg?.platform) {
    headers['X-Platform'] = tg.platform
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

// Hooks
export function useChannels() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(true)

  const fetchChannels = useCallback(async (filters: ChannelFilters = {}, append = false) => {
    setLoading(true)
    setError(null)

    try {
      const params = new URLSearchParams()
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          // v71.0: массивы передаём как comma-separated
          if (Array.isArray(value) && value.length > 0) {
            params.set(key, value.join(','))
          } else if (!Array.isArray(value)) {
            params.set(key, String(value))
          }
        }
      })

      const data = await fetchAPI<ChannelListResponse>(`/api/channels?${params}`)

      if (append) {
        setChannels(prev => [...prev, ...data.channels])
      } else {
        setChannels(data.channels)
      }

      setTotal(data.total)
      setHasMore(data.has_more)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  const reset = useCallback(() => {
    setChannels([])
    setTotal(0)
    setHasMore(true)
  }, [])

  return { channels, total, loading, error, hasMore, fetchChannels, reset }
}

export function useStats() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [categoryStats, setCategoryStats] = useState<CategoryStat[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchStats = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const [statsData, catData] = await Promise.all([
        fetchAPI<Stats>('/api/stats'),
        fetchAPI<CategoryStatsResponse>('/api/stats/categories'),
      ])

      setStats(statsData)
      setCategoryStats(catData.categories)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  return { stats, categoryStats, loading, error, fetchStats }
}

export function useScan() {
  const [result, setResult] = useState<ChannelDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isLiveScan] = useState(false)  // v59.5: Always false, no more live scan

  // v59.5: Only check database, no live scan
  // Live scan was creating incomplete records (no title, no LLM, no category)
  // Now channels must go through queue for full processing
  const scanChannel = useCallback(async (username: string, checkFullyProcessed = false) => {
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      // Only check database - if not found, return null (will be queued)
      const data = await fetchAPI<ChannelDetail>(`/api/channels/${username}`)

      // v59.5: For search - only return if fully processed (score > 0 and status GOOD/BAD)
      // For card clicks - always return data if found
      if (checkFullyProcessed && !(data.score > 0 && (data.status === 'GOOD' || data.status === 'BAD'))) {
        return null  // Not fully processed - will be queued
      }

      setResult(data)
      return data
    } catch {
      // Not in database - return null (will be queued by caller)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  const reset = useCallback(() => {
    setResult(null)
    setError(null)
  }, [])

  // v59.5: isLiveScan always false (kept for API compatibility)
  return { result, loading, error, isLiveScan, scanChannel, reset }
}


// ============================================================================
// v58.0: SCAN REQUEST QUEUE
// ============================================================================

interface ScanRequestResponse {
  success: boolean
  request_id?: number
  message: string
}

export function useScanRequest() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submitRequest = useCallback(async (username: string): Promise<ScanRequestResponse | null> => {
    setLoading(true)
    setError(null)

    try {
      const data = await fetchAPI<ScanRequestResponse>('/api/scan/request', {
        method: 'POST',
        body: JSON.stringify({ username }),
      })
      return data
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Request failed'
      setError(msg)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { submitRequest, loading, error }
}


// ============================================================================
// v49.0: HISTORY HOOK
// ============================================================================

const HISTORY_KEY = 'reklamshik_history'
const MAX_HISTORY = 50

export function useHistory() {
  const [history, setHistory] = useState<StoredChannel[]>([])

  // Load from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(HISTORY_KEY)
    if (stored) {
      try {
        setHistory(JSON.parse(stored))
      } catch {
        setHistory([])
      }
    }
  }, [])

  const addToHistory = useCallback((channel: Channel | ChannelDetail | StoredChannel) => {
    setHistory(prev => {
      // Remove if already exists (move to top)
      const filtered = prev.filter(c => c.username !== channel.username)

      const newItem: StoredChannel = {
        username: channel.username,
        score: channel.score,
        verdict: channel.verdict,
        members: channel.members,
        category: channel.category,
        viewedAt: new Date().toISOString(),
      }

      // Add to beginning, limit to MAX_HISTORY
      const updated = [newItem, ...filtered].slice(0, MAX_HISTORY)

      localStorage.setItem(HISTORY_KEY, JSON.stringify(updated))
      return updated
    })
  }, [])

  const clearHistory = useCallback(() => {
    localStorage.removeItem(HISTORY_KEY)
    setHistory([])
  }, [])

  const removeFromHistory = useCallback((username: string) => {
    setHistory(prev => {
      const updated = prev.filter(c => c.username !== username)
      localStorage.setItem(HISTORY_KEY, JSON.stringify(updated))
      return updated
    })
  }, [])

  return { history, addToHistory, clearHistory, removeFromHistory }
}


// ============================================================================
// v49.0: WATCHLIST HOOK
// v76.0: API sync when authenticated, localStorage fallback
// ============================================================================

const WATCHLIST_KEY = 'reklamshik_watchlist'
const MAX_WATCHLIST = 100

// API functions for favorites
async function fetchFavoritesApi(): Promise<StoredChannel[]> {
  const initData = getInitData()
  if (!initData) return []

  try {
    const res = await fetch(`${API_BASE}/api/favorites`, {
      headers: { 'X-Telegram-Init-Data': initData }
    })
    if (!res.ok) return []
    const data = await res.json()
    return data.favorites || []
  } catch {
    return []
  }
}

async function addFavoriteApi(channel: StoredChannel): Promise<boolean> {
  const initData = getInitData()
  if (!initData) return false

  try {
    const res = await fetch(`${API_BASE}/api/favorites`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': initData
      },
      body: JSON.stringify(channel)
    })
    return res.ok
  } catch {
    return false
  }
}

async function removeFavoriteApi(username: string): Promise<boolean> {
  const initData = getInitData()
  if (!initData) return false

  try {
    const res = await fetch(`${API_BASE}/api/favorites/${username}`, {
      method: 'DELETE',
      headers: { 'X-Telegram-Init-Data': initData }
    })
    return res.ok
  } catch {
    return false
  }
}

export function useWatchlist() {
  const [watchlist, setWatchlist] = useState<StoredChannel[]>([])
  const [loading, setLoading] = useState(false)
  const isAuthenticated = Boolean(getInitData())

  // Load from API (authenticated) or localStorage (fallback) on mount
  useEffect(() => {
    const loadWatchlist = async () => {
      // First, load from localStorage for instant display (offline-first)
      const stored = localStorage.getItem(WATCHLIST_KEY)
      if (stored) {
        try {
          setWatchlist(JSON.parse(stored))
        } catch {
          setWatchlist([])
        }
      }

      // If authenticated, sync from API
      if (isAuthenticated) {
        setLoading(true)
        const apiFavorites = await fetchFavoritesApi()
        if (apiFavorites.length > 0) {
          setWatchlist(apiFavorites)
          // Update localStorage cache
          localStorage.setItem(WATCHLIST_KEY, JSON.stringify(apiFavorites))
        }
        setLoading(false)
      }
    }

    loadWatchlist()
  }, [isAuthenticated])

  const isInWatchlist = useCallback((username: string) => {
    return watchlist.some(c => c.username === username)
  }, [watchlist])

  const addToWatchlist = useCallback((channel: Channel | ChannelDetail | StoredChannel) => {
    // Optimistic update
    setWatchlist(prev => {
      // Don't add if already exists
      if (prev.some(c => c.username === channel.username)) {
        return prev
      }

      const newItem: StoredChannel = {
        username: channel.username,
        score: channel.score,
        verdict: channel.verdict,
        members: channel.members,
        category: channel.category,
        addedAt: new Date().toISOString(),
      }

      const updated = [newItem, ...prev].slice(0, MAX_WATCHLIST)
      localStorage.setItem(WATCHLIST_KEY, JSON.stringify(updated))

      // Sync to API in background (fire and forget)
      if (isAuthenticated) {
        addFavoriteApi(newItem)
      }

      return updated
    })
  }, [isAuthenticated])

  const removeFromWatchlist = useCallback((username: string) => {
    setWatchlist(prev => {
      const updated = prev.filter(c => c.username !== username)
      localStorage.setItem(WATCHLIST_KEY, JSON.stringify(updated))

      // Sync to API in background (fire and forget)
      if (isAuthenticated) {
        removeFavoriteApi(username)
      }

      return updated
    })
  }, [isAuthenticated])

  const clearWatchlist = useCallback(() => {
    localStorage.removeItem(WATCHLIST_KEY)
    setWatchlist([])
    // Note: No API endpoint for clearing all favorites - would need to remove each
  }, [])

  return { watchlist, loading, isInWatchlist, addToWatchlist, removeFromWatchlist, clearWatchlist }
}


// ============================================================================
// v72.0: PROJECTS HOOK - "Мои Проекты" feature
// ============================================================================

export interface Project {
  id: number
  user_id: number
  channel_username: string
  name: string | null
  category: string | null
  created_at: string
  // Joined from channel
  channel_title?: string
  channel_members?: number
  channel_score?: number
  channel_verdict?: string
  // Stats
  purchases_count?: number
  total_spent?: number
}

export interface Purchase {
  id: number
  project_id: number
  channel_username: string
  status: PurchaseStatus
  price: number | null
  scheduled_at: string | null
  posted_at: string | null
  views: number | null
  subscribers_gained: number | null
  notes: string | null
  created_at: string
  updated_at: string | null
  // Joined from channel
  channel_title?: string
  channel_members?: number
  channel_score?: number
  // Calculated by backend
  cpm?: number | null
  cpf?: number | null
}

export type PurchaseStatus =
  | 'PLANNED'
  | 'CONTACTED'
  | 'NEGOTIATING'
  | 'PAID'
  | 'POSTED'
  | 'COMPLETED'
  | 'CANCELLED'

export interface ProjectStats {
  purchases_count: number
  by_status: Record<string, number>
  total_spent: number
  total_views: number
  total_subscribers_gained: number
  avg_cpm: number | null
  avg_cpf: number | null
}

// Helper to get initData from Telegram WebApp
function getInitData(): string {
  return window.Telegram?.WebApp?.initData || ''
}

export function useProjects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchProjects = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/projects`, {
        headers: {
          'X-Telegram-Init-Data': getInitData()
        }
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setProjects(data.projects || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch projects')
    } finally {
      setLoading(false)
    }
  }, [])

  const createProject = useCallback(async (channelUsername: string, name?: string): Promise<Project | null> => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/projects`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Telegram-Init-Data': getInitData()
        },
        body: JSON.stringify({ channel_username: channelUsername, name })
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      if (!data.success) {
        throw new Error(data.error || 'Failed to create project')
      }
      if (data.project) {
        setProjects(prev => [data.project, ...prev])
        return data.project
      }
      return null
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create project')
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  const deleteProject = useCallback(async (projectId: number): Promise<boolean> => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}`, {
        method: 'DELETE',
        headers: {
          'X-Telegram-Init-Data': getInitData()
        }
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      setProjects(prev => prev.filter(p => p.id !== projectId))
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete project')
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  const getRecommendations = useCallback(async (projectId: number, filters?: {
    max_price?: number
    min_trust?: number
    min_members?: number
    max_members?: number
  }): Promise<Channel[]> => {
    try {
      const params = new URLSearchParams()
      if (filters?.max_price) params.set('max_price', String(filters.max_price))
      if (filters?.min_trust) params.set('min_trust', String(filters.min_trust))
      if (filters?.min_members) params.set('min_members', String(filters.min_members))
      if (filters?.max_members) params.set('max_members', String(filters.max_members))

      const url = `${API_BASE}/api/projects/${projectId}/recommendations${params.toString() ? '?' + params : ''}`
      const res = await fetch(url, {
        headers: {
          'X-Telegram-Init-Data': getInitData()
        }
      })
      if (!res.ok) return []
      const data = await res.json()
      return data.recommendations || []
    } catch {
      return []
    }
  }, [])

  return { projects, loading, error, fetchProjects, createProject, deleteProject, getRecommendations }
}


// ============================================================================
// v72.0: PURCHASES HOOK - Purchase tracker
// ============================================================================

export function usePurchases(projectId: number | null) {
  const [purchases, setPurchases] = useState<Purchase[]>([])
  const [stats, setStats] = useState<ProjectStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchPurchases = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/purchases`, {
        headers: {
          'X-Telegram-Init-Data': getInitData()
        }
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setPurchases(data.purchases || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch purchases')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  const fetchStats = useCallback(async () => {
    if (!projectId) return
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/stats`, {
        headers: {
          'X-Telegram-Init-Data': getInitData()
        }
      })
      if (res.ok) {
        const data = await res.json()
        setStats(data)
      }
    } catch {
      // Stats are optional, don't set error
    }
  }, [projectId])

  const createPurchase = useCallback(async (channelUsername: string, notes?: string): Promise<Purchase | null> => {
    if (!projectId) return null
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/purchases`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Telegram-Init-Data': getInitData()
        },
        body: JSON.stringify({ channel_username: channelUsername, notes })
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      const purchase = await res.json()
      setPurchases(prev => [purchase, ...prev])
      return purchase
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create purchase')
      return null
    } finally {
      setLoading(false)
    }
  }, [projectId])

  const updatePurchase = useCallback(async (purchaseId: number, updates: {
    status?: PurchaseStatus
    price?: number
    scheduled_at?: string
    posted_at?: string
    views?: number
    subscribers_gained?: number
    notes?: string
  }): Promise<Purchase | null> => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/purchases/${purchaseId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'X-Telegram-Init-Data': getInitData()
        },
        body: JSON.stringify(updates)
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      const updated = await res.json()
      setPurchases(prev => prev.map(p => p.id === purchaseId ? updated : p))
      return updated
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update purchase')
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  const deletePurchase = useCallback(async (purchaseId: number): Promise<boolean> => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/purchases/${purchaseId}`, {
        method: 'DELETE',
        headers: {
          'X-Telegram-Init-Data': getInitData()
        }
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      setPurchases(prev => prev.filter(p => p.id !== purchaseId))
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete purchase')
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  // Fetch purchases when projectId changes
  useEffect(() => {
    if (projectId) {
      fetchPurchases()
      fetchStats()
    } else {
      setPurchases([])
      setStats(null)
    }
  }, [projectId, fetchPurchases, fetchStats])

  return { purchases, stats, loading, error, fetchPurchases, fetchStats, createPurchase, updatePurchase, deletePurchase }
}
