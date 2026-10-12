"""Standalone browser smoke with inline assets; no external HTTP required."""
from pathlib import Path
from playwright.sync_api import sync_playwright
base=Path(__file__).resolve().parents[1] / 'docs'
css=(base/'assets/styles.css').read_text()
js=(base/'assets/app.js').read_text().replace("const demo=params.get('demo')==='1'||location.protocol==='file:';","const demo=true;")
# `about:blank` denies localStorage; disable that one mutation in smoke only.
js=js.replace("localStorage.setItem('pasokhnama-v4-settings',JSON.stringify(config));","void 0;")
# Prevent external font fetch during tests.
css=css.replace("@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800;900&display=swap');",'')
def html_for(name,six_cards=False):
 h=(base/name).read_text()
 h=h.replace('<link rel="stylesheet" href="assets/styles.css">','<style>'+css+'</style>')
 h=h.replace('<script src="assets/app.js" defer></script>','<script>'+(js.replace('tv_card_count:5','tv_card_count:6') if six_cards else js)+'</script>')
 return h
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox','--disable-dev-shm-usage'])
 errors=[]
 desktop=browser.new_page(viewport={'width':1440,'height':950},device_scale_factor=1)
 desktop.on('pageerror',lambda x:errors.append(str(x)))
 desktop.set_content(html_for('index.html'),wait_until='domcontentloaded')
 desktop.wait_for_timeout(450)
 assert desktop.locator('.content-card').count()==6, desktop.locator('#cards').inner_text()
 assert desktop.locator('#metric-content').inner_text()=='۶'
 desktop.locator('.content-card button').first.click()
 assert desktop.locator('#modal').is_visible()
 desktop.locator('#modal-close').click()
 desktop.locator('#query').fill('مستند')
 assert desktop.locator('.content-card').count()>=1
 desktop.locator('#query').fill('')
 desktop.screenshot(path='/mnt/data/Pasokhnama-V4-Audience-Preview.png',full_page=True)
 tv=browser.new_page(viewport={'width':860,'height':1050},device_scale_factor=1)
 tv.on('pageerror',lambda x:errors.append(str(x)))
 tv.set_content(html_for('overlay.html',six_cards=True),wait_until='domcontentloaded')
 tv.wait_for_timeout(400)
 assert tv.locator('.tv-card').count()==6,tv.locator('#tv-cards').inner_text()
 assert tv.locator('#demo-label').is_visible()
 tv.screenshot(path='/mnt/data/Pasokhnama-V4-TV-Preview.png',full_page=True,omit_background=True)
 config=browser.new_page(viewport={'width':1000,'height':1000})
 config.on('pageerror',lambda x:errors.append(str(x)))
 config.set_content(html_for('settings.html'),wait_until='domcontentloaded')
 config.wait_for_timeout(350)
 assert config.locator('#s-count').input_value()=='5'
 config.locator('#s-count').fill('6');config.locator('#save-settings').click()
 assert 'ذخیره شد' in config.locator('#settings-feedback').inner_text()
 print('Browser smoke: audience=6; overlay=6; modal, search, settings OK; errors:',errors)
 assert not errors
 browser.close()
