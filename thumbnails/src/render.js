const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch();
  for (const [f, w, h, out] of [['check.html',1040,1040,'' + __dirname + '/../3min_check_square.png'],['tokuten.html',1280,670,'' + __dirname + '/../tokuten_kouryaku_cover.png']]) {
    const p = await b.newPage({ viewport: { width: w, height: h } });
    await p.goto('file://' + __dirname + '/' + f);
    await p.waitForLoadState('networkidle'); await p.evaluate(() => document.fonts.ready);
    await p.screenshot({ path: out });
  }
  await b.close();
})();
