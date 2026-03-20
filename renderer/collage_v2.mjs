import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import { readFileSync, writeFileSync } from 'fs';

const font = readFileSync('./fonts/DejaVuSans.ttf');

const card = (name, subtitle, bg, size, isPlaceholder, emoji) => ({
  type: 'div',
  props: {
    style: {
      width: size,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      background: bg,
      borderRadius: 16,
      padding: '14px 10px 10px',
      boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
    },
    children: [
      isPlaceholder
        ? { type: 'div', props: { style: { fontSize: size === '100%' ? 48 : 28, opacity: 0.25, marginBottom: 6 }, children: emoji || '👕' } }
        : { type: 'div', props: { style: { width: '85%', height: 60, background: 'linear-gradient(145deg, ' + bg + ', #FFFFFF)', borderRadius: 10, border: '1px solid rgba(0,0,0,0.04)' } } },
      { type: 'div', props: { style: { fontSize: 11, color: '#555', marginTop: 8, fontWeight: 500 }, children: name } },
      subtitle ? { type: 'div', props: { style: { fontSize: 9, color: '#AAA', marginTop: 1 }, children: subtitle } } : null,
    ].filter(Boolean)
  }
});

const element = {
  type: 'div',
  props: {
    style: {
      display: 'flex',
      flexDirection: 'column',
      width: '100%',
      height: '100%',
      background: '#FFFFFF',
      fontFamily: 'DejaVu',
    },
    children: [
      // Dark header with weather
      {
        type: 'div',
        props: {
          style: {
            background: 'linear-gradient(135deg, #2C2428 0%, #3D2F38 50%, #2C2830 100%)',
            padding: '16px 24px 14px',
            display: 'flex',
            flexDirection: 'column',
          },
          children: [
            {
              type: 'div',
              props: {
                style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
                children: [
                  { type: 'div', props: { style: { fontSize: 9, letterSpacing: 2, color: '#C8A8B0' }, children: 'LOOK OF THE DAY' } },
                  { type: 'div', props: { style: { display: 'flex', alignItems: 'center', gap: 4 }, children: [
                    { type: 'div', props: { style: { fontSize: 12, color: '#A8C8D0' }, children: '❄️' } },
                    { type: 'div', props: { style: { fontSize: 13, color: '#A8C8D0', fontWeight: 500 }, children: '+4°C' } },
                  ] } },
                ]
              }
            },
            { type: 'div', props: { style: { fontSize: 20, fontWeight: 700, color: '#FFFFFF', marginTop: 6 }, children: 'Алиса' } },
            { type: 'div', props: { style: { fontSize: 11, color: '#A08890', marginTop: 2 }, children: 'Четверг, 20 марта · садик' } },
          ]
        }
      },

      // Content area with soft background
      {
        type: 'div',
        props: {
          style: {
            display: 'flex',
            flexDirection: 'column',
            padding: '16px',
            gap: 12,
            flex: 1,
            background: 'linear-gradient(180deg, #F8F6F4 0%, #FDFCFB 100%)',
          },
          children: [
            // Hero outerwear
            {
              type: 'div',
              props: {
                style: {
                  display: 'flex',
                  justifyContent: 'center',
                },
                children: [card('Куртка', null, '#EDE8F5', '70%', true, '🧥')]
              }
            },

            // Top + Bottom row
            {
              type: 'div',
              props: {
                style: { display: 'flex', gap: 10 },
                children: [
                  { type: 'div', props: { style: { flex: 1, display: 'flex' }, children: [card('Лонгслив', 'белый с цветочн.', '#FFF5E8', '100%', false, null)] } },
                  { type: 'div', props: { style: { flex: 1, display: 'flex' }, children: [card('Юбка', 'клетка серо-зелёная', '#EEF3E8', '100%', false, null)] } },
                ]
              }
            },

            // Footwear + hat + base row
            {
              type: 'div',
              props: {
                style: { display: 'flex', gap: 10 },
                children: [
                  { type: 'div', props: { style: { flex: 1, display: 'flex' }, children: [card('Ботинки', null, '#F0EEEC', '100%', true, '👟')] } },
                  { type: 'div', props: { style: { flex: 1, display: 'flex' }, children: [card('Шапка', null, '#F5EEF2', '100%', true, '🧢')] } },
                  { type: 'div', props: { style: { flex: 1, display: 'flex' }, children: [card('Колготки', 'серый', '#EDEDEB', '100%', false, null)] } },
                ]
              }
            },
          ]
        }
      },

      // Palette footer
      {
        type: 'div',
        props: {
          style: {
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '10px 24px',
            borderTop: '0.5px solid #E8E4E0',
          },
          children: [
            { type: 'div', props: { style: { fontSize: 8, color: '#BBB', letterSpacing: 1 }, children: 'ПАЛИТРА' } },
            ...['#D4A0A0', '#8B9E7C', '#C4B8A0', '#A0B4C4'].map(c => ({
              type: 'div', props: { style: { width: 12, height: 12, borderRadius: '50%', background: c } }
            })),
            { type: 'div', props: { style: { flex: 1 } } },
            { type: 'div', props: { style: { fontSize: 8, color: '#CCC' }, children: 'Касси — твой личный стилист' } },
          ]
        }
      },
    ]
  }
};

const svg = await satori(element, {
  width: 440,
  height: 620,
  fonts: [{ name: 'DejaVu', data: font, weight: 400, style: 'normal' }],
});

const resvg = new Resvg(svg);
const png = resvg.render().asPng();
writeFileSync('collage_v2.png', png);
console.log('V2 collage: ' + png.length + ' bytes');
