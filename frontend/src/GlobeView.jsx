// The 3D globe: home seal, trip lines drawn one by one, city stamps, and detail
// (borders, city names, clearing fog) that appears as you zoom in.
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import Globe from 'react-globe.gl'
import { MeshPhongMaterial } from 'three'
import { makeGlobeTexture } from './globeTexture.js'
import { homeSeal, postmark } from './stamps.js'
import { BORDER_COLOR, citiesOf, DRAW_MS, distanceKm, PAUSE_MS, tripColor } from './data.js'
import { angularDistance, createBorderLayers, loadCities, visibleCities } from './geoLayers.js'

const TRAVEL_MS = 3200 // the travelling dot's time per leg, pause included
const DOT = 0.07 // the travelling dot's length, as a share of the leg
const FADED = 0.16 // how bright a leg stays once the route has moved on
const isPhone = () => window.innerWidth < 720
let texture = null // painted once, on first use
const hexAlpha = (hex, a) => hex + Math.round(Math.max(0, Math.min(1, a)) * 255).toString(16).padStart(2, '0')

// Fog and blur only appear when the camera is pulled far back: clear at the default view
// and closer, thickening from altitude 2.6 to the zoom-out limit (~5).
function applyFog(el, altitude) {
  if (!el) return // the camera can report in before the wrapper is mounted
  const t = Math.max(0, Math.min(1, (altitude - 2.6) / 2.4))
  // No filter at all when clear: even blur(0px) makes the browser re-composite the canvas every frame.
  el.style.setProperty('--fog-filter', t > 0 ? `blur(${(t * 2.8).toFixed(2)}px)` : 'none')
  el.style.setProperty('--fog-wash', (t * 0.6).toFixed(3))
}

const GlobeView = forwardRef(function GlobeView(
  { trips, home, follow, picking, onPick, onTripClick, onCityClick },
  ref,
) {
  const globe = useRef()
  const wrap = useRef()
  const overlay = useRef()
  const borders = useRef(null)
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight })
  const [tick, setTick] = useState(0) // bumps each animation frame (lines drawing, travelling dots)
  const [labels, setLabels] = useState([])
  const cities = useRef(null)
  const lastLabelPov = useRef(null)
  const globeImage = useMemo(() => (texture ??= makeGlobeTexture()), [])
  const material = useMemo(() => new MeshPhongMaterial({ shininess: 0 }), []) // matte paper, no glare
  const arcCache = useRef(new Map()) // key -> arc datum, kept so existing lines don't redraw
  const stampCache = useRef(new Map()) // city id -> html datum
  const labelCache = useRef(new Map())
  const handlers = useRef({})
  const followRef = useRef(follow)
  followRef.current = follow
  handlers.current = { onCityClick }

  useImperativeHandle(ref, () => ({
    flyTo(trip) {
      const pts = trip.cities
      const lat = pts.reduce((s, c) => s + c.lat, 0) / pts.length
      const lng = pts.reduce((s, c) => s + c.lng, 0) / pts.length
      setRotating(false)
      globe.current.pointOfView({ lat, lng, altitude: 1.5 }, 1400)
    },
    lookAt({ lat, lng }, altitude = 1.2) {
      setRotating(false)
      globe.current.pointOfView({ lat, lng, altitude }, 1200)
    },
    setRotating,
  }))

  // Turn the camera toward a leg: centred between its two ends, pulled back for long hops.
  function followLeg(a) {
    const g = globe.current
    if (!g) return
    setRotating(false)
    const km = distanceKm(a.from, a.to)
    const altitude = Math.min(2.2, Math.max(0.55, 0.45 + km / 2500))
    const lng = a.to.lng + (((a.from.lng - a.to.lng + 540) % 360) - 180) * 0.6
    g.pointOfView({ lat: a.to.lat + (a.from.lat - a.to.lat) * 0.6, lng, altitude }, DRAW_MS)
  }

  function setRotating(on) {
    const controls = globe.current?.controls()
    if (controls) controls.autoRotate = on
  }

  // Keep the canvas filling the window.
  useEffect(() => {
    const ro = new ResizeObserver(() => wrap.current && setSize({ width: wrap.current.clientWidth, height: wrap.current.clientHeight }))
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])

  useEffect(() => () => borders.current?.dispose(), [])


  function onReady() {
    const g = globe.current
    if (!g || borders.current) return // globe.gl can report ready more than once; set up only once
    const controls = g.controls()
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.35
    controls.minDistance = 112 // close enough to read town names
    controls.maxDistance = 600
    controls.zoomSpeed = 0.8
    const altitude = isPhone() ? 3.6 : 2.3
    g.pointOfView({ lat: home.lat - 8, lng: home.lng, altitude }, 0)
    borders.current = createBorderLayers(g.scene(), g.getGlobeRadius(), BORDER_COLOR)
    borders.current.setAltitude(altitude)
    applyFog(wrap.current, altitude)
    loadCities().then((list) => {
      cities.current = list
      onView(g.pointOfView())
    })
  }

  // Called on every camera change (including auto-rotation): fog, borders and pin
  // positions are updated directly; labels re-render only when the view moved enough.
  function onView(pov) {
    applyFog(wrap.current, pov.altitude)
    borders.current?.setAltitude(pov.altitude)
    layoutPins()
    if (!cities.current) return
    const last = lastLabelPov.current
    const moved = !last || Math.abs(last.altitude - pov.altitude) > 0.08 || angularDistance(last, pov) > 4 + pov.altitude * 6
    if (!moved) return
    lastLabelPov.current = pov
    setLabels(visibleCities(cities.current, pov))
  }

  // Arcs per trip, in visit order: home -> first city -> ... -> last city -> home.
  // Legs draw one after another (pausing at each city), and new trips queue behind each
  // other. Once a trip is drawn, a small dot keeps travelling it leg by leg, in order.
  const arcs = useMemo(() => {
    const now = performance.now()
    const next = new Map()
    const homeKey = `${home.lat},${home.lng}`
    let queue = 0 // when the next newly shown trip may start drawing
    for (const trip of trips) {
      const stops = [home, ...trip.cities, home]
      const fresh = !arcCache.current.has(`${homeKey}:${trip.id}:0`)
      const delay = fresh ? queue : 0
      if (fresh) queue += (stops.length - 1) * (DRAW_MS + PAUSE_MS)
      for (let i = 0; i < stops.length - 1; i++) {
        const key = `${homeKey}:${trip.id}:${i}`
        next.set(key, arcCache.current.get(key) ?? {
          key, trip, leg: i, homeward: i === stops.length - 2,
          // Dashes grow from the arc's end, so start/end are swapped to write outward from home.
          from: stops[i + 1], to: stops[i],
          born: now + delay + i * (DRAW_MS + PAUSE_MS), gap: 1,
          legs: stops.length - 1,
          dot: { key: `${key}:dot`, trip, isDot: true, from: stops[i], to: stops[i + 1], offset: 1 },
        })
      }
    }
    arcCache.current = next
    return [...next.values()]
  }, [trips, home])

  // Stamps land when the first line reaching them is finished. Each sits just above a
  // small dot on the city's exact position, so the lines visibly meet the right spot.
  const markers = useMemo(() => {
    const now = performance.now()
    const visited = citiesOf(trips)
    const maxCount = Math.max(1, ...visited.map((c) => c.photo_count))
    const next = new Map()
    for (const city of visited) {
      const first = city.visits[0].trip
      const px = Math.round(34 + 30 * Math.sqrt(city.photo_count / maxCount))
      // Stop number within its first trip, shown when that trip visits several cities.
      const stop = first.cities.length > 1 ? first.cities.findIndex((c) => c.id === city.id) + 1 : 0
      const signature = `${city.visits.length}:${px}:${stop}`
      let d = stampCache.current.get(city.id)
      if (!d || d.signature !== signature) {
        const el = document.createElement('div')
        el.className = 'pin stamp'
        el.style.setProperty('--size', `${px}px`)
        el.style.setProperty('--trip', tripColor(first))
        el.innerHTML = `<i class="pin-dot"></i>`
        const button = document.createElement('button')
        button.className = 'postmark'
        button.innerHTML = postmark(city, tripColor(first)) + (stop ? `<b class="stop-no">${stop}</b>` : '')
        // Listen on the whole pin so a folded stamp's dot is clickable too.
        el.addEventListener('click', (e) => {
          e.stopPropagation()
          handlers.current.onCityClick(el._city)
        })
        el.appendChild(button)
        const arc = arcs.find((a) => a.trip.id === first.id && a.from.id === city.id)
        button.style.animationDelay = `${arc ? Math.max(0, arc.born - now + DRAW_MS * 0.9) : 0}ms`
        d = { key: `stamp:${city.id}`, lat: city.lat, lng: city.lng, el, signature, kind: 'stamp', rank: 1e9 + city.photo_count, w: px, h: px * 0.7 }
      }
      d.el._city = city
      next.set(city.id, d)
    }
    stampCache.current = next
    return [...next.values()]
  }, [trips, arcs])

  const seal = useMemo(() => {
    const el = document.createElement('div')
    el.className = 'pin seal'
    el.title = `Home · ${home.city}`
    el.innerHTML = `<i class="pin-dot"></i><div class="seal-art">${homeSeal(home.city)}</div>`
    return { key: 'home', lat: home.lat, lng: home.lng, el, kind: 'seal', rank: 2e9, w: 46, h: 30 }
  }, [home])

  // Small map labels for nearby cities; visited cities already have a stamp, so skip them.
  const labelData = useMemo(() => {
    const stamped = new Set(markers.map((m) => `${m.lat.toFixed(1)},${m.lng.toFixed(1)}`))
    const next = new Map() // only labels in view are kept, so the cache doesn't grow while panning
    const list = labels
      .filter((c) => !stamped.has(`${c.lat.toFixed(1)},${c.lng.toFixed(1)}`) && Math.abs(c.lat - home.lat) + Math.abs(c.lng - home.lng) > 0.15)
      .map((c) => {
        const key = `${c.name}|${c.lat}|${c.lng}`
        let d = labelCache.current.get(key)
        if (!d) {
          const el = document.createElement('div')
          el.className = `pin city-label ${c.population >= 2e6 ? 'major' : ''}`
          el.innerHTML = `<i></i><span>${c.name}</span>`
          const font = c.population >= 2e6 ? 8.2 : 7.2 // rough width per character, in px
          d = { key, lat: c.lat, lng: c.lng, el, kind: 'label', rank: c.population, w: 10 + c.name.length * font, h: 16 }
        }
        next.set(key, d)
        return d
      })
    labelCache.current = next
    return list
  }, [labels, markers, home])

  // Pins live in our own layer on top of the canvas. Elements are added once and then
  // only moved, so stamps never re-mount (which used to replay their animation and flicker).
  const pins = useMemo(() => [seal, ...markers, ...labelData], [seal, markers, labelData])
  const pinsRef = useRef(pins)
  pinsRef.current = pins
  useEffect(() => {
    const layer = overlay.current
    const keep = new Set(pins.map((p) => p.el))
    for (const el of [...layer.children]) if (!keep.has(el)) el.remove()
    for (const p of pins) if (p.el.parentNode !== layer) layer.appendChild(p.el)
    layoutPins()
  }, [pins]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => layoutPins(), [size]) // eslint-disable-line react-hooks/exhaustive-deps

  // Position every pin, hide the ones on the far side, and declutter: higher-ranked pins
  // (home, then stamps by photos, then labels by population) claim space first; a stamp
  // that would overlap shrinks to its dot, and an overlapping label is hidden.
  function layoutPins() {
    const g = globe.current
    if (!g || !overlay.current) return
    // The camera reports changes before it renders, so refresh its matrices first or pins trail a frame.
    g.camera().updateMatrixWorld()
    const cam = g.camera().position
    const radius = g.getGlobeRadius()
    const placed = []
    const hits = (r) => placed.some((q) => r.x < q.x + q.w && q.x < r.x + r.w && r.y < q.y + q.h && q.y < r.y + r.h)
    const sorted = [...pinsRef.current].sort((a, b) => b.rank - a.rank)
    for (const p of sorted) {
      const c = g.getCoords(p.lat, p.lng, 0)
      const facing = (c.x * cam.x + c.y * cam.y + c.z * cam.z) / radius
      const visible = facing > radius * 1.04 // a little margin so pins fade before the rim
      p.el.classList.toggle('behind', !visible)
      if (!visible) continue
      const s = g.getScreenCoords(p.lat, p.lng, 0)
      p.el.style.transform = `translate(${s.x.toFixed(1)}px, ${s.y.toFixed(1)}px)`
      if (p.kind === 'label') {
        const r = { x: s.x - 3, y: s.y - p.h / 2, w: p.w, h: p.h }
        const crowded = hits(r)
        p.el.classList.toggle('crowded', crowded)
        if (!crowded) placed.push(r)
      } else {
        const r = { x: s.x - p.w / 2, y: s.y - p.h - 8, w: p.w, h: p.h + 8 }
        const crowded = p.kind === 'stamp' && hits(r)
        p.el.classList.toggle('mini', crowded)
        placed.push(crowded ? { x: s.x - 5, y: s.y - 5, w: 10, h: 10 } : r)
      }
    }
  }

  // One animation loop. Legs draw one after another; only the leg being drawn (or, once
  // everything is drawn, the leg the travelling dot is on) stays bright, and earlier legs
  // fade back like a meteor's tail, so the route reads one step at a time.
  // Runs at full rate while lines are drawing and at ~30 fps afterwards.
  useEffect(() => {
    let raf = 0
    let last = 0
    const order = [...arcs].sort((x, y) => x.born - y.born)
    const step = (now) => {
      raf = requestAnimationFrame(step)
      let drawing = false
      let active = null
      for (const a of order) {
        const t = Math.min(1, Math.max(0, (now - a.born) / DRAW_MS))
        a.gap = Math.pow(1 - t, 3)
        if (t < 1) drawing = true
        if (now >= a.born) active = a // the most recent leg to start
        // During a replay the camera follows each leg as it starts drawing.
        if (!a.followed && now >= a.born) {
          a.followed = true
          if (followRef.current && t < 1) followLeg(a)
        }
        a.dot.on = false
      }
      // All drawn: a dot travels every leg in date order, lighting each leg as it goes.
      const finished = !drawing && order.length ? order[order.length - 1].born + DRAW_MS : null
      if (finished !== null) {
        const time = (now - finished) % (order.length * TRAVEL_MS)
        active = order[Math.floor(time / TRAVEL_MS)]
        const p = Math.min(1, (time % TRAVEL_MS) / (TRAVEL_MS - PAUSE_MS))
        active.dot.on = p < 1
        active.dot.offset = 1 - p * (1 + DOT)
      }
      for (const a of order) {
        const target = a === active ? 1 : now >= a.born ? FADED : 1
        a.glow = a.glow === undefined ? target : a.glow + (target - a.glow) * 0.08
      }
      if (!drawing && now - last < 33) return
      last = now
      setTick((n) => n + 1)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [arcs])

  // Lines, plus the travelling dot on the lit leg.
  const arcData = useMemo(
    () => [...arcs, ...arcs.filter((a) => a.dot.on).map((a) => a.dot)],
    [arcs, tick], // eslint-disable-line react-hooks/exhaustive-deps
  )
  // Each leg's colour carries its current brightness; a new identity each tick re-reads it.
  const arcColor = useMemo(() => (d) => {
    if (d.isDot) return ['#fbf7ee', '#fbf7ee']
    const c = tripColor(d.trip)
    const glow = d.glow ?? 1
    return [hexAlpha(c, glow * 0.96), hexAlpha(c, glow * (d.homeward ? 0.6 : 0.86))]
  }, [tick]) // eslint-disable-line react-hooks/exhaustive-deps
  // A new accessor identity each tick tells react-globe.gl to re-read the offsets.
  const dashGap = useMemo(() => (d) => (d.isDot ? d.offset : d.gap), [tick]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`globe ${picking ? 'picking' : ''}`} ref={wrap}>
      <Globe
        ref={globe}
        width={size.width}
        height={size.height}
        animateIn={false}
        onGlobeReady={onReady}
        onZoom={onView}
        onGlobeClick={(pt) => picking && onPick(pt)}
        backgroundColor="rgba(0,0,0,0)"
        globeImageUrl={globeImage}
        globeMaterial={material}
        showAtmosphere
        atmosphereColor="#c9cdd0"
        atmosphereAltitude={0.13}
        arcsData={arcData}
        arcStartLat={(d) => d.from.lat}
        arcStartLng={(d) => d.from.lng}
        arcEndLat={(d) => d.to.lat}
        arcEndLng={(d) => d.to.lng}
        arcColor={arcColor}
        arcStroke={(d) => (d.isDot ? 0.9 : 0.55)}
        arcAltitudeAutoScale={0.32}
        arcDashLength={(d) => (d.isDot ? DOT : 1)}
        arcDashGap={2}
        arcDashInitialGap={dashGap}
        arcsTransitionDuration={0}
        arcLabel={(d) => `${d.trip.title} · ${d.trip.start_date}`}
        onArcClick={(d) => onTripClick(d.trip)}
      />
      <div className="pins" ref={overlay} />
    </div>
  )
})

export default GlobeView
