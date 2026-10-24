// Paints the watercolour globe onto an equirectangular canvas: washed ocean,
// pigment-pooled countries and a pen-drawn coastline.
import { feature } from 'topojson-client'
import world from 'world-atlas/countries-50m.json'

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
