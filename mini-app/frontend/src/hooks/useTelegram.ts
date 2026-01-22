import { useEffect, useState, useCallback } from 'react'

// Telegram WebApp types
interface TelegramWebApp {
  ready: () => void
  close: () => void
  expand: () => void
  MainButton: {
    text: string
    color: string
    textColor: string
    isVisible: boolean
    show: () => void
    hide: () => void
    onClick: (callback: () => void) => void
    offClick: (callback: () => void) => void
  }
  BackButton: {
    isVisible: boolean
    show: () => void
    hide: () => void
    onClick: (callback: () => void) => void
    offClick: (callback: () => void) => void
  }
  HapticFeedback: {
    impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void
    notificationOccurred: (type: 'error' | 'success' | 'warning') => void
    selectionChanged: () => void
  }
  themeParams: {
    bg_color?: string
    text_color?: string
    hint_color?: string
    link_color?: string
    button_color?: string
    button_text_color?: string
    secondary_bg_color?: string
  }
  initDataUnsafe: {
    user?: {
      id: number
      first_name: string
      last_name?: string
      username?: string
      language_code?: string
    }
  }
  platform: string
  colorScheme: 'light' | 'dark'
  isExpanded: boolean
  viewportHeight: number
  viewportStableHeight: number
  initData: string  // v62.0: Raw initData string for backend verification
}

declare global {
  interface Window {
    Telegram?: {
      WebApp: TelegramWebApp
    }
  }
}

export function useTelegram() {
  const [webApp, setWebApp] = useState<TelegramWebApp | null>(null)
  const [isReady, setIsReady] = useState(false)

  useEffect(() => {
    const tg = window.Telegram?.WebApp
    if (tg) {
      setWebApp(tg)
      setIsReady(true)
    }
  }, [])

  const openLink = useCallback((url: string) => {
    window.open(url, '_blank')
  }, [])

  const openTelegramLink = useCallback((username: string) => {
    window.open(`tg://resolve?domain=${username}`, '_blank')
  }, [])

  const hapticLight = useCallback(() => {
    webApp?.HapticFeedback?.impactOccurred('light')
  }, [webApp])

  const hapticMedium = useCallback(() => {
    webApp?.HapticFeedback?.impactOccurred('medium')
  }, [webApp])

  const hapticSuccess = useCallback(() => {
    webApp?.HapticFeedback?.notificationOccurred('success')
  }, [webApp])

  const hapticError = useCallback(() => {
    webApp?.HapticFeedback?.notificationOccurred('error')
  }, [webApp])

  return {
    webApp,
    isReady,
    user: webApp?.initDataUnsafe?.user,
    colorScheme: webApp?.colorScheme || 'dark',
    platform: webApp?.platform || 'unknown',
    themeParams: webApp?.themeParams || {},
    openLink,
    openTelegramLink,
    hapticLight,
    hapticMedium,
    hapticSuccess,
    hapticError,
  }
}
