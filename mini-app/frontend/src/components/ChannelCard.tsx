import { useTelegram } from '../hooks/useTelegram'
import type { Channel } from '../hooks/useApi'
import './ChannelCard.css'

interface ChannelCardProps {
  channel: Channel
  onClick?: () => void
}

function ChannelCard({ channel, onClick }: ChannelCardProps) {
  const { hapticLight, openTelegramLink } = useTelegram()

  const handleClick = () => {
    hapticLight()
    if (onClick) {
      onClick()
    }
  }

  const handleOpenChannel = (e: React.MouseEvent) => {
    e.stopPropagation()
    hapticLight()
    openTelegramLink(channel.username)
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
    <div className="channel-card" onClick={handleClick}>
      <div className="card-header">
        <span className="card-username">@{channel.username}</span>
        <span className={`card-verdict ${getVerdictClass(channel.verdict)}`}>
          {channel.verdict}
        </span>
      </div>

      <div className="card-body">
        <div className="card-score-row">
          <span className="card-score">{channel.score}</span>
          <span className={`card-trust ${getTrustClass(channel.trust_factor)}`}>
            x{channel.trust_factor.toFixed(2)}
          </span>
        </div>

        {channel.category && (
          <span className="card-category">{channel.category}</span>
        )}
      </div>

      <div className="card-footer">
        <span className="card-members">{formatMembers(channel.members)} подп.</span>
        {channel.cpm_min && channel.cpm_max && (
          <span className="card-cpm">{channel.cpm_min}-{channel.cpm_max}₽</span>
        )}
        <button className="card-open-btn" onClick={handleOpenChannel}>
          →
        </button>
      </div>
    </div>
  )
}

export default ChannelCard
