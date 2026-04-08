"""
PongPredict — Диагностика Flashscore

Этот скрипт открывает Flashscore, ждёт загрузки и сохраняет:
  1. Скриншот страницы (screenshot.png)
  2. HTML-структуру (page_dump.html)
  3. Все найденные CSS-классы и элементы

Запуск:
    python data/flashscore_debug.py
"""

import sys
import os
import re
from collections import Counter

def run_debug():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ pip install playwright && playwright install chromium")
        return

    print("🔍 Flashscore Debug — анализ структуры страницы\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Видимый браузер для отладки!
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})

        print("  1. Загружаю страницу...")
        page.goto('https://www.flashscore.com/table-tennis/results/', timeout=30000)
        page.wait_for_timeout(5000)

        # Принять куки
        print("  2. Принимаю куки...")
        try:
            page.click('#onetrust-accept-btn-handler', timeout=5000)
            page.wait_for_timeout(2000)
        except Exception:
            print("     (кнопка куки не найдена — ок)")

        # Ждём загрузки контента
        print("  3. Жду загрузки матчей (10 сек)...")
        page.wait_for_timeout(10000)

        # Скриншот
        print("  4. Сохраняю скриншот...")
        page.screenshot(path='data/debug_screenshot.png', full_page=False)
        print("     → data/debug_screenshot.png")

        # HTML
        print("  5. Сохраняю HTML...")
        html = page.content()
        with open('data/debug_page.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"     → data/debug_page.html ({len(html)} chars)")

        # Анализ классов
        print("\n  6. Анализ CSS-классов...")
        classes = re.findall(r'class="([^"]*)"', html)
        all_classes = []
        for c in classes:
            all_classes.extend(c.split())

        counter = Counter(all_classes)

        # Ищем классы связанные с матчами/событиями
        print("\n  📋 Классы содержащие 'event', 'match', 'game', 'sport':")
        relevant = {k: v for k, v in counter.items()
                    if any(word in k.lower() for word in
                           ['event', 'match', 'game', 'sport', 'score',
                            'participant', 'header', 'result', 'row',
                            'tennis', 'table'])}

        for cls, count in sorted(relevant.items(), key=lambda x: -x[1])[:40]:
            print(f"     .{cls}  ({count}x)")

        # Пробуем разные селекторы
        print("\n  🔎 Тестирую селекторы:")
        selectors = [
            'div.event__match',
            'div.event__header',
            'div[class*="event__match"]',
            'div[class*="event__header"]',
            'div[class*="sportName"]',
            'div[class*="match"]',
            'div[class*="participant"]',
            'div[class*="score"]',
            'a[class*="match"]',
            'div.leagues--static',
            'div[class*="event"]',
            'div[class*="rows"]',
            'section',
            'article',
            # Новые возможные паттерны Flashscore
            '[class*="___"]',  # CSS modules
            'div[data-testid]',
            'a[href*="/match/"]',
            'div[id*="match"]',
            'div[id*="event"]',
        ]

        for sel in selectors:
            try:
                els = page.query_selector_all(sel)
                if els:
                    print(f"     ✅ '{sel}' → {len(els)} элементов")
                    # Показать первый элемент
                    if len(els) > 0:
                        text = els[0].inner_text()[:100].replace('\n', ' | ')
                        print(f"        Первый: {text}")
            except Exception:
                pass

        # Ищем ссылки на матчи
        print("\n  🔗 Ссылки на матчи (href содержит 'match'):")
        links = page.query_selector_all('a[href*="match"]')
        for link in links[:5]:
            href = link.get_attribute('href') or ''
            text = link.inner_text()[:60].replace('\n', ' | ')
            print(f"     {href}  →  {text}")

        # Пробуем JavaScript для получения данных
        print("\n  📊 JavaScript анализ:")
        try:
            result = page.evaluate("""() => {
                // Ищем все элементы с текстом счёта (число-число)
                const all = document.querySelectorAll('*');
                const scoreElements = [];
                for (const el of all) {
                    if (el.children.length === 0) {
                        const text = el.textContent.trim();
                        if (/^\\d+$/.test(text) && parseInt(text) <= 11) {
                            const classes = el.className;
                            if (classes && !scoreElements.some(s => s.cls === classes)) {
                                scoreElements.push({cls: classes, text: text, tag: el.tagName});
                            }
                        }
                    }
                }
                return scoreElements.slice(0, 15);
            }""")
            print("     Элементы со счётом (цифры 0-11):")
            for r in result:
                print(f"       <{r['tag']} class=\"{r['cls']}\"> {r['text']}")
        except Exception as e:
            print(f"     Ошибка JS: {e}")

        # Ищем конкретные паттерны имён игроков
        print("\n  👤 Поиск имён игроков в DOM:")
        try:
            result = page.evaluate("""() => {
                const all = document.querySelectorAll('*');
                const names = [];
                const knownPlayers = ['Fan Zhendong', 'Wang Chuqin', 'Ma Long',
                    'Calderano', 'Harimoto', 'Ovtcharov', 'Boll'];
                for (const el of all) {
                    const text = el.textContent.trim();
                    for (const name of knownPlayers) {
                        if (text.includes(name) && el.children.length === 0) {
                            names.push({
                                cls: el.className,
                                tag: el.tagName,
                                text: text.substring(0, 50)
                            });
                            break;
                        }
                    }
                }
                return names.slice(0, 10);
            }""")
            for r in result:
                print(f"       <{r['tag']} class=\"{r['cls']}\"> {r['text']}")
        except Exception as e:
            print(f"     Ошибка: {e}")

        print("\n  ✅ Диагностика завершена!")
        print("  📁 Файлы: data/debug_screenshot.png, data/debug_page.html")
        print("\n  Скопируй вывод этого скрипта и отправь мне — я обновлю селекторы!")

        # Даём время посмотреть
        print("\n  Браузер закроется через 30 секунд...")
        page.wait_for_timeout(30000)
        browser.close()


if __name__ == '__main__':
    run_debug()
