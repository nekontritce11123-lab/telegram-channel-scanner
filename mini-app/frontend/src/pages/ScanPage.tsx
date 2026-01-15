import { useState } from 'react'
import { useScan } from '../hooks/useApi'
import { useTelegram } from '../hooks/useTelegram'
import './ScanPage.css'

function ScanPage() {
  const [input, setInput] = useState('')
  const { result, loading, error, scanChannel, reset } = useScan()
  const { hapticLight, hapticSuccess, hapticError, openTelegramLink } = useTelegram()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim()) return

    hapticLight()
    const channel = input.trim().replace('@', '')
    await scanChannel(channel)

    if (result) {
      hapticSuccess()
    } else if (error) {
      hapticError()
    }
  }

  const handleReset = () => {
    hapticLight()
    setInput('')
    reset()
  }

  const getVerdictClass = (verdict: string) => {
    switch (verdict) {
      case 'EXCELLENT': return 'excellent'
      case 'GOOD': return 'good'
      case 'MEDIUM': return 'medium'
      case 'HIGH_RISK': return 'high-risk'
      case 'SCAM': return 'scam'
      default: return ''
    }
  }

  const getTrustClass = (trust: number) => {
    if (trust >= 0.9) return 'high'
    if (trust >= 0.6) return 'medium'
    return 'low'
  }

  const formatMembers = (n: number) => {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
    return n.toString()
  }

  return (
    <div className="page scan-page">
      <h1 className="page-title">Проверить канал</h1>

      <form className="scan-form" onSubmit={handleSubmit}>
        <div className="input-wrapper">
          <span className="input-prefix">@</span>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="channel_name"
            disabled={loading}
          />
        </div>
        <button type="submit" disabled={loading || !input.trim()}>
          {loading ? 'Проверяю...' : 'Проверить'}
        </button>
      </form>

      {error && (
        <div className="error">
          {error}
          <button className="retry-btn" onClick={handleReset}>
            Попробовать другой
          </button>
        </div>
      )}

      {result && (
        <div className="result-card">
          <div className="result-header">
            <span className="result-username">@{result.username}</span>
            <span className={`result-verdict ${getVerdictClass(result.verdict)}`}>
              {result.verdict}
            </span>
          </div>

          <div className="result-score-section">
            <div className="score-gauge">
              <svg viewBox="0 0 100 100">
                <circle
                  cx="50" cy="50" r="45"
                  fill="none"
                  stroke="var(--secondary-bg-color)"
                  strokeWidth="8"
                />
                <circle
                  cx="50" cy="50" r="45"
                  fill="none"
                  className={`score-progress ${getVerdictClass(result.verdict)}`}
                  strokeWidth="8"
                  strokeLinecap="round"
                  strokeDasharray={`${result.score * 2.83} 283`}
                  transform="rotate(-90 50 50)"
                />
              </svg>
              <div className="score-value">
                <span className="score-number">{result.score}</span>
                <span className="score-label">Score</span>
              </div>
            </div>

            <div className="score-details">
              <div className="detail-row">
                <span className="detail-label">Trust Factor</span>
                <span className={`detail-value trust ${getTrustClass(result.trust_factor)}`}>
                  x{result.trust_factor.toFixed(2)}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Подписчики</span>
                <span className="detail-value">{formatMembers(result.members)}</span>
              </div>
              {result.category && (
                <div className="detail-row">
                  <span className="detail-label">Категория</span>
                  <span className="detail-value category">{result.category}</span>
                </div>
              )}
              {result.cpm_min && result.cpm_max && (
                <div className="detail-row">
                  <span className="detail-label">CPM</span>
                  <span className="detail-value cpm">{result.cpm_min}-{result.cpm_max}₽</span>
                </div>
              )}
            </div>
          </div>

          <div className="result-actions">
            <button
              className="action-btn primary"
              onClick={() => {
                hapticLight()
                openTelegramLink(result.username)
              }}
            >
              Открыть канал
            </button>
            <button className="action-btn secondary" onClick={handleReset}>
              Проверить другой
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default ScanPage
