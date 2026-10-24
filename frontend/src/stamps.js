// SVG markup for the home seal and the city stamps, in each globe style.
import { stampDate } from './data.js'

let uid = 0

const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

// Rough-edged ink, shared by every stamp on the page.
export const INK_FILTER = `
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <filter id="ink-rough" x="-10%" y="-10%" width="120%" height="120%">
    <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="3" result="n"/>
    <feDisplacementMap in="SourceGraphic" in2="n" scale="2.2"/>
    <feComponentTransfer><feFuncA type="table" tableValues="0 0.75 0.95"/></feComponentTransfer>
  </filter>
  <filter id="paint-rough" x="-15%" y="-15%" width="130%" height="130%">
    <feTurbulence type="fractalNoise" baseFrequency="0.08 0.35" numOctaves="3" seed="8" result="n"/>
    <feDisplacementMap in="SourceGraphic" in2="n" scale="7" result="d"/>
    <feTurbulence type="fractalNoise" baseFrequency="1.4" numOctaves="1" seed="2" result="g"/>
    <feColorMatrix in="g" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -0.9 1.25" result="dry"/>
    <feComposite in="d" in2="dry" operator="in"/>
  </filter>
</svg>`

// Gouache style: a swatch of paint laid with one flat brush, slightly wobbly.
function swatch(color, w = 84, h = 56) {
  const x = (100 - w) / 2
  const y = (100 - h) / 2
  return `<path d="M${x + 3},${y + 4} C${x + w * 0.3},${y - 2} ${x + w * 0.7},${y + 3} ${x + w - 2},${y + 1}
    L${x + w + 1},${y + h - 3} C${x + w * 0.65},${y + h + 2} ${x + w * 0.35},${y + h - 2} ${x - 1},${y + h + 1} Z" fill="${color}"/>`
}

function gouacheHome(city) {
  return `
<svg viewBox="0 0 100 100" class="seal-svg gouache-home" role="img" aria-label="Home: ${esc(city)}">
  <g filter="url(#paint-rough)">${swatch('#a8473a', 78, 46)}</g>
  <text x="50" y="57" text-anchor="middle" font-family="'Cormorant Garamond', Georgia, serif" font-style="italic"
    font-weight="700" font-size="22" fill="#f6f0e4">Home</text>
</svg>`
}

function gouacheStamp(city, color) {
  const name = city.name.length > 11 ? city.name.split(' ')[0] : city.name
  const size = Math.max(11, Math.min(19, 120 / name.length))
  const year = city.visits[0].arrive.slice(0, 4)
  // Repeat visits show as extra swatches peeking out from under the first, in paler coats.
  const extra = city.visits.slice(1, 3)
    .map((_, i) => `<g transform="translate(${7 + i * 6} ${8 + i * 6}) rotate(${4 + i * 3} 50 50)" opacity="${0.45 - i * 0.1}" filter="url(#paint-rough)">${swatch(color)}</g>`)
    .join('')
  return `
<svg viewBox="-4 -4 116 116" class="postmark-svg gouache-stamp" role="img"
  aria-label="${esc(city.name)}: ${city.visits.length} visit(s), ${city.photo_count} photos">
  ${extra}
  <g transform="rotate(-3 50 50)">
    <g filter="url(#paint-rough)">${swatch(color)}</g>
    <text x="50" y="${52 + size * 0.15}" text-anchor="middle" font-family="'Cormorant Garamond', Georgia, serif"
      font-style="italic" font-weight="700" font-size="${size}" fill="#f6f0e4">${esc(name)}</text>
    <text x="50" y="68" text-anchor="middle" font-family="'Cormorant Garamond', Georgia, serif"
      font-size="8.5" letter-spacing="2.5" fill="#f6f0e4" opacity="0.85">${year}</text>
  </g>
</svg>`
}

// A square vermilion chop reading HO/ME, the way a name seal is cut in two columns.
export function homeSeal(city, style = 'journal') {
  if (style === 'gouache') return gouacheHome(city)
  return `
<svg viewBox="0 0 64 64" class="seal-svg" role="img" aria-label="Home: ${esc(city)}">
  <g filter="url(#ink-rough)">
    <rect x="4" y="4" width="56" height="56" rx="6" fill="#c23b22"/>
    <rect x="9" y="9" width="46" height="46" rx="3" fill="none" stroke="#fbf3e6" stroke-width="2"/>
    <text text-anchor="middle" font-family="Fraunces, Georgia, serif" font-weight="700" font-size="17"
      letter-spacing="1" fill="#fbf3e6"><tspan x="32" y="30">HO</tspan><tspan x="32" y="48">ME</tspan></text>
  </g>
</svg>`
}

// Ink-wash style: each city is a small red seal with the name cut in white, the way
// collectors stamp a painting. Repeat visits add more seals beside it.
function citySeal(city) {
  const name = city.name.toUpperCase()
  const words = name.length > 9 && name.includes(' ') ? name.split(' ') : [name]
  const size = Math.max(9, Math.min(15, 70 / Math.max(...words.map((w) => w.length))))
  const lines = words
    .map((w, i) => `<tspan x="50" dy="${i === 0 ? 0 : size * 1.05}">${esc(w)}</tspan>`)
    .join('')
  const y = 50 - ((words.length - 1) * size * 1.05) / 2 + size * 0.35 - 6
  const year = city.visits[0].arrive.slice(0, 4)
  const seal = (dx, dy, rot, opacity) => `
  <g transform="translate(${dx} ${dy}) rotate(${rot} 50 50)" opacity="${opacity}" filter="url(#ink-rough)">
    <rect x="12" y="16" width="76" height="68" rx="9" fill="#b8321f"/>
    <rect x="17" y="21" width="66" height="58" rx="5" fill="none" stroke="#f6efe2" stroke-width="1.6"/>
    <text text-anchor="middle" font-family="'Cormorant Garamond', Georgia, serif" font-weight="700"
      font-size="${size}" letter-spacing="0.5" fill="#f6efe2" y="${y}">${lines}</text>
    <text x="50" y="74" text-anchor="middle" font-family="'Cormorant Garamond', Georgia, serif"
      font-size="9" letter-spacing="2" fill="#f6efe2">${year}</text>
  </g>`
  const extra = city.visits.slice(1, 3).map((_, i) => seal(10 + i * 8, 9 + i * 7, 6 + i * 5, 0.75)).join('')
  return `
<svg viewBox="-4 -4 124 124" class="postmark-svg seal-city" role="img"
  aria-label="${esc(city.name)}: ${city.visits.length} visit(s), ${city.photo_count} photos">
  ${extra}${seal(0, 0, -4, 0.95)}
</svg>`
}

// A cancellation postmark: double ring, city name around the rim, date in the middle.
// Repeat visits are over-stamped with a second, rotated impression.
export function postmark(city, color, style = 'journal') {
  if (style === 'ink') return citySeal(city)
  if (style === 'gouache') return gouacheStamp(city, color)
  const id = `pm-${++uid}`
  const first = city.visits[0]
  const label = `${city.name} · ${city.country}`.toUpperCase()
  const year = first.arrive.slice(0, 4)
  const ring = (rot, opacity) => `
  <g transform="rotate(${rot} 50 50)" opacity="${opacity}" filter="url(#ink-rough)" stroke="${color}" fill="none">
    <circle cx="50" cy="50" r="44" stroke-width="3"/>
    <circle cx="50" cy="50" r="27" stroke-width="1.6"/>
    <text font-family="Fraunces, serif" font-size="10.5" letter-spacing="1.4" fill="${color}" stroke="none">
      <textPath href="#${id}" startOffset="25%" text-anchor="middle">${esc(label)}</textPath>
    </text>
    <text x="50" y="49" text-anchor="middle" font-family="Fraunces, serif" font-size="11" font-weight="600"
      fill="${color}" stroke="none">${stampDate(first.arrive)}</text>
    <text x="50" y="61" text-anchor="middle" font-family="Fraunces, serif" font-size="9" fill="${color}"
      stroke="none">${year}</text>
  </g>`
  const extra = city.visits.slice(1, 3).map((_, i) => ring(-24 + i * 19, 0.55)).join('')
  return `
<svg viewBox="-4 -4 108 108" class="postmark-svg" role="img"
  aria-label="${esc(city.name)}: ${city.visits.length} visit(s), ${city.photo_count} photos">
  <defs><path id="${id}" d="M50,50 m-35.5,0 a35.5,35.5 0 1,1 71,0 a35.5,35.5 0 1,1 -71,0"/></defs>
  ${ring(8, 0.92)}${extra}
</svg>`
}
