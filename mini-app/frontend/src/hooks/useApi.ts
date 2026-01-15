import { useState, useCallback } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || 'https://api.factchain-traker.online'

// Types
export interface Channel {
  username: string
  score: number
  verdict: string
  trust_factor: number
  members: number
  category: string | null
  category_secondary: string | null
  scanned_at: string | null
  cpm_min: number | null
  cpm_max: number | null
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

export interface ChannelFilters {
  category?: string
  min_score?: number
  max_score?: number
  min_members?: number
  max_members?: number
  sort_by?: 'score' | 'members' | 'scanned_at'
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

// API functions
async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
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
          params.set(key, String(value))
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
  const [result, setResult] = useState<Channel | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const scanChannel = useCallback(async (username: string) => {
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      // Сначала пробуем получить из базы
      const data = await fetchAPI<Channel>(`/api/channels/${username}`)
      setResult(data)
    } catch {
      // Если нет в базе - пока показываем ошибку
      // В будущем можно добавить live scan
      setError('Канал не найден в базе')
    } finally {
      setLoading(false)
    }
  }, [])

  const reset = useCallback(() => {
    setResult(null)
    setError(null)
  }, [])

  return { result, loading, error, scanChannel, reset }
}
