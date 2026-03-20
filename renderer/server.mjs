import express from 'express';
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import { readFileSync } from 'fs';

const app = express();
app.use(express.json({ limit: '20mb' }));

// Fonts: DejaVu (Regular + Bold) for full Cyrillic + Latin coverage
const fontRegular = readFileSync('./fonts/DejaVuSans.ttf');
const fontBold = readFileSync('./fonts/DejaVuSans-Bold.ttf');

const FONTS = [
  { name: 'DejaVu', data: fontRegular, weight: 400, style: 'normal' },
  { name: 'DejaVu', data: fontBold, weight: 700, style: 'normal' },
];

// Emoji cache: codepoint → SVG data URI
const emojiCache = new Map();

async function loadEmoji(segment) {
  const cacheKey = segment;
  if (emojiCache.has(cacheKey)) return emojiCache.get(cacheKey);

  try {
    // Convert emoji to codepoint for Twemoji CDN
    const codePoints = [...segment]
      .map(c => c.codePointAt(0).toString(16))
      .filter(cp => cp !== 'fe0f') // remove variation selector
      .join('-');
    const url = `https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/${codePoints}.svg`;
    const resp = await fetch(url);
    if (resp.ok) {
      const svg = await resp.text();
      const uri = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;
      emojiCache.set(cacheKey, uri);
      return uri;
    }
  } catch (e) {
    console.warn(`emoji fetch failed for "${segment}":`, e.message);
  }
  return segment; // fallback: render as text
}

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.post('/render', async (req, res) => {
  try {
    const { element, width, height } = req.body;
    const svg = await satori(element, {
      width: width || 440,
      height: height || 620,
      fonts: FONTS,
      loadAdditionalAsset: async (code, segment) => {
        if (code === 'emoji') {
          return loadEmoji(segment);
        }
        return segment;
      },
    });
    const resvg = new Resvg(svg);
    const png = resvg.render().asPng();
    res.set('Content-Type', 'image/png');
    res.send(png);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

app.listen(3100, () => console.log('Satori renderer on :3100 (DejaVu Regular+Bold, Twemoji)'));
