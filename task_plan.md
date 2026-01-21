# Task Plan: v59.0 Desktop Adaptation + Swap Quality/Reputation

## Goal
Сделать UI хорошо выглядящим на ПК (сейчас мелко) и поменять местами блоки Качество/Репутация.

## Current Phase
Phase 1

## Проблема

### Текущее состояние:
- **clamp()** ограничивает размеры: `clamp(15px, 2.5vw, 17px)` → на ПК max 17px (мелко!)
- **Только 3 media queries** на 600px — минимальные изменения
- **Нет desktop breakpoint** (768px, 1024px)
- **Порядок блоков**: Quality → Engagement → Reputation

### Что нужно:
1. На ПК (>768px) увеличить шрифты, отступы, элементы
2. Центрировать контент с max-width (не растягивать на весь экран)
3. Поменять порядок: **Reputation → Engagement → Quality**

---

## Phases

### Phase 1: Analysis ✅
- [x] Найти все media queries → только 3 на 600px
- [x] Найти CSS переменные → clamp() с маленькими max значениями
- [x] Найти порядок блоков → lines 807-861 в App.tsx
- **Status:** complete

### Phase 2: CSS Desktop Variables
- [ ] Добавить @media (min-width: 768px) для :root
- [ ] Увеличить --font-* переменные на 30-50%
- [ ] Увеличить --spacing-* переменные
- **Status:** pending

### Phase 3: CSS Desktop Layout
- [ ] Добавить max-width: 600px для .app на desktop
- [ ] Центрировать контейнер с margin: 0 auto
- [ ] Добавить боковые границы для визуального отделения
- **Status:** pending

### Phase 4: CSS Desktop Components
- [ ] Увеличить карточки каналов (avatar, score circle)
- [ ] Увеличить шапку детальной страницы (avatar, title)
- [ ] Увеличить спидометр
- [ ] Увеличить метрики и цены
- **Status:** pending

### Phase 5: TSX - Swap Blocks
- [ ] Поменять порядок блоков Quality ↔ Reputation
- **Status:** pending

### Phase 6: Build & Test
- [ ] npm run build
- [ ] Проверить на мобильном (DevTools)
- [ ] Проверить на desktop
- [ ] Deploy frontend
- **Status:** pending

---

## Детальный план CSS изменений

### 1. Desktop Variables Override (после :root)

```css
@media (min-width: 768px) {
  :root {
    /* Desktop: увеличенные шрифты (+50%) */
    --font-title: 36px;
    --font-body: 20px;
    --font-secondary: 17px;
    --font-meta: 15px;

    /* Desktop: увеличенные отступы (+50%) */
    --spacing-xs: 10px;
    --spacing-sm: 14px;
    --spacing-md: 22px;
    --spacing-lg: 32px;
    --spacing-xl: 40px;

    /* Desktop: увеличенные радиусы */
    --radius-sm: 12px;
    --radius-md: 16px;
    --radius-lg: 24px;
  }
}
```

### 2. App Container (max-width)

```css
@media (min-width: 768px) {
  .app {
    max-width: 540px;
    margin: 0 auto;
    border-left: 1px solid rgba(255,255,255,0.08);
    border-right: 1px solid rgba(255,255,255,0.08);
    min-height: 100vh;
  }
}
```

### 3. Channel Cards

```css
@media (min-width: 768px) {
  .channelCard {
    padding: 20px;
  }

  .cardAvatar {
    width: 60px;
    height: 60px;
  }

  .cardName {
    font-size: 20px;
  }

  .scoreCircle {
    width: 60px;
    height: 60px;
  }

  .scoreNumber {
    font-size: 22px;
  }
}
```

### 4. Detail Page Header

```css
@media (min-width: 768px) {
  .channelHeader {
    padding: 28px 20px;
  }

  .headerAvatar {
    width: 88px;
    height: 88px;
  }

  .headerTitle {
    font-size: 28px;
  }

  .headerUsername {
    font-size: 17px;
  }
}
```

### 5. Speedometer

```css
@media (min-width: 768px) {
  .speedometerContainer {
    padding: 28px;
  }

  .speedometer {
    width: 220px;
    height: 220px;
  }

  .speedometerScore {
    font-size: 48px;
  }

  .speedometerLabel {
    font-size: 17px;
  }
}
```

### 6. Metrics Grid

```css
@media (min-width: 768px) {
  .metricsGrid {
    gap: 16px;
  }

  .metricsBlock {
    padding: 16px;
  }

  .metricsBlockTitle {
    font-size: 15px;
  }

  .metricRow {
    padding: 12px 0;
  }

  .metricLabel {
    font-size: 16px;
  }

  .metricValue {
    font-size: 16px;
  }

  .metricBar {
    height: 10px;
  }
}
```

### 7. Price Card

```css
@media (min-width: 768px) {
  .priceCard {
    padding: 24px;
  }

  .priceMain {
    font-size: 36px;
  }

  .priceLabel {
    font-size: 15px;
  }
}
```

---

## TSX Change: Swap Blocks

**Файл:** `mini-app/frontend/src/App.tsx`
**Строки:** 806-870

**Текущий порядок:**
1. Quality Block (line 807)
2. Engagement Block (line 831)
3. Reputation Block (line 847)

**Новый порядок:**
1. Reputation Block ← ПЕРВЫЙ
2. Engagement Block
3. Quality Block ← ПОСЛЕДНИЙ

Просто вырезать блок Reputation и вставить перед Quality.

---

## Files to Modify

| # | File | Changes |
|---|------|---------|
| 1 | mini-app/frontend/src/App.module.css | Desktop media queries (~100 lines) |
| 2 | mini-app/frontend/src/App.tsx | Swap blocks (~20 lines move) |

---

## Verification

```bash
# 1. Build
cd mini-app/frontend && npm run build

# 2. Local test
npm run dev
# DevTools → Toggle device → iPhone → должно выглядеть как раньше
# Full window desktop → должно быть крупнее, центрировано

# 3. Deploy
cd ../deploy && python deploy_frontend.py

# 4. Live test
# Open https://ads.factchain-traker.online on:
# - Phone → без изменений
# - Desktop → крупнее, центрировано
```

---

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Breakpoint 768px | Стандартный порог tablet/desktop |
| max-width: 540px | Немного меньше 600px для визуального комфорта |
| Font increase +50% | Заметно крупнее, но не гигантское |
| Spacing increase +50% | Пропорционально шрифтам |
| Border subtle | Визуально отделить контент от фона |

---

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| - | - | - |
