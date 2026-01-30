# Task Plan: Mini-App v72.0 — "Мои Проекты" (Excel Killer)

## Goal
Превратить приложение из "поисковика каналов" в "рабочее место рекламщика". Пользователь указывает СВОЙ канал и получает персонализированные рекомендации + трекинг закупок.

## Features
1. **Bottom Navigation** — 3 вкладки: Поиск, Проекты, Избранное
2. **Smart Match** — алгоритмический подбор каналов по категории/trust/размеру
3. **Трекер закупок** — статусы, цены, даты, авто-расчёт CPM/CPF
4. **Серверное хранение** — привязка к Telegram user_id

## Current Phase
Phase 5: Integration

---

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Серверная БД (не localStorage) | Синхронизация между устройствами, данные не потеряются |
| Рефакторинг App.tsx на компоненты | Монолит 68KB слишком большой для поддержки |
| Сначала Smart Match, потом Трекер | Пользователь хочет сначала "подбор" |
| Алгоритмы вместо AI | Проще реализовать: фильтр по category + sort by trust |
| Мониторинг постов вручную | Автоматический мониторинг сложнее, пока не нужен |

---

## Phases

### Phase 1: Backend Infrastructure
- [x] Создать таблицы `projects` и `purchases` в database.py
- [x] Добавить API endpoints в main.py:
  - POST/GET/DELETE `/api/projects`
  - GET `/api/projects/{id}/recommendations`
  - POST/GET/PUT/DELETE `/api/purchases`
- [x] Авторизация через Telegram initData (user_id)
- **Status:** `completed`
- **Files:** `scanner/database.py`, `mini-app/backend/main.py`

### Phase 2: Frontend Refactoring
- [x] Разбить App.tsx на компоненты:
  - `components/BottomNav.tsx` ✓
  - `pages/SearchPage.tsx` (текущий каталог остаётся в App.tsx)
  - `pages/ProjectsPage.tsx` ✓ (список + detail + подбор + трекер)
  - `pages/FavoritesPage.tsx` ✓
- [x] Добавить простой роутинг (useState для activeTab)
- [x] Хуки: `useProjects()`, `usePurchases()` в useApi.ts
- **Status:** `completed`
- **Files:** `mini-app/frontend/src/App.tsx`, `mini-app/frontend/src/App.module.css`, `mini-app/frontend/src/components/BottomNav.tsx`, `mini-app/frontend/src/pages/ProjectsPage.tsx`, `mini-app/frontend/src/pages/FavoritesPage.tsx`, `mini-app/frontend/src/hooks/useApi.ts`

### Phase 3: Smart Match (Подбор каналов)
- [x] Страница "Мои проекты" (пустое состояние + список)
- [x] Создание проекта (ввод @username)
- [x] Вкладка "Подбор" с алгоритмическим ранжированием
- [x] Фильтры: бюджет, минимальный trust, размер (v75.0)
- [x] Кнопка "В план" → добавляет в трекер
- **Status:** `completed`
- **Files:** `pages/ProjectsPage.tsx`

### Phase 4: Трекер закупок (Excel Killer)
- [x] Вкладка "Трекер" со списком закупок
- [x] Карточка закупки с полями: статус, цена, дата
- [x] Pipeline статусов (редактирование статуса в Bottom Sheet) - PurchaseEditorSheet
- [x] Авто-расчёт CPM/CPF (v75.0: CPF badge on purchase cards)
- [x] Итоговая статистика проекта
- **Status:** `completed`
- **Files:** `pages/ProjectsPage.tsx`

### Phase 5: Integration
- [ ] Bottom Sheet "Добавить в проект" при нажатии ❤️
- [ ] Избранное как отдельная вкладка в BottomNav
- [ ] Toast уведомления при действиях
- **Status:** `pending`
- **Files:** `components/AddToSheet.tsx`, `pages/FavoritesPage.tsx`

---

## Database Schema

### projects
```sql
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,           -- Telegram user ID
    channel_username TEXT NOT NULL,      -- @crypto_blog
    name TEXT,                           -- Опциональное название
    category TEXT,                       -- Авто-определённая категория
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, channel_username)
);
```

### purchases
```sql
CREATE TABLE purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    channel_username TEXT NOT NULL,      -- Канал где купили рекламу
    status TEXT DEFAULT 'PLANNED',       -- PLANNED, CONTACTED, NEGOTIATING, PAID, POSTED, COMPLETED, CANCELLED
    price INTEGER,                       -- Цена в рублях
    scheduled_at DATETIME,               -- Дата выхода
    views INTEGER,                       -- Охват
    subscribers_gained INTEGER,          -- Прирост подписчиков
    notes TEXT,                          -- Заметки
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);
```

---

## API Endpoints

**Авторизация:** `X-Telegram-Init-Data` header с initData из Telegram WebApp.

```
# Проекты
POST   /api/projects                     -- Создать проект
GET    /api/projects                     -- Список проектов пользователя
GET    /api/projects/{id}                -- Детали проекта
DELETE /api/projects/{id}                -- Удалить проект
GET    /api/projects/{id}/recommendations -- Алгоритмический подбор

# Закупки
POST   /api/projects/{id}/purchases      -- Добавить закупку
GET    /api/projects/{id}/purchases      -- Список закупок
PUT    /api/purchases/{id}               -- Обновить закупку
DELETE /api/purchases/{id}               -- Удалить закупку
GET    /api/projects/{id}/stats          -- Статистика проекта
```

---

## UI Architecture

### Bottom Navigation
```
┌─────────────────────────────────────────────────────┐
│                                                     │
│              [Текущий контент]                      │
│                                                     │
├─────────────────────────────────────────────────────┤
│   🔍 Поиск    │   🚀 Проекты   │   ⭐ Избранное    │
└─────────────────────────────────────────────────────┘
```

### Status Pipeline
| Статус | English | Цвет |
|--------|---------|------|
| Планируется | PLANNED | #8e8e93 (gray) |
| Связались | CONTACTED | #3390ec (blue) |
| Переговоры | NEGOTIATING | #ffcc00 (yellow) |
| Оплачено | PAID | #ff9500 (orange) |
| Опубликовано | POSTED | #5ac8fa (light blue) |
| Завершено | COMPLETED | #34c759 (green) |
| Отменено | CANCELLED | #ff3b30 (red) |

---

## Files to Modify

| File | Action | Est. Lines |
|------|--------|------------|
| `scanner/database.py` | ADD tables | +50 |
| `mini-app/backend/main.py` | ADD endpoints | +200 |
| `mini-app/frontend/src/App.tsx` | REFACTOR | -500, +100 |
| `mini-app/frontend/src/App.module.css` | ADD styles | +200 |
| `mini-app/frontend/src/components/BottomNav.tsx` | CREATE | +80 |
| `mini-app/frontend/src/pages/SearchPage.tsx` | CREATE | +300 |
| `mini-app/frontend/src/pages/ProjectsPage.tsx` | CREATE | +200 |
| `mini-app/frontend/src/pages/ProjectDetailPage.tsx` | CREATE | +400 |
| `mini-app/frontend/src/pages/FavoritesPage.tsx` | CREATE | +150 |
| `mini-app/frontend/src/hooks/useProjects.ts` | CREATE | +100 |
| `mini-app/frontend/src/hooks/usePurchases.ts` | CREATE | +100 |

---

## Verification Checklist

```bash
# 1. Backend API
curl https://ads-api.factchain-traker.online/api/health
curl -X POST https://ads-api.factchain-traker.online/api/projects \
  -H "X-Telegram-Init-Data: ..." \
  -d '{"channel_username": "test_channel"}'

# 2. Frontend
npm run build  # должен собраться без ошибок
npm run dev    # должен показать 3 вкладки внизу

# 3. E2E Flow
- Открыть Проекты → Добавить проект
- Перейти в Подбор → Увидеть рекомендации
- Добавить канал в Трекер → Изменить статус
- Проверить расчёт CPM/CPF
```

---

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| (пока нет) | - | - |

---

## ВАЖНО: Не трогать!

- **Порт 3000/3001** - t-cloud, НЕ наш
- **Порт 3002** - reklamshik-api (наш)
- **Домен api.factchain-traker.online** - принадлежит t-cloud
- **Наш домен**: ads-api.factchain-traker.online
