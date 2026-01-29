// v72.0: Bottom Navigation - 3 tabs (Search, Projects, Favorites)
import styles from '../App.module.css'

export type TabType = 'search' | 'projects' | 'favorites'

interface BottomNavProps {
  activeTab: TabType
  onTabChange: (tab: TabType) => void
  favoritesCount?: number
}

// SVG Icons as components
const SearchIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="11" cy="11" r="8"/>
    <path d="M21 21l-4.35-4.35"/>
  </svg>
)

const ProjectsIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09Z"/>
    <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2Z"/>
    <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/>
    <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>
  </svg>
)

const FavoritesIcon = ({ filled }: { filled?: boolean }) => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2">
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
  </svg>
)

export function BottomNav({ activeTab, onTabChange, favoritesCount = 0 }: BottomNavProps) {
  const tabs = [
    { id: 'search' as TabType, label: 'Поиск', Icon: SearchIcon },
    { id: 'projects' as TabType, label: 'Проекты', Icon: ProjectsIcon },
    { id: 'favorites' as TabType, label: 'Избранное', Icon: () => <FavoritesIcon filled={favoritesCount > 0} /> },
  ]

  return (
    <nav className={styles.bottomNav}>
      {tabs.map(({ id, label, Icon }) => (
        <button
          key={id}
          className={`${styles.navItem} ${activeTab === id ? styles.navItemActive : ''}`}
          onClick={() => onTabChange(id)}
        >
          <span className={styles.navIcon}>
            <Icon />
          </span>
          <span className={styles.navLabel}>{label}</span>
          {id === 'favorites' && favoritesCount > 0 && (
            <span className={styles.navBadge}>{favoritesCount > 99 ? '99+' : favoritesCount}</span>
          )}
        </button>
      ))}
    </nav>
  )
}

export default BottomNav
