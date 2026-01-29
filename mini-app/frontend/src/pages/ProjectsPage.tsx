// v72.6: Projects Page - карточки как на главной
import { useState, useEffect, useCallback, useMemo, JSX } from 'react'
import { useProjects, usePurchases, Project, Channel, Purchase, PurchaseStatus, API_BASE } from '../hooks/useApi'
import { useTelegram } from '../hooks/useTelegram'
import styles from '../App.module.css'

// Category icons (same as App.tsx)
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

const CATEGORY_NAMES: Record<string, string> = {
  CRYPTO: 'Крипто', TECH: 'Tech', AI_ML: 'AI', FINANCE: 'Финансы', BUSINESS: 'Бизнес',
  REAL_ESTATE: 'Недвиж.', EDUCATION: 'Образ.', NEWS: 'Новости', ENTERTAINMENT: 'Развлеч.',
  LIFESTYLE: 'Лайф', BEAUTY: 'Красота', HEALTH: 'Здоровье', TRAVEL: 'Путеш.',
  RETAIL: 'Ритейл', GAMBLING: 'Азарт', ADULT: '18+', OTHER: 'Др.'
}

function getCategoryIcon(category: string): JSX.Element | null {
  return CATEGORY_ICONS[category] || null
}

function getCategoryName(category: string): string {
  return CATEGORY_NAMES[category] || category
}

// Avatar colors for placeholder
function getAvatarColor(username: string): string {
  const colors = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
    '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9'
  ]
  return colors[username.charCodeAt(0) % colors.length]
}

// Avatar component
function Avatar({ username, size = 32 }: { username: string; size?: number }) {
  const [imgError, setImgError] = useState(false)
  const [retryCount, setRetryCount] = useState(0)
  const maxRetries = 2
  // v73.3: Protect against undefined username
  const safeUsername = username || 'U'
  const firstLetter = safeUsername.charAt(0).toUpperCase()
  const bgColor = getAvatarColor(safeUsername)

  const photoUrl = `${API_BASE}/api/photo/${safeUsername.toLowerCase().replace('@', '')}${retryCount > 0 ? `?r=${retryCount}` : ''}`

  const handleError = useCallback(() => {
    if (retryCount < maxRetries) {
      setTimeout(() => setRetryCount(c => c + 1), 1000 * (retryCount + 1))
    } else {
      setImgError(true)
    }
  }, [retryCount])

  if (!imgError) {
    return (
      <img
        src={photoUrl}
        alt={safeUsername}
        className={size >= 48 ? styles.detailAvatar : styles.avatar}
        style={{ width: size, height: size, borderRadius: '50%' }}
        loading="lazy"
        onError={handleError}
      />
    )
  }

  return (
    <div
      className={size >= 48 ? styles.detailAvatarPlaceholder : styles.avatarPlaceholder}
      style={{ width: size, height: size, backgroundColor: bgColor, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 600 }}
    >
      {firstLetter}
    </div>
  )
}

// SVG Icons
const RocketIcon = ({ size = 24 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09Z"/>
    <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2Z"/>
    <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/>
    <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>
  </svg>
)

const TargetIcon = ({ size = 16 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="10"/>
    <circle cx="12" cy="12" r="6"/>
    <circle cx="12" cy="12" r="2"/>
  </svg>
)

const ChartIcon = ({ size = 16 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M3 3v18h18"/>
    <path d="M18 17V9"/>
    <path d="M13 17V5"/>
    <path d="M8 17v-3"/>
  </svg>
)

// v73.5: Status SVG icons (replacing emoji)
const StatusIconPlan = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
    <polyline points="14 2 14 8 20 8"/>
    <line x1="16" y1="13" x2="8" y2="13"/>
    <line x1="16" y1="17" x2="8" y2="17"/>
  </svg>
)
const StatusIconChat = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
  </svg>
)
const StatusIconHandshake = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M20.42 4.58a5.4 5.4 0 0 0-7.65 0l-.77.78-.77-.78a5.4 5.4 0 0 0-7.65 0C1.46 6.7 1.33 10.28 4 13l8 8 8-8c2.67-2.72 2.54-6.3.42-8.42z"/>
  </svg>
)
const StatusIconCard = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="1" y="4" width="22" height="16" rx="2" ry="2"/>
    <line x1="1" y1="10" x2="23" y2="10"/>
  </svg>
)
const StatusIconCheck = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5">
    <polyline points="20 6 9 17 4 12"/>
  </svg>
)
const StatusIconChart = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M18 20V10"/>
    <path d="M12 20V4"/>
    <path d="M6 20v-6"/>
  </svg>
)
const StatusIconCancel = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5">
    <line x1="18" y1="6" x2="6" y2="18"/>
    <line x1="6" y1="6" x2="18" y2="18"/>
  </svg>
)

// v73.5: Status colors, labels, icons (SVG), backgrounds
const STATUS_CONFIG: Record<PurchaseStatus, { label: string; icon: JSX.Element; color: string; bg: string }> = {
  PLANNED: { label: 'План', icon: <StatusIconPlan />, color: '#8e8e93', bg: 'rgba(142, 142, 147, 0.15)' },
  CONTACTED: { label: 'Связ.', icon: <StatusIconChat />, color: '#3390ec', bg: 'rgba(51, 144, 236, 0.15)' },
  NEGOTIATING: { label: 'Перег.', icon: <StatusIconHandshake />, color: '#ffcc00', bg: 'rgba(255, 204, 0, 0.15)' },
  PAID: { label: 'Оплач.', icon: <StatusIconCard />, color: '#ff9500', bg: 'rgba(255, 149, 0, 0.15)' },
  POSTED: { label: 'Вышло', icon: <StatusIconCheck />, color: '#34c759', bg: 'rgba(52, 199, 89, 0.15)' },
  COMPLETED: { label: 'Итог', icon: <StatusIconChart />, color: '#af52de', bg: 'rgba(175, 82, 222, 0.15)' },
  CANCELLED: { label: 'Отмена', icon: <StatusIconCancel />, color: '#ff3b30', bg: 'rgba(255, 59, 48, 0.15)' },
}

// ScoreRing component (from App.tsx pattern)
function ScoreRing({ score, small }: { score: number; small?: boolean }) {
  const size = small ? 36 : 48
  const radius = small ? 14 : 19
  const strokeWidth = small ? 3 : 4
  const circumference = 2 * Math.PI * radius
  const progress = (score / 100) * circumference

  // Get color based on score
  const getColor = (s: number) => {
    if (s >= 75) return '#34c759'
    if (s >= 55) return '#5ac8fa'
    if (s >= 40) return '#ffcc00'
    if (s >= 25) return '#ff9500'
    return '#ff3b30'
  }
  const color = getColor(score)

  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle
          cx={size/2} cy={size/2} r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.1)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size/2} cy={size/2} r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={circumference - progress}
          strokeLinecap="round"
        />
      </svg>
      <span style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: small ? 11 : 14,
        fontWeight: 700,
        color: color
      }}>
        {score}
      </span>
    </div>
  )
}

// Format number for display
function formatNumber(num: number): string {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
  return num.toString()
}

// v72.8: Currency type
type Currency = 'RUB' | 'USD'

// v75.0: Filter icon
const FilterIcon = ({ size = 16 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="4" y1="21" x2="4" y2="14"/>
    <line x1="4" y1="10" x2="4" y2="3"/>
    <line x1="12" y1="21" x2="12" y2="12"/>
    <line x1="12" y1="8" x2="12" y2="3"/>
    <line x1="20" y1="21" x2="20" y2="16"/>
    <line x1="20" y1="12" x2="20" y2="3"/>
    <line x1="1" y1="14" x2="7" y2="14"/>
    <line x1="9" y1="8" x2="15" y2="8"/>
    <line x1="17" y1="16" x2="23" y2="16"/>
  </svg>
)

// v75.0: Recommendation filters interface
interface RecommendationFilters {
  maxPrice: number | null
  minTrust: number | null
  minMembers: number | null
  maxMembers: number | null
}

const DEFAULT_FILTERS: RecommendationFilters = {
  maxPrice: null,
  minTrust: null,
  minMembers: null,
  maxMembers: null
}

// v75.0: Size presets for quick selection
const SIZE_PRESETS = [
  { label: 'Все', min: null, max: null },
  { label: '<5K', min: null, max: 5000 },
  { label: '5-20K', min: 5000, max: 20000 },
  { label: '20-100K', min: 20000, max: 100000 },
  { label: '>100K', min: 100000, max: null },
]

// v75.0: Trust presets
const TRUST_PRESETS = [
  { label: 'Любой', value: null },
  { label: '≥50%', value: 0.5 },
  { label: '≥70%', value: 0.7 },
  { label: '≥90%', value: 0.9 },
]

// v75.0: Budget presets (in rubles)
const BUDGET_PRESETS = [
  { label: 'Любой', value: null },
  { label: '≤10K', value: 10000 },
  { label: '≤50K', value: 50000 },
  { label: '≤100K', value: 100000 },
]

// v72.9: Custom DatePicker (calendar style like "Подписки")
interface DatePickerProps {
  value: string // YYYY-MM-DD format
  onChange: (date: string) => void
  minDate?: Date
  maxDate?: Date
}

const MONTHS_RU = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
]

const WEEKDAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

function DatePicker({ value, onChange, minDate, maxDate }: DatePickerProps) {
  const initialDate = value ? new Date(value) : new Date()
  const [viewYear, setViewYear] = useState(initialDate.getFullYear())
  const [viewMonth, setViewMonth] = useState(initialDate.getMonth())

  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const selectedDate = value ? new Date(value) : null

  // Get days in month
  const getDaysInMonth = (year: number, month: number) => {
    return new Date(year, month + 1, 0).getDate()
  }

  // Get first day of month (0 = Sunday, convert to Monday-first)
  const getFirstDayOfMonth = (year: number, month: number) => {
    const day = new Date(year, month, 1).getDay()
    return day === 0 ? 6 : day - 1
  }

  const daysInMonth = getDaysInMonth(viewYear, viewMonth)
  const firstDayOffset = getFirstDayOfMonth(viewYear, viewMonth)

  const handlePrevMonth = () => {
    if (viewMonth === 0) {
      setViewMonth(11)
      setViewYear(viewYear - 1)
    } else {
      setViewMonth(viewMonth - 1)
    }
  }

  const handleNextMonth = () => {
    if (viewMonth === 11) {
      setViewMonth(0)
      setViewYear(viewYear + 1)
    } else {
      setViewMonth(viewMonth + 1)
    }
  }

  const handleDayClick = (day: number) => {
    const date = new Date(viewYear, viewMonth, day)
    if (minDate && date < minDate) return
    if (maxDate && date > maxDate) return

    // Format as YYYY-MM-DD
    const yyyy = viewYear
    const mm = String(viewMonth + 1).padStart(2, '0')
    const dd = String(day).padStart(2, '0')
    onChange(`${yyyy}-${mm}-${dd}`)
  }

  const isToday = (day: number) => {
    return (
      viewYear === today.getFullYear() &&
      viewMonth === today.getMonth() &&
      day === today.getDate()
    )
  }

  const isSelected = (day: number) => {
    if (!selectedDate) return false
    return (
      viewYear === selectedDate.getFullYear() &&
      viewMonth === selectedDate.getMonth() &&
      day === selectedDate.getDate()
    )
  }

  const isDisabled = (day: number) => {
    const date = new Date(viewYear, viewMonth, day)
    if (minDate && date < minDate) return true
    if (maxDate && date > maxDate) return true
    return false
  }

  // Generate calendar days array with empty slots for offset
  const days: (number | null)[] = []
  for (let i = 0; i < firstDayOffset; i++) {
    days.push(null)
  }
  for (let d = 1; d <= daysInMonth; d++) {
    days.push(d)
  }

  return (
    <div className={styles.calendar}>
      <div className={styles.calendarHeader}>
        <button type="button" className={styles.calendarNavBtn} onClick={handlePrevMonth}>‹</button>
        <span className={styles.calendarTitle}>
          {MONTHS_RU[viewMonth]} {viewYear}
        </span>
        <button type="button" className={styles.calendarNavBtn} onClick={handleNextMonth}>›</button>
      </div>
      <div className={styles.calendarWeekdays}>
        {WEEKDAYS_SHORT.map(w => (
          <span key={w} className={styles.calendarWeekday}>{w}</span>
        ))}
      </div>
      <div className={styles.calendarDays}>
        {days.map((day, idx) => (
          <div key={idx} className={styles.calendarDayCell}>
            {day !== null && (
              <button
                type="button"
                className={`${styles.calendarDay} ${isSelected(day) ? styles.selected : ''} ${isToday(day) ? styles.today : ''} ${isDisabled(day) ? styles.disabled : ''}`}
                onClick={() => handleDayClick(day)}
                disabled={isDisabled(day)}
              >
                {day}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}


// v72.8: Format price with currency symbol
function formatPrice(amount: number, currency: Currency): string {
  if (currency === 'USD') {
    return `$${amount.toLocaleString('en-US')}`
  }
  return `${amount.toLocaleString('ru-RU')} ₽`
}

// v72.8: PurchaseEditorSheet - Bottom Sheet for editing purchase
interface PurchaseEditorSheetProps {
  purchase: Purchase
  onSave: (data: {
    status?: PurchaseStatus
    price?: number
    currency?: Currency
    subscribers_gained?: number
    scheduled_at?: string
    notes?: string
  }) => void
  onDelete: () => void
  onClose: () => void
}

// v72.8: All status keys for chips
const STATUS_KEYS: PurchaseStatus[] = ['PLANNED', 'CONTACTED', 'NEGOTIATING', 'PAID', 'POSTED', 'COMPLETED', 'CANCELLED']

function PurchaseEditorSheet({ purchase, onSave, onDelete, onClose }: PurchaseEditorSheetProps) {
  const [status, setStatus] = useState<PurchaseStatus>(purchase.status || 'PLANNED')
  const [showStatusPicker, setShowStatusPicker] = useState(false)
  const [price, setPrice] = useState(purchase.price?.toString() || '')
  const [currency, setCurrency] = useState<Currency>((purchase as { currency?: Currency }).currency || 'RUB')
  const [subs, setSubs] = useState(purchase.subscribers_gained?.toString() || '')
  const [date, setDate] = useState(purchase.scheduled_at?.split('T')[0] || '')
  const [notes, setNotes] = useState(purchase.notes || '')

  // v74.0: Toggle currency
  const toggleCurrency = () => {
    setCurrency(currency === 'RUB' ? 'USD' : 'RUB')
  }

  // Calculate CPF
  const cpf = price && subs && Number(subs) > 0
    ? (Number(price) / Number(subs)).toFixed(2)
    : null

  // v72.8: CPF with currency
  const cpfFormatted = cpf ? formatPrice(Number(cpf), currency) : null

  const handleSave = () => {
    onSave({
      status,
      price: price ? Number(price) : undefined,
      currency,
      subscribers_gained: subs ? Number(subs) : undefined,
      scheduled_at: date || undefined,
      notes: notes || undefined
    })
    onClose()
  }

  return (
    <div className={styles.sheetOverlay} onClick={onClose}>
      <div className={styles.purchaseEditorSheet} onClick={e => e.stopPropagation()}>
        <div className={styles.sheetHandle} />

        {/* Header */}
        <div className={styles.purchaseEditorHeader}>
          <Avatar username={purchase.channel_username} size={48} />
          <div className={styles.purchaseEditorInfo}>
            <span className={styles.purchaseEditorName}>@{purchase.channel_username}</span>
            {purchase.channel_members && (
              <span className={styles.purchaseEditorMeta}>
                {formatNumber(purchase.channel_members)} подп.
              </span>
            )}
          </div>
          {purchase.channel_score && (
            <ScoreRing score={purchase.channel_score} />
          )}
        </div>

        {/* Form */}
        <div className={styles.purchaseEditorForm}>
          {/* v74.0: Three fields: Price | Subscribers | Status (at right) */}
          <div className={styles.rowThree}>
            {/* Price with currency */}
            <div className={styles.fieldWrapper}>
              <span className={styles.fieldLabel}>Цена рекламы</span>
              <div className={styles.inputWrapper}>
                <input
                  type="number"
                  value={price}
                  onChange={e => setPrice(e.target.value)}
                  placeholder="0"
                />
                <span className={styles.currencySuffix} onClick={toggleCurrency}>
                  {currency === 'RUB' ? '₽' : '$'}
                </span>
              </div>
            </div>

            {/* Subscribers gained */}
            <div className={styles.fieldWrapper}>
              <span className={styles.fieldLabel}>Приход подп.</span>
              <div className={styles.inputWrapper}>
                <input
                  type="number"
                  value={subs}
                  onChange={e => setSubs(e.target.value)}
                  placeholder="0"
                />
              </div>
            </div>

            {/* Status dropdown (at right edge) */}
            <div className={styles.fieldWrapper}>
              <span className={styles.fieldLabel}>Статус</span>
              <button
                type="button"
                className={styles.statusButton}
                style={{ background: STATUS_CONFIG[status].bg, color: STATUS_CONFIG[status].color }}
                onClick={() => setShowStatusPicker(!showStatusPicker)}
              >
                <span className={styles.statusIcon}>{STATUS_CONFIG[status].icon}</span>
                <span className={styles.statusLabel}>{STATUS_CONFIG[status].label}</span>
              </button>
            </div>
          </div>

          {/* Status picker popup */}
          {showStatusPicker && (
            <div className={styles.statusPicker}>
              {STATUS_KEYS.map(key => {
                const cfg = STATUS_CONFIG[key]
                return (
                  <button
                    key={key}
                    type="button"
                    className={`${styles.statusPickerOption} ${status === key ? styles.active : ''}`}
                    style={{ '--chip-color': cfg.color, '--chip-bg': cfg.bg } as React.CSSProperties}
                    onClick={() => { setStatus(key); setShowStatusPicker(false) }}
                  >
                    {cfg.icon} {cfg.label}
                  </button>
                )
              })}
            </div>
          )}

          {/* CPF (calculated with currency) */}
          {cpfFormatted && (
            <div className={styles.cpfDisplay}>
              <span className={styles.cpfLabel}>CPF</span>
              <span className={styles.cpfValue}>{cpfFormatted}</span>
            </div>
          )}

          {/* v72.9: Date - calendar ALWAYS visible */}
          <div className={styles.dateSection}>
            <span className={styles.dateLabel}>Дата рекламы</span>
            <DatePicker value={date} onChange={setDate} />
          </div>

          {/* Notes - auto-resize */}
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Примечания</label>
            <textarea
              className={styles.formTextarea}
              value={notes}
              onChange={e => {
                setNotes(e.target.value)
                // Auto-resize
                e.target.style.height = 'auto'
                e.target.style.height = e.target.scrollHeight + 'px'
              }}
              placeholder="Заметки о закупке..."
              rows={2}
              style={{ minHeight: 44, overflow: 'hidden' }}
            />
          </div>
        </div>

        {/* Actions */}
        <div className={styles.purchaseEditorActions}>
          <button className={styles.saveBtn} onClick={handleSave}>
            Сохранить
          </button>
          <button className={styles.deleteBtn} onClick={onDelete}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            </svg>
            Удалить
          </button>
        </div>
      </div>
    </div>
  )
}

interface ProjectsPageProps {
  onChannelClick?: (username: string) => void
  onClose?: () => void
}

export function ProjectsPage({ onChannelClick, onClose }: ProjectsPageProps) {
  void onChannelClick; // v72.4: Reserved for long press (future)
  const { hapticLight, hapticMedium, hapticSuccess, hapticError } = useTelegram()
  const { projects, loading, error, fetchProjects, createProject, deleteProject, getRecommendations } = useProjects()

  // UI State
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [channelInput, setChannelInput] = useState('')
  const [creating, setCreating] = useState(false)
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [activeProjectTab, setActiveProjectTab] = useState<'recommendations' | 'tracker'>('recommendations')

  // Recommendations
  const [recommendations, setRecommendations] = useState<Channel[]>([])
  const [loadingRecs, setLoadingRecs] = useState(false)

  // v75.0: Filters
  const [filters, setFilters] = useState<RecommendationFilters>(DEFAULT_FILTERS)
  const [showFilters, setShowFilters] = useState(false)

  // v75.0: Check if any filters are active
  const hasActiveFilters = filters.maxPrice !== null || filters.minTrust !== null ||
    filters.minMembers !== null || filters.maxMembers !== null

  // Purchases for selected project
  const { purchases: rawPurchases, stats, loading: loadingPurchases, createPurchase, updatePurchase, deletePurchase } = usePurchases(selectedProject?.id ?? null)

  // v72.3: Deduplicate purchases by channel_username (keep most recent)
  const purchases = useMemo(() => {
    const seen = new Map<string, Purchase>()
    for (const p of rawPurchases) {
      const existing = seen.get(p.channel_username)
      if (!existing || new Date(p.created_at) > new Date(existing.created_at)) {
        seen.set(p.channel_username, p)
      }
    }
    return Array.from(seen.values())
  }, [rawPurchases])

  // v72.4: Editing state for purchase (opens Bottom Sheet)
  const [editingPurchase, setEditingPurchase] = useState<number | null>(null)

  // v72.4: Get purchase being edited
  const purchaseBeingEdited = editingPurchase
    ? purchases.find(p => p.id === editingPurchase)
    : null

  // Load projects on mount
  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  // Load recommendations when project selected or filters change
  useEffect(() => {
    if (selectedProject && activeProjectTab === 'recommendations') {
      setLoadingRecs(true)
      getRecommendations(selectedProject.id, {
        max_price: filters.maxPrice ?? undefined,
        min_trust: filters.minTrust ?? undefined,
        min_members: filters.minMembers ?? undefined,
        max_members: filters.maxMembers ?? undefined,
      })
        .then(setRecommendations)
        .finally(() => setLoadingRecs(false))
    }
  }, [selectedProject, activeProjectTab, getRecommendations, filters])

  // Handle create project
  const handleCreate = useCallback(async () => {
    const username = channelInput.trim().replace('@', '')
    if (!username) return

    setCreating(true)
    hapticMedium()

    const project = await createProject(username)
    if (project) {
      hapticSuccess()
      setChannelInput('')
      setShowCreateForm(false)
      setSelectedProject(project)
    } else {
      hapticError()
    }
    setCreating(false)
  }, [channelInput, createProject, hapticMedium, hapticSuccess, hapticError])

  // v72.4: Check if channel is already in plan
  const isChannelInPlan = useCallback((username: string) => {
    return purchases.some(p => p.channel_username === username)
  }, [purchases])

  // v72.4: Toggle add/remove from plan
  const handleTogglePlan = useCallback(async (channel: Channel) => {
    if (!selectedProject) return
    hapticMedium()

    const existingPurchase = purchases.find(p => p.channel_username === channel.username)
    if (existingPurchase) {
      // Remove from plan
      await deletePurchase(existingPurchase.id)
      hapticLight()
    } else {
      // Add to plan
      const purchase = await createPurchase(channel.username)
      if (purchase) {
        hapticSuccess()
      }
    }
  }, [selectedProject, purchases, createPurchase, deletePurchase, hapticMedium, hapticLight, hapticSuccess])

  // Handle back from project detail
  const handleBack = useCallback(() => {
    hapticLight()
    setSelectedProject(null)
    setActiveProjectTab('recommendations')
  }, [hapticLight])

  // Empty state - no projects
  if (!loading && projects.length === 0 && !showCreateForm) {
    return (
      <div className={styles.projectsEmpty}>
        {/* v72.3: Header with close button */}
        {onClose && (
          <header className={styles.projectsListHeader}>
            <h1 className={styles.projectsListTitle}>Мои проекты</h1>
            <button className={styles.projectsCloseBtn} onClick={onClose}>
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </header>
        )}
        <div className={styles.projectsEmptyContent}>
          <div className={styles.projectsEmptyIcon}><RocketIcon size={64} /></div>
          <h2 className={styles.projectsEmptyTitle}>Добавь свой канал</h2>
          <p className={styles.projectsEmptyText}>и найди лучшие площадки для рекламы</p>
          <div className={styles.projectsEmptyForm}>
            <div className={styles.projectsInput}>
              <span className={styles.projectsInputPrefix}>@</span>
              <input
                type="text"
                placeholder="username канала"
                value={channelInput}
                onChange={(e) => setChannelInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              />
            </div>
            <button
              className={styles.projectsCreateBtn}
              onClick={handleCreate}
              disabled={!channelInput.trim() || creating}
            >
              {creating ? 'Создание...' : '+ Создать проект'}
            </button>
          </div>
          {error && <p className={styles.projectsError}>{error}</p>}
        </div>
      </div>
    )
  }

  // Project detail view
  if (selectedProject) {
    return (
      <div className={styles.projectDetail}>
        {/* Header */}
        <header className={styles.projectDetailHeader}>
          <button className={styles.backButton} onClick={handleBack}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 19l-7-7 7-7"/>
            </svg>
          </button>
          <Avatar username={selectedProject.channel_username} size={32} />
          <span className={styles.projectDetailTitle}>@{selectedProject.channel_username}</span>
          <button
            className={styles.projectDeleteBtn}
            onClick={async () => {
              if (confirm('Удалить проект и все закупки?')) {
                hapticMedium()
                await deleteProject(selectedProject.id)
                setSelectedProject(null)
              }
            }}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            </svg>
          </button>
        </header>

        {/* Tabs - categoryChip style */}
        <div className={styles.projectTabsNew}>
          <button
            className={`${styles.tabChip} ${activeProjectTab === 'recommendations' ? styles.active : ''}`}
            onClick={() => { hapticLight(); setActiveProjectTab('recommendations') }}
          >
            <TargetIcon size={14} /> Подбор
          </button>
          <button
            className={`${styles.tabChip} ${activeProjectTab === 'tracker' ? styles.active : ''}`}
            onClick={() => { hapticLight(); setActiveProjectTab('tracker') }}
          >
            <ChartIcon size={14} /> Трекер {purchases.length > 0 && `(${purchases.length})`}
          </button>
          {/* v75.0: Filter button (only on recommendations tab) */}
          {activeProjectTab === 'recommendations' && (
            <button
              className={`${styles.filterChip} ${hasActiveFilters ? styles.active : ''}`}
              onClick={() => { hapticLight(); setShowFilters(!showFilters) }}
            >
              <FilterIcon size={14} />
              {hasActiveFilters && <span className={styles.filterDot} />}
            </button>
          )}
        </div>

        {/* v75.0: Filter panel */}
        {showFilters && activeProjectTab === 'recommendations' && (
          <div className={styles.filterPanel}>
            {/* Budget filter */}
            <div className={styles.filterSection}>
              <span className={styles.filterSectionLabel}>Бюджет</span>
              <div className={styles.filterChips}>
                {BUDGET_PRESETS.map(p => (
                  <button
                    key={p.label}
                    className={`${styles.filterOption} ${filters.maxPrice === p.value ? styles.active : ''}`}
                    onClick={() => {
                      hapticLight()
                      setFilters(f => ({ ...f, maxPrice: p.value }))
                    }}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Trust filter */}
            <div className={styles.filterSection}>
              <span className={styles.filterSectionLabel}>Минимальный Trust</span>
              <div className={styles.filterChips}>
                {TRUST_PRESETS.map(p => (
                  <button
                    key={p.label}
                    className={`${styles.filterOption} ${filters.minTrust === p.value ? styles.active : ''}`}
                    onClick={() => {
                      hapticLight()
                      setFilters(f => ({ ...f, minTrust: p.value }))
                    }}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Size filter */}
            <div className={styles.filterSection}>
              <span className={styles.filterSectionLabel}>Размер канала</span>
              <div className={styles.filterChips}>
                {SIZE_PRESETS.map(p => (
                  <button
                    key={p.label}
                    className={`${styles.filterOption} ${filters.minMembers === p.min && filters.maxMembers === p.max ? styles.active : ''}`}
                    onClick={() => {
                      hapticLight()
                      setFilters(f => ({ ...f, minMembers: p.min, maxMembers: p.max }))
                    }}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Reset button */}
            {hasActiveFilters && (
              <button
                className={styles.filterResetBtn}
                onClick={() => {
                  hapticLight()
                  setFilters(DEFAULT_FILTERS)
                }}
              >
                Сбросить фильтры
              </button>
            )}
          </div>
        )}

        {/* Tab content */}
        <div className={styles.projectTabContent}>
          {activeProjectTab === 'recommendations' ? (
            // Recommendations tab
            <div className={styles.recommendationsList}>
              {loadingRecs ? (
                <div className={styles.loadingState}>Загрузка рекомендаций...</div>
              ) : recommendations.length === 0 ? (
                <div className={styles.emptyState}>
                  <p>Нет рекомендаций для категории проекта</p>
                </div>
              ) : (
                <>
                  {/* v72.7: Same size avatar and ScoreRing (48px) */}
                  {recommendations.map((channel) => (
                    <button
                      key={channel.username}
                      className={`${styles.channelCardNew} ${isChannelInPlan(channel.username) ? styles.inPlan : ''}`}
                      onClick={() => handleTogglePlan(channel)}
                    >
                      <div className={styles.cardRow1}>
                        <Avatar username={channel.username} size={48} />
                        <div className={styles.cardInfo}>
                          <div className={styles.cardNameLine}>
                            <span className={styles.cardName}>
                              {channel.title || channel.username}
                            </span>
                            {channel.category && (
                              <span className={styles.categoryBadge}>
                                <span className={styles.categoryIcon}>
                                  {getCategoryIcon(channel.category)}
                                </span>
                                {getCategoryName(channel.category)}
                              </span>
                            )}
                            {isChannelInPlan(channel.username) && (
                              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#34c759" strokeWidth="3" style={{ marginLeft: 4, flexShrink: 0 }}>
                                <polyline points="20 6 9 17 4 12"/>
                              </svg>
                            )}
                          </div>
                          <div className={styles.cardMeta}>
                            @{channel.username} · {formatNumber(channel.members)}
                          </div>
                        </div>
                        <ScoreRing score={channel.score} />
                      </div>
                    </button>
                  ))}
                </>
              )}
            </div>
          ) : (
            // Tracker tab
            <div className={styles.trackerList}>
              {loadingPurchases ? (
                <div className={styles.loadingState}>Загрузка закупок...</div>
              ) : purchases.length === 0 ? (
                <div className={styles.emptyState}>
                  <p>Нет закупок</p>
                  <p className={styles.emptyHint}>Добавьте каналы из вкладки "Подбор"</p>
                </div>
              ) : (
                <>
                  {purchases.map((purchase) => {
                    // v72.8: channelCardNew style for consistency
                    const status = STATUS_CONFIG[purchase.status] || STATUS_CONFIG.PLANNED
                    return (
                      <button
                        key={purchase.id}
                        className={styles.channelCardNew}
                        onClick={() => {
                          hapticLight()
                          setEditingPurchase(purchase.id)
                        }}
                      >
                        <div className={styles.cardRow1}>
                          <Avatar username={purchase.channel_username} size={48} />
                          <div className={styles.cardInfo}>
                            <div className={styles.cardNameLine}>
                              <span className={styles.cardName}>
                                @{purchase.channel_username}
                              </span>
                              {/* v72.8: Status badge with icon and background */}
                              <span
                                className={styles.purchaseStatusBadge}
                                style={{ background: status.bg, color: status.color }}
                              >
                                {status.icon} {status.label}
                              </span>
                            </div>
                            <div className={styles.cardMeta}>
                              {purchase.channel_members ? formatNumber(purchase.channel_members) + ' подп.' : ''}
                            </div>
                            {/* v72.8: Stats row (price, subs, date, CPF) */}
                            {(purchase.price || purchase.subscribers_gained || purchase.scheduled_at) && (
                              <div className={styles.purchaseStatsRow}>
                                {purchase.price && <span>💰 {formatNumber(purchase.price)} ₽</span>}
                                {purchase.subscribers_gained && <span>+{purchase.subscribers_gained} подп.</span>}
                                {/* v75.0: Show CPF if we have price and subscribers */}
                                {purchase.price && purchase.subscribers_gained && purchase.subscribers_gained > 0 && (
                                  <span className={styles.cpfBadge}>
                                    CPF {Math.round(purchase.price / purchase.subscribers_gained)} ₽
                                  </span>
                                )}
                                {purchase.scheduled_at && <span>📅 {new Date(purchase.scheduled_at).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })}</span>}
                              </div>
                            )}
                          </div>
                          {/* v72.8: ScoreRing 48px (same as Avatar) */}
                          {purchase.channel_score && (
                            <ScoreRing score={purchase.channel_score} />
                          )}
                        </div>
                      </button>
                    )
                  })}

                  {/* Stats summary */}
                  {stats && (
                    <div className={styles.trackerStats}>
                      <span>Итого: {stats.purchases_count} закупок</span>
                      <span>Потрачено: {formatNumber(stats.total_spent)} ₽</span>
                      {stats.avg_cpf && (
                        <span>Средний CPF: {Math.round(stats.avg_cpf)} ₽</span>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* v72.4: Purchase Editor Bottom Sheet */}
        {purchaseBeingEdited && (
          <PurchaseEditorSheet
            purchase={purchaseBeingEdited}
            onSave={async (data) => {
              await updatePurchase(purchaseBeingEdited.id, data)
              hapticSuccess()
              setEditingPurchase(null)
            }}
            onDelete={async () => {
              if (confirm('Удалить закупку?')) {
                await deletePurchase(purchaseBeingEdited.id)
                hapticLight()
                setEditingPurchase(null)
              }
            }}
            onClose={() => {
              hapticLight()
              setEditingPurchase(null)
            }}
          />
        )}
      </div>
    )
  }

  // Projects list
  return (
    <div className={styles.projectsPage}>
      {/* v72.3: Header with close button */}
      <header className={styles.projectsListHeader}>
        <h1 className={styles.projectsListTitle}>Мои проекты</h1>
        {onClose && (
          <button className={styles.projectsCloseBtn} onClick={onClose}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        )}
      </header>

      {/* Add button - плавающая кнопка */}
      <button
        className={styles.projectsAddBtnFloat}
        onClick={() => { hapticLight(); setShowCreateForm(true) }}
      >
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 5v14M5 12h14"/>
        </svg>
      </button>

      {/* v72.7: Create form as bottom sheet */}
      {showCreateForm && (
        <>
          <div
            className={styles.sheetBackdrop}
            onClick={() => { hapticLight(); setShowCreateForm(false); setChannelInput('') }}
          />
          <div className={styles.projectsCreateForm}>
            <div className={styles.projectsInput}>
              <span className={styles.projectsInputPrefix}>@</span>
              <input
                type="text"
                placeholder="username канала"
                value={channelInput}
                onChange={(e) => setChannelInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                autoFocus
              />
            </div>
            <div className={styles.projectsFormActions}>
              <button
                className={styles.projectsCancelBtn}
                onClick={() => { hapticLight(); setShowCreateForm(false); setChannelInput('') }}
              >
                Отмена
              </button>
              <button
                className={styles.projectsCreateBtn}
                onClick={handleCreate}
                disabled={!channelInput.trim() || creating}
              >
                {creating ? 'Создание...' : 'Создать'}
              </button>
            </div>
            {error && <p className={styles.projectsError}>{error}</p>}
          </div>
        </>
      )}

      {/* Loading state */}
      {loading && projects.length === 0 && (
        <div className={styles.loadingState}>Загрузка проектов...</div>
      )}

      {/* Projects grid */}
      <div className={styles.projectsGrid}>
        {projects.map((project) => (
          <div
            key={project.id}
            className={styles.projectCard}
            onClick={() => { hapticLight(); setSelectedProject(project) }}
          >
            <Avatar username={project.channel_username} size={48} />
            <div className={styles.projectCardName}>@{project.channel_username}</div>
            <div className={styles.projectCardStats}>
              {project.purchases_count ?? 0} закупок
              {project.total_spent ? ` • ${formatNumber(project.total_spent)} ₽` : ''}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default ProjectsPage
