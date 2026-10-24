// Zoom-dependent detail: vector borders that sharpen as you zoom in, and city names
// that appear in order of size. Data is loaded lazily so the first paint stays fast.
import { BufferGeometry, Float32BufferAttribute, LineBasicMaterial, LineSegments } from 'three'
import { mesh } from 'topojson-client'
import world from 'world-atlas/countries-50m.json'

const toXYZ = (lat, lng, r) => {
  // Same convention as three-globe's polar2Cartesian.
  const phi = ((90 - lat) * Math.PI) / 180
  const theta = ((90 - lng) * Math.PI) / 180
  return [r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta)]
}

function segments(lines, radius) {
  const pos = []
  for (const line of lines) {
    for (let i = 0; i < line.length - 1; i++) {
      const [lng1, lat1] = line[i]
      const [lng2, lat2] = line[i + 1]
      if (Math.abs(lng1 - lng2) > 180) continue // don't draw across the antimeridian
      pos.push(...toXYZ(lat1, lng1, radius), ...toXYZ(lat2, lng2, radius))
    }
  }
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new Float32BufferAttribute(pos, 3))
  return geometry
}

function lineLayer(lines, radius, color) {
  const material = new LineBasicMaterial({ color, transparent: true, opacity: 0, depthWrite: false })
  const obj = new LineSegments(segments(lines, radius), material)
  obj.renderOrder = 2
  return obj
}

// Builds country borders right away and state/province borders once their data arrives.
export function createBorderLayers(scene, radius, color) {
  const countryLines = mesh(world, world.objects.countries).coordinates
  const countries = lineLayer(countryLines, radius * 1.0006, color)
  scene.add(countries)
  const layers = { countries, states: null }

  import('./geo/admin1-lines.json').then(({ default: data }) => {
    const s = data.scale
    const lines = data.lines.map((flat) => {
      const pts = []
      for (let i = 0; i < flat.length; i += 2) pts.push([flat[i] / s, flat[i + 1] / s])
      return pts
    })
    layers.states = lineLayer(lines, radius * 1.0005, color)
    scene.add(layers.states)
    layers.onReady?.()
  })

  return {
    // Fade borders in as the camera comes closer (altitude is in globe radii).
    setAltitude(alt) {
      countries.material.opacity = clamp01((2.4 - alt) / 1.4) * 0.75
      if (layers.states) layers.states.material.opacity = clamp01((1.3 - alt) / 0.7) * 0.55
    },
    setColor(c) {
      countries.material.color.set(c)
      layers.states?.material.color.set(c)
      layers.pendingColor = c
    },
    onReady(fn) {
      layers.onReady = () => {
        if (layers.pendingColor) layers.states.material.color.set(layers.pendingColor)
        fn()
      }
    },
    dispose() {
      for (const l of [countries, layers.states]) {
        if (!l) continue
        scene.remove(l)
        l.geometry.dispose()
        l.material.dispose()
      }
    },
  }
}

const clamp01 = (v) => Math.max(0, Math.min(1, v))

let cityCache = null
export async function loadCities() {
  if (!cityCache) {
    const { default: data } = await import('./geo/cities.json')
    cityCache = data.cities.map(([name, cc, lat, lng, population]) => ({
      name, country_code: cc, country: data.countries[cc] ?? cc, lat, lng, population,
    }))
  }
  return cityCache
}

// Smallest population shown at each altitude: big cities first, towns only when close.
function minPopulation(alt) {
  if (alt > 1.8) return Infinity
  if (alt > 1.3) return 5e6
  if (alt > 0.9) return 2e6
  if (alt > 0.6) return 8e5
  if (alt > 0.35) return 3e5
  return 1e5
}

const toRad = (d) => (d * Math.PI) / 180
export function angularDistance(a, b) {
  const h =
    Math.sin(toRad(b.lat - a.lat) / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(toRad(b.lng - a.lng) / 2) ** 2
  return (2 * Math.asin(Math.min(1, Math.sqrt(h))) * 180) / Math.PI
}

// City names worth showing for the current view, capped so the page stays smooth.
export function visibleCities(cities, pov, limit = 140) {
  const min = minPopulation(pov.altitude)
  if (min === Infinity) return []
  const reach = Math.min(90, 25 + pov.altitude * 45) // degrees from the view centre
  const out = []
  for (const c of cities) {
    if (c.population < min) break // list is sorted by population
    if (angularDistance(pov, c) < reach) out.push(c)
    if (out.length >= limit) break
  }
  return out
}

export function nearestCity(cities, point) {
  let best = null
  let bestD = Infinity
  for (const c of cities) {
    const d = angularDistance(point, c)
    if (d < bestD) {
      best = c
      bestD = d
    }
  }
  return best
}
