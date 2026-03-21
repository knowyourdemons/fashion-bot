import express from 'express';
import { chromium } from 'playwright';

const app = express();
app.use(express.json({ limit: '20mb' }));

let browser;

async function getBrowser() {
  if (!browser || !browser.isConnected()) {
    browser = await chromium.launch({
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
      ],
    });
  }
  return browser;
}

getBrowser().then(() => console.log('Browser ready'));

app.get('/health', async (req, res) => {
  try {
    const b = await getBrowser();
    res.json({ status: 'ok', connected: b.isConnected() });
  } catch (e) {
    res.status(500).json({ status: 'error', error: e.message });
  }
});

app.post('/render', async (req, res) => {
  const start = Date.now();
  let page;
  try {
    const { html, width = 440, height } = req.body;
    if (!html) return res.status(400).json({ error: 'html required' });

    const b = await getBrowser();
    page = await b.newPage({ viewport: { width, height: height || 800 } });
    await page.setContent(html, { waitUntil: 'load', timeout: 10000 });

    const bodyHeight = height || await page.evaluate(() => document.body.scrollHeight);
    if (!height) await page.setViewportSize({ width, height: bodyHeight });

    const png = await page.screenshot({
      type: 'png',
      clip: { x: 0, y: 0, width, height: bodyHeight },
    });
    await page.close();
    page = null;

    console.log(`Rendered ${width}x${bodyHeight} in ${Date.now() - start}ms`);
    res.set('Content-Type', 'image/png');
    res.send(png);
  } catch (err) {
    if (page) await page.close().catch(() => {});
    console.error('Render error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

process.on('SIGTERM', async () => {
  if (browser) await browser.close();
  process.exit(0);
});

app.listen(3100, () => console.log('Playwright renderer on :3100'));
