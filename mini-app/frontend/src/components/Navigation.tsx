import { NavLink } from 'react-router-dom'
import { useTelegram } from '../hooks/useTelegram'
import './Navigation.css'

function Navigation() {
  const { hapticLight } = useTelegram()

  const handleClick = () => {
    hapticLight()
  }

  return (
    <nav className="navigation">
      <NavLink
        to="/database"
        className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
        onClick={handleClick}
      >
        <svg className="nav-icon" viewBox="0 0 24 24" fill="currentColor">
          <path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" />
        </svg>
        <span className="nav-label">База</span>
      </NavLink>

      <NavLink
        to="/scan"
        className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
        onClick={handleClick}
      >
        <svg className="nav-icon" viewBox="0 0 24 24" fill="currentColor">
          <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" />
        </svg>
        <span className="nav-label">Проверить</span>
      </NavLink>

      <NavLink
        to="/stats"
        className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
        onClick={handleClick}
      >
        <svg className="nav-icon" viewBox="0 0 24 24" fill="currentColor">
          <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z" />
        </svg>
        <span className="nav-label">Статистика</span>
      </NavLink>
    </nav>
  )
}

export default Navigation
