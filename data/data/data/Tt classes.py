"""Мини-дебаг: дойти до Table Tennis и показать классы матчей"""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        viewport={'width': 1920, 'height': 1080},
    ).new_page()

    # 1. Главная
    page.goto('https://www.flashscore.com/', timeout=30000)
    page.wait_for_timeout(4000)
    try:
        page.click('#onetrust-accept-btn-handler', timeout=5000)
        page.wait_for_timeout(1000)
    except:
        pass

    # 2. Раскрыть меню + Table Tennis
    arrow = page.query_selector('.menuMinority__arrow')
    if arrow:
        arrow.click()
        page.wait_for_timeout(2000)

    items = page.query_selector_all('.menuMinority__text')
    for item in items:
        if 'table tennis' in item.inner_text().strip().lower():
            parent = item.evaluate_handle('el => el.closest("a") || el.parentElement')
            parent.as_element().click()
            page.wait_for_timeout(5000)
            break

    # 3. Кликнуть FINISHED
    page.evaluate("""() => {
        const els = document.querySelectorAll('a, div, span, button');
        for (const el of els) {
            const t = el.textContent.trim().toUpperCase();
            if (t === 'FINISHED' || t === 'RESULTS') {
                el.click();
                return true;
            }
        }
        return false;
    }""")
    page.wait_for_timeout(5000)

    print(f"URL: {page.url}")

    # 4. Дампим ВСЕ что видим
    data = page.evaluate("""() => {
        const output = {classes: {}, sampleElements: [], matchAttempt: []};

        // Все уникальные классы
        document.querySelectorAll('*').forEach(el => {
            const cls = el.className;
            if (typeof cls === 'string' && cls.length > 0) {
                cls.split(/\\s+/).forEach(c => {
                    if (!output.classes[c]) output.classes[c] = 0;
                    output.classes[c]++;
                });
            }
        });

        // Ищем элементы содержащие имена/цифры из скриншота
        const testNames = ['Choi', 'Malik', 'Kwan', 'Ruiz', 'Woo', 'Yoshimura', 'Sakai'];
        document.querySelectorAll('*').forEach(el => {
            if (el.children.length > 3) return; // не листовой
            const t = el.textContent.trim();
            for (const name of testNames) {
                if (t.includes(name) && t.length < 60) {
                    output.sampleElements.push({
                        tag: el.tagName,
                        cls: (el.className || '').substring(0, 120),
                        text: t.substring(0, 60),
                        parentCls: (el.parentElement?.className || '').substring(0, 120),
                        grandCls: (el.parentElement?.parentElement?.className || '').substring(0, 120),
                    });
                    break;
                }
            }
        });

        // Ищем элементы со счётом "3" рядом с именами
        document.querySelectorAll('*').forEach(el => {
            if (el.children.length === 0) {
                const t = el.textContent.trim();
                if (t === '3' || t === '0' || t === '1') {
                    const cls = el.className || '';
                    if (cls.length > 5) {
                        output.matchAttempt.push({
                            tag: el.tagName,
                            cls: cls.substring(0, 120),
                            text: t,
                        });
                    }
                }
            }
        });

        return output;
    }""")

    # Выводим
    print("\n=== КЛАССЫ С 'event' / 'match' / 'participant' / 'score' ===")
    for cls, cnt in sorted(data['classes'].items(), key=lambda x: -x[1]):
        if any(w in cls.lower() for w in ['event', 'match', 'particip', 'score', 'header', 'league', 'home', 'away']):
            print(f"  .{cls}  ({cnt}x)")

    print("\n=== ЭЛЕМЕНТЫ С ИМЕНАМИ ИГРОКОВ ===")
    for el in data['sampleElements'][:15]:
        print(f"  <{el['tag']} class=\"{el['cls']}\">")
        print(f"    text: {el['text']}")
        print(f"    parent: {el['parentCls']}")
        print(f"    grand:  {el['grandCls']}")
        print()

    print("\n=== ЭЛЕМЕНТЫ СО СЧЁТОМ (3/0/1) ===")
    seen = set()
    for el in data['matchAttempt'][:10]:
        key = el['cls']
        if key not in seen:
            seen.add(key)
            print(f"  <{el['tag']} class=\"{el['cls']}\"> {el['text']}")

    print("\n30 сек до закрытия...")
    page.wait_for_timeout(30000)
    browser.close()