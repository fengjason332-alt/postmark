// SVG markup for the home swatch and the city stamps: patches of gouache with a serif name.

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

// Repeat visits show as extra swatches peeking out from under the first.
export function postmark(city, color) {
  const name = city.name.length > 11 ? city.name.split(' ')[0] : city.name
  const size = Math.max(11, Math.min(19, 120 / name.length))
  const year = city.visits[0].arrive.slice(0, 4)
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
