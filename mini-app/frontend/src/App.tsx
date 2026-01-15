import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useTelegram } from './hooks/useTelegram'
import { useChannels, useStats, useScan, Channel, ChannelDetail, ChannelFilters } from './hooks/useApi'
import styles from './App.module.css'

// All 17 categories
const ALL_CATEGORIES = [
  { id: null, label: 'Все' },
  { id: 'CRYPTO', label: 'Крипто' },
  { id: 'TECH', label: 'Tech' },
  { id: 'AI_ML', label: 'AI' },
  { id: 'FINANCE', label: 'Финансы' },
  { id: 'BUSINESS', label: 'Бизнес' },
  { id: 'REAL_ESTATE', label: 'Недвиж.' },
  { id: 'EDUCATION', label: 'Образ.' },
  { id: 'NEWS', label: 'Новости' },
  { id: 'ENTERTAINMENT', label: 'Развлеч.' },
  { id: 'LIFESTYLE', label: 'Лайф' },
  { id: 'BEAUTY', label: 'Красота' },
  { id: 'HEALTH', label: 'Здоровье' },
  { id: 'TRAVEL', label: 'Путеш.' },
  { id: 'RETAIL', label: 'Ритейл' },
  { id: 'GAMBLING', label: 'Азарт' },
  { id: 'ADULT', label: '18+' },
  { id: 'OTHER', label: 'Др.' },
]

// Quick filter categories (shown in sticky header)
const QUICK_CATEGORIES = ALL_CATEGORIES.slice(0, 6)

// Category names for display
const CATEGORY_NAMES: Record<string, string> = Object.fromEntries(
  ALL_CATEGORIES.filter(c => c.id).map(c => [c.id!, c.label])
)

// Russian verdicts
function getVerdictText(verdict: string): string {
  const map: Record<string, string> = {
    'EXCELLENT': 'Отличный',
    'GOOD': 'Хороший',
    'MEDIUM': 'Средний',
    'HIGH_RISK': 'Рискованный',
    'SCAM': 'Мошенник',
  }
  return map[verdict] || verdict
}

// Get category name
function getCategoryName(category: string): string {
  return CATEGORY_NAMES[category] || category
}

// Format number
function formatNumber(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return n.toString()
}

// Format price
function formatPrice(min: number, max: number): string {
  const formatP = (n: number) => {
    if (n >= 1000) return Math.round(n / 1000) + 'K'
    return n.toString()
  }
  return `${formatP(min)}-${formatP(max)}₽`
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

// Avatar colors
function getAvatarColor(username: string): string {
  const colors = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
    '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9'
  ]
  return colors[username.charCodeAt(0) % colors.length]
}

// v8.0: Get metric color based on percentage
function getMetricColor(score: number, max: number): string {
  const pct = (score / max) * 100
  if (pct >= 75) return 'excellent'
  if (pct >= 50) return 'good'
  if (pct >= 25) return 'warning'
  return 'poor'
}

// v8.0: Metric descriptions for modal
const METRIC_DESCRIPTIONS: Record<string, { title: string; description: string; interpretation: string }> = {
  'cv_views': {
    title: 'CV просмотров',
    description: 'Коэффициент вариации просмотров между постами. Показывает естественность распределения просмотров.',
    interpretation: '30-60% = идеально. < 10% = подозрительно ровно (боты). > 100% = волновая накрутка.'
  },
  'reach': {
    title: 'Охват аудитории',
    description: 'Какой процент подписчиков видит каждый пост в среднем.',
    interpretation: '30-60% = норма. > 100% = накрутка просмотров.'
  },
  'views_decay': {
    title: 'Стабильность просмотров',
    description: 'Соотношение просмотров новых и старых постов. Показывает органичность роста.',
    interpretation: '0.3-0.95 = органический рост. 0.98-1.02 = Bot Wall (автонакрутка).'
  },
  'forward_rate': {
    title: 'Виральность',
    description: 'Сколько раз посты репостят другие каналы и пользователи.',
    interpretation: '> 3% = вирусный контент. < 0.5% = низкая виральность.'
  },
  'comments': {
    title: 'Комментарии',
    description: 'Среднее количество комментариев на пост.',
    interpretation: 'Зависит от размера канала. Важна живость дискуссий и отсутствие спама.'
  },
  'reaction_rate': {
    title: 'Реакции',
    description: 'Процент постов с реакциями от подписчиков.',
    interpretation: '> 2% = хорошая вовлечённость. < 0.1% = Zombie Engagement (мёртвая аудитория).'
  },
  'er_variation': {
    title: 'Разнообразие вовлечения',
    description: 'Насколько разные реакции на разные посты.',
    interpretation: 'Высокое = естественное поведение. Низкое = накрутка одним методом.'
  },
  'stability': {
    title: 'Стабильность ER',
    description: 'Постоянство вовлечённости во времени.',
    interpretation: 'Стабильный ER = качественная лояльная аудитория.'
  },
  'verified': {
    title: 'Верификация',
    description: 'Канал верифицирован Telegram.',
    interpretation: 'Верификация = доверие платформы и подтверждённый автор.'
  },
  'age': {
    title: 'Возраст канала',
    description: 'Сколько времени существует канал.',
    interpretation: '> 2 лет = устоявшийся канал. < 3 мес = новый (высокий риск).'
  },
  'premium': {
    title: 'Премиум подписчики',
    description: 'Процент подписчиков с Telegram Premium.',
    interpretation: '> 5% = платёжеспособная аудитория. 0% = подозрительно.'
  },
  'source': {
    title: 'Оригинальность',
    description: 'Доля оригинального контента (не репосты).',
    interpretation: '> 70% = авторский канал. < 30% = агрегатор.'
  }
}

// Avatar component
function Avatar({ username, photoUrl, size = 32 }: { username: string; photoUrl?: string | null; size?: number }) {
  const [imgError, setImgError] = useState(false)
  const firstLetter = username.charAt(0).toUpperCase()
  const bgColor = getAvatarColor(username)

  if (photoUrl && !imgError) {
    return (
      <img
        src={photoUrl}
        alt={username}
        className={size >= 48 ? styles.detailAvatar : styles.avatar}
        style={{ width: size, height: size }}
        onError={() => setImgError(true)}
      />
    )
  }

  return (
    <div
      className={size >= 48 ? styles.detailAvatarPlaceholder : styles.avatarPlaceholder}
      style={{ width: size, height: size, backgroundColor: bgColor }}
    >
      {firstLetter}
    </div>
  )
}

// Skeleton Card
function SkeletonCard() {
  return (
    <div className={styles.skeletonCard}>
      <div className={`${styles.skeletonAvatar} ${styles.shimmer}`} />
      <div className={styles.skeletonInfo}>
        <div className={`${styles.skeletonText} ${styles.skeletonTextWide} ${styles.shimmer}`} />
        <div className={`${styles.skeletonText} ${styles.skeletonTextMedium} ${styles.shimmer}`} />
      </div>
    </div>
  )
}

function App() {
  const { webApp, hapticLight, hapticMedium, hapticSuccess, hapticError } = useTelegram()
  const { channels, total, loading, error, hasMore, fetchChannels, reset } = useChannels()
  const { stats, fetchStats } = useStats()
  const { result: scanResult, loading: scanning, error: scanError, scanChannel, reset: resetScan } = useScan()

  // State
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<ChannelFilters['sort_by']>('score')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [minScore, setMinScore] = useState(0)
  const [minTrust, setMinTrust] = useState(0)
  const [minMembers, setMinMembers] = useState(0)
  const [maxMembers, setMaxMembers] = useState(0)
  const [verdictFilter, setVerdictFilter] = useState<'good_plus' | null>(null)
  const [page, setPage] = useState(1)
  const [selectedChannel, setSelectedChannel] = useState<ChannelDetail | null>(null)
  const [showCategorySheet, setShowCategorySheet] = useState(false)
  const [showFilterSheet, setShowFilterSheet] = useState(false)
  const [expandedRisks, setExpandedRisks] = useState<Set<number>>(new Set())
  const [selectedMetric, setSelectedMetric] = useState<string | null>(null)  // v8.0: Modal state

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
      fetchChannels({ page: 1, page_size: 30, sort_by: 'score', sort_order: 'desc' })
    }
  }, [fetchStats, fetchChannels])

  // BackButton for channel detail
  useEffect(() => {
    if (!webApp) return

    if (selectedChannel) {
      webApp.BackButton.show()
      const handleBack = () => {
        hapticLight()
        setSelectedChannel(null)
        setExpandedRisks(new Set())
      }
      webApp.BackButton.onClick(handleBack)
      return () => {
        webApp.BackButton.offClick(handleBack)
        webApp.BackButton.hide()
      }
    } else {
      webApp.BackButton.hide()
    }
  }, [webApp, selectedChannel, hapticLight])

  // Build filters object
  const buildFilters = useCallback((pageNum: number): ChannelFilters => ({
    page: pageNum,
    page_size: 30,
    category: selectedCategory || undefined,
    sort_by: sortBy,
    sort_order: sortOrder,
    min_score: minScore || undefined,
    min_trust: minTrust || undefined,
    min_members: minMembers || undefined,
    max_members: maxMembers || undefined,
    verdict: verdictFilter || undefined,
  }), [selectedCategory, sortBy, sortOrder, minScore, minTrust, minMembers, maxMembers, verdictFilter])

  // Apply filters
  const applyFilters = useCallback(() => {
    setPage(1)
    reset()
    fetchChannels(buildFilters(1))
    setShowFilterSheet(false)
    setShowCategorySheet(false)
  }, [buildFilters, reset, fetchChannels])

  // Handle category change
  const handleCategorySelect = useCallback((categoryId: string | null) => {
    hapticLight()
    setSelectedCategory(categoryId)
    setPage(1)
    reset()
    fetchChannels({
      ...buildFilters(1),
      category: categoryId || undefined,
    })
  }, [hapticLight, reset, fetchChannels, buildFilters])

  // Handle search
  const handleSearch = useCallback(async () => {
    const query = searchQuery.trim().replace('@', '')
    if (!query) return

    hapticMedium()
    await scanChannel(query)
  }, [searchQuery, hapticMedium, scanChannel])

  // Handle search result
  useEffect(() => {
    if (scanResult) {
      hapticSuccess()
      setSelectedChannel(scanResult)
    }
  }, [scanResult, hapticSuccess])

  // Handle search on Enter
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }, [handleSearch])

  // Infinite scroll
  const handleScroll = useCallback(() => {
    if (!gridRef.current || loading || !hasMore) return

    const { scrollTop, scrollHeight, clientHeight } = gridRef.current
    if (scrollHeight - scrollTop - clientHeight < 200) {
      const nextPage = page + 1
      setPage(nextPage)
      fetchChannels(buildFilters(nextPage), true)
    }
  }, [loading, hasMore, page, buildFilters, fetchChannels])

  // Click on channel card
  const handleChannelClick = useCallback((channel: Channel) => {
    hapticLight()
    scanChannel(channel.username)
  }, [hapticLight, scanChannel])

  // Close channel detail
  const closeChannelDetail = useCallback(() => {
    hapticLight()
    setSelectedChannel(null)
    setExpandedRisks(new Set())
    resetScan()
  }, [hapticLight, resetScan])

  // Toggle sort order
  const toggleSort = useCallback(() => {
    hapticLight()
    const newOrder = sortOrder === 'desc' ? 'asc' : 'desc'
    setSortOrder(newOrder)
    setPage(1)
    reset()
    fetchChannels({ ...buildFilters(1), sort_order: newOrder })
  }, [hapticLight, sortOrder, reset, fetchChannels, buildFilters])

  // Toggle sort field
  const toggleSortField = useCallback(() => {
    hapticLight()
    const newField = sortBy === 'score' ? 'members' : 'score'
    setSortBy(newField)
    setPage(1)
    reset()
    fetchChannels({ ...buildFilters(1), sort_by: newField })
  }, [hapticLight, sortBy, reset, fetchChannels, buildFilters])

  // Toggle verdict filter
  const toggleVerdictFilter = useCallback(() => {
    hapticLight()
    const newVerdict = verdictFilter === 'good_plus' ? null : 'good_plus'
    setVerdictFilter(newVerdict)
    setPage(1)
    reset()
    fetchChannels({ ...buildFilters(1), verdict: newVerdict || undefined })
  }, [hapticLight, verdictFilter, reset, fetchChannels, buildFilters])

  // Clear filters
  const clearFilters = useCallback(() => {
    hapticLight()
    setSelectedCategory(null)
    setMinScore(0)
    setMinTrust(0)
    setMinMembers(0)
    setMaxMembers(0)
    setVerdictFilter(null)
    setSortBy('score')
    setSortOrder('desc')
    setPage(1)
    reset()
    fetchChannels({ page: 1, page_size: 30, sort_by: 'score', sort_order: 'desc' })
  }, [hapticLight, reset, fetchChannels])

  // Show scan error
  useEffect(() => {
    if (scanError) {
      hapticError()
    }
  }, [scanError, hapticError])

  // Toggle risk accordion
  const toggleRisk = useCallback((index: number) => {
    hapticLight()
    setExpandedRisks(prev => {
      const newSet = new Set(prev)
      if (newSet.has(index)) {
        newSet.delete(index)
      } else {
        newSet.add(index)
      }
      return newSet
    })
  }, [hapticLight])

  // Has active filters
  const hasActiveFilters = selectedCategory || minScore > 0 || minTrust > 0 ||
    minMembers > 0 || maxMembers > 0 || verdictFilter || sortBy !== 'score'

  // Count active filters
  const activeFilterCount = [
    selectedCategory,
    minScore > 0,
    minTrust > 0,
    minMembers > 0 || maxMembers > 0,
    verdictFilter,
  ].filter(Boolean).length

  // v7.0: Detailed breakdown from API
  const breakdown = useMemo(() => {
    if (!selectedChannel) return null
    return selectedChannel.breakdown || null
  }, [selectedChannel])

  // Mocked risks (will come from API later)
  const mockRisks = useMemo(() => {
    if (!selectedChannel) return []
    if (selectedChannel.trust_penalties) return selectedChannel.trust_penalties
    const tf = selectedChannel.trust_factor
    const risks = []
    if (tf < 0.9) {
      risks.push({
        name: 'Premium 0%',
        multiplier: 0.9,
        description: 'Отсутствуют премиум-подписчики.',
      })
    }
    if (tf < 0.8) {
      risks.push({
        name: 'Bot Wall',
        multiplier: 0.6,
        description: 'Просмотры подозрительно ровные.',
      })
    }
    if (tf < 0.7) {
      risks.push({
        name: 'Hollow Views',
        multiplier: 0.6,
        description: 'Высокий охват при низкой вовлечённости.',
      })
    }
    return risks
  }, [selectedChannel])

  // Channel Detail Page - v6.0 UNIFIED (no tabs!)
  if (selectedChannel) {
    return (
      <div className={styles.detailPage}>
        {/* Header */}
        <header className={styles.detailHeader}>
          <button className={styles.backButton} onClick={closeChannelDetail}>
            <span>&larr;</span>
          </button>
          <span className={styles.detailHeaderTitle}>@{selectedChannel.username}</span>
          <a
            href={`https://t.me/${selectedChannel.username}`}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.openLink}
          >
            Открыть
          </a>
        </header>

        {/* Content - ALL SECTIONS UNIFIED */}
        <div className={styles.detailContent}>
          {/* Profile Hero */}
          <div className={styles.detailHero}>
            <Avatar
              username={selectedChannel.username}
              photoUrl={selectedChannel.photo_url}
              size={56}
            />
            <div className={styles.heroInfo}>
              <div className={styles.heroScore}>
                <span className={styles.heroScoreNum}>{selectedChannel.score}</span>
                <span className={styles.heroScoreMax}>/100</span>
              </div>
              <span
                className={styles.heroVerdict}
                style={{ color: getVerdictColor(selectedChannel.verdict) }}
              >
                {getVerdictText(selectedChannel.verdict)}
              </span>
            </div>
            <div className={styles.heroMeta}>
              <span>{formatNumber(selectedChannel.members)}</span>
              <span>•</span>
              <span>Trust ×{selectedChannel.trust_factor.toFixed(2)}</span>
            </div>
          </div>

          {/* Section: Score Breakdown - v7.0 All 13 metrics */}
          <section className={styles.detailSection}>
            <h3 className={styles.sectionTitle}>Оценка</h3>
            {breakdown ? (
              <div className={styles.breakdownGrid}>
                {/* Quality Category */}
                <div className={styles.breakdownCategory}>
                  <div className={styles.breakdownRow}>
                    <span className={styles.categoryLabel}>КАЧЕСТВО</span>
                    <span>{breakdown.quality.total}/{breakdown.quality.max}</span>
                  </div>
                  <div className={styles.progressBar}>
                    <div
                      className={styles.progressFill}
                      style={{ width: `${(breakdown.quality.total / breakdown.quality.max) * 100}%` }}
                    />
                  </div>
                  {breakdown.quality.items && Object.entries(breakdown.quality.items).map(([key, item]) => (
                    <div
                      key={key}
                      className={styles.breakdownItem}
                      onClick={() => setSelectedMetric(key)}
                      role="button"
                      tabIndex={0}
                    >
                      <span className={styles.breakdownLabel}>{item.label}</span>
                      <div className={styles.breakdownBar}>
                        <div
                          className={`${styles.breakdownFill} ${styles[getMetricColor(item.score, item.max)]}`}
                          style={{ width: `${(item.score / item.max) * 100}%` }}
                        />
                      </div>
                      <span className={styles.breakdownValue}>{item.score}/{item.max}</span>
                      <span className={styles.infoIcon}>ⓘ</span>
                    </div>
                  ))}
                </div>

                {/* Engagement Category */}
                <div className={styles.breakdownCategory}>
                  <div className={styles.breakdownRow}>
                    <span className={styles.categoryLabel}>ВОВЛЕЧЁННОСТЬ</span>
                    <span>{breakdown.engagement.total}/{breakdown.engagement.max}</span>
                  </div>
                  <div className={styles.progressBar}>
                    <div
                      className={styles.progressFill}
                      style={{ width: `${(breakdown.engagement.total / breakdown.engagement.max) * 100}%` }}
                    />
                  </div>
                  {breakdown.engagement.items && Object.entries(breakdown.engagement.items).map(([key, item]) => (
                    <div
                      key={key}
                      className={styles.breakdownItem}
                      onClick={() => setSelectedMetric(key)}
                      role="button"
                      tabIndex={0}
                    >
                      <span className={styles.breakdownLabel}>{item.label}</span>
                      <div className={styles.breakdownBar}>
                        <div
                          className={`${styles.breakdownFill} ${styles[getMetricColor(item.score, item.max)]}`}
                          style={{ width: `${(item.score / item.max) * 100}%` }}
                        />
                      </div>
                      <span className={styles.breakdownValue}>{item.score}/{item.max}</span>
                      <span className={styles.infoIcon}>ⓘ</span>
                    </div>
                  ))}
                </div>

                {/* Reputation Category */}
                <div className={styles.breakdownCategory}>
                  <div className={styles.breakdownRow}>
                    <span className={styles.categoryLabel}>РЕПУТАЦИЯ</span>
                    <span>{breakdown.reputation.total}/{breakdown.reputation.max}</span>
                  </div>
                  <div className={styles.progressBar}>
                    <div
                      className={styles.progressFill}
                      style={{ width: `${(breakdown.reputation.total / breakdown.reputation.max) * 100}%` }}
                    />
                  </div>
                  {breakdown.reputation.items && Object.entries(breakdown.reputation.items).map(([key, item]) => (
                    <div
                      key={key}
                      className={styles.breakdownItem}
                      onClick={() => setSelectedMetric(key)}
                      role="button"
                      tabIndex={0}
                    >
                      <span className={styles.breakdownLabel}>{item.label}</span>
                      <div className={styles.breakdownBar}>
                        <div
                          className={`${styles.breakdownFill} ${styles[getMetricColor(item.score, item.max)]}`}
                          style={{ width: `${(item.score / item.max) * 100}%` }}
                        />
                      </div>
                      <span className={styles.breakdownValue}>{item.score}/{item.max}</span>
                      <span className={styles.infoIcon}>ⓘ</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className={styles.noPrice}>Данные загружаются...</div>
            )}
          </section>

          {/* Section: Risks */}
          <section className={styles.detailSection}>
            <h3 className={styles.sectionTitle}>Риски</h3>
            {mockRisks.length === 0 ? (
              <div className={styles.noRisks}>
                <span className={styles.noRisksIcon}>🛡️</span>
                <span className={styles.noRisksTitle}>Рисков не обнаружено</span>
                <span className={styles.noRisksText}>Канал прошёл все проверки на накрутку</span>
              </div>
            ) : (
              <div className={styles.risksList}>
                {mockRisks.map((risk, i) => (
                  <div
                    key={i}
                    className={`${styles.riskItem} ${expandedRisks.has(i) ? styles.expanded : ''}`}
                  >
                    <button
                      className={styles.riskHeader}
                      onClick={() => toggleRisk(i)}
                    >
                      <span className={styles.riskIcon}>{expandedRisks.has(i) ? '▼' : '▶'}</span>
                      <span className={styles.riskName}>{risk.name}</span>
                      <span className={`${styles.riskMult} ${
                        risk.multiplier >= 0.8 ? styles.riskLow :
                        risk.multiplier >= 0.5 ? styles.riskMedium : styles.riskHigh
                      }`}>
                        ×{risk.multiplier.toFixed(1)}
                      </span>
                    </button>
                    {expandedRisks.has(i) && (
                      <div className={styles.riskDesc}>
                        {risk.description}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Section: Price */}
          <section className={styles.detailSection}>
            <h3 className={styles.sectionTitle}>Цена</h3>
            {selectedChannel.cpm_min && selectedChannel.cpm_max ? (
              <div className={styles.priceBlock}>
                <div className={styles.priceMain}>
                  {formatPrice(selectedChannel.cpm_min, selectedChannel.cpm_max)}
                </div>
                <div className={styles.priceGrid}>
                  <div className={styles.priceRow}>
                    <span>Категория</span>
                    <span>{selectedChannel.category ? getCategoryName(selectedChannel.category) : '—'}</span>
                  </div>
                  <div className={styles.priceRow}>
                    <span>Подписчики</span>
                    <span>{formatNumber(selectedChannel.members)}</span>
                  </div>
                  <div className={styles.priceRow}>
                    <span>Score</span>
                    <span>{selectedChannel.score}%</span>
                  </div>
                  <div className={styles.priceRow}>
                    <span>Trust</span>
                    <span>×{selectedChannel.trust_factor.toFixed(2)}</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className={styles.noPrice}>
                Недостаточно данных
              </div>
            )}
          </section>

          {/* Section: Recommendations */}
          {selectedChannel.recommendations && selectedChannel.recommendations.length > 0 && (
            <section className={styles.detailSection}>
              <h3 className={styles.sectionTitle}>Рекомендации</h3>
              <div className={styles.recList}>
                {selectedChannel.recommendations.map((rec, i) => (
                  <div key={i} className={`${styles.recItem} ${styles[`rec_${rec.type}`]}`}>
                    <span className={styles.recIcon}>{rec.icon}</span>
                    <span className={styles.recText}>{rec.text}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Meta Info */}
          <div className={styles.detailMeta}>
            {selectedChannel.category && (
              <span>Категория: {getCategoryName(selectedChannel.category)}</span>
            )}
            {selectedChannel.scanned_at && (
              <span>Проверен: {new Date(selectedChannel.scanned_at).toLocaleDateString('ru-RU')}</span>
            )}
          </div>
        </div>

        {/* v8.0: Metric Explanation Modal */}
        {selectedMetric && METRIC_DESCRIPTIONS[selectedMetric] && (
          <div className={styles.metricModal} onClick={() => setSelectedMetric(null)}>
            <div className={styles.metricModalContent} onClick={e => e.stopPropagation()}>
              <h3 className={styles.metricModalTitle}>
                {METRIC_DESCRIPTIONS[selectedMetric].title}
              </h3>
              <p className={styles.metricModalDescription}>
                {METRIC_DESCRIPTIONS[selectedMetric].description}
              </p>
              <div className={styles.metricInterpretation}>
                <span className={styles.interpretationIcon}>💡</span>
                <span className={styles.interpretationText}>
                  {METRIC_DESCRIPTIONS[selectedMetric].interpretation}
                </span>
              </div>
              <button className={styles.closeModal} onClick={() => setSelectedMetric(null)}>
                Понятно
              </button>
            </div>
          </div>
        )}
      </div>
    )
  }

  // Main List View - v6.0 NO BOTTOM TABS
  return (
    <div className={styles.app}>
      {/* Sticky Header */}
      <div className={styles.stickyHeader}>
        <header className={styles.header}>
          {/* Stats Bar - NO duplicate title! Telegram shows it */}
          <div className={styles.statsBar}>
            <span className={styles.statsBadge}>
              <strong>{stats ? formatNumber(stats.total) : '...'}</strong> каналов
              {stats && stats.good > 0 && (
                <span className={styles.statsGood}> • {formatNumber(stats.good)} ✓</span>
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
              {scanning ? '...' : '▶'}
            </button>
          </div>
        </header>

        {/* Category Chips + Filter Button */}
        <div className={styles.categories}>
          {QUICK_CATEGORIES.map((cat) => (
            <button
              key={cat.id || 'all'}
              className={`${styles.chip} ${selectedCategory === cat.id ? styles.chipSelected : ''}`}
              onClick={() => handleCategorySelect(cat.id)}
            >
              {cat.label}
            </button>
          ))}
          <button
            className={styles.chip}
            onClick={() => { hapticLight(); setShowCategorySheet(true) }}
          >
            ...
          </button>
          <button
            className={`${styles.filterButton} ${activeFilterCount > 0 ? styles.hasFilters : ''}`}
            onClick={() => { hapticLight(); setShowFilterSheet(true) }}
          >
            ⚙{activeFilterCount > 0 && <span className={styles.filterBadge}>{activeFilterCount}</span>}
          </button>
        </div>

        {/* Active Filters Chips */}
        <div className={styles.activeFilters}>
          <button className={styles.sortChip} onClick={toggleSortField}>
            {sortBy === 'score' ? 'Score' : 'Подп.'}
          </button>
          <button className={styles.sortChip} onClick={toggleSort}>
            {sortOrder === 'desc' ? '↓' : '↑'}
          </button>
          <button
            className={`${styles.filterChip} ${verdictFilter ? styles.active : ''}`}
            onClick={toggleVerdictFilter}
          >
            {verdictFilter ? 'GOOD+' : 'Все'}
          </button>
          {minScore > 0 && (
            <span className={styles.activeChip}>{minScore}+</span>
          )}
          {minTrust > 0 && (
            <span className={styles.activeChip}>T≥{minTrust}</span>
          )}
          {(minMembers > 0 || maxMembers > 0) && (
            <span className={styles.activeChip}>
              {minMembers > 0 ? formatNumber(minMembers) : '0'}-{maxMembers > 0 ? formatNumber(maxMembers) : '∞'}
            </span>
          )}
          {hasActiveFilters && (
            <button className={styles.clearChip} onClick={clearFilters}>×</button>
          )}
          <span className={styles.channelCount}>{total}</span>
        </div>
      </div>

      {/* Category Bottom Sheet */}
      {showCategorySheet && (
        <>
          <div className={styles.sheetOverlay} onClick={() => setShowCategorySheet(false)} />
          <div className={styles.bottomSheet}>
            <div className={styles.sheetHandle} />
            <h3 className={styles.sheetTitle}>Категория</h3>
            <div className={styles.categoryGrid}>
              {ALL_CATEGORIES.map((cat) => (
                <button
                  key={cat.id || 'all'}
                  className={`${styles.categoryOption} ${selectedCategory === cat.id ? styles.selected : ''}`}
                  onClick={() => {
                    handleCategorySelect(cat.id)
                    setShowCategorySheet(false)
                  }}
                >
                  {cat.label}
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Filter Bottom Sheet - v6.0 EXTENDED */}
      {showFilterSheet && (
        <>
          <div className={styles.sheetOverlay} onClick={() => setShowFilterSheet(false)} />
          <div className={styles.filterSheet}>
            <div className={styles.sheetHandle} />
            <div className={styles.sheetHeader}>
              <h3 className={styles.sheetTitle}>Фильтры</h3>
              <button className={styles.sheetClose} onClick={() => setShowFilterSheet(false)}>×</button>
            </div>

            {/* Sort */}
            <div className={styles.filterGroup}>
              <label className={styles.filterLabel}>Сортировка</label>
              <div className={styles.filterOptions}>
                <button
                  className={`${styles.filterOption} ${sortBy === 'score' ? styles.active : ''}`}
                  onClick={() => setSortBy('score')}
                >
                  Score
                </button>
                <button
                  className={`${styles.filterOption} ${sortBy === 'members' ? styles.active : ''}`}
                  onClick={() => setSortBy('members')}
                >
                  Подп.
                </button>
                <button
                  className={`${styles.filterOption} ${sortBy === 'trust_factor' ? styles.active : ''}`}
                  onClick={() => setSortBy('trust_factor')}
                >
                  Trust
                </button>
                <button
                  className={`${styles.filterOption} ${sortBy === 'scanned_at' ? styles.active : ''}`}
                  onClick={() => setSortBy('scanned_at')}
                >
                  Дата
                </button>
              </div>
            </div>

            {/* Min Score */}
            <div className={styles.filterGroup}>
              <label className={styles.filterLabel}>Мин. оценка: {minScore}</label>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
                className={styles.filterSlider}
              />
            </div>

            {/* Min Trust */}
            <div className={styles.filterGroup}>
              <label className={styles.filterLabel}>Мин. Trust: {minTrust.toFixed(1)}</label>
              <div className={styles.trustChips}>
                {[0, 0.5, 0.7, 0.9].map((t) => (
                  <button
                    key={t}
                    className={`${styles.trustChip} ${minTrust === t ? styles.active : ''}`}
                    onClick={() => setMinTrust(t)}
                  >
                    {t === 0 ? 'Все' : `≥${t}`}
                  </button>
                ))}
              </div>
            </div>

            {/* Verdict */}
            <div className={styles.filterGroup}>
              <label className={styles.filterLabel}>Вердикт</label>
              <div className={styles.verdictToggle}>
                <button
                  className={`${styles.verdictOption} ${!verdictFilter ? styles.active : ''}`}
                  onClick={() => setVerdictFilter(null)}
                >
                  Все
                </button>
                <button
                  className={`${styles.verdictOption} ${verdictFilter === 'good_plus' ? styles.active : ''}`}
                  onClick={() => setVerdictFilter('good_plus')}
                >
                  GOOD+
                </button>
              </div>
            </div>

            {/* Members Range */}
            <div className={styles.filterGroup}>
              <label className={styles.filterLabel}>Подписчики</label>
              <div className={styles.rangeInputs}>
                <input
                  type="number"
                  placeholder="от"
                  value={minMembers || ''}
                  onChange={(e) => setMinMembers(Number(e.target.value) || 0)}
                  className={styles.rangeInput}
                />
                <span>—</span>
                <input
                  type="number"
                  placeholder="до"
                  value={maxMembers || ''}
                  onChange={(e) => setMaxMembers(Number(e.target.value) || 0)}
                  className={styles.rangeInput}
                />
              </div>
            </div>

            {/* Actions */}
            <div className={styles.sheetActions}>
              <button className={styles.filterReset} onClick={() => {
                setMinScore(0)
                setMinTrust(0)
                setMinMembers(0)
                setMaxMembers(0)
                setVerdictFilter(null)
                setSortBy('score')
                setSortOrder('desc')
              }}>
                Сбросить
              </button>
              <button className={styles.filterApply} onClick={applyFilters}>
                Показать {total}
              </button>
            </div>
          </div>
        </>
      )}

      {/* Content */}
      <main
        className={styles.content}
        ref={gridRef}
        onScroll={handleScroll}
      >
        {scanError && (
          <div className={styles.searchError}>
            {scanError}
          </div>
        )}

        {error ? (
          <div className={styles.errorState}>
            <span className={styles.stateIcon}>⚠️</span>
            <p>{error}</p>
            <button onClick={() => fetchChannels({ page: 1, page_size: 30 })}>
              Повторить
            </button>
          </div>
        ) : loading && channels.length === 0 ? (
          <div className={styles.channelGrid}>
            {Array.from({ length: 8 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : channels.length === 0 ? (
          <div className={styles.emptyState}>
            <span className={styles.stateIcon}>{hasActiveFilters ? '🔍' : '📭'}</span>
            <p>{hasActiveFilters ? 'Ничего не найдено' : 'Нет каналов'}</p>
            {hasActiveFilters && (
              <button onClick={clearFilters}>Сбросить фильтры</button>
            )}
          </div>
        ) : (
          <>
            <div className={styles.channelGrid}>
              {channels.map((channel, index) => (
                <button
                  key={channel.username}
                  className={styles.channelCard}
                  data-verdict={channel.verdict}
                  onClick={() => handleChannelClick(channel)}
                  style={{ animationDelay: `${Math.min(index, 5) * 20}ms` }}
                >
                  {/* Avatar */}
                  <Avatar
                    username={channel.username}
                    photoUrl={channel.photo_url}
                    size={32}
                  />

                  {/* Card Info */}
                  <div className={styles.cardInfo}>
                    <div className={styles.cardTop}>
                      <span className={styles.cardUsername}>@{channel.username}</span>
                      <span
                        className={styles.cardScore}
                        style={{ color: getVerdictColor(channel.verdict) }}
                      >
                        {channel.score}
                      </span>
                    </div>
                    <div className={styles.cardBottom}>
                      {channel.category && (
                        <span className={styles.cardCategory}>{getCategoryName(channel.category)}</span>
                      )}
                      <span>•</span>
                      <span>{formatNumber(channel.members)}</span>
                      <span>•</span>
                      <span>T:{channel.trust_factor.toFixed(2)}</span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
            {loading && (
              <div className={styles.loadingMore}>
                <div className={styles.spinner} />
              </div>
            )}
          </>
        )}
      </main>

      {/* NO BOTTOM TABS in v6.0! */}
    </div>
  )
}

export default App
