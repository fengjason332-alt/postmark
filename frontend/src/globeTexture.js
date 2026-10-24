// Paints the gouache globe onto an equirectangular canvas.
import { feature } from 'topojson-client'
import world from 'world-atlas/countries-50m.json'
import landTopo from 'world-atlas/land-50m.json'

const W = 4096
const H = 2048

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

// Cream paper, a pale indigo sea laid in broad strokes, and each country as a flat,
// opaque block of muted pigment with dry, ragged edges.
const GOUACHE_LAND = ['#d6b97e', '#c4907c', '#a9b493', '#ded0aa', '#a3b2c2', '#c9a684', '#bab386', '#d3ae98']

export function makeGlobeTexture() {
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
