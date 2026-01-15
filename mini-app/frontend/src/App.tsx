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

// v9.0: All categories shown in filter sheet (no quick categories)

// Category names for display
const CATEGORY_NAMES: Record<string, string> = Object.fromEntries(
  ALL_CATEGORIES.filter(c => c.id).map(c => [c.id!, c.label])
)

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

// v10.0: Trust label — понятный текст вместо ×1.00
function getTrustLabel(trust: number): { text: string; color: string } {
  if (trust >= 0.9) return { text: 'высокое', color: 'var(--verdict-excellent)' }
  if (trust >= 0.7) return { text: 'среднее', color: 'var(--verdict-medium)' }
  return { text: 'низкое', color: 'var(--verdict-scam)' }
}

// Avatar colors
function getAvatarColor(username: string): string {
  const colors = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
    '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9'
  ]
  return colors[username.charCodeAt(0) % colors.length]
}

// v11.3: Estimate ER based on score and channel size
// ER = Views / Members * 100
// Small channels: higher ER (15-30%), Large: lower (3-8%)
function estimateER(members: number, score: number): number {
  // Base ER by channel size
  let baseER: number
  if (members < 5000) {
    baseER = 25 // micro channels ~25%
  } else if (members < 20000) {
    baseER = 15 // small channels ~15%
  } else if (members < 50000) {
    baseER = 10 // medium channels ~10%
  } else if (members < 100000) {
    baseER = 6 // large channels ~6%
  } else {
    baseER = 4 // mega channels ~4%
  }

  // Adjust by score (quality affects engagement)
  // Score 80+ = +30%, Score 60-80 = +0%, Score <60 = -30%
  const scoreMult = score >= 80 ? 1.3 : score >= 60 ? 1.0 : 0.7

  const er = baseER * scoreMult
  // Round to 1 decimal place
  return Math.round(er * 10) / 10
}

// v11.0: Traffic Light system
function getTrafficLight(score: number, max: number): { emoji: string; color: 'green' | 'yellow' | 'red' } {
  const pct = (score / max) * 100
  if (pct >= 70) return { emoji: '🟢', color: 'green' }
  if (pct >= 40) return { emoji: '🟡', color: 'yellow' }
  return { emoji: '🔴', color: 'red' }
}

// v11.0: Alert severity based on multiplier
function getAlertSeverity(multiplier: number): 'critical' | 'warning' | 'info' {
  if (multiplier < 0.7) return 'critical'
  if (multiplier < 0.9) return 'warning'
  return 'info'
}

// v11.5: ScoreRing компонент для карточек (SVG circle с прогрессом)
// large: для детального просмотра (90px), обычный: 64px
function ScoreRing({ score, verdict, showCheck, large }: { score: number; verdict: string; showCheck?: boolean; large?: boolean }) {
  // Большой размер для детального просмотра
  const size = large ? 90 : 64
  const radius = large ? 36 : 26
  const center = size / 2
  const circumference = 2 * Math.PI * radius
  const progress = (score / 100) * circumference
  const offset = circumference - progress

  return (
    <div className={large ? styles.scoreRingLarge : styles.scoreRing}>
      <svg viewBox={`0 0 ${size} ${size}`} className={styles.scoreRingSvg}>
        {/* Background circle */}
        <circle
          cx={center} cy={center} r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.1)"
          strokeWidth={large ? 4 : 3}
        />
        {/* Progress circle */}
        <circle
          cx={center} cy={center} r={radius}
          fill="none"
          stroke={getVerdictColor(verdict)}
          strokeWidth={large ? 4 : 3}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transform: 'rotate(-90deg)', transformOrigin: 'center' }}
        />
      </svg>
      <span className={styles.scoreRingValue}>{score}</span>
      {/* Синий кружок с галочкой справа-сверху */}
      {showCheck && (
        <div className={styles.verifiedBadge}>
          <svg viewBox="0 0 24 24" fill="#000">
            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
          </svg>
        </div>
      )}
    </div>
  )
}

// v9.0: Metric descriptions - simple Russian without numbers
const METRIC_DESCRIPTIONS: Record<string, { title: string; description: string; interpretation: string }> = {
  'cv_views': {
    title: 'CV просмотров',
    description: 'Насколько разные просмотры на разных постах.',
    interpretation: 'Хорошо когда просмотры разные на разных постах. Если везде одинаково — возможна накрутка.'
  },
  'reach': {
    title: 'Охват аудитории',
    description: 'Какая часть подписчиков видит каждый пост.',
    interpretation: 'Нормально когда каждый пост видит часть аудитории. Если охват больше подписчиков — накрутка.'
  },
  'views_decay': {
    title: 'Стабильность просмотров',
    description: 'Как меняются просмотры со временем.',
    interpretation: 'Старые посты должны получать меньше просмотров. Если везде одинаково — это накрутка ботами.'
  },
  'forward_rate': {
    title: 'Виральность',
    description: 'Как часто посты репостят.',
    interpretation: 'Вирусный контент постоянно репостят. Мало репостов — слабая виральность.'
  },
  'comments': {
    title: 'Комментарии',
    description: 'Активность в комментариях.',
    interpretation: 'Живые обсуждения — признак настоящей аудитории. Пустые комменты или спам — плохо.'
  },
  'reaction_rate': {
    title: 'Реакции',
    description: 'Как активно подписчики ставят реакции.',
    interpretation: 'Подписчики должны реагировать на посты. Нет реакций — мёртвая аудитория.'
  },
  'er_variation': {
    title: 'Разнообразие вовлечения',
    description: 'Насколько разные реакции на разные посты.',
    interpretation: 'Естественно когда на разные посты разная реакция. Одинаково везде — накрутка.'
  },
  'stability': {
    title: 'Стабильность ER',
    description: 'Постоянство активности аудитории.',
    interpretation: 'Стабильная вовлечённость = лояльная аудитория. Скачки — подозрительно.'
  },
  'verified': {
    title: 'Верификация',
    description: 'Официальная верификация от Telegram.',
    interpretation: 'Верификация означает что Telegram подтвердил подлинность канала.'
  },
  'age': {
    title: 'Возраст канала',
    description: 'Сколько времени существует канал.',
    interpretation: 'Старые каналы проверены временем. Новые каналы — высокий риск.'
  },
  'premium': {
    title: 'Премиум подписчики',
    description: 'Есть ли подписчики с Telegram Premium.',
    interpretation: 'Премиум подписчики — признак живой платёжеспособной аудитории.'
  },
  'source': {
    title: 'Оригинальность',
    description: 'Сколько контента создано автором.',
    interpretation: 'Много оригинального контента — авторский канал. Одни репосты — агрегатор.'
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
  const { fetchStats } = useStats()  // v9.0: stats removed from UI
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
  const [showFilterSheet, setShowFilterSheet] = useState(false)  // v9.0: single unified filter sheet
  const [selectedMetric, setSelectedMetric] = useState<string | null>(null)  // v8.0: Modal state
  const [activeTab, setActiveTab] = useState<'search' | 'history' | 'watchlist' | 'profile'>('search')  // v11.0: Bottom Nav
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())  // v11.0: Accordions

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
  }, [buildFilters, reset, fetchChannels])

  // v9.0: Category selection now happens in filter sheet, applied on "Показать"

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
    resetScan()
  }, [hapticLight, resetScan])

  // v9.0: All filter toggles now in unified filter sheet, applied on "Показать"

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

  // v11.0: Toggle accordion category
  const toggleCategory = useCallback((cat: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev)
      if (next.has(cat)) {
        next.delete(cat)
      } else {
        next.add(cat)
      }
      return next
    })
  }, [])

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

  // Channel Detail Page - v9.0 COMPACT LAYOUT
  if (selectedChannel) {
    return (
      <div className={styles.detailPage}>
        {/* Header - v9.0: Compact, no nickname */}
        <header className={styles.detailHeader}>
          <button className={styles.backButton} onClick={closeChannelDetail}>
            ← Назад
          </button>
          <a
            href={`https://t.me/${selectedChannel.username}`}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.openLink}
          >
            Открыть →
          </a>
        </header>

        {/* Content - ALL SECTIONS UNIFIED */}
        <div className={styles.detailContent}>
          {/* v11.0: Hero with Speedometer instead of badge */}
          <div className={styles.heroWithSpeedometer}>
            <Avatar
              username={selectedChannel.username}
              photoUrl={selectedChannel.photo_url}
              size={56}
            />
            <div className={styles.heroInfoCompact}>
              <span className={styles.heroUsername}>@{selectedChannel.username}</span>
              <span className={styles.heroSubtitle}>
                {formatNumber(selectedChannel.members)} • {selectedChannel.trust_factor >= 0.9 ? '🛡️' : '⚠️'}{' '}
                <span style={{ color: getTrustLabel(selectedChannel.trust_factor).color }}>
                  {getTrustLabel(selectedChannel.trust_factor).text}
                </span>
              </span>
              {selectedChannel.cpm_min && selectedChannel.cpm_max && (
                <span className={styles.heroPrice}>
                  💰 {formatPrice(selectedChannel.cpm_min, selectedChannel.cpm_max)}
                </span>
              )}
            </div>
            {/* v11.5: Единый ScoreRing (большой размер) */}
            <ScoreRing
              score={selectedChannel.score}
              verdict={selectedChannel.verdict}
              showCheck={selectedChannel.trust_factor >= 0.9}
              large
            />
          </div>

          {/* v11.0: Key Alerts Block */}
          <div className={styles.alertsSection}>
            {mockRisks.length > 0 ? (
              <>
                <div className={styles.alertsHeader}>
                  ⚠️ Риски ({mockRisks.length})
                </div>
                {mockRisks.map((risk, i) => {
                  const severity = getAlertSeverity(risk.multiplier)
                  return (
                    <div key={i} className={`${styles.alertCard} ${styles[severity]}`}>
                      <span className={styles.alertIcon}>
                        {severity === 'critical' ? '🚨' : '⚠️'}
                      </span>
                      <div className={styles.alertContent}>
                        <div className={styles.alertTitle}>
                          <span>{risk.name}</span>
                          <span className={`${styles.alertMult} ${styles[severity]}`}>
                            ×{risk.multiplier.toFixed(2)}
                          </span>
                        </div>
                        <div className={styles.alertDesc}>{risk.description}</div>
                      </div>
                    </div>
                  )
                })}
              </>
            ) : (
              <div className={styles.noAlertsCard}>
                <span>🛡️</span>
                <span className={styles.noAlertsText}>Рисков не обнаружено</span>
              </div>
            )}
          </div>

          {/* v11.0: Breakdown with Accordions and Traffic Lights */}
          {breakdown ? (
            <div className={styles.accordionSection}>
              {/* Quality Accordion */}
              <button
                className={`${styles.accordionHeader} ${expandedCategories.has('quality') ? styles.expanded : ''}`}
                onClick={() => toggleCategory('quality')}
              >
                <span className={styles.accordionArrow}>›</span>
                <span className={styles.accordionLabel}>КАЧЕСТВО</span>
                <span className={styles.accordionScore}>{breakdown.quality.total}/{breakdown.quality.max}</span>
              </button>
              {expandedCategories.has('quality') && (
                <div className={styles.accordionBody}>
                  {breakdown.quality.items && Object.entries(breakdown.quality.items).map(([key, item]) => {
                    const light = getTrafficLight(item.score, item.max)
                    return (
                      <div
                        key={key}
                        className={styles.metricRow}
                        onClick={() => setSelectedMetric(key)}
                        role="button"
                        tabIndex={0}
                      >
                        <span className={styles.metricLight}>{light.emoji}</span>
                        <span className={styles.metricLabel}>{item.label}</span>
                        <span className={styles.metricValue}>{item.score}/{item.max}</span>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Engagement Accordion */}
              <button
                className={`${styles.accordionHeader} ${expandedCategories.has('engagement') ? styles.expanded : ''}`}
                onClick={() => toggleCategory('engagement')}
              >
                <span className={styles.accordionArrow}>›</span>
                <span className={styles.accordionLabel}>ВОВЛЕЧЁННОСТЬ</span>
                <span className={styles.accordionScore}>{breakdown.engagement.total}/{breakdown.engagement.max}</span>
              </button>
              {expandedCategories.has('engagement') && (
                <div className={styles.accordionBody}>
                  {breakdown.engagement.items && Object.entries(breakdown.engagement.items).map(([key, item]) => {
                    const light = getTrafficLight(item.score, item.max)
                    return (
                      <div
                        key={key}
                        className={styles.metricRow}
                        onClick={() => setSelectedMetric(key)}
                        role="button"
                        tabIndex={0}
                      >
                        <span className={styles.metricLight}>{light.emoji}</span>
                        <span className={styles.metricLabel}>{item.label}</span>
                        <span className={styles.metricValue}>{item.score}/{item.max}</span>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Reputation Accordion */}
              <button
                className={`${styles.accordionHeader} ${expandedCategories.has('reputation') ? styles.expanded : ''}`}
                onClick={() => toggleCategory('reputation')}
              >
                <span className={styles.accordionArrow}>›</span>
                <span className={styles.accordionLabel}>РЕПУТАЦИЯ</span>
                <span className={styles.accordionScore}>{breakdown.reputation.total}/{breakdown.reputation.max}</span>
              </button>
              {expandedCategories.has('reputation') && (
                <div className={styles.accordionBody}>
                  {breakdown.reputation.items && Object.entries(breakdown.reputation.items).map(([key, item]) => {
                    const light = getTrafficLight(item.score, item.max)
                    return (
                      <div
                        key={key}
                        className={styles.metricRow}
                        onClick={() => setSelectedMetric(key)}
                        role="button"
                        tabIndex={0}
                      >
                        <span className={styles.metricLight}>{light.emoji}</span>
                        <span className={styles.metricLabel}>{item.label}</span>
                        <span className={styles.metricValue}>{item.score}/{item.max}</span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          ) : (
            <div className={styles.noPrice}>Данные загружаются...</div>
          )}

          {/* v10.1: Risks section REMOVED - now shown in Hero */}

          {/* v10.1: Price section REMOVED - now shown in Hero */}

          {/* Section: Recommendations - v10.1 filter out cpm (shown in Hero) */}
          {selectedChannel.recommendations && selectedChannel.recommendations.filter(r => r.type !== 'cpm').length > 0 && (
            <div className={styles.recsCompact}>
              {selectedChannel.recommendations.filter(r => r.type !== 'cpm').slice(0, 2).map((rec, i) => (
                <div key={i} className={styles.recCompactItem}>
                  <span>{rec.icon}</span>
                  <span>{rec.text}</span>
                </div>
              ))}
            </div>
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

  // v11.0: Stub pages for inactive tabs
  if (activeTab !== 'search') {
    const tabInfo = {
      history: { icon: '📋', title: 'История', text: 'История просмотров появится здесь' },
      watchlist: { icon: '⭐', title: 'Избранное', text: 'Сохраняйте интересные каналы' },
      profile: { icon: '👤', title: 'Профиль', text: 'Настройки и статистика' },
    }[activeTab]

    return (
      <div className={styles.app}>
        <div className={styles.stubPage}>
          <span className={styles.stubIcon}>{tabInfo.icon}</span>
          <h2 className={styles.stubTitle}>{tabInfo.title}</h2>
          <p className={styles.stubText}>{tabInfo.text}</p>
          <p className={styles.stubText} style={{ marginTop: '8px', opacity: 0.6 }}>Скоро</p>
        </div>

        {/* v11.0: Bottom Navigation Bar */}
        <nav className={styles.bottomNav}>
          {[
            { id: 'search' as const, icon: '🔍', label: 'Поиск' },
            { id: 'history' as const, icon: '📋', label: 'История' },
            { id: 'watchlist' as const, icon: '⭐', label: 'Избранное' },
            { id: 'profile' as const, icon: '👤', label: 'Профиль' },
          ].map(tab => (
            <button
              key={tab.id}
              className={`${styles.navItem} ${activeTab === tab.id ? styles.active : ''}`}
              onClick={() => { hapticLight(); setActiveTab(tab.id) }}
            >
              <span className={styles.navIcon}>{tab.icon}</span>
              <span className={styles.navLabel}>{tab.label}</span>
            </button>
          ))}
        </nav>
      </div>
    )
  }

  // Main List View - v11.0 with Bottom Nav
  return (
    <div className={styles.app}>
      {/* Sticky Header - v11.1: Search + Quick Categories */}
      <div className={styles.stickyHeader}>
        <div className={styles.searchRow}>
          {/* Search Bar */}
          <div className={styles.searchBar}>
            <span className={styles.searchIconSvg}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8"/>
                <path d="m21 21-4.35-4.35"/>
              </svg>
            </span>
            <input
              type="text"
              className={styles.searchInput}
              placeholder="Поиск канала..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleKeyDown}
            />
            {scanning && <span className={styles.searchSpinner}>...</span>}
            {searchQuery && !scanning && (
              <button
                className={styles.clearButton}
                onClick={() => setSearchQuery('')}
              >
                ×
              </button>
            )}
          </div>
          {/* Filter button with funnel SVG icon */}
          <button
            className={`${styles.filtersButtonNew} ${activeFilterCount > 0 ? styles.hasFilters : ''}`}
            onClick={() => { hapticLight(); setShowFilterSheet(true) }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
            </svg>
            Фильтры
            {activeFilterCount > 0 && <span className={styles.filterBadge}>{activeFilterCount}</span>}
          </button>
        </div>

      </div>

      {/* v9.0: UNIFIED Filter Bottom Sheet with categories */}
      {showFilterSheet && (
        <>
          <div className={styles.sheetOverlay} onClick={() => setShowFilterSheet(false)} />
          <div className={styles.filterSheet}>
            <div className={styles.sheetHandle} />
            <div className={styles.sheetHeader}>
              <h3 className={styles.sheetTitle}>Фильтры</h3>
              <button className={styles.sheetClose} onClick={() => setShowFilterSheet(false)}>×</button>
            </div>

            {/* Category - moved from separate sheet */}
            <div className={styles.filterGroup}>
              <label className={styles.filterLabel}>Категория</label>
              <div className={styles.categoryChips}>
                {ALL_CATEGORIES.map((cat) => (
                  <button
                    key={cat.id || 'all'}
                    className={`${styles.categoryChip} ${selectedCategory === cat.id ? styles.active : ''}`}
                    onClick={() => setSelectedCategory(cat.id)}
                  >
                    {cat.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Sort */}
            <div className={styles.filterGroup}>
              <label className={styles.filterLabel}>Сортировка</label>
              <div className={styles.filterOptions}>
                <button
                  className={`${styles.filterOption} ${sortBy === 'score' ? styles.active : ''}`}
                  onClick={() => setSortBy('score')}
                >
                  Score ↓
                </button>
                <button
                  className={`${styles.filterOption} ${sortBy === 'members' ? styles.active : ''}`}
                  onClick={() => setSortBy('members')}
                >
                  Подписчики
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

            {/* Trust Factor */}
            <div className={styles.filterGroup}>
              <label className={styles.filterLabel}>Trust Factor</label>
              <div className={styles.trustChips}>
                {[0, 0.7, 0.9].map((t) => (
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

            {/* Actions */}
            <div className={styles.sheetActions}>
              <button className={styles.filterReset} onClick={() => {
                setSelectedCategory(null)
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
                Показать {total} шт.
              </button>
            </div>
          </div>
        </>
      )}

      {/* Content - v11.0: with padding for Bottom Nav */}
      <main
        className={`${styles.content} ${styles.contentWithNav}`}
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
            {/* v11.1: Card List - структура как на референсе */}
            <div className={styles.channelList}>
              {channels.map((channel, index) => (
                <button
                  key={channel.username}
                  className={styles.channelCardNew}
                  onClick={() => handleChannelClick(channel)}
                  style={{ animationDelay: `${Math.min(index, 5) * 20}ms` }}
                >
                  {/* v11.5: Новая структура по референсу */}
                  <div className={styles.cardRow1}>
                    <Avatar
                      username={channel.username}
                      photoUrl={channel.photo_url}
                      size={54}
                    />
                    <div className={styles.cardInfo}>
                      {/* Name + Category в одной строке */}
                      <div className={styles.cardNameLine}>
                        <span className={styles.cardName}>
                          {channel.username.charAt(0).toUpperCase() + channel.username.slice(1).replace(/_/g, ' ')}
                        </span>
                        {channel.category && (
                          <span className={styles.categoryBadge}>
                            <svg className={styles.categoryIcon} viewBox="0 0 24 24" fill="currentColor">
                              <path d="M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm2 4v2h2V8H8zm4 0v2h2V8h-2zm4 0v2h2V8h-2zM8 12v2h2v-2H8zm4 0v2h2v-2h-2zm4 0v2h2v-2h-2z"/>
                            </svg>
                            {getCategoryName(channel.category)}
                          </span>
                        )}
                      </div>
                      {/* Meta line */}
                      <span className={styles.cardMeta}>
                        @{channel.username} • {formatNumber(channel.members)} подписчиков • ER {estimateER(channel.members, channel.score)}%
                      </span>
                    </div>
                    {/* Score Ring с галочкой внутри */}
                    <ScoreRing
                      score={channel.score}
                      verdict={channel.verdict}
                      showCheck={channel.trust_factor >= 0.9}
                    />
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

      {/* v11.0: Bottom Navigation Bar */}
      <nav className={styles.bottomNav}>
        {[
          { id: 'search' as const, icon: '🔍', label: 'Поиск' },
          { id: 'history' as const, icon: '📋', label: 'История' },
          { id: 'watchlist' as const, icon: '⭐', label: 'Избранное' },
          { id: 'profile' as const, icon: '👤', label: 'Профиль' },
        ].map(tab => (
          <button
            key={tab.id}
            className={`${styles.navItem} ${activeTab === tab.id ? styles.active : ''}`}
            onClick={() => { hapticLight(); setActiveTab(tab.id) }}
          >
            <span className={styles.navIcon}>{tab.icon}</span>
            <span className={styles.navLabel}>{tab.label}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}

export default App
