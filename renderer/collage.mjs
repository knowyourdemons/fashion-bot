import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import { readFileSync, writeFileSync } from 'fs';

const font = readFileSync('./fonts/DejaVuSans.ttf');

// Тестовые данные - имитация реального образа
const header = 'Чт, 20 мар · +4°C · Алиса, садик';
const footer = 'Касси — твой личный стилист';
const palette = ['#D4A0A0', '#8B9E7C', '#C4B8A0', '#A0B4C4'];

const slots = [
  { name: 'Куртка', color: '#E8E0F0', hasPhoto: false, zone: 'outerwear' },
  { name: 'Лонгслив белый', color: '#F5E8D0', hasPhoto: true, zone: 'top' },
  { name: 'Юбка клетка', color: '#D8E0D0', hasPhoto: true, zone: 'bottom' },
  { name: 'Ботинки', color: '#E8E4E0', hasPhoto: false, zone: 'footwear' },
  { name: 'Шапка', color: '#F0E0E8', hasPhoto: false, zone: 'accessory' },
  { name: 'Колготки серый', color: '#E8E8E8', hasPhoto: true, zone: 'base' },
];

// Magazine style layout
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
      // Dark header
      {
        type: 'div',
        props: {
          style: {
            background: 'linear-gradient(135deg, #2C2428, #3D2F38)',
            padding: '18px 24px 14px',
            display: 'flex',
            flexDirection: 'column',
          },
          children: [
            { type: 'div', props: { style: { fontSize: 9, letterSpacing: 2, color: '#C8A8B0', textTransform: 'uppercase' }, children: 'LOOK OF THE DAY' } },
            { type: 'div', props: { style: { fontSize: 18, fontWeight: 700, color: '#FFFFFF', marginTop: 4 }, children: 'Алиса, садик' } },
            { type: 'div', props: { style: { fontSize: 11, color: '#A08890', marginTop: 2 }, children: 'Четверг, 20 марта · +4°C' } },
          ]
        }
      },
      // Hero - outerwear
      {
        type: 'div',
        props: {
          style: {
            background: '#F0EDF5',
            padding: '28px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            borderBottom: '0.5px solid #E8E4E0',
          },
          children: [
            { type: 'div', props: { style: { fontSize: 40, opacity: 0.3 }, children: '🧥' } },
            { type: 'div', props: { style: { fontSize: 12, color: '#8B7FA8', marginTop: 8 }, children: 'Куртка' } },
          ]
        }
      },
      // Two items row - top + bottom
      {
        type: 'div',
        props: {
          style: {
            display: 'flex',
            borderBottom: '0.5px solid #E8E4E0',
          },
          children: [
            {
              type: 'div',
              props: {
                style: { flex: 1, padding: '18px', display: 'flex', flexDirection: 'column', alignItems: 'center', borderRight: '0.5px solid #E8E4E0', background: '#FFF8F0' },
                children: [
                  { type: 'div', props: { style: { width: 70, height: 60, background: '#F5E8D0', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: '#B8A080' }, children: 'фото' } },
                  { type: 'div', props: { style: { fontSize: 11, color: '#666', marginTop: 8 }, children: 'Лонгслив' } },
                  { type: 'div', props: { style: { fontSize: 9, color: '#AAA' }, children: 'белый с цветочн.' } },
                ]
              }
            },
            {
              type: 'div',
              props: {
                style: { flex: 1, padding: '18px', display: 'flex', flexDirection: 'column', alignItems: 'center', background: '#F5FAF5' },
                children: [
                  { type: 'div', props: { style: { width: 70, height: 60, background: '#D8E0D0', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: '#8B9E7C' }, children: 'фото' } },
                  { type: 'div', props: { style: { fontSize: 11, color: '#666', marginTop: 8 }, children: 'Юбка' } },
                  { type: 'div', props: { style: { fontSize: 9, color: '#AAA' }, children: 'клетка серо-зелёная' } },
                ]
              }
            },
          ]
        }
      },
      // Small items row - footwear + hat
      {
        type: 'div',
        props: {
          style: { display: 'flex', borderBottom: '0.5px solid #E8E4E0' },
          children: [
            {
              type: 'div',
              props: {
                style: { flex: 1, padding: '12px', display: 'flex', flexDirection: 'column', alignItems: 'center', borderRight: '0.5px solid #E8E4E0' },
                children: [
                  { type: 'div', props: { style: { fontSize: 24, opacity: 0.3 }, children: '👟' } },
                  { type: 'div', props: { style: { fontSize: 10, color: '#999', marginTop: 4 }, children: 'Ботинки' } },
                ]
              }
            },
            {
              type: 'div',
              props: {
                style: { flex: 1, padding: '12px', display: 'flex', flexDirection: 'column', alignItems: 'center', borderRight: '0.5px solid #E8E4E0' },
                children: [
                  { type: 'div', props: { style: { fontSize: 24, opacity: 0.3 }, children: '🧢' } },
                  { type: 'div', props: { style: { fontSize: 10, color: '#999', marginTop: 4 }, children: 'Шапка' } },
                ]
              }
            },
            {
              type: 'div',
              props: {
                style: { flex: 1, padding: '12px', display: 'flex', flexDirection: 'column', alignItems: 'center' },
                children: [
                  { type: 'div', props: { style: { width: 40, height: 40, background: '#E8E8E8', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, color: '#999' }, children: 'фото' } },
                  { type: 'div', props: { style: { fontSize: 10, color: '#999', marginTop: 4 }, children: 'Колготки' } },
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
            gap: 8,
            padding: '10px 24px',
            background: '#FAFAF8',
            marginTop: 'auto',
          },
          children: [
            { type: 'div', props: { style: { fontSize: 9, color: '#AAA', letterSpacing: 1 }, children: 'ПАЛИТРА' } },
            ...palette.map(c => ({
              type: 'div',
              props: { style: { width: 14, height: 14, borderRadius: '50%', background: c } }
            })),
            { type: 'div', props: { style: { flex: 1 } } },
            { type: 'div', props: { style: { fontSize: 9, color: '#BBB' }, children: footer } },
          ]
        }
      },
    ]
  }
};

const svg = await satori(element, {
  width: 440,
  height: 580,
  fonts: [{ name: 'DejaVu', data: font, weight: 400, style: 'normal' }],
});

const resvg = new Resvg(svg);
const png = resvg.render().asPng();
writeFileSync('collage_magazine.png', png);
console.log('Magazine collage: ' + png.length + ' bytes');
