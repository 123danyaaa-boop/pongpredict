"""Быстрая диагностика table-tennis страницы Flashscore"""
from playwright.sync_api import sync_playwright
import re
from collections import Counter

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})

    print("1. Загрузка...")
    page.goto('https://www.flashscore.com/table-tennis/results/', timeout=30000)

    print("2. Куки...")
    try:
        page.click('#onetrust-accept-btn-handler', timeout=5000)
    except:
        pass

    print("3. Жду 15 сек...")
    page.wait_for_timeout(15000)

    print(f"4. URL: {page.url}")

    # Скриншот
    page.screenshot(path='data/tt_screenshot.png')
    print("5. Скриншот → data/tt_screenshot.png")

    # Все классы с "event"
    html = page.content()
    classes = re.findall(r'class="([^"]*)"', html)
    all_cls = []
    for c in classes:
        all_cls.extend(c.split())
    counter = Counter(all_cls)

    print("\n6. Классы с 'event' или 'match' или 'participant' или 'score':")
    for cls, cnt in counter.most_common(300):
        if any(w in cls.lower() for w in ['event', 'match', 'participant', 'score', 'header', 'league', 'row']):
            print(f"   .{cls}  ({cnt}x)")

    # JS: попробовать найти любой текст с именами или цифрами
    print("\n7. JS поиск элементов с текстом (первые 20 div с коротким текстом):")
    items = page.evaluate("""() => {
        const divs = document.querySelectorAll('div, span, a');
        const found = [];
        for (const d of divs) {
            if (d.children.length === 0) {
                const t = d.textContent.trim();
                if (t.length > 1 && t.length < 40) {
                    found.push({tag: d.tagName, cls: d.className.substring(0, 80), text: t});
                }
            }
            if (found.length >= 40) break;
        }
        return found;
    }""")
    for it in items:
        print(f"   <{it['tag']} class=\"{it['cls']}\"> {it['text']}")

    print("\n8. Браузер закроется через 60 сек — посмотри что на экране!")
    page.wait_for_timeout(60000)
    browser.close()