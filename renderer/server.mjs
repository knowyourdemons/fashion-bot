import express from 'express';
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import { readFileSync } from 'fs';

const app = express();
app.use(express.json({ limit: '20mb' }));

const font = readFileSync('./fonts/DejaVuSans.ttf');
const FONTS = [{ name: 'DejaVu', data: font, weight: 400, style: 'normal' }];

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.post('/render', async (req, res) => {
  try {
    const { element, width, height } = req.body;
    const svg = await satori(element, { width: width || 440, height: height || 620, fonts: FONTS });
    const resvg = new Resvg(svg);
    const png = resvg.render().asPng();
    res.set('Content-Type', 'image/png');
    res.send(png);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

app.listen(3100, () => console.log('Satori renderer on :3100'));
