import { useEffect, useState, useCallback } from 'react'
import { useChannels, type ChannelFilters } from '../hooks/useApi'
import { useTelegram } from '../hooks/useTelegram'
import ChannelCard from '../components/ChannelCard'
import './DatabasePage.css'

const CATEGORIES = [
  'CRYPTO', 'FINANCE', 'TECH', 'AI_ML', 'BUSINESS',
  'EDUCATION', 'ENTERTAINMENT', 'NEWS', 'LIFESTYLE', 'OTHER'
]

function DatabasePage() {
  const { channels, total, loading, error, hasMore, fetchChannels, reset } = useChannels()
  const { hapticLight } = useTelegram()

  const [filters, setFilters] = useState<ChannelFilters>({
    page: 1,
    page_size: 20,
    sort_by: 'score',
    sort_order: 'desc',
  })

  const [showFilters, setShowFilters] = useState(false)

  // Initial load
  useEffect(() => {
    fetchChannels(filters)
  }, [])

  // Apply filters
  const applyFilters = useCallback(() => {
    hapticLight()
    reset()
    fetchChannels({ ...filters, page: 1 })
    setShowFilters(false)
  }, [filters, fetchChannels, reset, hapticLight])

  // Load more
  const loadMore = useCallback(() => {
    if (!loading && hasMore) {
      const nextPage = (filters.page || 1) + 1
      setFilters(prev => ({ ...prev, page: nextPage }))
      fetchChannels({ ...filters, page: nextPage }, true)
    }
  }, [loading, hasMore, filters, fetchChannels])

  // Filter change
  const handleFilterChange = (key: keyof ChannelFilters, value: any) => {
    setFilters(prev => ({ ...prev, [key]: value }))
  }

  // Scroll handler for infinite scroll
  useEffect(() => {
    const handleScroll = () => {
      if (
        window.innerHeight + window.scrollY >= document.body.offsetHeight - 500 &&
        !loading &&
        hasMore
      ) {
        loadMore()
      }
    }

    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [loadMore, loading, hasMore])

  return (
    <div className="page database-page">
      <div className="page-header">
        <h1 className="page-title">База каналов</h1>
        <button
          className="filter-toggle"
          onClick={() => {
            hapticLight()
            setShowFilters(!showFilters)
          }}
        >
          Фильтры {showFilters ? '▲' : '▼'}
        </button>
      </div>

      {showFilters && (
        <div className="filters-panel">
          <div className="filter-row">
            <label>Категория</label>
            <select
              value={filters.category || ''}
              onChange={(e) => handleFilterChange('category', e.target.value || undefined)}
            >
              <option value="">Все</option>
              {CATEGORIES.map(cat => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>
          </div>

          <div className="filter-row">
            <label>Score от</label>
            <input
              type="number"
              min="0"
              max="100"
              value={filters.min_score || 0}
              onChange={(e) => handleFilterChange('min_score', parseInt(e.target.value) || 0)}
            />
          </div>

          <div className="filter-row">
            <label>Подписчики от</label>
            <input
              type="number"
              min="0"
              value={filters.min_members || 0}
              onChange={(e) => handleFilterChange('min_members', parseInt(e.target.value) || 0)}
            />
          </div>

          <div className="filter-row">
            <label>Сортировка</label>
            <select
              value={filters.sort_by}
              onChange={(e) => handleFilterChange('sort_by', e.target.value)}
            >
              <option value="score">По качеству</option>
              <option value="members">По подписчикам</option>
              <option value="scanned_at">По дате</option>
            </select>
          </div>

          <button className="apply-filters-btn" onClick={applyFilters}>
            Применить
          </button>
        </div>
      )}

      <div className="stats-bar">
        <span>Найдено: {total}</span>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="channels-list">
        {channels.map((channel) => (
          <ChannelCard key={channel.username} channel={channel} />
        ))}
      </div>

      {loading && (
        <div className="loader">
          <div className="loader-spinner" />
        </div>
      )}

      {!loading && !hasMore && channels.length > 0 && (
        <div className="empty-state">Это все каналы</div>
      )}

      {!loading && channels.length === 0 && !error && (
        <div className="empty-state">Каналы не найдены</div>
      )}
    </div>
  )
}

export default DatabasePage
