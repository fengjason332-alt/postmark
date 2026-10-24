// SVG markup for the vermilion home seal and the round city postmarks.
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
</svg>`

export function homeSeal(city) {
  return `
<svg viewBox="0 0 64 64" class="seal-svg" role="img" aria-label="Home: ${esc(city)}">
  <g filter="url(#ink-rough)">
    <rect x="4" y="4" width="56" height="56" rx="6" fill="#c23b22"/>
    <rect x="9" y="9" width="46" height="46" rx="3" fill="none" stroke="#fbf3e6" stroke-width="2"/>
    <text x="32" y="43" text-anchor="middle" font-family="'Noto Serif SC', serif" font-weight="700"
      font-size="28" fill="#fbf3e6">家</text>
  </g>
</svg>`
}

// A cancellation postmark: double ring, city name around the rim, date in the middle.
// Repeat visits are over-stamped with a second, rotated impression.
export function postmark(city, color) {
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
