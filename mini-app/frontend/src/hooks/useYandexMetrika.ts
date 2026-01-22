/**
 * v62.0: Яндекс.Метрика integration hook
 *
 * Поддержка:
 * - reachGoal() - отслеживание целей
 * - hit() - виртуальные страницы для SPA
 * - trackError() - отслеживание ошибок (вне React)
 */

import { useCallback } from 'react'

// v62.0: Яндекс.Метрика counter ID
const COUNTER_ID = 106393488

declare global {
  interface Window {
    ym?: (counterId: number, method: string, ...args: unknown[]) => void
  }
}

type YMGoal =
  | 'search_submitted' | 'search_found' | 'search_queued' | 'search_error'
  | 'channel_viewed' | 'channel_link_clicked'
  | 'filter_opened' | 'filter_applied' | 'filter_reset'
  | 'watchlist_added' | 'watchlist_removed' | 'watchlist_opened'
  | 'metric_details_opened' | 'scroll_load_more'
  | 'error_occurred'

function safeYM(method: string, ...args: unknown[]): void {
  try {
    if (typeof window !== 'undefined' && window.ym && COUNTER_ID > 0) {
      window.ym(COUNTER_ID, method, ...args)
    }
  } catch {
    // Silent fail - аналитика не должна ломать приложение
  }
}

export function useYandexMetrika() {
  const reachGoal = useCallback((goal: YMGoal, params?: Record<string, unknown>) => {
    safeYM('reachGoal', goal, params || {})
  }, [])

  const hit = useCallback((page: string, options?: { title?: string }) => {
    const url = page.startsWith('/') ? `${window.location.origin}${page}` : page
    safeYM('hit', url, { title: options?.title || document.title })
  }, [])

  return { reachGoal, hit }
}

/**
 * Для использования вне React компонентов (ErrorBoundary, handlers)
 */
export function trackError(error: string, context?: string): void {
  safeYM('reachGoal', 'error_occurred', { error, context })
}

/**
 * Трекинг события поиска
 */
export function trackSearch(query: string, result: 'found' | 'queued' | 'error'): void {
  const goal = `search_${result}` as YMGoal
  safeYM('reachGoal', goal, { query })
}
