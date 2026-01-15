import { useEffect } from 'react'
import { useStats } from '../hooks/useApi'
import './StatsPage.css'

function StatsPage() {
  const { stats, categoryStats, loading, error, fetchStats } = useStats()

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  if (loading) {
    return (
      <div className="page stats-page">
        <h1 className="page-title">Статистика</h1>
        <div className="loader">
          <div className="loader-spinner" />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="page stats-page">
        <h1 className="page-title">Статистика</h1>
        <div className="error">{error}</div>
      </div>
    )
  }

  return (
    <div className="page stats-page">
      <h1 className="page-title">Статистика</h1>

      {stats && (
        <div className="stats-grid">
          <div className="stat-card">
            <span className="stat-value">{stats.total}</span>
            <span className="stat-label">Всего</span>
          </div>
          <div className="stat-card good">
            <span className="stat-value">{stats.good}</span>
            <span className="stat-label">GOOD</span>
          </div>
          <div className="stat-card bad">
            <span className="stat-value">{stats.bad}</span>
            <span className="stat-label">BAD</span>
          </div>
          <div className="stat-card waiting">
            <span className="stat-value">{stats.waiting}</span>
            <span className="stat-label">В очереди</span>
          </div>
        </div>
      )}

      <h2 className="section-title">По категориям</h2>

      <div className="categories-list">
        {categoryStats.map((cat) => (
          <div key={cat.category} className="category-row">
            <div className="category-info">
              <span className="category-name">{cat.category}</span>
              <span className="category-count">{cat.count} каналов</span>
            </div>
            <div className="category-cpm">
              <span className="cpm-range">{cat.cpm_min}-{cat.cpm_max}₽</span>
              <span className="cpm-label">CPM</span>
            </div>
          </div>
        ))}
      </div>

      <h2 className="section-title">CPM по категориям</h2>

      <div className="cpm-table">
        <div className="cpm-header">
          <span>Категория</span>
          <span>CPM диапазон</span>
        </div>
        <div className="cpm-row premium">
          <span>CRYPTO</span>
          <span>2000-7000₽</span>
        </div>
        <div className="cpm-row premium">
          <span>FINANCE</span>
          <span>2000-5000₽</span>
        </div>
        <div className="cpm-row premium">
          <span>REAL_ESTATE</span>
          <span>2000-4000₽</span>
        </div>
        <div className="cpm-row tech">
          <span>TECH</span>
          <span>1000-2000₽</span>
        </div>
        <div className="cpm-row tech">
          <span>AI_ML</span>
          <span>1000-2000₽</span>
        </div>
        <div className="cpm-row edu">
          <span>EDUCATION</span>
          <span>700-1200₽</span>
        </div>
        <div className="cpm-row content">
          <span>ENTERTAINMENT</span>
          <span>100-500₽</span>
        </div>
        <div className="cpm-row content">
          <span>NEWS</span>
          <span>100-500₽</span>
        </div>
      </div>
    </div>
  )
}

export default StatsPage
