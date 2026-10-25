// Lokta paper: a hand-made Nepali paper texture (deckled edge, cloudy pulp, long fibres,
// specks and the odd pressed petal), drawn once per variant on a canvas and cached.
// Ported from Alan's earlier 晴雨绳 journal.
function rng(seed) {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const hexRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
const cache = {}

function lokta(key, W, H, base, seed, opt = {}) {
  if (cache[key]) return cache[key]
  const c = document.createElement('canvas')
  c.width = W
  c.height = H
  const g = c.getContext('2d')
  const r = rng(seed)
  const [br, bg, bb] = hexRgb(base)
  const light = `rgba(${Math.min(255, br + 46)},${Math.min(255, bg + 42)},${Math.min(255, bb + 36)},`
  const dark = `rgba(${(br * 0.55) | 0},${(bg * 0.5) | 0},${(bb * 0.45) | 0},`
  const ins = opt.inset ?? 9
  // the deckled edge: a slightly wobbly outline a few pixels in from the sheet's edge
  const wob = (t, k) => Math.sin(t * 0.07 + k) * 1.8 + Math.sin(t * 0.023 + k * 2) * 2.4 + (r() - 0.5) * 2.6
  const pts = []
  for (let x = ins; x <= W - ins; x += 4) pts.push([x, ins + wob(x, 1)])
  for (let y = ins; y <= H - ins; y += 4) pts.push([W - ins + wob(y, 2), y])
  for (let x = W - ins; x >= ins; x -= 4) pts.push([x, H - ins + wob(x, 3)])
  for (let y = H - ins; y >= ins; y -= 4) pts.push([ins + wob(y, 4), y])
  const path = new Path2D()
  pts.forEach(([x, y], i) => (i ? path.lineTo(x, y) : path.moveTo(x, y)))
  path.closePath()
  try {
    g.save()
    g.filter = 'blur(1.4px)'
    g.fillStyle = base
    g.fill(path)
    g.restore()
  } catch {
    // older browsers without canvas filters just get a crisp edge
  }
  g.save()
  g.clip(path)
  g.fillStyle = base
  g.fillRect(0, 0, W, H)
  for (let i = 0; i < 36; i++) { // cloudy pulp
    const x = r() * W, y = r() * H, rad = 40 + r() * 200
    const tone = r() > 0.5 ? light : dark
    const gr = g.createRadialGradient(x, y, 0, x, y, rad)
    gr.addColorStop(0, `${tone}${(r() * 0.08).toFixed(3)})`)
    gr.addColorStop(1, `${tone}0)`)
    g.fillStyle = gr
    g.fillRect(x - rad, y - rad, rad * 2, rad * 2)
  }
  const fibres = Math.round((W * H) / 620)
  for (let i = 0; i < fibres; i++) {
    const x = r() * W, y = r() * H, len = 6 + r() ** 2 * 90, ang = r() * Math.PI * 2, bend = (r() - 0.5) * len * 0.7
    const x2 = x + Math.cos(ang) * len, y2 = y + Math.sin(ang) * len
    const mx = (x + x2) / 2 + Math.cos(ang + 1.57) * bend, my = (y + y2) / 2 + Math.sin(ang + 1.57) * bend
    g.strokeStyle = `${r() > 0.42 ? light : dark}${(0.07 + r() * 0.2).toFixed(2)})`
    g.lineWidth = 0.35 + r() * 1.15
    g.beginPath()
    g.moveTo(x, y)
    g.quadraticCurveTo(mx, my, x2, y2)
    g.stroke()
  }
  const specks = Math.round((W * H) / 240)
  for (let i = 0; i < specks; i++) {
    g.fillStyle = `${r() > 0.5 ? light : dark}${(0.05 + r() * 0.13).toFixed(2)})`
    g.fillRect(r() * W, r() * H, 1 + r() * 1.5, 1 + r() * 1.5)
  }
  const bits = Math.round((W * H) / 8000)
  for (let i = 0; i < bits; i++) {
    g.fillStyle = `${dark}${(0.22 + r() * 0.35).toFixed(2)})`
    g.beginPath()
    g.ellipse(r() * W, r() * H, 0.7 + r() * 2.4, 0.4 + r() * 1.2, r() * 3, 0, 6.3)
    g.fill()
  }
  if (opt.petals) {
    const cols = ['rgba(198,132,122,', 'rgba(214,176,90,', 'rgba(140,156,112,', 'rgba(170,120,150,']
    for (let i = 0; i < 18; i++) {
      g.fillStyle = `${cols[i % 4]}${(0.35 + r() * 0.3).toFixed(2)})`
      g.beginPath()
      g.ellipse(r() * W, r() * H, 2 + r() * 5, 1 + r() * 2.4, r() * 3, 0, 6.3)
      g.fill()
    }
  }
  g.restore()
  g.strokeStyle = `${light}.45)`
  g.lineWidth = 1.3
  g.stroke(path)
  return (cache[key] = c.toDataURL('image/png'))
}

const PAGE_BASES = ['#E9DFCA', '#E6DBC4', '#EBE2CF']
// Three page variants (one with pressed petals) so neighbouring pages are not identical.
export const pagePaper = (i) => lokta(`page${i % 3}`, 600, 880, PAGE_BASES[i % 3], 11 + (i % 3) * 7, { petals: i % 3 === 1 })
// A heavier, warmer sheet for the cover and the end paper.
export const coverPaper = () => lokta('cover', 600, 880, '#D8C6A2', 91, { inset: 7 })
