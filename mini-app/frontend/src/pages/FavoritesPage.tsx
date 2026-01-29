// v72.0: Favorites Page - Watchlist as separate tab
import { useWatchlist, StoredChannel, API_BASE } from '../hooks/useApi'
import { useTelegram } from '../hooks/useTelegram'
import styles from '../App.module.css'

// Format number for display
function formatNumber(num: number): string {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
  return num.toString()
}

// Get verdict color
function getVerdictColor(verdict: string): string {
  switch (verdict) {
    case 'EXCELLENT': return '#34c759'
    case 'GOOD': return '#5ac8fa'
    case 'MEDIUM': return '#ffcc00'
    case 'HIGH_RISK': return '#ff9500'
    case 'SCAM': return '#ff3b30'
    default: return '#8e8e93'
  }
}

// Format channel name
function formatChannelName(username: string): string {
  return username
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

// Avatar component
function Avatar({ username, size = 44 }: { username: string; size?: number }) {
  const photoUrl = `${API_BASE}/api/channels/${username}/photo`
  const initial = username.charAt(0).toUpperCase()

  return (
    <div
      className={styles.favAvatar}
      style={{ width: size, height: size }}
    >
      <img
        src={photoUrl}
        alt={username}
        className={styles.favAvatarImg}
        onError={(e) => {
          const target = e.currentTarget
          target.style.display = 'none'
          const parent = target.parentElement
          if (parent) {
            parent.classList.add(styles.favAvatarFallback)
            parent.textContent = initial
          }
        }}
      />
    </div>
  )
}

interface FavoritesPageProps {
  onChannelClick?: (channel: StoredChannel) => void
}

export function FavoritesPage({ onChannelClick }: FavoritesPageProps) {
  const { hapticLight, hapticMedium } = useTelegram()
  const { watchlist, removeFromWatchlist, clearWatchlist } = useWatchlist()

  // Empty state
  if (watchlist.length === 0) {
    return (
      <div className={styles.favoritesEmpty}>
        <div className={styles.favoritesEmptyIcon}>
          <svg viewBox="0 0 24 24" width="64" height="64" fill="none" stroke="var(--hint-color)" strokeWidth="1.5">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
          </svg>
        </div>
        <h2 className={styles.favoritesEmptyTitle}>Нет сохранённых каналов</h2>
        <p className={styles.favoritesEmptyText}>
          Нажми ⭐ на канале в каталоге, чтобы добавить в избранное
        </p>
      </div>
    )
  }

  return (
    <div className={styles.favoritesPage}>
      {/* Header */}
      <div className={styles.favoritesHeader}>
        <h1 className={styles.favoritesTitle}>Избранное</h1>
        <span className={styles.favoritesCount}>{watchlist.length}</span>
        {watchlist.length > 0 && (
          <button
            className={styles.favoritesClearBtn}
            onClick={() => {
              if (confirm('Очистить все избранное?')) {
                hapticMedium()
                clearWatchlist()
              }
            }}
          >
            Очистить
          </button>
        )}
      </div>

      {/* List */}
      <div className={styles.favoritesList}>
        {watchlist.map((channel) => (
          <div
            key={channel.username}
            className={styles.favoriteCard}
            onClick={() => {
              hapticLight()
              onChannelClick?.(channel)
            }}
          >
            <Avatar username={channel.username} size={48} />
            <div className={styles.favoriteInfo}>
              <span className={styles.favoriteName}>
                {formatChannelName(channel.username)}
              </span>
              <span className={styles.favoriteMeta}>
                @{channel.username} • {formatNumber(channel.members)} подп.
              </span>
            </div>
            <span
              className={styles.favoriteScore}
              style={{
                backgroundColor: `${getVerdictColor(channel.verdict)}20`,
                color: getVerdictColor(channel.verdict)
              }}
            >
              {channel.score}
            </span>
            <button
              className={styles.favoriteRemoveBtn}
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
        ))}
      </div>
    </div>
  )
}

export default FavoritesPage
