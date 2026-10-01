from playwright.sync_api import sync_playwright

JS = """
() => {
  const chain = el => { const out=[]; let e=el;
    for (let i=0;i<6&&e;i++){
      const c = (typeof e.className==='string' && e.className.trim()) ? '.'+e.className.trim().split(/\\s+/).join('.') : '';
      out.push(e.tagName.toLowerCase()+c); e=e.parentElement; }
    return out.join('  <  '); };
  const res = {date:[], rating:[], title:[]};
  const leaves = [...document.querySelectorAll('body *')].filter(e => e.children.length===0);
  for (const e of leaves) {
    const t = e.textContent.trim();
    if (/^[A-Z][a-z]{2} \\d{1,2}, \\d{4}$/.test(t) && res.date.length<2) res.date.push(t+'  =>  '+chain(e));
    if (/^\\d\\.\\d$/.test(t) && res.rating.length<3) res.rating.push(t+'  =>  '+chain(e));
  }
  document.querySelectorAll('h3').forEach((h,i)=>{ if(i<8) res.title.push(h.textContent.trim().slice(0,40)+'  =>  '+chain(h)); });
  return res;
}
"""

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context("browser_profile", channel="chrome", headless=False, viewport=None)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://clutch.co/profile/simform", wait_until="domcontentloaded")
    print("\nLook at the Chrome window. If you see a 'verify you are human' check, solve it.")
    print("Wait until you can see the Simform reviews, scroll down to them,")
    input("then come back here and press ENTER... ")
    print("\nPAGE TITLE:", page.title())
    print("PAGE URL:  ", page.url)
    print("TEXT LENGTH:", len(page.inner_text("body")))
    print("FIRST 300 CHARS:", page.inner_text("body")[:300].replace("\n", " | "))
    res = page.evaluate(JS)
    for k, v in res.items():
        print("\n==", k.upper(), "==")
        for line in v:
            print(line)
    ctx.close()
