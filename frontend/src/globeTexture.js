// Paints the watercolour globe onto an equirectangular canvas: washed ocean,
// pigment-pooled countries and a pen-drawn coastline.
import { feature } from 'topojson-client'
import world from 'world-atlas/countries-50m.json'
import landTopo from 'world-atlas/land-50m.json'

const W = 4096
const H = 2048
const LAND = ['#e3d2a8', '#d3d9b2', '#e7cfaa', '#cfd8c0', '#ead9b0', '#dcc6a6', '#cbd3ad', '#e4d6b8']
const INK = 'rgba(52, 42, 32, 0.78)'

const x = (lng) => ((lng + 180) / 360) * W
const y = (lat) => ((90 - lat) / 180) * H

function rand(seed) {
  let s = seed
  return () => ((s = (s * 16807) % 2147483647) / 2147483647)
}

// Rings that cross the antimeridian (Russia, Fiji...) are unwrapped so they stay
// continuous, then drawn again one world-width left and right to wrap around.
function tracePolygons(ctx, geometry, dx = 0, dy = 0) {
  const polys = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
  ctx.beginPath()
  for (const shift of [-W, 0, W]) {
    for (const poly of polys) {
      for (const ring of poly) {
        let prev = null
        ring.forEach(([lng, lat], i) => {
          if (prev !== null) {
            while (lng - prev > 180) lng -= 360
            while (lng - prev < -180) lng += 360
          }
          prev = lng
          const px = x(lng) + dx + shift
          const py = y(lat) + dy
          if (i === 0) ctx.moveTo(px, py)
          else ctx.lineTo(px, py)
        })
        ctx.closePath()
      }
    }
  }
}

function grain(ctx, amount, alpha) {
  const r = rand(7)
  for (let i = 0; i < amount; i++) {
    const shade = r() > 0.5 ? 255 : 60
    ctx.fillStyle = `rgba(${shade},${shade},${shade - 10},${alpha * r()})`
    ctx.fillRect(r() * W, r() * H, 1 + r() * 2, 1 + r() * 2)
  }
}

export function makeGlobeTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  const r = rand(42)

  // Ocean: pale paper with soft blue blooms.
  ctx.fillStyle = '#e3ebe7'
  ctx.fillRect(0, 0, W, H)
  for (let i = 0; i < 70; i++) {
    const cx = r() * W
    const cy = H * 0.2 + r() * H * 0.6 // keep blooms off the poles, where they'd pinch into rings
    const rad = 120 + r() * 420
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad)
    // Alternate darker blue pools and paler, paper-white blooms.
    const tone = i % 2 ? '170, 200, 212' : '246, 244, 236'
    g.addColorStop(0, `rgba(${tone}, ${0.2 + r() * 0.25})`)
    g.addColorStop(1, `rgba(${tone}, 0)`)
    ctx.fillStyle = g
    ctx.fillRect(cx - rad, cy - rad, rad * 2, rad * 2)
  }

  // Faint pencil graticule every 30 degrees.
  ctx.strokeStyle = 'rgba(80, 90, 100, 0.13)'
  ctx.lineWidth = 2
  ctx.setLineDash([6, 10])
  for (let lng = -180; lng <= 180; lng += 30) {
    ctx.beginPath(); ctx.moveTo(x(lng), y(75)); ctx.lineTo(x(lng), y(-75)); ctx.stroke()
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    ctx.beginPath(); ctx.moveTo(0, y(lat)); ctx.lineTo(W, y(lat)); ctx.stroke()
  }
  ctx.setLineDash([])

  const countries = feature(world, world.objects.countries).features

  // Land: a few slightly offset translucent washes so pigment pools at the edges.
  countries.forEach((f, i) => {
    if (!f.geometry) return
    const color = LAND[(i * 7) % LAND.length]
    ctx.fillStyle = color
    for (let pass = 0; pass < 3; pass++) {
      ctx.globalAlpha = 0.42
      tracePolygons(ctx, f.geometry, (r() - 0.5) * 5, (r() - 0.5) * 5)
      ctx.fill('evenodd')
    }
    ctx.globalAlpha = 0.35
    ctx.strokeStyle = color
    ctx.lineWidth = 7
    ctx.filter = 'blur(3px) brightness(0.88)'
    tracePolygons(ctx, f.geometry)
    ctx.stroke()
    ctx.filter = 'none'
  })
  ctx.globalAlpha = 1

  // Pen coastline and borders.
  ctx.strokeStyle = INK
  ctx.lineWidth = 1.8
  ctx.lineJoin = 'round'
  countries.forEach((f) => {
    if (!f.geometry) return
    tracePolygons(ctx, f.geometry)
    ctx.stroke()
  })

  grain(ctx, 90000, 0.12)
  return canvas.toDataURL('image/jpeg', 0.9)
}

// Ink-wash (shui-mo) variant: rice paper, land in soft layered grey washes with darker
// ink pooling inland, and a wet brush coastline that bleeds into the paper.
export function makeInkTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  const r = rand(11)
  const land = feature(landTopo, landTopo.objects.land)
  const geometry = land.type === 'FeatureCollection' ? land.features[0].geometry : land.geometry

  // Rice paper with a few drifting bands of mist over the sea.
  ctx.fillStyle = '#f1ede3'
  ctx.fillRect(0, 0, W, H)
  for (let i = 0; i < 26; i++) {
    const cy = H * 0.15 + r() * H * 0.7
    const g = ctx.createLinearGradient(0, cy - 60, 0, cy + 60)
    g.addColorStop(0, 'rgba(120, 128, 130, 0)')
    g.addColorStop(0.5, `rgba(120, 128, 130, ${0.04 + r() * 0.06})`)
    g.addColorStop(1, 'rgba(120, 128, 130, 0)')
    ctx.fillStyle = g
    ctx.fillRect(r() * W - W * 0.2, cy - 60, W * (0.3 + r() * 0.5), 120)
  }

  // Pale first wash that bleeds past the coast.
  ctx.fillStyle = 'rgba(60, 62, 60, 1)'
  ctx.filter = 'blur(10px)'
  for (let pass = 0; pass < 2; pass++) {
    ctx.globalAlpha = 0.09
    tracePolygons(ctx, geometry, (r() - 0.5) * 8, (r() - 0.5) * 8)
    ctx.fill('evenodd')
  }
  ctx.filter = 'none'
  ctx.globalAlpha = 0.1
  tracePolygons(ctx, geometry)
  ctx.fill('evenodd')
  ctx.globalAlpha = 1

  // Ink pooling inside the land: mottled darker blooms, clipped to the coastline.
  ctx.save()
  tracePolygons(ctx, geometry)
  ctx.clip('evenodd')
  for (let i = 0; i < 900; i++) {
    const cx = r() * W
    const cy = H * 0.08 + r() * H * 0.84
    const rad = 10 + r() ** 2 * 140
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad)
    const a = 0.03 + r() * 0.13
    g.addColorStop(0, `rgba(25, 26, 28, ${a})`)
    g.addColorStop(0.6, `rgba(25, 26, 28, ${a * 0.4})`)
    g.addColorStop(1, 'rgba(25, 26, 28, 0)')
    ctx.fillStyle = g
    ctx.fillRect(cx - rad, cy - rad, rad * 2, rad * 2)
  }
  ctx.restore()

  // Coastline: a wet halo, the main stroke, then a broken dry-brush pass.
  ctx.lineJoin = 'round'
  ctx.strokeStyle = 'rgba(20, 20, 20, 0.16)'
  ctx.lineWidth = 6
  ctx.filter = 'blur(3px)'
  tracePolygons(ctx, geometry)
  ctx.stroke()
  ctx.filter = 'none'
  ctx.strokeStyle = 'rgba(18, 18, 18, 0.78)'
  ctx.lineWidth = 1.6
  tracePolygons(ctx, geometry)
  ctx.stroke()
  ctx.strokeStyle = 'rgba(18, 18, 18, 0.3)'
  ctx.lineWidth = 3
  ctx.setLineDash([3, 9, 14, 6, 2, 11])
  tracePolygons(ctx, geometry, 1.5, -1)
  ctx.stroke()
  ctx.setLineDash([])

  // Faint paper fibres.
  ctx.strokeStyle = 'rgba(90, 80, 60, 0.07)'
  ctx.lineWidth = 1
  for (let i = 0; i < 2500; i++) {
    const fx = r() * W
    const fy = r() * H
    const len = 8 + r() * 30
    const ang = r() * Math.PI
    ctx.beginPath()
    ctx.moveTo(fx, fy)
    ctx.quadraticCurveTo(fx + Math.cos(ang) * len * 0.5 + 4, fy + Math.sin(ang) * len * 0.5, fx + Math.cos(ang) * len, fy + Math.sin(ang) * len)
    ctx.stroke()
  }
  grain(ctx, 60000, 0.08)
  return canvas.toDataURL('image/jpeg', 0.9)
}

// Gouache variant: cream paper, a pale indigo sea laid in broad strokes, and each
// country as a flat, opaque block of muted pigment with dry, ragged edges.
const GOUACHE_LAND = ['#d6b97e', '#c4907c', '#a9b493', '#ded0aa', '#a3b2c2', '#c9a684', '#bab386', '#d3ae98']

export function makeGouacheTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  const r = rand(23)

  // Sea: cream paper under a thin indigo wash, then long horizontal brush strokes.
  ctx.fillStyle = '#f1ebdd'
  ctx.fillRect(0, 0, W, H)
  ctx.fillStyle = 'rgba(132, 156, 180, 0.38)'
  ctx.fillRect(0, 0, W, H)
  ctx.lineCap = 'round'
  for (let i = 0; i < 1400; i++) {
    const sy = H * 0.12 + r() * H * 0.76
    const sx = r() * W
    const len = 60 + r() * 260
    const light = r() > 0.5
    ctx.strokeStyle = light ? `rgba(240, 236, 224, ${0.05 + r() * 0.08})` : `rgba(70, 98, 132, ${0.03 + r() * 0.05})`
    ctx.lineWidth = 3 + r() * 9
    ctx.beginPath()
    ctx.moveTo(sx, sy)
    ctx.quadraticCurveTo(sx + len / 2, sy + (r() - 0.5) * 10, sx + len, sy + (r() - 0.5) * 6)
    ctx.stroke()
  }

  const countries = feature(world, world.objects.countries).features

  // Land: an opaque base coat, then a slightly offset dry-brush coat whose dashed
  // edge leaves the ragged rim you get from a half-loaded brush.
  countries.forEach((f, i) => {
    if (!f.geometry) return
    const color = GOUACHE_LAND[(i * 5) % GOUACHE_LAND.length]
    ctx.fillStyle = color
    ctx.globalAlpha = 0.95
    tracePolygons(ctx, f.geometry)
    ctx.fill('evenodd')
    ctx.globalAlpha = 0.5
    ctx.strokeStyle = color
    ctx.lineWidth = 5
    ctx.setLineDash([4 + r() * 6, 3 + r() * 5, 10, 4])
    tracePolygons(ctx, f.geometry, (r() - 0.5) * 3, (r() - 0.5) * 3)
    ctx.stroke()
    ctx.setLineDash([])
  })
  ctx.globalAlpha = 1

  // Brush texture inside the land: short strokes a shade lighter or darker.
  const land = feature(landTopo, landTopo.objects.land)
  const geometry = land.type === 'FeatureCollection' ? land.features[0].geometry : land.geometry
  ctx.save()
  tracePolygons(ctx, geometry)
  ctx.clip('evenodd')
  for (let i = 0; i < 9000; i++) {
    const sx = r() * W
    const sy = r() * H
    const len = 10 + r() * 40
    const ang = -0.4 + r() * 0.8
    ctx.strokeStyle = r() > 0.5 ? `rgba(255, 250, 236, ${0.06 + r() * 0.1})` : `rgba(90, 60, 40, ${0.04 + r() * 0.07})`
    ctx.lineWidth = 3 + r() * 7
    ctx.beginPath()
    ctx.moveTo(sx, sy)
    ctx.lineTo(sx + Math.cos(ang) * len, sy + Math.sin(ang) * len)
    ctx.stroke()
  }
  ctx.restore()

  // A thin charcoal line where land meets sea, drawn lightly so it reads as pencil.
  ctx.lineJoin = 'round'
  ctx.strokeStyle = 'rgba(47, 58, 69, 0.55)'
  ctx.lineWidth = 1.3
  tracePolygons(ctx, geometry)
  ctx.stroke()

  grain(ctx, 110000, 0.1)
  return canvas.toDataURL('image/jpeg', 0.9)
}
