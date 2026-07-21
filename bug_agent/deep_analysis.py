from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    
    page.goto("http://localhost:5678/login", wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(1000)
    page.fill('input[id="username"]', 'admin')
    page.fill('input[id="password"]', 'admin123')
    page.click('button[type="submit"]')
    page.wait_for_timeout(3000)
    
    pages_to_check = [
        ("1-UserManagement", "http://localhost:5678/users"),
        ("2-AuditLog", "http://localhost:5678/system/audit-log"),
        ("2b-ProjectList", "http://localhost:5678/projects"),
        ("3-DefectList", "http://localhost:5678/projects/1/defects"),
        ("3b-IssuePool", "http://localhost:5678/projects/1/issues"),
        ("3c-RegressionCenter", "http://localhost:5678/projects/1/regression"),
        ("4-Repos", "http://localhost:5678/projects/1/repos"),
        ("5-DefectDetail", "http://localhost:5678/projects/1/defects/4"),
    ]
    
    for name, url in pages_to_check:
        try:
            page.goto(url, wait_until="networkidle", timeout=10000)
            page.wait_for_timeout(2000)
            
            result = page.evaluate("""() => {
                const out = { url: location.href };
                
                // 1. All buttons - find blank/empty ones
                out.buttons = [];
                document.querySelectorAll('.ant-btn').forEach((btn, i) => {
                    const rect = btn.getBoundingClientRect();
                    const text = btn.textContent.trim();
                    if (!text && !btn.querySelector('.anticon') || (rect.width < 50 && !text)) {
                        const style = window.getComputedStyle(btn);
                        out.buttons.push({
                            index: i, text: text || '(empty)',
                            width: Math.round(rect.width), height: Math.round(rect.height),
                            x: Math.round(rect.x), y: Math.round(rect.y),
                            background: style.background.substring(0, 60),
                            border: style.border, parentClass: btn.parentElement?.className?.substring(0, 80),
                            hasIcon: btn.querySelector('.anticon') !== null,
                        });
                    }
                });
                
                // 2. Search input nesting
                out.searchNesting = [];
                document.querySelectorAll('.ant-input-affix-wrapper').forEach((wrapper, i) => {
                    const rect = wrapper.getBoundingClientRect();
                    const style = window.getComputedStyle(wrapper);
                    const parentWrapper = wrapper.parentElement?.closest('.ant-input-affix-wrapper');
                    const isNested = parentWrapper !== null && parentWrapper !== wrapper;
                    out.searchNesting.push({
                        index: i, width: Math.round(rect.width), height: Math.round(rect.height),
                        borderRadius: style.borderRadius, isNested,
                        parentTag: wrapper.parentElement?.tagName,
                        parentClass: wrapper.parentElement?.className?.substring(0, 80),
                        grandParentClass: wrapper.parentElement?.parentElement?.className?.substring(0, 80),
                    });
                });
                
                // 3. Container overflow
                out.overflow = [];
                document.querySelectorAll('.action-rail, .page-filter-bar, .metric-action-row').forEach((el, i) => {
                    const rect = el.getBoundingClientRect();
                    out.overflow.push({
                        index: i, class: el.className?.substring(0, 60),
                        width: Math.round(rect.width), scrollWidth: el.scrollWidth,
                        overflowing: el.scrollWidth > rect.width,
                    });
                });
                
                // 4. Table cell density (first 10 cells)
                out.tableCells = [];
                document.querySelectorAll('.ant-table-cell').forEach((cell, i) => {
                    if (i < 10) {
                        const style = window.getComputedStyle(cell);
                        out.tableCells.push({
                            index: i, padding: style.padding,
                            width: Math.round(cell.getBoundingClientRect().width),
                            whiteSpace: style.whiteSpace,
                        });
                    }
                });
                
                // 5. Section/card spacing
                out.sections = [];
                document.querySelectorAll('.page-layout > *').forEach((sec, i) => {
                    if (i < 10) {
                        const style = window.getComputedStyle(sec);
                        out.sections.push({
                            index: i, class: sec.className?.substring(0, 60),
                            marginBottom: style.marginBottom, height: Math.round(sec.getBoundingClientRect().height),
                        });
                    }
                });
                
                out.cards = [];
                document.querySelectorAll('.ant-card').forEach((card, i) => {
                    if (i < 8) {
                        const style = window.getComputedStyle(card);
                        const body = card.querySelector('.ant-card-body');
                        const bodyStyle = body ? window.getComputedStyle(body) : null;
                        out.cards.push({
                            index: i, class: card.className?.substring(0, 60),
                            borderRadius: style.borderRadius,
                            bodyPadding: bodyStyle?.padding,
                            marginBottom: style.marginBottom,
                        });
                    }
                });
                
                // 6. Summary band detail
                const summaryBand = document.querySelector('.detail-summary-band');
                if (summaryBand) {
                    const style = window.getComputedStyle(summaryBand);
                    out.summaryBand = { padding: style.padding, childCount: summaryBand.children.length };
                }
                
                const sidebar = document.querySelector('.decision-rail');
                if (sidebar) {
                    out.sidebar = { gap: window.getComputedStyle(sidebar).gap };
                }
                
                return out;
            }""")
            
            print(f"\n{'='*50}")
            print(f"MODULE: {name}")
            print(f"{'='*50}")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
        except Exception as e:
            print(f"\nERR [{name}]: {e}")
    
    browser.close()
