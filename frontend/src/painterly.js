// Turns a photo into a small gouache-style painting, entirely in the browser:
// soften, cut into a handful of flat colour masses, push them toward a muted
// palette, add brush texture and a ragged painted edge on cream paper.
// Nothing leaves the device; results are cached per image URL.
import { useEffect, useState } from 'react'

const cache = new Map() // src -> Promise<dataURL>
const MAX = 520 // longest side of the painting, in pixels
const COLOURS = 7 // colour masses per painting
const PAPER = [243, 239, 231]
// Muted pigments that every mass is pulled toward a little.
const PIGMENTS = [
  [52, 85, 122], [168, 71, 58], [184, 134, 42], [79, 107, 82],
  [47, 58, 69], [216, 196, 160], [140, 160, 182], [236, 228, 212],
]

export function paint(src) {
  if (!cache.has(src)) cache.set(src, load(src).then(render))
  return cache.get(src)
}

// React helper: the painted data URL, or null while it is still being made.
export function usePainting(src, enabled = true) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    if (!enabled) return undefined
    let live = true
    paint(src).then((u) => live && setUrl(u)).catch(() => live && setUrl(src))
    return () => { live = false }
  }, [src, enabled])
  return url
}

function load(src) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

function rand(seed) {
  let s = seed % 2147483647 || 1
  return () => ((s = (s * 16807) % 2147483647) / 2147483647)
}

// Cheap smooth noise: random values on a coarse grid that wraps, bilinearly interpolated.
function noiseField(w, h, cell, r) {
  const gw = Math.ceil(w / cell) + 1
  const gh = Math.ceil(h / cell) + 1
  const grid = Float32Array.from({ length: gw * gh }, () => r())
  const at = (ix, iy) => grid[(iy % gh) * gw + (ix % gw)]
  return (x, y) => {
    const gx = Math.abs(x) / cell
    const gy = Math.abs(y) / cell
    const ix = gx | 0
    const iy = gy | 0
    const fx = gx - ix
    const fy = gy - iy
    const a = at(ix, iy)
    const b = at(ix + 1, iy)
    const c = at(ix, iy + 1)
    const d = at(ix + 1, iy + 1)
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy
  }
}

function render(img) {
  const scale = Math.min(1, MAX / Math.max(img.naturalWidth, img.naturalHeight))
  const w = Math.max(8, Math.round(img.naturalWidth * scale))
  const h = Math.max(8, Math.round(img.naturalHeight * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d', { willReadFrequently: true })

  // Soften: draw small then scale back up, which blurs without ctx.filter (Safari lacks it).
  const small = document.createElement('canvas')
  small.width = Math.max(4, Math.round(w / 5))
  small.height = Math.max(4, Math.round(h / 5))
  const sctx = small.getContext('2d')
  sctx.imageSmoothingQuality = 'high'
  sctx.drawImage(img, 0, 0, small.width, small.height)
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(small, 0, 0, w, h)
  const data = ctx.getImageData(0, 0, w, h)
  const px = data.data
  const n = w * h

  const centres = kmeans(px, n, COLOURS)
  // Pull each mass toward its nearest pigment and calm the saturation a little.
  for (const c of centres) {
    const p = nearest(PIGMENTS, c)
    const grey = (c[0] + c[1] + c[2]) / 3
    for (let k = 0; k < 3; k++) c[k] = (c[k] * 0.8 + grey * 0.2) * 0.72 + PIGMENTS[p][k] * 0.28
  }

  // Assign every pixel to a mass, then a majority filter to merge specks into shapes.
  let labels = new Uint8Array(n)
  for (let i = 0; i < n; i++) labels[i] = nearest(centres, [px[i * 4], px[i * 4 + 1], px[i * 4 + 2]])
  for (let pass = 0; pass < 3; pass++) labels = majority(labels, w, h, centres.length, 3)

  const r = rand(w * 7919 + h)
  const strokes = noiseField(w, h, 3, r) // fine brush streaks
  const mottle = noiseField(w, h, 26, r) // uneven paint load
  const edge = noiseField(w, h, 9, r) // ragged painted border
  const margin = Math.round(Math.min(w, h) * 0.035)

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x
      const c = centres[labels[i]]
      // Streaks run mostly sideways, like a flat brush pulled across the paper.
      const streak = (strokes(x * 0.35, y * 1.6) - 0.5) * 18 + (mottle(x, y) - 0.5) * 22
      // Paint pools a touch darker where two masses meet.
      const border = (x > 0 && labels[i - 1] !== labels[i]) || (y > 0 && labels[i - w] !== labels[i]) ? -10 : 0
      const d = Math.min(x, y, w - 1 - x, h - 1 - y)
      const ragged = (d - margin - (edge(x, y) - 0.5) * margin * 1.8) / 3
      const alpha = Math.max(0, Math.min(1, ragged)) * (0.9 + mottle(y, x) * 0.1)
      const grain = (r() - 0.5) * 10
      for (let k = 0; k < 3; k++) {
        const paintV = c[k] + streak + border + grain
        px[i * 4 + k] = paintV * alpha + PAPER[k] * (1 - alpha)
      }
      px[i * 4 + 3] = 255
    }
  }
  ctx.putImageData(data, 0, 0)
  return canvas.toDataURL('image/jpeg', 0.88)
}

function nearest(list, c) {
  let best = 0
  let bestD = Infinity
  for (let j = 0; j < list.length; j++) {
    const p = list[j]
    const d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2
    if (d < bestD) { bestD = d; best = j }
  }
  return best
}

// A few rounds of k-means on a sample of pixels, seeded across the brightness range.
function kmeans(px, n, k) {
  const step = Math.max(1, Math.floor(n / 4000))
  const sample = []
  for (let i = 0; i < n; i += step) sample.push([px[i * 4], px[i * 4 + 1], px[i * 4 + 2]])
  sample.sort((a, b) => a[0] + a[1] + a[2] - (b[0] + b[1] + b[2]))
  let centres = Array.from({ length: k }, (_, j) => [...sample[Math.floor(((j + 0.5) / k) * sample.length)]])
  for (let round = 0; round < 6; round++) {
    const sums = centres.map(() => [0, 0, 0, 0])
    for (const s of sample) {
      const j = nearest(centres, s)
      sums[j][0] += s[0]; sums[j][1] += s[1]; sums[j][2] += s[2]; sums[j][3]++
    }
    centres = centres.map((c, j) => (sums[j][3] ? [sums[j][0] / sums[j][3], sums[j][1] / sums[j][3], sums[j][2] / sums[j][3]] : c))
  }
  return centres
}

function majority(labels, w, h, k, radius) {
  const out = new Uint8Array(labels.length)
  const counts = new Uint16Array(k)
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      counts.fill(0)
      for (let dy = -radius; dy <= radius; dy += 1) {
        const yy = Math.min(h - 1, Math.max(0, y + dy))
        for (let dx = -radius; dx <= radius; dx += 1) {
          const xx = Math.min(w - 1, Math.max(0, x + dx))
          counts[labels[yy * w + xx]]++
        }
      }
      let best = labels[y * w + x]
      for (let j = 0; j < k; j++) if (counts[j] > counts[best]) best = j
      out[y * w + x] = best
    }
  }
  return out
}

// A short poetic title for a painting, chosen by the photo's tag and id so it stays stable.
const TITLES = {
  food: ['Where the Table Lingers', 'Bread and Slow Light', 'The Warmth Between Plates'],
  nature: ['Where the Hills Hold Still', 'Green in Repose', 'The Quiet Before Wind'],
  city: ['Where the Streets Hum', 'Corners in Repose', 'Where the Crowd Holds Its Breath'],
  night: ['Where the Lamps Stay On', 'After the Last Train', 'The Hour of Soft Light'],
  museum: ['Where the Walls Remember', 'Rooms That Keep Time', 'Where the Shadow Holds'],
  beach: ['Where the Tide Lingers', 'Hull in Repose', 'Salt and Open Air'],
  other: ['Where the Road Paused', 'Where the Shadow Holds', 'A Small Hour, Kept'],
}

export function paintingTitle(photo) {
  const tag = (photo.tags ?? []).find((t) => TITLES[t]) ?? 'other'
  let h = 0
  for (const ch of photo.id) h = (h * 31 + ch.charCodeAt(0)) | 0
  const list = TITLES[tag]
  return list[Math.abs(h) % list.length]
}
