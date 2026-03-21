import express from 'express';
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import { readFileSync, existsSync } from 'fs';

const app = express();
app.use(express.json({ limit: '20mb' }));

// Fonts: Nunito (primary, beautiful) + DejaVu (fallback for missing chars)
const nunitoRegular = readFileSync('./fonts/Nunito-Regular.ttf');
const nunitoBold = readFileSync('./fonts/Nunito-Bold.ttf');
const dejaVuRegular = readFileSync('./fonts/DejaVuSans.ttf');
const dejaVuBold = readFileSync('./fonts/DejaVuSans-Bold.ttf');

const FONTS = [
  { name: 'Nunito', data: nunitoRegular, weight: 400, style: 'normal' },
  { name: 'Nunito', data: nunitoBold, weight: 700, style: 'normal' },
  { name: 'DejaVu', data: dejaVuRegular, weight: 400, style: 'normal' },
  { name: 'DejaVu', data: dejaVuBold, weight: 700, style: 'normal' },
];

// Emoji cache: codepoint → SVG data URI
const emojiCache = new Map();

async function loadEmoji(segment) {
  const cacheKey = segment;
  if (emojiCache.has(cacheKey)) return emojiCache.get(cacheKey);

  // Convert emoji to codepoint for Twemoji CDN
  const codePoints = [...segment]
    .map(c => c.codePointAt(0).toString(16))
    .filter(cp => cp !== 'fe0f') // remove variation selector
    .join('-');

  // Try CDN first
  try {
    const url = `https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/svg/${codePoints}.svg`;
    const resp = await fetch(url);
    if (resp.ok) {
      const svg = await resp.text();
      const uri = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;
      emojiCache.set(cacheKey, uri);
      return uri;
    }
  } catch (e) {
    console.warn(`emoji CDN fetch failed for "${segment}":`, e.message);
  }

  // Local fallback: try reading from ./emoji/{codepoint}.svg
  try {
    const localPath = `./emoji/${codePoints}.svg`;
    if (existsSync(localPath)) {
      const svg = readFileSync(localPath, 'utf8');
      const uri = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;
      emojiCache.set(cacheKey, uri);
      console.log(`emoji loaded from local fallback: ${localPath}`);
      return uri;
    }
  } catch (e) {
    console.warn(`emoji local fallback failed for "${segment}":`, e.message);
  }

  return segment; // fallback: render as text
}

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.get('/test', async (req, res) => {
  try {
    const element = {
      type: 'div',
      props: {
        style: {
          display: 'flex',
          flexDirection: 'column',
          width: '100%',
          height: '100%',
          background: 'linear-gradient(180deg, #F5EDE8 0%, #F0E8E4 100%)',
          padding: '32px',
          fontFamily: 'Nunito',
        },
        children: [
          {
            type: 'div',
            props: {
              style: {
                display: 'flex',
                fontSize: 32,
                fontWeight: 700,
                color: '#2D2D2D',
                marginBottom: '16px',
                fontFamily: 'Nunito',
              },
              children: 'Алиса, садик',
            },
          },
          {
            type: 'div',
            props: {
              style: {
                display: 'flex',
                fontSize: 20,
                fontWeight: 400,
                color: '#4A4A4A',
                marginBottom: '24px',
                fontFamily: 'Nunito',
              },
              children: 'Кофта розовая',
            },
          },
          {
            type: 'div',
            props: {
              style: {
                display: 'flex',
                fontSize: 36,
                marginBottom: '24px',
              },
              children: '☀️ 🌧 👚 🧥',
            },
          },
          {
            type: 'div',
            props: {
              style: {
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
              },
              children: [
                {
                  type: 'div',
                  props: {
                    style: {
                      width: '10px',
                      height: '10px',
                      borderRadius: '50%',
                      background: '#F4A0B0',
                    },
                  },
                },
                {
                  type: 'div',
                  props: {
                    style: {
                      display: 'flex',
                      fontSize: 16,
                      color: '#888',
                      fontFamily: 'Nunito',
                    },
                    children: 'Color swatch test',
                  },
                },
              ],
            },
          },
        ],
      },
    };

    const svg = await satori(element, {
      width: 440,
      height: 620,
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
    console.error('Test render error:', err);
    res.status(500).json({ error: err.message });
  }
});

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

app.listen(3100, () => console.log('Satori renderer on :3100 (Nunito+DejaVu, Twemoji+local)'));
