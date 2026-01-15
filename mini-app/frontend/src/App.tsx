import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useTelegram } from './hooks/useTelegram'
import { useChannels, useStats, useScan, Channel } from './hooks/useApi'
import styles from './App.module.css'

// Category list
const CATEGORIES = [
  { id: null, label: 'Все' },
  { id: 'TECH', label: 'Tech' },
  { id: 'CRYPTO', label: 'Crypto' },
  { id: 'FINANCE', label: 'Finance' },
  { id: 'AI_ML', label: 'AI/ML' },
  { id: 'BUSINESS', label: 'Business' },
  { id: 'EDUCATION', label: 'Education' },
  { id: 'NEWS', label: 'News' },
  { id: 'ENTERTAINMENT', label: 'Entertainment' },
  { id: 'LIFESTYLE', label: 'Lifestyle' },
]

// Format number
function formatNumber(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return n.toString()
}

// Verdict color
function getVerdictColor(verdict: string): string {
  switch (verdict) {
    case 'EXCELLENT': return 'var(--verdict-excellent)'
    case 'GOOD': return 'var(--verdict-good)'
    case 'MEDIUM': return 'var(--verdict-medium)'
    case 'HIGH_RISK': return 'var(--verdict-high-risk)'
    case 'SCAM': return 'var(--verdict-scam)'
    default: return 'var(--hint-color)'
  }
}

function App() {
  const { webApp, hapticLight, hapticMedium, hapticSuccess, hapticError } = useTelegram()
  const { channels, loading, error, hasMore, fetchChannels, reset } = useChannels()
  const { stats, fetchStats } = useStats()
  const { result: scanResult, loading: scanning, error: scanError, scanChannel, reset: resetScan } = useScan()

  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [showResult, setShowResult] = useState(false)
  const [page, setPage] = useState(1)

  const gridRef = useRef<HTMLDivElement>(null)
  const isInitialized = useRef(false)

  // Initialize Telegram WebApp
  useEffect(() => {
    if (webApp) {
      try {
        webApp.ready()
        webApp.expand()
      } catch (e) {
        console.warn('[App] WebApp init failed:', e)
      }
    }
  }, [webApp])

  // Load initial data
  useEffect(() => {
    if (!isInitialized.current) {
      isInitialized.current = true
      fetchStats()
      fetchChannels({ page: 1, page_size: 30, category: undefined })
    }
  }, [fetchStats, fetchChannels])

  // Handle category change
  const handleCategorySelect = useCallback((categoryId: string | null) => {
    hapticLight()
    setSelectedCategory(categoryId)
    setPage(1)
    reset()
    fetchChannels({
      page: 1,
      page_size: 30,
      category: categoryId || undefined
    })
  }, [hapticLight, reset, fetchChannels])

  // Handle search
  const handleSearch = useCallback(async () => {
    const query = searchQuery.trim().replace('@', '')
    if (!query) return

    hapticMedium()
    await scanChannel(query)
    setShowResult(true)

    if (scanResult) {
      hapticSuccess()
    }
  }, [searchQuery, hapticMedium, scanChannel, scanResult, hapticSuccess])

  // Handle search on Enter
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }, [handleSearch])

  // Close result sheet
  const closeResult = useCallback(() => {
    hapticLight()
    setShowResult(false)
    setTimeout(() => resetScan(), 300)
  }, [hapticLight, resetScan])

  // Infinite scroll
  const handleScroll = useCallback(() => {
    if (!gridRef.current || loading || !hasMore) return

    const { scrollTop, scrollHeight, clientHeight } = gridRef.current
    if (scrollHeight - scrollTop - clientHeight < 200) {
      const nextPage = page + 1
      setPage(nextPage)
      fetchChannels({
        page: nextPage,
        page_size: 30,
        category: selectedCategory || undefined
      }, true)
    }
  }, [loading, hasMore, page, selectedCategory, fetchChannels])

  // Click on channel card
  const handleChannelClick = useCallback((channel: Channel) => {
    hapticLight()
    setSearchQuery(channel.username)
    // Show result directly without API call since we have the data
    resetScan()
    // Use scanChannel to fetch fresh data
    scanChannel(channel.username).then(() => {
      setShowResult(true)
    })
  }, [hapticLight, resetScan, scanChannel])

  // Filtered channels (for display)
  const displayChannels = useMemo(() => {
    return channels
  }, [channels])

  // Show scan error
  useEffect(() => {
    if (scanError) {
      hapticError()
    }
  }, [scanError, hapticError])

  return (
    <div className={styles.app}>
      {/* Header */}
      <header className={styles.header}>
        {/* Stats Badge */}
        <div className={styles.statsBar}>
          <span className={styles.statsBadge}>
            {stats ? (
              <>
                <strong>{formatNumber(stats.total)}</strong> каналов
                <span className={styles.statsGood}>{stats.good} GOOD</span>
              </>
            ) : (
              'Загрузка...'
            )}
          </span>
        </div>

        {/* Search Bar */}
        <div className={styles.searchBar}>
          <span className={styles.searchIcon}>@</span>
          <input
            type="text"
            className={styles.searchInput}
            placeholder="Проверить канал..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          {searchQuery && (
            <button
              className={styles.clearButton}
              onClick={() => setSearchQuery('')}
            >
              &times;
            </button>
          )}
          <button
            className={styles.scanButton}
            onClick={handleSearch}
            disabled={!searchQuery.trim() || scanning}
          >
            {scanning ? '...' : 'Scan'}
          </button>
        </div>

        {/* Category Chips */}
        <div className={styles.categoryChips}>
          {CATEGORIES.map((cat) => (
            <button
              key={cat.id || 'all'}
              className={`${styles.chip} ${selectedCategory === cat.id ? styles.chipSelected : ''}`}
              onClick={() => handleCategorySelect(cat.id)}
            >
              {cat.label}
            </button>
          ))}
        </div>
      </header>

      {/* Content */}
      <main
        className={styles.content}
        ref={gridRef}
        onScroll={handleScroll}
      >
        {error ? (
          <div className={styles.errorState}>
            <p>{error}</p>
            <button onClick={() => fetchChannels({ page: 1, page_size: 30 })}>
              Повторить
            </button>
          </div>
        ) : displayChannels.length === 0 && !loading ? (
          <div className={styles.emptyState}>
            <p>Каналы не найдены</p>
          </div>
        ) : (
          <div className={styles.channelGrid}>
            {displayChannels.map((channel, index) => (
              <button
                key={channel.username}
                className={styles.channelCard}
                onClick={() => handleChannelClick(channel)}
                style={{ animationDelay: `${Math.min(index, 9) * 30}ms` }}
              >
                <div
                  className={styles.cardScore}
                  style={{ backgroundColor: getVerdictColor(channel.verdict) }}
                >
                  {channel.score}
                </div>
                <div className={styles.cardUsername}>@{channel.username}</div>
                <div className={styles.cardVerdict} style={{ color: getVerdictColor(channel.verdict) }}>
                  {channel.verdict}
                </div>
                {channel.category && (
                  <div className={styles.cardCategory}>{channel.category}</div>
                )}
                <div className={styles.cardMembers}>{formatNumber(channel.members)}</div>
              </button>
            ))}
          </div>
        )}

        {loading && (
          <div className={styles.loading}>
            <div className={styles.spinner} />
          </div>
        )}
      </main>

      {/* Result Sheet (BottomSheet) */}
      {showResult && (scanResult || scanError) && (
        <div className={styles.overlay} onClick={closeResult}>
          <div className={styles.sheet} onClick={(e) => e.stopPropagation()}>
            <div className={styles.sheetHandle} />

            {scanError ? (
              <div className={styles.sheetError}>
                <p>{scanError}</p>
              </div>
            ) : scanResult && (
              <>
                <div className={styles.sheetHeader}>
                  <span className={styles.sheetUsername}>@{scanResult.username}</span>
                  <span className={styles.sheetMembers}>{formatNumber(scanResult.members)} subs</span>
                </div>

                <div className={styles.scoreSection}>
                  <div
                    className={styles.scoreRing}
                    style={{
                      '--score': scanResult.score,
                      '--color': getVerdictColor(scanResult.verdict)
                    } as React.CSSProperties}
                  >
                    <svg viewBox="0 0 100 100">
                      <circle cx="50" cy="50" r="45" className={styles.ringBg} />
                      <circle cx="50" cy="50" r="45" className={styles.ringProgress} />
                    </svg>
                    <div className={styles.scoreValue}>
                      <span className={styles.scoreNumber}>{scanResult.score}</span>
                      <span
                        className={styles.scoreVerdict}
                        style={{ color: getVerdictColor(scanResult.verdict) }}
                      >
                        {scanResult.verdict}
                      </span>
                    </div>
                  </div>

                  <div className={styles.trustSection}>
                    <span className={styles.trustLabel}>Trust Factor</span>
                    <span
                      className={styles.trustValue}
                      style={{
                        color: scanResult.trust_factor >= 0.8
                          ? 'var(--trust-high)'
                          : scanResult.trust_factor >= 0.5
                            ? 'var(--trust-medium)'
                            : 'var(--trust-low)'
                      }}
                    >
                      &times;{scanResult.trust_factor.toFixed(2)}
                    </span>
                  </div>
                </div>

                <div className={styles.infoGrid}>
                  {scanResult.category && (
                    <div className={styles.infoItem}>
                      <span className={styles.infoLabel}>Категория</span>
                      <span className={styles.infoValue}>{scanResult.category}</span>
                    </div>
                  )}
                  {scanResult.cpm_min && scanResult.cpm_max && (
                    <div className={styles.infoItem}>
                      <span className={styles.infoLabel}>CPM</span>
                      <span className={styles.infoValue}>
                        {scanResult.cpm_min}-{scanResult.cpm_max}
                      </span>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default App
