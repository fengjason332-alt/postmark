// SVG markup for the home swatch (a patch of gouache) and the city stamps (hot-foil badges).

const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

// Dry, ragged paint edges, shared by every stamp on the page.
export const PAINT_FILTER = `
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <filter id="paint-rough" x="-15%" y="-15%" width="130%" height="130%">
    <feTurbulence type="fractalNoise" baseFrequency="0.08 0.35" numOctaves="3" seed="8" result="n"/>
    <feDisplacementMap in="SourceGraphic" in2="n" scale="7" result="d"/>
    <feTurbulence type="fractalNoise" baseFrequency="1.4" numOctaves="1" seed="2" result="g"/>
    <feColorMatrix in="g" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -0.9 1.25" result="dry"/>
    <feComposite in="d" in2="dry" operator="in"/>
  </filter>
  <linearGradient id="foil" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#f6dc93"/><stop offset="0.35" stop-color="#c79a3a"/>
    <stop offset="0.55" stop-color="#fbe9b0"/><stop offset="0.8" stop-color="#a87a26"/><stop offset="1" stop-color="#e9c876"/>
  </linearGradient>
  <radialGradient id="leather" cx="0.42" cy="0.36" r="0.75">
    <stop offset="0" stop-color="#fff" stop-opacity="0.16"/><stop offset="0.7" stop-color="#000" stop-opacity="0"/>
    <stop offset="1" stop-color="#000" stop-opacity="0.32"/>
  </radialGradient>
  <filter id="foil-press" x="-10%" y="-10%" width="120%" height="120%">
    <feDropShadow dx="0" dy="0.5" stdDeviation="0.25" flood-color="#000" flood-opacity="0.55"/>
  </filter>
</svg>`

// A swatch of paint laid with one flat brush, slightly wobbly.
function swatch(color, w = 84, h = 56) {
  const x = (100 - w) / 2
  const y = (100 - h) / 2
  return `<path d="M${x + 3},${y + 4} C${x + w * 0.3},${y - 2} ${x + w * 0.7},${y + 3} ${x + w - 2},${y + 1}
    L${x + w + 1},${y + h - 3} C${x + w * 0.65},${y + h + 2} ${x + w * 0.35},${y + h - 2} ${x - 1},${y + h + 1} Z" fill="${color}"/>`
}

export function homeSeal(city) {
  return `
<svg viewBox="0 0 100 100" class="seal-svg gouache-home" role="img" aria-label="Home: ${esc(city)}">
  <g filter="url(#paint-rough)">${swatch('#a8473a', 78, 46)}</g>
  <text x="50" y="57" text-anchor="middle" font-family="'Cormorant Garamond', Georgia, serif" font-style="italic"
    font-weight="700" font-size="22" fill="#f6f0e4">Home</text>
</svg>`
}

// ---------- city stamps: hot-foil badges ----------
// Each city gets a leather-coloured badge (its trip's colour) pressed with gold foil: a
// landmark for well-known cities, otherwise a motif and badge shape picked from the city's
// name, so every city looks different but always the same. Name on top, country and year below.

const FOIL = 'url(#foil)'

// Landmarks, drawn in a 40×40 box. `L` marks shapes cut back out in the leather colour.
const LANDMARKS = {
  newyork: `<path d="M24 3h2.6v11H24z"/><ellipse cx="25.3" cy="2.6" rx="1.8" ry="2.4"/>
    <path d="M15.6 11.5l1.4-4 1 3.2 1-3.8 1 3.8 1-3.2 1.4 4z"/><circle cx="19" cy="14" r="2.7"/>
    <path d="M15 17h8l2.4 13H12.8z"/><path d="M11 30h16v3H11zM8 33h22v4H8z"/>`,
  paris: `<path d="M19.3 1h1.4l1.8 13h2.6l.6 3h-1.6l5.6 20h-5.2c-1.2-6-3-9-4.5-9s-3.3 3-4.5 9H10.3l5.6-20h-1.6l.6-3h2.6z"/>
    <path d="M14 24.5h12v1.6H14z"/>`,
  london: `<path d="M20 .5l.6 3L26 12H14l5.4-8.5z"/><path d="M15 12h10v26H15z"/>
    <circle cx="20" cy="17.5" r="3.4" L/><path d="M20 15.6v2.2l1.4.8" L/><path d="M17 24h6v1.4h-6zM17 29h6v1.4h-6z" L/>`,
  tokyo: `<circle cx="31" cy="8" r="4.2"/><path d="M2 35l12-20c3-3 9-3 12 0l12 20z"/>
    <path d="M14.2 15c3-3 8.6-3 11.6 0l-2.6 3.6-1.8-2-2 3.2-2-3.2-1.8 2z" L/>`,
  montreal: `<path d="M20 2l2.5 6 3.5-2-1 7 6-4-1 4h6l-4 5 2 2-9 5 1 3-5-1v9h-2v-9l-5 1 1-3-9-5 2-2-4-5h6l-1-4 6 4-1-7 3.5 2z"/>`,
  quebeccity: `<path d="M6 20h28v17H6z"/><path d="M6 14h7v6H6zM5 14l4.5-8 4.5 8z"/><path d="M27 14h7v6h-7zM26 14l4.5-8 4.5 8z"/>
    <path d="M16 10h8v10h-8zM15 10l5-9 5 9z"/><path d="M17.5 37v-6a2.5 2.5 0 015 0v6z" L/>
    <path d="M9 24h2v3H9zM29 24h2v3h-2zM19 13h2v3h-2z" L/>`,
  boston: `<path d="M19.4 3h1.2v4h-1.2z"/><path d="M18 7h4v5h-4z"/><path d="M9 25c0-8 5-13 11-13s11 5 11 13z"/>
    <path d="M5 25h30v3H5z"/><path d="M7 28h3v8H7zM13 28h3v8h-3zM24 28h3v8h-3zM30 28h3v8h-3z"/><path d="M4 36h32v2H4z"/>`,
  providence: `<circle cx="20" cy="5" r="3" fill="none" stroke="${FOIL}" stroke-width="2"/><path d="M19 8h2v26h-2zM12 11h16v2.2H12z"/>
    <path d="M7 24l3-1c1 5 4.6 8.4 10 8.4S29 28 30 23l3 1c-1 7-6 11-13 11S8 31 7 24z"/><path d="M5 25l4-5 2 5zM35 25l-4-5-2 5z"/>`,
  sanfrancisco: `<path d="M9 5h3v31H9zM28 5h3v31h-3z"/><path d="M2 24h36v2.4H2z"/>
    <path d="M10.5 6Q20 26 29.5 6M10.5 6Q6 16 2 21M29.5 6Q34 16 38 21" fill="none" stroke="${FOIL}" stroke-width="1.2"/>
    <path d="M0 33c4-2 8 2 12 0s8 2 12 0 8 2 12 0 4 0 4 0v3H0z"/>`,
  rome: `<path d="M3 13c0-3 34-3 34 0v22H3z"/>
    <path d="M6 18h4v6H6zM12 18h4v6h-4zM18 18h4v6h-4zM24 18h4v6h-4zM30 18h4v6h-4zM6 27h4v8H6zM12 27h4v8h-4zM18 27h4v8h-4zM24 27h4v8h-4zM30 27h4v8h-4z" L/>`,
  beijing: `<path d="M2 14Q20 4 38 14l-3 2.4H5zM8 23q12-6 24 0l-2 2H10z"/><path d="M10 16.4h20v6.6H10zM12 25h16v11H12z"/>
    <path d="M18 29h4v7h-4z" L/><path d="M4 36h32v2H4z"/>`,
  shanghai: `<path d="M19.5 0h1v6h-1z"/><circle cx="20" cy="10" r="3"/><path d="M19 13h2v8h-2z"/><circle cx="20" cy="25" r="5"/>
    <path d="M17 29l-7 9h3l6-8zM23 29l7 9h-3l-6-8zM19 30h2v8h-2z"/>`,
  sydney: `<path d="M5 32C7 20 13 13 21 11c-5 5-7 12-6 21z"/><path d="M14 32c2-9 7-15 14-17-4 4-5 10-4 17z"/>
    <path d="M23 32c2-6 6-10 11-11-3 3-3 7-2 11z"/><path d="M2 32h36v3H2z"/>`,
  losangeles: `<path d="M19 38c0-10 1-19 3-26l2 .5c-2 7-2.6 16-2.6 25.5z"/>
    <path d="M23 12c-4-4-10-4-14-1 5-1 9 0 13 3zM23 12c3-5 9-6 13-4-5 0-9 2-12 5zM23 12c-2-4-6-7-10-7 4 1 7 4 9 8zM23 12c3-3 7-4 11-2-4 0-7 1-10 3z"/>
    <path d="M2 38h36v1.5H2z"/>`,
  seattle: `<path d="M19.6 0h.8v5h-.8z"/><ellipse cx="20" cy="8" rx="9" ry="2.6"/><path d="M14 10h12l-2 2H16z"/>
    <path d="M18.5 12h3l-.5 9 3 17h-2.4L20 26l-1.6 12H16l3-17z"/>`,
  chicago: `<path d="M3 38V22h5v16zM9 38V14h6v24zM16 38V4h2V2h1v2h2v34zM22 38V18h5v20zM28 38V10h6v28zM35 38V24h3v14z"/>`,
  washington: `<path d="M19.4 2h1.2v4h-1.2z"/><path d="M17.5 6h5v5h-5z"/><path d="M12 22c0-7 3.6-11 8-11s8 4 8 11z"/>
    <path d="M10 22h20v3H10zM2 27h36v3H2zM4 30h32v6H4z"/><path d="M8 31h2v5H8zM14 31h2v5h-2zM24 31h2v5h-2zM30 31h2v5h-2z" L/>`,
}
const ALIASES = { newyorkcity: 'newyork', nyc: 'newyork', quebec: 'quebeccity', sf: 'sanfrancisco', washingtondc: 'washington', roma: 'rome' }

// Motifs for every other city.
const MOTIFS = [
  `<path d="M20 1l3 15 15 4-15 4-3 15-3-15-15-4 15-4z"/><path d="M20 10l2 8 8 2-8 2-2 8-2-8-8-2 8-2z" L/>`, // compass
  `<circle cx="20" cy="20" r="7"/>` + Array.from({ length: 12 }, (_, i) => `<path d="M19.2 2h1.6l-.3 7h-1z" transform="rotate(${i * 30} 20 20)"/>`).join(''), // sun
  `<path d="M2 14c4-4 8 4 12 0s8 4 12 0 8 4 12 0v3c-4 4-8-4-12 0s-8-4-12 0-8-4-12 0zM2 22c4-4 8 4 12 0s8 4 12 0 8 4 12 0v3c-4 4-8-4-12 0s-8-4-12 0-8-4-12 0zM2 30c4-4 8 4 12 0s8 4 12 0 8 4 12 0v3c-4 4-8-4-12 0s-8-4-12 0-8-4-12 0z"/>`, // waves
  `<path d="M1 36L13 14l6 9 7-15 13 28z"/><path d="M26 8l-3 6 2-1 1 2 1-2 2 1z" L/>`, // peaks
  `<path d="M20 2l5 12.6 13.4.6-10.4 8.6 3.6 13.2L20 29.6 8.4 37l3.6-13.2L1.6 15.2 15 14.6z"/>`, // star
  `<path d="M20 4c-3 6-3 12 0 16 3-4 3-10 0-16zM20 20c-6-2-11 0-14 4 5 1 10 0 14-4zm0 0c6-2 11 0 14 4-5 1-10 0-14-4zM19 20h2v17h-2z"/>`, // sprig
]

// Leather is the trip colour taken a little deeper, so the gold always stands out.
function deepen(hex, f = 0.72) {
  const n = parseInt(hex.slice(1), 16)
  const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(v * f))
  return `#${c.map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7)
const key = (name) => name.toLowerCase().normalize('NFD').replace(/[^a-z]/g, '')

// Badge outlines in a 100×100 box.
function badge(kind) {
  if (kind === 1) {
    // scalloped edge, like a wax seal
    const pts = []
    for (let i = 0; i < 48; i++) {
      const a = (i / 48) * Math.PI * 2
      const r = i % 2 ? 44 : 47.5
      pts.push(`${(50 + Math.cos(a) * r).toFixed(1)},${(50 + Math.sin(a) * r).toFixed(1)}`)
    }
    return `<polygon points="${pts.join(' ')}"/>`
  }
  if (kind === 2) {
    const pts = []
    for (let i = 0; i < 8; i++) {
      const a = ((i + 0.5) / 8) * Math.PI * 2
      pts.push(`${(50 + Math.cos(a) * 48).toFixed(1)},${(50 + Math.sin(a) * 48).toFixed(1)}`)
    }
    return `<polygon points="${pts.join(' ')}"/>` // octagon
  }
  if (kind === 3) return '<rect x="5" y="5" width="90" height="90" rx="16"/>'
  return '<circle cx="50" cy="50" r="47"/>'
}

export function postmark(city, tripColor) {
  const color = deepen(tripColor)
  const k = ALIASES[key(city.name)] ?? key(city.name)
  const h = hash(k)
  const art = LANDMARKS[k] ?? MOTIFS[h % MOTIFS.length]
  const shape = badge(Math.floor(h / 7) % 4)
  const id = `arc-${h.toString(36)}`
  const name = city.name.toUpperCase()
  const size = Math.max(6, Math.min(10.5, 108 / name.length))
  const spacing = name.length > 9 ? 0.6 : 1.4
  const fit = name.length > 17 ? ' textLength="100" lengthAdjust="spacingAndGlyphs"' : '' // very long names are squeezed onto the arc
  const year = city.visits[0].arrive.slice(0, 4)
  const icon = art.replace(/ L\/>/g, ` fill="${color}"/>`) // cut-outs show the leather through the foil
  // Repeat visits: more badges stacked underneath, slightly turned.
  const under = city.visits.slice(1, 3)
    .map((_, i) => `<g transform="translate(${5 + i * 4} ${6 + i * 4}) rotate(${8 + i * 6} 50 50)" fill="${color}" opacity="${0.55 - i * 0.15}">${shape}</g>`)
    .join('')
  return `
<svg viewBox="-6 -6 116 116" class="postmark-svg foil-stamp" role="img"
  aria-label="${esc(city.name)}: ${city.visits.length} visit(s), ${city.photo_count} photos">
  <defs><path id="${id}" d="M16 50a34 34 0 0 1 68 0"/></defs>
  ${under}
  <g transform="rotate(-4 50 50)">
    <g fill="${color}">${shape}</g>
    <g fill="url(#leather)">${shape}</g>
    <g filter="url(#foil-press)">
      <g fill="none" stroke="${FOIL}" stroke-width="1.4" transform="translate(50 50) scale(0.9) translate(-50 -50)">${shape}</g>
      <circle cx="50" cy="50" r="37" fill="none" stroke="${FOIL}" stroke-width="0.6" stroke-dasharray="1 1.6"/>
      <text font-family="'Cormorant Garamond', Georgia, serif" font-weight="700" font-size="${size}" letter-spacing="${spacing}" fill="${FOIL}">
        <textPath href="#${id}" startOffset="50%" text-anchor="middle"${fit}>${esc(name)}</textPath>
      </text>
      <g fill="${FOIL}" transform="translate(30.5 30) scale(0.975)">${icon}</g>
      <text x="50" y="80" text-anchor="middle" font-family="'Cormorant Garamond', Georgia, serif" font-weight="700"
        font-size="7.5" letter-spacing="2" fill="${FOIL}">${esc(city.country_code ?? '')} · ${year}</text>
    </g>
  </g>
</svg>`
}
