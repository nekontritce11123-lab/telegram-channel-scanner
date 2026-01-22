import { useState, useEffect, useCallback, useMemo, useRef, JSX } from 'react'
import { useTelegram } from './hooks/useTelegram'
import { useChannels, useStats, useScan, useScanRequest, useHistory, useWatchlist, Channel, ChannelDetail, ChannelFilters, BotInfo, StoredChannel, API_BASE } from './hooks/useApi'
import { useYandexMetrika } from './hooks/useYandexMetrika'
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

// v12.3: SVG иконки для категорий
const CATEGORY_ICONS: Record<string, JSX.Element> = {
  CRYPTO: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M14.8 9a2 2 0 0 0-1.8-1h-2a2 2 0 0 0 0 4h2a2 2 0 0 1 0 4h-2a2 2 0 0 1-1.8-1M12 6v2m0 8v2"/></svg>,
  FINANCE: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>,
  REAL_ESTATE: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>,
  BUSINESS: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>,
  TECH: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>,
  AI_ML: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/></svg>,
  EDUCATION: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c0 2 2 3 6 3s6-1 6-3v-5"/></svg>,
  BEAUTY: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.937A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.582a.5.5 0 0 1 0 .962L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/></svg>,
  HEALTH: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>,
  TRAVEL: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>,
  RETAIL: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18M16 10a4 4 0 0 1-8 0"/></svg>,
  ENTERTAINMENT: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>,
  NEWS: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8V6Z"/></svg>,
  LIFESTYLE: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>,
  GAMBLING: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M16 8h.01M8 8h.01M8 16h.01M16 16h.01M12 12h.01"/></svg>,
  ADULT: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M12 8v4M12 16h.01"/></svg>,
  OTHER: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2 2 7l10 5 10-5-10-5ZM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>,
}

// v51.1: RECOMMENDATION_ICONS removed - recommendations section no longer shown

// v12.3: Получить иконку категории
function getCategoryIcon(category: string): JSX.Element | null {
  return CATEGORY_ICONS[category] || null
}

// Get category name
function getCategoryName(category: string): string {
  return CATEGORY_NAMES[category] || category
}

// v20.0: Format category with percentage for multi-label
function formatCategoryWithPercent(
  category: string | null,
  categorySecondary: string | null,
  categoryPercent: number | null
): string {
  if (!category) return ''

  const primaryName = getCategoryName(category)

  // Если нет второй категории или 100% — просто показываем основную
  if (!categorySecondary || categoryPercent === 100 || categoryPercent === null) {
    return primaryName
  }

  const secondaryName = getCategoryName(categorySecondary)
  const secondaryPercent = 100 - categoryPercent

  return `${primaryName} ${categoryPercent}% + ${secondaryName} ${secondaryPercent}%`
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

// v12.0: Format channel name (capitalize, replace underscores)
function formatChannelName(username: string): string {
  return username.charAt(0).toUpperCase() + username.slice(1).replace(/_/g, ' ')
}

// v50.0: Format relative date for scan freshness
function formatRelativeDate(dateString: string | null | undefined): string {
  if (!dateString) return ''
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffDays === 0) return 'Сегодня'
  if (diffDays === 1) return 'Вчера'
  if (diffDays < 7) return `${diffDays} дн. назад`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} нед. назад`
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

// v12.0: Get color class for metric bar
function getMetricColorClass(score: number, max: number): string {
  const pct = (score / max) * 100
  if (pct >= 70) return 'excellent'
  if (pct >= 50) return 'good'
  if (pct >= 30) return 'warning'
  return 'poor'
}

// v11.5: ScoreRing компонент для карточек (SVG circle с прогрессом)
// v53.0: Добавлен small размер (36px) для Unified Card
// large: 90px, medium: 48px, small: 36px, default: 64px
// v34.0: Галочка для Telegram верифицированных каналов, SCAM бейдж для score=0
function ScoreRing({ score, verdict, verified, large, medium, small }: { score: number; verdict: string; verified?: boolean; large?: boolean; medium?: boolean; small?: boolean }) {
  // Размеры: large=90px, medium=48px, small=36px, default=64px
  const size = large ? 90 : medium ? 48 : small ? 36 : 64
  const radius = large ? 36 : medium ? 19 : small ? 14 : 26
  const center = size / 2
  const circumference = 2 * Math.PI * radius
  const progress = (score / 100) * circumference
  const offset = circumference - progress

  // v34.0: SCAM/Error badge для score=0 или verdict=SCAM
  const isScam = score === 0 || verdict === 'SCAM'

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
      <span className={styles.scoreRingValue}>{isScam ? '!' : score}</span>
      {/* v34.0: SCAM badge для score=0 */}
      {isScam && (
        <div className={styles.scamBadge}>
          <svg viewBox="0 0 24 24" fill="#fff">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
          </svg>
        </div>
      )}
      {/* v34.0: Verified badge для Telegram верифицированных каналов (не для SCAM) */}
      {verified && !isScam && (
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
  },
  // v20.0: Новые метрики
  'posting': {
    title: 'Частота постинга',
    description: 'Сколько постов публикуется в день.',
    interpretation: 'Оптимально 3-6 постов в день. Слишком много — реклама "тонет" в потоке контента.'
  },
  'links': {
    title: 'Качество связей',
    description: 'Репутация рекламируемых каналов.',
    interpretation: 'Реклама SCAM каналов или много приватных ссылок — признак участия в скам-сети.'
  },
  // v23.0: Info Metrics (Trust Penalties отображаемые как информационные метрики)
  'ad_load': {
    title: 'Рекламная нагрузка',
    description: 'Процент постов с рекламой от общего числа.',
    interpretation: 'До 20% — норма. 20-30% — много. Больше 30% — аудитория устаёт от рекламы.'
  },
  'activity': {
    title: 'Активность канала',
    description: 'Как часто публикуются посты на канале.',
    interpretation: '1-5 постов/день — активный канал. Меньше 1/неделю — канал еле живой. Больше 15/день — спам.'
  },
  'private_links': {
    title: 'Приватные ссылки',
    description: 'Процент рекламы с приватными invite-ссылками.',
    interpretation: 'Приватные ссылки нельзя проверить. До 30% — норма. Больше 60% — риск.'
  },
  // v38.0: LLM Analysis Metrics
  'toxicity': {
    title: 'Токсичность',
    description: 'Уровень hate speech, дискриминации и оскорблений.',
    interpretation: 'До 20% — норма (мат без targeting). 20-50% — риск. 50%+ — hate speech, бренды избегают.'
  },
  'violence': {
    title: 'Насилие',
    description: 'Призывы к насилию, графический контент.',
    interpretation: 'До 20% — упоминания конфликтов. 50%+ — призывы к насилию, исключение из рекламы.'
  },
  'political_quantity': {
    title: 'Политика',
    description: 'Процент постов с политическим контентом.',
    interpretation: 'До 30% — обычный канал. 30-70% — политический канал. 70%+ — ограниченный инвентарь.'
  },
  'political_risk': {
    title: 'Политический риск',
    description: 'Насколько опасен политический контент для брендов.',
    interpretation: '0-20 — нейтральные новости. 40-60 — односторонность. 80+ — пропаганда/экстремизм.'
  },
  'brand_safety': {
    title: 'Brand Safety',
    description: 'Общий показатель безопасности для рекламодателей.',
    interpretation: '80%+ — безопасно для любого бренда. 50-80% — требует проверки. <50% — высокий риск.'
  },
  'bot_percentage': {
    title: 'Боты',
    description: 'Процент ботов среди комментаторов.',
    interpretation: 'До 15% — норма. 15-30% — подозрительно. 30%+ — вероятна накрутка комментариев.'
  },
  // v41.0: authenticity REMOVED (дубликат bot_percentage)
  'misinformation': {
    title: 'Дезинформация',
    description: 'Уровень непроверенных/ложных утверждений.',
    interpretation: 'До 20% — норма. 40%+ — канал распространяет сомнительную информацию.'
  },
  'trust_score': {
    title: 'Доверие аудитории',
    description: 'Насколько аудитория доверяет контенту канала.',
    interpretation: '70%+ — аудитория активно поддерживает контент. 40-70% — смешанно. <40% — много скептических комментариев.'
  }
}

// Avatar component
// v22.0: Загружаем фото через API endpoint вместо хранения base64 в БД
// v50.1: Добавлен retry механизм и lazy loading для медленных загрузок
function Avatar({ username, size = 32 }: { username: string; size?: number }) {
  const [imgError, setImgError] = useState(false)
  const [retryCount, setRetryCount] = useState(0)
  const maxRetries = 2
  const firstLetter = username.charAt(0).toUpperCase()
  const bgColor = getAvatarColor(username)

  // URL для загрузки аватарки через API (с cache buster для retry)
  const photoUrl = `${API_BASE}/api/photo/${username.toLowerCase().replace('@', '')}${retryCount > 0 ? `?r=${retryCount}` : ''}`

  const handleError = useCallback(() => {
    if (retryCount < maxRetries) {
      // Retry after delay
      setTimeout(() => setRetryCount(c => c + 1), 1000 * (retryCount + 1))
    } else {
      setImgError(true)
    }
  }, [retryCount])

  if (!imgError) {
    return (
      <img
        src={photoUrl}
        alt={username}
        className={size >= 48 ? styles.detailAvatar : styles.avatar}
        style={{ width: size, height: size }}
        loading="lazy"
        onError={handleError}
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

// v12.0: MetricItem component with progress bar
// v22.2: Support for disabled metrics (reactions/comments off)
// v25.0: Support for Info Metrics (value without max, e.g. ad_load, activity)
// v39.0: Support for bot_info in comments metric (AI-detected bots)
function MetricItem({ item, onClick }: { item: { score: number; max: number; label: string; disabled?: boolean; value?: string; status?: 'good' | 'warning' | 'bad'; bot_info?: BotInfo }; onClick: () => void }) {
  // v22.2: If disabled, show "откл." and grey bar
  if (item.disabled) {
    return (
      <div className={`${styles.metricItem} ${styles.metricItemDisabled}`} onClick={onClick} role="button" tabIndex={0}>
        <div className={styles.metricItemHeader}>
          <span className={styles.metricItemLabel}>{item.label}</span>
          <span className={styles.metricItemValue}>{item.value || 'откл.'}</span>
        </div>
        <div className={styles.metricBar}>
          <div className={styles.metricBarDisabled} style={{ width: '100%' }} />
        </div>
      </div>
    )
  }

  // v24.0: Info Metric - показываем прогресс-бар как Score Metrics
  // bar_percent: good=100%, warning=60%, bad=20%
  if (item.value && item.max === 0) {
    const barPercent = (item as { bar_percent?: number }).bar_percent ?? (
      item.status === 'good' ? 100 : item.status === 'warning' ? 60 : 20
    )
    // Используем те же CSS классы что и для Score Metrics
    const colorClass = item.status === 'good' ? 'excellent'
      : item.status === 'warning' ? 'warning'
      : 'poor'

    return (
      <div className={styles.metricItem} onClick={onClick} role="button" tabIndex={0}>
        <div className={styles.metricItemHeader}>
          <span className={styles.metricItemLabel}>{item.label}</span>
          <span className={styles.metricItemValue}>{item.value}</span>
        </div>
        <div className={styles.metricBar}>
          <div
            className={`${styles.metricBarFill} ${styles[colorClass]}`}
            style={{ width: `${barPercent}%` }}
          />
        </div>
      </div>
    )
  }

  // Score Metric with max=0 (floating weights - метрика отключена)
  if (item.max === 0) {
    return (
      <div className={`${styles.metricItem} ${styles.metricItemDisabled}`} onClick={onClick} role="button" tabIndex={0}>
        <div className={styles.metricItemHeader}>
          <span className={styles.metricItemLabel}>{item.label}</span>
          <span className={styles.metricItemValue}>откл.</span>
        </div>
        <div className={styles.metricBar}>
          <div className={styles.metricBarDisabled} style={{ width: '100%' }} />
        </div>
      </div>
    )
  }

  const pct = (item.score / item.max) * 100
  const colorClass = getMetricColorClass(item.score, item.max)

  return (
    <div className={styles.metricItem} onClick={onClick} role="button" tabIndex={0}>
      <div className={styles.metricItemHeader}>
        <span className={styles.metricItemLabel}>{item.label}</span>
        <span className={styles.metricItemValue}>
          {item.score}/{item.max}
          {/* v39.0: Показываем bot_info если есть (AI-детекция ботов в комментах) */}
          {item.bot_info && (
            <span className={`${styles.botInfoBadge} ${styles[`bot_${item.bot_info.status}`]}`}>
              {item.bot_info.value}
            </span>
          )}
        </span>
      </div>
      <div className={styles.metricBar}>
        <div
          className={`${styles.metricBarFill} ${styles[colorClass]}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function App() {
  const { webApp, hapticLight, hapticMedium, hapticSuccess, hapticError } = useTelegram()
  const { channels, loading, error, hasMore, fetchChannels, reset } = useChannels()
  const { fetchStats } = useStats()  // v9.0: stats removed from UI
  const { result: scanResult, loading: scanning, error: scanError, scanChannel, reset: resetScan } = useScan()
  const { submitRequest, loading: submitting } = useScanRequest()  // v58.0: Scan request queue

  // v55.0: History & Watchlist hooks (history removed from UI, kept for future)
  const { addToHistory } = useHistory()
  const { watchlist, isInWatchlist, addToWatchlist, removeFromWatchlist } = useWatchlist()

  // v62.0: Яндекс.Метрика analytics
  const { reachGoal, hit } = useYandexMetrika()

  // State
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<ChannelFilters['sort_by']>('score')  // v59.6: По умолчанию по Score
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
  const [showWatchlistSheet, setShowWatchlistSheet] = useState(false)  // v55.0: Watchlist sheet

  // v58.0: Scan on Demand UI state
  const [toast, setToast] = useState<{type: 'success' | 'error', text: string} | null>(null)

  // v59.7: Filter preview count
  const [filterPreviewCount, setFilterPreviewCount] = useState<number | null>(null)

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
      fetchChannels({ page: 1, page_size: 30, sort_by: 'score', sort_order: 'desc' })  // v59.6: По умолчанию по Score
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
    // v62.0: Analytics
    reachGoal('filter_applied', { category: selectedCategory, minScore, sortBy })
  }, [buildFilters, reset, fetchChannels, reachGoal, selectedCategory, minScore, sortBy])

  // v59.7: Fetch filter preview count when filter sheet is open
  useEffect(() => {
    if (!showFilterSheet) {
      setFilterPreviewCount(null)
      return
    }

    const fetchCount = async () => {
      try {
        const params = new URLSearchParams()
        if (selectedCategory) params.set('category', selectedCategory)
        if (minScore > 0) params.set('min_score', String(minScore))
        if (minTrust > 0) params.set('min_trust', String(minTrust))
        if (minMembers > 0) params.set('min_members', String(minMembers))
        if (maxMembers > 0) params.set('max_members', String(maxMembers))
        if (verdictFilter) params.set('verdict', verdictFilter)

        const response = await fetch(`${API_BASE}/api/channels/count?${params}`)
        if (response.ok) {
          const data = await response.json()
          setFilterPreviewCount(data.count)
        }
      } catch {
        setFilterPreviewCount(null)
      }
    }

    // Debounce: fetch after 300ms
    const timer = setTimeout(fetchCount, 300)
    return () => clearTimeout(timer)
  }, [showFilterSheet, selectedCategory, minScore, minTrust, minMembers, maxMembers, verdictFilter])

  // v9.0: Category selection now happens in filter sheet, applied on "Показать"

  // v58.0: Toast helper
  const showToast = useCallback((type: 'success' | 'error', text: string) => {
    setToast({ type, text })
    setTimeout(() => setToast(null), 3000)
  }, [])

  // Handle search
  // v58.0: Queue-based scan - first check DB, then submit to queue if not found
  // v59.5: checkFullyProcessed=true to only show fully scanned channels
  const handleSearch = useCallback(async () => {
    const query = searchQuery.trim().replace('@', '')
    if (!query) return

    hapticMedium()
    reachGoal('search_submitted', { query })  // v62.0

    // First try to get from DB (only if fully processed)
    const result = await scanChannel(query, true)

    if (result) {
      // Found in DB and fully processed - show channel detail
      reachGoal('search_found', { query, username: result.username, score: result.score })  // v62.0
      return
    }

    // Not found or not fully processed - submit to queue
    const queueResult = await submitRequest(query)
    if (queueResult?.success) {
      showToast('success', `@${query} добавлен в очередь`)
      reachGoal('search_queued', { query })  // v62.0
    } else {
      showToast('error', queueResult?.message || 'Ошибка добавления')
      reachGoal('search_error', { query, error: queueResult?.message })  // v62.0
    }
  }, [searchQuery, hapticMedium, scanChannel, submitRequest, showToast, reachGoal])

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
  // v49.0: Updated to support StoredChannel from history/watchlist + auto-add to history
  const handleChannelClick = useCallback((channel: Channel | StoredChannel) => {
    hapticLight()
    addToHistory(channel)  // v49.0: Auto-add to history on view
    scanChannel(channel.username)
    // v62.0: Analytics
    reachGoal('channel_viewed', { username: channel.username, score: channel.score, source: 'list' })
    hit(`/channel/${channel.username}`, { title: `@${channel.username}` })
  }, [hapticLight, scanChannel, addToHistory, reachGoal, hit])

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
    setSortBy('scanned_at')
    setSortOrder('desc')
    setPage(1)
    reset()
    fetchChannels({ page: 1, page_size: 30, sort_by: 'scanned_at', sort_order: 'desc' })
  }, [hapticLight, reset, fetchChannels])

  // Show scan error
  useEffect(() => {
    if (scanError) {
      hapticError()
    }
  }, [scanError, hapticError])

  // Has active filters
  const hasActiveFilters = selectedCategory || minScore > 0 || minTrust > 0 ||
    minMembers > 0 || maxMembers > 0 || verdictFilter || sortBy !== 'scanned_at'

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

  // Channel Detail Page - v12.0 NEW LAYOUT
  if (selectedChannel) {
    return (
      <div className={styles.detailPage}>
        {/* Header - v59.3: Icon buttons */}
        <header className={styles.detailHeader}>
          <button className={styles.backButton} onClick={closeChannelDetail} title="Назад">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 19l-7-7 7-7"/>
            </svg>
          </button>
          <div className={styles.headerActions}>
            {/* v49.0: Watchlist toggle button */}
            <button
              className={`${styles.watchlistBtn} ${isInWatchlist(selectedChannel.username) ? styles.active : ''}`}
              onClick={() => {
                hapticMedium()
                if (isInWatchlist(selectedChannel.username)) {
                  removeFromWatchlist(selectedChannel.username)
                } else {
                  addToWatchlist(selectedChannel)
                }
              }}
              title="В избранное"
            >
              <svg viewBox="0 0 24 24" fill={isInWatchlist(selectedChannel.username) ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2">
                <path d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0 1 11.186 0Z"/>
              </svg>
            </button>
            <a
              href={`https://t.me/${selectedChannel.username}`}
              target="_blank"
              rel="noopener noreferrer"
              className={styles.openLink}
              title="Открыть в Telegram"
            >
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/>
              </svg>
            </a>
          </div>
        </header>

        {/* Content */}
        <div className={styles.detailContent}>
          {/* v53.0: Unified Card - Avatar + Name + Flags + Price */}
          <div className={styles.unifiedCard}>
            <div className={styles.unifiedTop}>
              <Avatar username={selectedChannel.username} size={48} />
              <div className={styles.unifiedInfo}>
                <div className={styles.unifiedNameRow}>
                  <span className={styles.unifiedName}>{selectedChannel.title || formatChannelName(selectedChannel.username)}</span>
                  {selectedChannel.category && (
                    <span className={styles.categoryBadge}>
                      <span className={styles.categoryIcon}>{getCategoryIcon(selectedChannel.category)}</span>
                      {getCategoryName(selectedChannel.category)}
                    </span>
                  )}
                </div>
                <div className={styles.unifiedMeta}>
                  @{selectedChannel.username} · {formatNumber(selectedChannel.members)} подп.
                </div>
                <div className={styles.unifiedFlags}>
                  <span className={selectedChannel.is_verified ? styles.flagActive : styles.flagInactive} title="Верификация">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
                  </span>
                  <span className={breakdown?.comments_enabled !== false ? styles.flagActive : styles.flagInactive} title="Комментарии">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M21 6h-2v9H6v2c0 .55.45 1 1 1h11l4 4V7c0-.55-.45-1-1-1zm-4 6V3c0-.55-.45-1-1-1H3c-.55 0-1 .45-1 1v14l4-4h10c.55 0 1-.45 1-1z"/></svg>
                  </span>
                  <span className={breakdown?.reactions_enabled !== false ? styles.flagActive : styles.flagInactive} title="Реакции">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
                  </span>
                </div>
              </div>
              {/* v53.1: Score + Price column */}
              <div className={styles.unifiedScore}>
                <ScoreRing
                  score={selectedChannel.score}
                  verdict={selectedChannel.verdict}
                  verified={selectedChannel.is_verified}
                  small
                />
                {selectedChannel.cpm_min && selectedChannel.cpm_max && (
                  <div className={styles.scorePrice}>
                    {formatPrice(selectedChannel.cpm_min, selectedChannel.cpm_max)}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* v51.0: SCAM Banner - показываем предупреждение, но ВСЕ данные доступны */}
          {(selectedChannel.score === 0 || selectedChannel.verdict === 'SCAM') && (
            <div className={styles.scamBanner}>
              <div className={styles.scamTitle}>Канал определён как SCAM</div>
              <div className={styles.scamDesc}>
                Обнаружены критические признаки накрутки. Ниже показаны все собранные данные для анализа.
              </div>
            </div>
          )}

          {/* v51.0: Metrics Grid - всегда показываем если есть данные */}
          {/* v59.0: Порядок изменён: Репутация → Вовлечённость → Качество */}
          {breakdown ? (
            <div className={styles.metricsGrid}>
              {/* v59.0: Reputation Block - ПЕРВЫЙ */}
              <div className={styles.metricsBlock}>
                <div className={styles.metricsBlockHeader}>
                  <span className={styles.metricsBlockTitle}>Репутация</span>
                  <span className={styles.metricsBlockScore}>{breakdown.reputation.total}/{breakdown.reputation.max}</span>
                </div>
                {breakdown.reputation.items && Object.entries(breakdown.reputation.items).map(([key, item]) => (
                  <MetricItem
                    key={key}
                    item={item}
                    onClick={() => setSelectedMetric(key)}
                  />
                ))}
                {/* v25.0: Info Metrics (private_links) */}
                {breakdown.reputation.info_metrics && Object.entries(breakdown.reputation.info_metrics).map(([key, item]) => (
                  <MetricItem
                    key={key}
                    item={item as { score: number; max: number; label: string; disabled?: boolean; value?: string; status?: 'good' | 'warning' | 'bad' }}
                    onClick={() => setSelectedMetric(key)}
                  />
                ))}
              </div>

              {/* Engagement Block */}
              {/* v39.0: comments теперь включает bot_info с LLM данными (если есть) */}
              <div className={styles.metricsBlock}>
                <div className={styles.metricsBlockHeader}>
                  <span className={styles.metricsBlockTitle}>Вовлечённость</span>
                  <span className={styles.metricsBlockScore}>{breakdown.engagement.total}/{breakdown.engagement.max}</span>
                </div>
                {breakdown.engagement.items && Object.entries(breakdown.engagement.items).map(([key, item]) => (
                  <MetricItem
                    key={key}
                    item={item as { score: number; max: number; label: string; disabled?: boolean; value?: string; status?: 'good' | 'warning' | 'bad'; bot_info?: BotInfo }}
                    onClick={() => setSelectedMetric(key)}
                  />
                ))}
              </div>

              {/* v59.0: Quality Block - ПОСЛЕДНИЙ */}
              <div className={styles.metricsBlock}>
                <div className={styles.metricsBlockHeader}>
                  <span className={styles.metricsBlockTitle}>Качество</span>
                  <span className={styles.metricsBlockScore}>{breakdown.quality.total}/{breakdown.quality.max}</span>
                </div>
                {breakdown.quality.items && Object.entries(breakdown.quality.items).map(([key, item]) => (
                  <MetricItem
                    key={key}
                    item={item}
                    onClick={() => setSelectedMetric(key)}
                  />
                ))}
                {/* v25.0: Info Metrics (ad_load, activity) */}
                {/* v39.0: ad_load теперь интегрирует LLM ad_percentage (если есть) — показывает "(AI)" в label */}
                {breakdown.quality.info_metrics && Object.entries(breakdown.quality.info_metrics).map(([key, item]) => (
                  <MetricItem
                    key={key}
                    item={item as { score: number; max: number; label: string; disabled?: boolean; value?: string; status?: 'good' | 'warning' | 'bad' }}
                    onClick={() => setSelectedMetric(key)}
                  />
                ))}
              </div>
            </div>
          ) : (
            <div className={styles.noPrice}>Данные загружаются...</div>
          )}

          {/* v52.1: Trust Penalties section with icons */}
          {selectedChannel.trust_penalties && selectedChannel.trust_penalties.length > 0 && (
            <div className={styles.trustPenaltiesSection}>
              <div className={styles.trustPenaltiesHeader}>
                <div className={styles.trustPenaltiesTitleRow}>
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="#FF9500">
                    <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
                  </svg>
                  <span className={styles.trustPenaltiesTitle}>Штрафы доверия</span>
                </div>
                {selectedChannel.trust_factor && selectedChannel.trust_factor < 1 && (
                  <span className={styles.trustPenaltiesTotal}>×{selectedChannel.trust_factor.toFixed(2)}</span>
                )}
              </div>
              <div className={styles.trustPenaltiesList}>
                {selectedChannel.trust_penalties.map((penalty, i) => (
                  <div key={i} className={styles.trustPenaltyItem}>
                    <div className={styles.penaltyIcon}>
                      <svg viewBox="0 0 24 24" width="20" height="20" fill="#FF3B30">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
                      </svg>
                    </div>
                    <div className={styles.penaltyInfo}>
                      <span className={styles.penaltyName}>{penalty.name}</span>
                      <span className={styles.penaltyDesc}>{penalty.description}</span>
                    </div>
                    <span className={styles.penaltyMult}>×{penalty.multiplier.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* v12.0: Footer with v20.0 category percentages */}
          <div className={styles.detailFooter}>
            <span>{formatCategoryWithPercent(selectedChannel.category, selectedChannel.category_secondary, selectedChannel.category_percent)}</span>
            <span>{selectedChannel.scanned_at ? new Date(selectedChannel.scanned_at).toLocaleDateString('ru-RU') : ''}</span>
          </div>
        </div>

        {/* Metric Explanation Modal */}
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





  // v55.0: Main List View - No Bottom Nav
  return (
    <div className={styles.app}>
      {/* v55.0: Sticky Header - Search + Filters + Watchlist */}
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
            {(scanning || submitting) && <span className={styles.searchSpinner}>{submitting ? 'Очередь...' : '...'}</span>}
            {searchQuery && !scanning && !submitting && (
              <button
                className={styles.clearButton}
                onClick={() => setSearchQuery('')}
              >
                ×
              </button>
            )}
          </div>
          {/* Filter button */}
          <button
            className={`${styles.filtersButtonNew} ${activeFilterCount > 0 ? styles.hasFilters : ''}`}
            onClick={() => { hapticLight(); setShowFilterSheet(true) }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
            </svg>
            {activeFilterCount > 0 && <span className={styles.filterBadge}>{activeFilterCount}</span>}
          </button>
          {/* v55.0: Watchlist button */}
          <button
            className={styles.watchlistBtn}
            onClick={() => { hapticLight(); setShowWatchlistSheet(true) }}
          >
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0 1 11.186 0Z"/>
            </svg>
            {watchlist.length > 0 && (
              <span className={styles.watchlistBadge}>{watchlist.length}</span>
            )}
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
                setSortBy('score')  // v59.6: По умолчанию по Score
                setSortOrder('desc')
              }}>
                Сбросить
              </button>
              <button className={styles.filterApply} onClick={applyFilters}>
                Показать{filterPreviewCount !== null ? ` ${filterPreviewCount} шт.` : ''}
              </button>
            </div>
          </div>
        </>
      )}

      {/* v55.0: Content - full height */}
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
                      size={54}
                    />
                    <div className={styles.cardInfo}>
                      {/* Name + Category в одной строке */}
                      <div className={styles.cardNameLine}>
                        <span className={styles.cardName}>
                          {channel.title || (channel.username.charAt(0).toUpperCase() + channel.username.slice(1).replace(/_/g, ' '))}
                        </span>
                        {channel.category && (
                          <span className={styles.categoryBadge}>
                            <span className={styles.categoryIcon}>
                              {getCategoryIcon(channel.category)}
                            </span>
                            {getCategoryName(channel.category)}
                          </span>
                        )}
                      </div>
                      {/* Meta line */}
                      <span className={styles.cardMeta}>
                        @{channel.username} • {formatNumber(channel.members)}
                        {channel.scanned_at && ` • ${formatRelativeDate(channel.scanned_at)}`}
                      </span>
                    </div>
                    {/* v59.3: Score Ring small - синхронизирован с детальной страницей */}
                    <ScoreRing
                      score={channel.score}
                      verdict={channel.verdict}
                      verified={channel.is_verified}
                      small
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

      {/* v55.0: Watchlist Sheet */}
      {showWatchlistSheet && (
        <div className={styles.sheetOverlay} onClick={() => setShowWatchlistSheet(false)}>
          <div className={styles.watchlistSheet} onClick={e => e.stopPropagation()}>
            <div className={styles.sheetHandle} />
            <div className={styles.watchlistSheetHeader}>
              <h2 className={styles.watchlistSheetTitle}>Избранное ({watchlist.length})</h2>
              <button
                className={styles.sheetCloseBtn}
                onClick={() => setShowWatchlistSheet(false)}
              >
                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M6 18L18 6M6 6l12 12"/>
                </svg>
              </button>
            </div>
            <div className={styles.watchlistSheetContent}>
              {watchlist.length === 0 ? (
                <div className={styles.emptyState}>
                  <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="var(--hint-color)" strokeWidth="1">
                    <path d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0 1 11.186 0Z"/>
                  </svg>
                  <p className={styles.emptyTitle}>Нет сохранённых каналов</p>
                  <p className={styles.emptyText}>Нажми ★ на канале чтобы добавить</p>
                </div>
              ) : (
                watchlist.map(channel => (
                  <div
                    key={channel.username}
                    className={styles.watchlistSheetItem}
                    onClick={() => {
                      hapticLight()
                      setShowWatchlistSheet(false)
                      handleChannelClick(channel)
                    }}
                  >
                    <Avatar username={channel.username} size={44} />
                    <div className={styles.watchlistSheetInfo}>
                      <span className={styles.watchlistSheetName}>{formatChannelName(channel.username)}</span>
                      <span className={styles.watchlistSheetMeta}>
                        @{channel.username} • {formatNumber(channel.members)} подп.
                      </span>
                    </div>
                    <span
                      className={styles.watchlistSheetScore}
                      style={{
                        backgroundColor: `${getVerdictColor(channel.verdict)}20`,
                        color: getVerdictColor(channel.verdict)
                      }}
                    >
                      {channel.score}
                    </span>
                    <button
                      className={styles.watchlistSheetRemove}
                      onClick={(e) => {
                        e.stopPropagation()
                        hapticMedium()
                        removeFromWatchlist(channel.username)
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M6 18L18 6M6 6l12 12"/>
                      </svg>
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* v58.0: Toast Notifications */}
      {toast && (
        <div className={`${styles.toast} ${styles[`toast_${toast.type}`]}`}>
          {toast.type === 'success' ? '✓' : '✕'} {toast.text}
        </div>
      )}
    </div>
  )
}

export default App
