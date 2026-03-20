import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import { readFileSync, writeFileSync } from 'fs';

const font = readFileSync('./fonts/DejaVuSans.ttf');
const FONTS = [{ name: 'DejaVu', data: font, weight: 400, style: 'normal' }];

const W = 440, H = 620;

// Fake photo placeholder (colored rectangle with border)
const photo = (w, h, bg, radius) => ({
  type: 'div', props: { style: {
    width: w, height: h, background: bg, borderRadius: radius || 10,
    border: '1px solid rgba(0,0,0,0.06)',
  }}
});

const placeholder = (emoji, size) => ({
  type: 'div', props: { style: {
    width: size || 50, height: size || 50, background: 'rgba(0,0,0,0.04)',
    borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: (size || 50) * 0.5, color: 'rgba(0,0,0,0.15)',
  }, children: emoji }
});

// ═══════════════════════════════════════
// STYLE 1: STORY CARD (Instagram Story)
// ═══════════════════════════════════════
const storyCard = {
  type: 'div', props: { style: {
    display: 'flex', flexDirection: 'column', width: '100%', height: '100%',
    background: 'linear-gradient(160deg, #F5E6F0 0%, #E8D8F0 30%, #D8E8F0 60%, #E8F0E8 100%)',
    fontFamily: 'DejaVu', padding: '24px 20px',
  }, children: [
    // Top: temp + context
    { type: 'div', props: { style: {
      display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16,
    }, children: [
      { type: 'div', props: { style: { fontSize: 12, color: 'rgba(0,0,0,0.4)' }, children: 'Четверг · садик' }},
      { type: 'div', props: { style: { fontSize: 14, color: 'rgba(0,0,0,0.5)', fontWeight: 700 }, children: '+4\u00B0C' }},
    ]}},
    // Hero outfit item
    { type: 'div', props: { style: {
      display: 'flex', justifyContent: 'center', marginBottom: 16,
    }, children: [
      { type: 'div', props: { style: {
        width: 200, height: 180, background: 'rgba(255,255,255,0.6)', borderRadius: 20,
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        boxShadow: '0 8px 32px rgba(0,0,0,0.08)',
      }, children: [
        photo(120, 100, 'linear-gradient(135deg, #E8D0F0, #F0D0E0)', 12),
        { type: 'div', props: { style: { fontSize: 11, color: 'rgba(0,0,0,0.5)', marginTop: 10 }, children: 'Куртка лавандовая' }},
      ]}}
    ]}},
    // Two items
    { type: 'div', props: { style: { display: 'flex', gap: 12, marginBottom: 12 }, children: [
      { type: 'div', props: { style: {
        flex: 1, background: 'rgba(255,255,255,0.5)', borderRadius: 16, padding: '14px 10px',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        boxShadow: '0 4px 16px rgba(0,0,0,0.05)',
      }, children: [
        photo(80, 65, 'linear-gradient(135deg, #F5E8D0, #FFF0E0)', 8),
        { type: 'div', props: { style: { fontSize: 10, color: 'rgba(0,0,0,0.45)', marginTop: 8 }, children: 'Лонгслив' }},
      ]}},
      { type: 'div', props: { style: {
        flex: 1, background: 'rgba(255,255,255,0.5)', borderRadius: 16, padding: '14px 10px',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        boxShadow: '0 4px 16px rgba(0,0,0,0.05)',
      }, children: [
        photo(80, 65, 'linear-gradient(135deg, #D8E8D0, #E8F0E0)', 8),
        { type: 'div', props: { style: { fontSize: 10, color: 'rgba(0,0,0,0.45)', marginTop: 8 }, children: 'Юбка клетка' }},
      ]}},
    ]}},
    // Small items row
    { type: 'div', props: { style: { display: 'flex', gap: 10, marginBottom: 16 }, children: [
      { type: 'div', props: { style: {
        flex: 1, background: 'rgba(255,255,255,0.35)', borderRadius: 12, padding: '10px 6px',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
      }, children: [
        placeholder('B', 32),
        { type: 'div', props: { style: { fontSize: 9, color: 'rgba(0,0,0,0.35)', marginTop: 4 }, children: 'Ботинки' }},
      ]}},
      { type: 'div', props: { style: {
        flex: 1, background: 'rgba(255,255,255,0.35)', borderRadius: 12, padding: '10px 6px',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
      }, children: [
        placeholder('S', 32),
        { type: 'div', props: { style: { fontSize: 9, color: 'rgba(0,0,0,0.35)', marginTop: 4 }, children: 'Шапка' }},
      ]}},
      { type: 'div', props: { style: {
        flex: 1, background: 'rgba(255,255,255,0.35)', borderRadius: 12, padding: '10px 6px',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
      }, children: [
        photo(40, 35, '#E8E6E4', 6),
        { type: 'div', props: { style: { fontSize: 9, color: 'rgba(0,0,0,0.35)', marginTop: 4 }, children: 'Колготки' }},
      ]}},
    ]}},
    // Spacer
    { type: 'div', props: { style: { flex: 1 } }},
    // Bottom: name + kassi
    { type: 'div', props: { style: { display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
      { type: 'div', props: { style: { fontSize: 18, fontWeight: 700, color: 'rgba(0,0,0,0.6)' }, children: 'Алиса' }},
      { type: 'div', props: { style: { fontSize: 10, color: 'rgba(0,0,0,0.3)', marginTop: 4 }, children: 'Касси · твой личный стилист' }},
    ]}},
  ]}
};

// ═══════════════════════════════════════
// STYLE 2: POLAROID
// ═══════════════════════════════════════
const polaroidCard = (name, bg, w, h, rot) => ({
  type: 'div', props: { style: {
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    background: '#FFFFFF', borderRadius: 4, padding: '8px 8px 24px',
    boxShadow: '0 3px 16px rgba(0,0,0,0.1)',
    width: w, transform: `rotate(${rot}deg)`,
  }, children: [
    photo(w - 16, h, bg, 2),
    { type: 'div', props: { style: { fontSize: 10, color: '#888', marginTop: 8 }, children: name }},
  ]}
});

const polaroid = {
  type: 'div', props: { style: {
    display: 'flex', flexDirection: 'column', width: '100%', height: '100%',
    background: '#F5F0EB', fontFamily: 'DejaVu', padding: '20px',
  }, children: [
    // Header handwritten style
    { type: 'div', props: { style: {
      display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 20,
    }, children: [
      { type: 'div', props: { style: { fontSize: 16, color: '#8B7B6B', fontWeight: 700 }, children: 'Алиса, садик' }},
      { type: 'div', props: { style: { fontSize: 12, color: '#B8A898' }, children: 'чт, +4\u00B0C' }},
    ]}},
    // Polaroids scattered
    { type: 'div', props: { style: { display: 'flex', justifyContent: 'center', marginBottom: 12 }, children: [
      polaroidCard('Куртка', 'linear-gradient(135deg, #E8D0F0, #F0D8E8)', 160, 120, -2),
    ]}},
    { type: 'div', props: { style: { display: 'flex', gap: 12, justifyContent: 'center', marginBottom: 12 }, children: [
      polaroidCard('Лонгслив', 'linear-gradient(135deg, #F5E8D0, #FFF0E0)', 130, 95, 3),
      polaroidCard('Юбка', 'linear-gradient(135deg, #D8E8D0, #E8F0E0)', 130, 95, -3),
    ]}},
    { type: 'div', props: { style: { display: 'flex', gap: 10, justifyContent: 'center' }, children: [
      polaroidCard('Ботинки', '#ECEAE8', 90, 60, 4),
      polaroidCard('Шапка', '#F0E8EE', 90, 60, -2),
      polaroidCard('Колготки', '#EAEAEA', 90, 60, 5),
    ]}},
    // Footer
    { type: 'div', props: { style: { display: 'flex', justifyContent: 'center', marginTop: 'auto', paddingTop: 16 }, children: [
      { type: 'div', props: { style: { fontSize: 9, color: '#C8B8A8' }, children: 'Касси \u00B7 твой личный стилист' }},
    ]}},
  ]}
};

// ═══════════════════════════════════════
// STYLE 3: EDITORIAL (Magazine cover)
// ═══════════════════════════════════════
const editorial = {
  type: 'div', props: { style: {
    display: 'flex', flexDirection: 'column', width: '100%', height: '100%',
    background: '#FFFFFF', fontFamily: 'DejaVu',
  }, children: [
    // Minimal top bar
    { type: 'div', props: { style: {
      display: 'flex', justifyContent: 'space-between', padding: '14px 24px',
      borderBottom: '0.5px solid #E8E4E0',
    }, children: [
      { type: 'div', props: { style: { fontSize: 9, letterSpacing: 2, color: '#AAA' }, children: 'LOOK OF THE DAY' }},
      { type: 'div', props: { style: { fontSize: 9, color: '#AAA' }, children: 'Четверг +4\u00B0C' }},
    ]}},
    // HERO item - 55% of space
    { type: 'div', props: { style: {
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      flex: 1, background: '#F8F5FA', padding: '20px',
    }, children: [
      photo(200, 180, 'linear-gradient(135deg, #E8D0F0, #F0D8E8)', 12),
      { type: 'div', props: { style: { fontSize: 14, color: '#555', marginTop: 14, fontWeight: 700 }, children: 'Куртка лавандовая' }},
    ]}},
    // Quote / Haiku description
    { type: 'div', props: { style: {
      display: 'flex', justifyContent: 'center', padding: '14px 30px',
      background: '#FAFAF8', borderTop: '0.5px solid #E8E4E0', borderBottom: '0.5px solid #E8E4E0',
    }, children: [
      { type: 'div', props: { style: {
        fontSize: 12, color: '#888', textAlign: 'center', lineHeight: 1.5,
      }, children: 'Теплый уютный образ для садика. Клетка + цветочный принт = стильный микс' }},
    ]}},
    // Strip of small items
    { type: 'div', props: { style: {
      display: 'flex', padding: '12px 16px', gap: 8,
    }, children: [
      { type: 'div', props: { style: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
        photo(52, 44, '#FFF5E8', 6),
        { type: 'div', props: { style: { fontSize: 8, color: '#AAA', marginTop: 4 }, children: 'Лонгслив' }},
      ]}},
      { type: 'div', props: { style: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
        photo(52, 44, '#EEF3E8', 6),
        { type: 'div', props: { style: { fontSize: 8, color: '#AAA', marginTop: 4 }, children: 'Юбка' }},
      ]}},
      { type: 'div', props: { style: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
        placeholder('B', 28),
        { type: 'div', props: { style: { fontSize: 8, color: '#AAA', marginTop: 4 }, children: 'Ботинки' }},
      ]}},
      { type: 'div', props: { style: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
        placeholder('S', 28),
        { type: 'div', props: { style: { fontSize: 8, color: '#AAA', marginTop: 4 }, children: 'Шапка' }},
      ]}},
      { type: 'div', props: { style: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
        photo(40, 36, '#EAEAEA', 6),
        { type: 'div', props: { style: { fontSize: 8, color: '#AAA', marginTop: 4 }, children: 'Колготки' }},
      ]}},
    ]}},
    // Footer
    { type: 'div', props: { style: {
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '10px 24px', borderTop: '0.5px solid #E8E4E0',
    }, children: [
      { type: 'div', props: { style: { fontSize: 14, fontWeight: 700, color: '#333' }, children: 'Алиса' }},
      { type: 'div', props: { style: { fontSize: 9, color: '#CCC' }, children: 'Касси' }},
    ]}},
  ]}
};

// ═══════════════════════════════════════
// STYLE 4: PALETTE FIRST
// ═══════════════════════════════════════
const colors = ['#D4A0A0', '#8B9E7C', '#C4B8A0', '#E8D0F0'];
const colorNames = ['Пыльный розовый', 'Серо-зелёный', 'Бежевый', 'Лавандовый'];
const colorItems = ['Лонгслив', 'Юбка', 'Колготки', 'Куртка'];

const paletteFirst = {
  type: 'div', props: { style: {
    display: 'flex', flexDirection: 'column', width: '100%', height: '100%',
    background: '#FAFAF8', fontFamily: 'DejaVu',
  }, children: [
    // Header
    { type: 'div', props: { style: {
      display: 'flex', flexDirection: 'column', padding: '20px 24px 16px',
    }, children: [
      { type: 'div', props: { style: { fontSize: 9, letterSpacing: 2, color: '#AAA' }, children: 'ПАЛИТРА ДНЯ' }},
      { type: 'div', props: { style: { fontSize: 16, fontWeight: 700, color: '#444', marginTop: 4 }, children: 'Алиса · садик · +4\u00B0C' }},
    ]}},
    // Big color blocks
    { type: 'div', props: { style: {
      display: 'flex', gap: 3, padding: '0 24px', marginBottom: 16,
    }, children: colors.map(c => ({
      type: 'div', props: { style: { flex: 1, height: 48, background: c, borderRadius: 8 }}
    }))}},
    // Items under each color
    { type: 'div', props: { style: {
      display: 'flex', gap: 8, padding: '0 20px', marginBottom: 20,
    }, children: colors.map((c, i) => ({
      type: 'div', props: { style: {
        flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
        background: '#FFFFFF', borderRadius: 12, padding: '12px 4px 10px',
        boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
      }, children: [
        photo(55, 50, c + '40', 8),
        { type: 'div', props: { style: { fontSize: 9, color: '#666', marginTop: 6 }, children: colorItems[i] }},
        { type: 'div', props: { style: { fontSize: 7, color: '#BBB', marginTop: 1 }, children: colorNames[i] }},
      ]}
    }))}},
    // Accessories row
    { type: 'div', props: { style: {
      display: 'flex', gap: 10, padding: '0 24px', marginBottom: 16,
    }, children: [
      { type: 'div', props: { style: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
        placeholder('B', 36), { type: 'div', props: { style: { fontSize: 8, color: '#AAA', marginTop: 4 }, children: 'Ботинки' }},
      ]}},
      { type: 'div', props: { style: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
        placeholder('S', 36), { type: 'div', props: { style: { fontSize: 8, color: '#AAA', marginTop: 4 }, children: 'Шапка' }},
      ]}},
    ]}},
    // Description
    { type: 'div', props: { style: {
      display: 'flex', padding: '12px 24px', background: '#FFFFFF',
      borderTop: '0.5px solid #E8E4E0', borderBottom: '0.5px solid #E8E4E0',
    }, children: [
      { type: 'div', props: { style: { fontSize: 11, color: '#888', lineHeight: 1.5 }, children: 'Гармоничное сочетание теплых тонов: пыльный розовый + зеленый акцент клеткой' }},
    ]}},
    // Footer
    { type: 'div', props: { style: {
      display: 'flex', justifyContent: 'center', padding: '12px', marginTop: 'auto',
    }, children: [
      { type: 'div', props: { style: { fontSize: 9, color: '#CCC' }, children: 'Касси \u00B7 твой личный стилист' }},
    ]}},
  ]}
};

// ═══════════════════════════════════════
// STYLE 5: MAGAZINE (v2 - dark header)
// ═══════════════════════════════════════
const magazineV2 = {
  type: 'div', props: { style: {
    display: 'flex', flexDirection: 'column', width: '100%', height: '100%',
    background: '#FFFFFF', fontFamily: 'DejaVu',
  }, children: [
    // Dark header
    { type: 'div', props: { style: {
      display: 'flex', flexDirection: 'column',
      background: 'linear-gradient(135deg, #2C2428 0%, #3D2F38 100%)',
      padding: '16px 24px 14px',
    }, children: [
      { type: 'div', props: { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' }, children: [
        { type: 'div', props: { style: { fontSize: 9, letterSpacing: 2, color: '#C8A8B0' }, children: 'LOOK OF THE DAY' }},
        { type: 'div', props: { style: { fontSize: 13, color: '#A8C8D0' }, children: '+4\u00B0C' }},
      ]}},
      { type: 'div', props: { style: { fontSize: 20, fontWeight: 700, color: '#FFFFFF', marginTop: 6 }, children: 'Алиса' }},
      { type: 'div', props: { style: { fontSize: 11, color: '#A08890', marginTop: 2 }, children: 'Четверг, 20 марта \u00B7 садик' }},
    ]}},
    // Content
    { type: 'div', props: { style: {
      display: 'flex', flexDirection: 'column', padding: '16px', gap: 10, flex: 1,
      background: 'linear-gradient(180deg, #F8F6F4 0%, #FDFCFB 100%)',
    }, children: [
      // Hero
      { type: 'div', props: { style: { display: 'flex', justifyContent: 'center' }, children: [
        { type: 'div', props: { style: {
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          background: '#EDE8F5', borderRadius: 16, padding: '20px 40px 14px',
          boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
        }, children: [
          photo(120, 100, 'linear-gradient(135deg, #D8C8E8, #E8D8F0)', 10),
          { type: 'div', props: { style: { fontSize: 12, color: '#7B6FA8', marginTop: 10 }, children: 'Куртка' }},
        ]}}
      ]}},
      // Two items
      { type: 'div', props: { style: { display: 'flex', gap: 10 }, children: [
        { type: 'div', props: { style: {
          flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
          background: '#FFF5E8', borderRadius: 16, padding: '14px 8px 10px',
          boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
        }, children: [
          photo(80, 65, 'linear-gradient(135deg, #F0DCC0, #FFF0D8)', 8),
          { type: 'div', props: { style: { fontSize: 11, color: '#555', marginTop: 8 }, children: 'Лонгслив' }},
          { type: 'div', props: { style: { fontSize: 8, color: '#AAA' }, children: 'белый с цветочн.' }},
        ]}},
        { type: 'div', props: { style: {
          flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
          background: '#EEF3E8', borderRadius: 16, padding: '14px 8px 10px',
          boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
        }, children: [
          photo(80, 65, 'linear-gradient(135deg, #C8D8C0, #D8E8D0)', 8),
          { type: 'div', props: { style: { fontSize: 11, color: '#555', marginTop: 8 }, children: 'Юбка' }},
          { type: 'div', props: { style: { fontSize: 8, color: '#AAA' }, children: 'клетка серо-зелёная' }},
        ]}},
      ]}},
      // Three small items
      { type: 'div', props: { style: { display: 'flex', gap: 10 }, children: [
        { type: 'div', props: { style: {
          flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
          background: '#F0EEEC', borderRadius: 14, padding: '10px 6px 8px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
        }, children: [
          placeholder('B', 30),
          { type: 'div', props: { style: { fontSize: 9, color: '#999', marginTop: 4 }, children: 'Ботинки' }},
        ]}},
        { type: 'div', props: { style: {
          flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
          background: '#F5EEF2', borderRadius: 14, padding: '10px 6px 8px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
        }, children: [
          placeholder('S', 30),
          { type: 'div', props: { style: { fontSize: 9, color: '#999', marginTop: 4 }, children: 'Шапка' }},
        ]}},
        { type: 'div', props: { style: {
          flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
          background: '#EDEDEB', borderRadius: 14, padding: '10px 6px 8px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
        }, children: [
          photo(40, 35, '#E0DEDD', 6),
          { type: 'div', props: { style: { fontSize: 9, color: '#999', marginTop: 4 }, children: 'Колготки' }},
        ]}},
      ]}},
    ]}},
    // Palette footer
    { type: 'div', props: { style: {
      display: 'flex', alignItems: 'center', gap: 6, padding: '10px 24px',
      borderTop: '0.5px solid #E8E4E0',
    }, children: [
      { type: 'div', props: { style: { fontSize: 8, color: '#BBB', letterSpacing: 1 }, children: 'ПАЛИТРА' }},
      ...['#D4A0A0', '#8B9E7C', '#C4B8A0', '#E8D0F0'].map(c => ({
        type: 'div', props: { style: { width: 12, height: 12, borderRadius: '50%', background: c }}
      })),
      { type: 'div', props: { style: { flex: 1 }}},
      { type: 'div', props: { style: { fontSize: 8, color: '#CCC' }, children: 'Касси' }},
    ]}},
  ]}
};

// ═══════════════════════════════════════
// STYLE 6: PRO STYLIST (Polyvore/Flat lay)
// ═══════════════════════════════════════
const proStylist = {
  type: 'div', props: { style: {
    display: 'flex', flexDirection: 'column', width: '100%', height: '100%',
    background: '#FFFFFF', fontFamily: 'DejaVu', padding: '20px',
  }, children: [
    // Minimal header
    { type: 'div', props: { style: {
      display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      marginBottom: 20, paddingBottom: 10, borderBottom: '1px solid #F0F0F0',
    }, children: [
      { type: 'div', props: { style: { fontSize: 14, fontWeight: 700, color: '#333' }, children: 'Алиса · садик' }},
      { type: 'div', props: { style: { fontSize: 11, color: '#CCC' }, children: 'чт +4\u00B0C' }},
    ]}},
    // Main composition - overlapping style
    { type: 'div', props: { style: {
      display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, gap: 6,
    }, children: [
      // Outerwear - centered, large
      { type: 'div', props: { style: { display: 'flex', justifyContent: 'center', marginBottom: 4 }, children: [
        photo(180, 150, 'linear-gradient(135deg, #E8D0F0, #F0D8E8)', 6),
      ]}},
      // Top + Bottom side by side, slightly offset
      { type: 'div', props: { style: { display: 'flex', gap: 16, marginBottom: 4 }, children: [
        { type: 'div', props: { style: { display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
          photo(130, 100, 'linear-gradient(135deg, #F5E8D0, #FFF0E0)', 4),
          { type: 'div', props: { style: { fontSize: 9, color: '#BBB', marginTop: 4 }, children: 'Лонгслив' }},
        ]}},
        { type: 'div', props: { style: { display: 'flex', flexDirection: 'column', alignItems: 'center', marginTop: 10 }, children: [
          photo(120, 100, 'linear-gradient(135deg, #D8E8D0, #E8F0E0)', 4),
          { type: 'div', props: { style: { fontSize: 9, color: '#BBB', marginTop: 4 }, children: 'Юбка клетка' }},
        ]}},
      ]}},
      // Accessories in a row
      { type: 'div', props: { style: { display: 'flex', gap: 20, marginTop: 8 }, children: [
        { type: 'div', props: { style: { display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
          placeholder('B', 40), { type: 'div', props: { style: { fontSize: 8, color: '#CCC', marginTop: 3 }, children: 'Ботинки' }},
        ]}},
        { type: 'div', props: { style: { display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
          placeholder('S', 40), { type: 'div', props: { style: { fontSize: 8, color: '#CCC', marginTop: 3 }, children: 'Шапка' }},
        ]}},
        { type: 'div', props: { style: { display: 'flex', flexDirection: 'column', alignItems: 'center' }, children: [
          photo(44, 40, '#E8E6E4', 4), { type: 'div', props: { style: { fontSize: 8, color: '#CCC', marginTop: 3 }, children: 'Колготки' }},
        ]}},
      ]}},
    ]}},
    // Footer line
    { type: 'div', props: { style: {
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      paddingTop: 12, borderTop: '1px solid #F0F0F0', marginTop: 'auto',
    }, children: [
      { type: 'div', props: { style: { display: 'flex', gap: 4 }, children:
        ['#D4A0A0', '#8B9E7C', '#C4B8A0', '#E8D0F0'].map(c => ({
          type: 'div', props: { style: { width: 10, height: 10, borderRadius: '50%', background: c }}
        }))
      }},
      { type: 'div', props: { style: { fontSize: 8, color: '#DDD' }, children: 'Касси' }},
    ]}},
  ]}
};

// ═══════════════════════════════════════
// RENDER ALL
// ═══════════════════════════════════════
const styles = [
  ['story_card', storyCard],
  ['polaroid', polaroid],
  ['editorial', editorial],
  ['palette_first', paletteFirst],
  ['magazine_v2', magazineV2],
  ['pro_stylist', proStylist],
];

for (const [name, el] of styles) {
  try {
    const svg = await satori(el, { width: W, height: H, fonts: FONTS });
    const resvg = new Resvg(svg);
    const png = resvg.render().asPng();
    writeFileSync(`style_${name}.png`, png);
    console.log(`${name}: ${png.length} bytes OK`);
  } catch(e) {
    console.log(`${name}: ERROR ${e.message}`);
  }
}
console.log('ALL DONE');
