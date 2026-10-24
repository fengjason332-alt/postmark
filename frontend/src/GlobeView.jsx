// The 3D globe: home seal, trip lines drawn one by one, city stamps, and detail
// (borders, city names, clearing fog) that appears as you zoom in.
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import Globe from 'react-globe.gl'
import { MeshPhongMaterial } from 'three'
import globeTexture from './assets/globe-gouache.webp' // painted by globeTexture.js, baked so it loads instantly
import { homeSeal, postmark } from './stamps.js'
import { createSparkles } from './sparkles.js'
import { BORDER_COLOR, citiesOf, DRAW_MS, distanceKm, STAY, tripColor } from './data.js'
import { angularDistance, createBorderLayers, loadCities, visibleCities } from './geoLayers.js'

const FADED = 0.16 // how bright a leg stays once the route has moved on
const REST = 0.55 // brightness of every route once all legs have flown
// Route line styles; ?line=pencil or ?line=stitch in the URL tries the others.
const LINES = {
  ink: { stroke: 0.2, dash: 1, gap: 0 }, // thin solid ink
  pencil: { stroke: 0.2, dash: 0.022, gap: 0.014 }, // short pencil dashes
  stitch: { stroke: 0.36, dash: 0.005, gap: 0.016 }, // dotted, like a stitched route
}
const line = LINES[new URLSearchParams(window.location.search).get('line')] ?? LINES.ink
const IDLE_MS = 2500 // untouched this long (and zoomed out), the globe starts its slow spin
const isPhone = () => window.innerWidth < 720
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
  { trips, story, cursor, home, follow, picking, onPick, onTripClick, onCityClick },
  ref,
) {
  const globe = useRef()
  const wrap = useRef()
  const overlay = useRef()
  const dust = useRef() // canvas for the pigment flecks around the rim
  const sparkles = useRef(null)
  const borders = useRef(null)
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight })
  const [tick, setTick] = useState(0) // bumps each animation frame while lines draw or fade
  const [labels, setLabels] = useState([])
  const cities = useRef(null)
  const lastLabelPov = useRef(null)
  const material = useMemo(() => new MeshPhongMaterial({ shininess: 0 }), []) // matte paper, no glare
  const arcCache = useRef(new Map()) // key -> arc datum, kept so existing lines don't redraw
  const stampCache = useRef(new Map()) // city id -> html datum
  const labelCache = useRef(new Map())
  const handlers = useRef({})
  handlers.current = { onCityClick }

  useImperativeHandle(ref, () => ({
    flyTo(trip) {
      const pts = trip.cities
      const lat = pts.reduce((s, c) => s + c.lat, 0) / pts.length
      const lng = pts.reduce((s, c) => s + c.lng, 0) / pts.length
      touch()
      globe.current.pointOfView({ lat, lng, altitude: 1.5 }, 1400)
    },
    lookAt({ lat, lng }, altitude = 1.2) {
      touch()
      globe.current.pointOfView({ lat, lng, altitude }, 1200)
    },
    setRotating,
  }))

  // Turn the camera toward a leg: centred between its two ends, pulled back for long hops.
  function followLeg(a, ms = DRAW_MS) {
    const g = globe.current
    if (!g) return
    touch()
    const km = distanceKm(a.from, a.to)
    const altitude = Math.min(2.2, Math.max(0.55, 0.45 + km / 2500))
    const lng = a.from.lng + (((a.to.lng - a.from.lng + 540) % 360) - 180) * 0.6
    g.pointOfView({ lat: a.from.lat + (a.to.lat - a.from.lat) * 0.6, lng, altitude }, ms)
  }

  // Idle spin: the globe turns slowly only while it is zoomed out and nobody has touched it
  // for a few seconds. Any press, drag, zoom or hovering a pin stops it at once, so pins hold
  // still when you go to click them. App can switch it off entirely (e.g. while a page is open).
  const spin = useRef({ allowed: true, hover: false, last: 0, replay: false })
  spin.current.replay = follow // only while the replay is actually playing, not when paused on the bar
  function touch() {
    spin.current.last = performance.now()
    const controls = globe.current?.controls()
    if (controls) controls.autoRotate = false
  }
  function setRotating(on) {
    spin.current.allowed = on
    touch()
  }
  useEffect(() => {
    const id = setInterval(() => {
      const g = globe.current
      if (!g) return
      const s = spin.current
      if (s.hover && !overlay.current?.querySelector('.pin:hover')) s.hover = false // pin went away under the pointer
      const idle = performance.now() - s.last > IDLE_MS
      const controls = g.controls()
      const altitude = g.pointOfView().altitude
      controls.autoRotate = s.allowed && !s.hover && !s.replay && idle
      controls.autoRotateSpeed = 0.35 * Math.max(0.2, Math.min(1, altitude / 2.3)) // gentler when close
    }, 300)
    return () => clearInterval(id)
  }, [])

  // Keep the canvas filling the window.
  useEffect(() => {
    const ro = new ResizeObserver(() => wrap.current && setSize({ width: wrap.current.clientWidth, height: wrap.current.clientHeight }))
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])

  useEffect(() => () => borders.current?.dispose(), [])

  // Touching the globe with the pointer: the globe leans in a touch and a few pigment flecks
  // puff off the rim where the pointer came in. Mouse/trackpad only (no hover on phones).
  useEffect(() => {
    const el = wrap.current
    const sp = (sparkles.current = createSparkles(dust.current))
    if (!window.matchMedia?.('(hover: hover)').matches) return () => sp.dispose()
    let over = false
    const move = (e) => {
      const g = globe.current
      if (!g || !borders.current) return
      const rect = el.getBoundingClientRect()
      const k = rect.width / el.clientWidth // the wrapper may be scaled up while hovered
      const x = (e.clientX - rect.left) / k
      const y = (e.clientY - rect.top) / k
      const on = !!g.toGlobeCoords(x, y)
      if (on === over) return
      over = on
      el.classList.toggle('touched', on)
      if (on) {
        sp.setRim(rimOnScreen())
        sp.enter(x, y)
      } else sp.leave()
    }
    const out = () => {
      over = false
      el.classList.remove('touched')
      sp.leave()
    }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', out)
    return () => {
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerleave', out)
      sp.dispose()
    }
  }, [])

  useEffect(() => sparkles.current?.resize(), [size])

  // Where the globe's outline sits on screen (it is always centred in the view).
  function rimOnScreen() {
    const g = globe.current
    const cam = g.camera()
    const R = g.getGlobeRadius()
    const d = cam.position.length()
    const r = (R / Math.sqrt(Math.max(1e-6, d * d - R * R)) / Math.tan((cam.fov * Math.PI) / 360)) * (wrap.current.clientHeight / 2)
    return { x: wrap.current.clientWidth / 2, y: wrap.current.clientHeight / 2, r }
  }


  function onReady() {
    const g = globe.current
    if (!g || borders.current) return // globe.gl can report ready more than once; set up only once
    const controls = g.controls()
    controls.addEventListener('start', touch) // user starts dragging or zooming
    wrap.current.addEventListener('pointerdown', touch)
    wrap.current.addEventListener('wheel', touch, { passive: true })
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
    if (globe.current) sparkles.current?.setRim(rimOnScreen())
    layoutPins()
    if (!cities.current) return
    const last = lastLabelPov.current
    const moved = !last || Math.abs(last.altitude - pov.altitude) > 0.08 || angularDistance(last, pov) > 4 + pov.altitude * 6
    if (!moved) return
    lastLabelPov.current = pov
    setLabels(visibleCities(cities.current, pov))
  }

  // Arcs per trip, in visit order: home -> first city -> ... -> last city -> home.
  // While exploring, every route is simply there, drawn softly. During a replay (the play
  // button) the timeline's position draws them leg by leg instead.
  const arcs = useMemo(() => {
    const next = new Map()
    const homeKey = `${home.lat},${home.lng}`
    for (const trip of trips) {
      const stops = [home, ...trip.cities, home]
      for (let i = 0; i < stops.length - 1; i++) {
        const key = `${homeKey}:${trip.id}:${i}`
        const a = arcCache.current.get(key) ?? {
          key, trip, leg: i, homeward: i === stops.length - 2,
          // three-globe reveals a dash from the arc's start, so each leg grows from where it leaves.
          from: stops[i], to: stops[i + 1], gap: 0,
        }
        a.span = story.legs[trip.id]?.[i] ?? { start: 0, end: 0 } // this leg's stretch of the timeline
        next.set(key, a)
      }
    }
    arcCache.current = next
    return [...next.values()]
  }, [trips, story, home])

  // During a replay, every leg is drawn exactly as far as the timeline knob is through its
  // stretch, glows while its stamp lands, then fades as the route moves on.
  const replay = cursor !== null
  if (replay) {
    for (const a of arcs) {
      const p = Math.max(0, Math.min(1, cursor - a.span.start))
      a.gap = 1 - p
      const after = cursor - a.span.end - STAY
      a.glow = after <= 0 ? 1 : Math.max(FADED, 1 - after * 1.6)
    }
  }
  const landedKey = replay ? arcs.filter((a) => cursor >= a.span.end - 0.08).map((a) => a.key).join('|') : null

  // The camera follows the leg the knob is in, arriving as the line does.
  const followed = useRef(null)
  useEffect(() => {
    if (!replay) {
      followed.current = null
      return
    }
    const a = arcs.find((x) => cursor >= x.span.start && cursor < x.span.end)
    if (follow && a && followed.current !== a.key) {
      followed.current = a.key
      followLeg(a, Math.max(300, (a.span.end - cursor) * DRAW_MS))
    }
  })

  // A stamp with others folded under it zooms in until they separate; otherwise it opens the city.
  function openStamp(el) {
    const members = el._members ?? []
    if (!members.length) return handlers.current.onCityClick(el._city)
    const all = [el._city, ...members]
    const lat = all.reduce((s, c) => s + c.lat, 0) / all.length
    const lng = all.reduce((s, c) => s + c.lng, 0) / all.length
    touch()
    globe.current.pointOfView({ lat, lng, altitude: Math.max(0.35, globe.current.pointOfView().altitude * 0.45) }, 900)
  }

  // Stamps land when the first line reaching them is finished. Each sits just above a
  // small dot on the city's exact position, so the lines visibly meet the right spot.
  const markers = useMemo(() => {
    const landed = landedKey === null ? null : new Set(landedKey.split('|'))
    const visited = citiesOf(trips)
    const maxCount = Math.max(1, ...visited.map((c) => c.photo_count))
    const next = new Map()
    for (const city of visited) {
      const first = city.visits[0].trip
      const arc = arcs.find((a) => a.trip.id === first.id && a.to.id === city.id)
      // During a replay a stamp only appears once the line reaching it has arrived.
      if (landed && !landed.has(arc?.key)) continue
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
        // Listen on the whole pin so the dot, the stamp and a folded stamp are all clickable.
        el.addEventListener('click', (e) => {
          e.stopPropagation()
          openStamp(el)
        })
        // Hovering a pin holds the globe still so it can be clicked.
        el.addEventListener('pointerenter', () => { spin.current.hover = true; touch() })
        el.addEventListener('pointerleave', () => { spin.current.hover = false; touch() })
        el.appendChild(button)
        el._more = document.createElement('b')
        el._more.className = 'more'
        el.appendChild(el._more)
                d = { key: `stamp:${city.id}`, lat: city.lat, lng: city.lng, el, signature, kind: 'stamp', rank: 1e9 + city.photo_count, w: px, h: px * 0.7 }
      }
      d.el._city = city
      next.set(city.id, d)
    }
    stampCache.current = next
    return [...next.values()]
  }, [trips, arcs, landedKey])

  const seal = useMemo(() => {
    const el = document.createElement('div')
    el.className = 'pin seal'
    el.title = `Home · ${home.city}`
    el.innerHTML = `<i class="pin-dot"></i><div class="seal-art">${homeSeal(home.city)}</div>`
    return { key: 'home', lat: home.lat, lng: home.lng, el, kind: 'seal', rank: 5e8, w: 46, h: 30 }
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
  // (stamps by photos, then the home seal, then labels by population) claim space first;
  // a stamp that would overlap folds to its dot under a "+N" stamp, and an overlapping
  // label is hidden.
  function layoutPins() {
    const g = globe.current
    if (!g || !overlay.current) return
    // The camera reports changes before it renders, so refresh its matrices first or pins trail a frame.
    g.camera().updateMatrixWorld()
    const cam = g.camera().position
    const radius = g.getGlobeRadius()
    // Stamps shrink as the camera pulls back, so far away they don't cover their neighbours.
    const zs = Math.max(0.55, Math.min(1, 1.25 - g.pointOfView().altitude * 0.22))
    overlay.current.style.setProperty('--zs', zs.toFixed(3))
    const placed = [] // { x, y, w, h, host } boxes already claimed on screen
    const hit = (r) => placed.find((q) => r.x < q.x + q.w && q.x < r.x + r.w && r.y < q.y + q.h && q.y < r.y + r.h)
    const sorted = [...pinsRef.current].sort((a, b) => b.rank - a.rank)
    for (const p of sorted) {
      if (p.kind === 'stamp') p.el._members = []
      const c = g.getCoords(p.lat, p.lng, 0)
      const facing = (c.x * cam.x + c.y * cam.y + c.z * cam.z) / radius
      const visible = facing > radius * 1.04 // a little margin so pins fade before the rim
      p.el.classList.toggle('behind', !visible)
      if (!visible) continue
      const s = g.getScreenCoords(p.lat, p.lng, 0)
      p.el.style.transform = `translate(${s.x.toFixed(1)}px, ${s.y.toFixed(1)}px)`
      p.el._xy = s
      if (p.kind === 'label') {
        const r = { x: s.x - 3, y: s.y - p.h / 2, w: p.w, h: p.h }
        const crowded = !!hit(r)
        p.el.classList.toggle('crowded', crowded)
        if (!crowded) placed.push(r)
      } else {
        const w = p.kind === 'stamp' ? p.w * zs : p.w
        const h = p.kind === 'stamp' ? p.h * zs : p.h
        const r = { x: s.x - w / 2, y: s.y - h - 8, w, h: h + 8, host: p.kind === 'stamp' ? p : null }
        const other = hit(r)
        // A stamp that would cover a bigger one folds down to its dot (still clickable, still
        // on the exact spot) and is counted on that stamp's "+N" badge instead. The home seal
        // gives way to stamps the same way, leaving its red dot.
        p.el.classList.toggle('mini', !!other)
        if (p.kind === 'stamp') other?.host?.el._members.push(p.el._city)
        placed.push(other ? { x: s.x - 6, y: s.y - 6, w: 12, h: 12, host: other.host } : r)
      }
    }
    // A crowd of stamps becomes one numbered bubble in the middle of its dots; every dot
    // stays on its exact spot, and clicking the bubble zooms in until they separate.
    for (const p of sorted) if (p.kind === 'stamp') p.el.classList.remove('clustered')
    for (const p of sorted) {
      if (p.kind !== 'stamp') continue
      const group = [p.el, ...p.el._members.map((c) => stampCache.current.get(c.id)?.el).filter(Boolean)]
      const n = group.length
      p.el.classList.toggle('has-more', n > 1)
      // Dots tucked under the bubble step back, so the bubble is the only thing to click.
      for (const el of group.slice(1)) el.classList.add('clustered')
      if (n < 2) continue
      const cx = group.reduce((t, el) => t + el._xy.x, 0) / n - p.el._xy.x
      const cy = group.reduce((t, el) => t + el._xy.y, 0) / n - p.el._xy.y
      p.el._more.textContent = n
      p.el._more.title = group.map((el) => el._city.name).join(' · ')
      p.el._more.style.transform = `translate(${cx.toFixed(1)}px, ${cy.toFixed(1)}px)`
    }
  }

  // Outside a replay every route rests fully drawn at a soft brightness. After a replay
  // ends, the lines ease back to that rest state; the loop stops once they are still.
  useEffect(() => {
    if (replay) return undefined // the timeline drives the lines during a replay
    let raf = 0
    const step = () => {
      let moving = false
      for (const a of arcs) {
        a.gap = 0
        a.glow = a.glow === undefined ? REST : a.glow + (REST - a.glow) * 0.07
        if (Math.abs(a.glow - REST) > 0.01) moving = true
      }
      setTick((n) => n + 1)
      if (moving) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [arcs, replay])

  // Each leg's colour carries its current brightness; a new identity each tick re-reads it.
  const arcColor = useMemo(() => (d) => {
    const c = tripColor(d.trip)
    const glow = d.glow ?? 1
    return [hexAlpha(c, glow * 0.96), hexAlpha(c, glow * (d.homeward ? 0.6 : 0.86))]
  }, [tick, cursor]) // eslint-disable-line react-hooks/exhaustive-deps
  // A new accessor identity each tick tells react-globe.gl to re-read the offsets.
  const dashGap = useMemo(() => (d) => d.gap, [tick, cursor]) // eslint-disable-line react-hooks/exhaustive-deps

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
        globeImageUrl={globeTexture}
        globeMaterial={material}
        showAtmosphere
        atmosphereColor="#c9cdd0"
        atmosphereAltitude={0.13}
        arcsData={arcs}
        arcStartLat={(d) => d.from.lat}
        arcStartLng={(d) => d.from.lng}
        arcEndLat={(d) => d.to.lat}
        arcEndLng={(d) => d.to.lng}
        arcColor={arcColor}
        arcStroke={line.stroke}
        arcAltitudeAutoScale={0.32}
        arcDashLength={replay ? 1 : line.dash}
        arcDashGap={replay ? 2 : line.gap}
        arcDashInitialGap={dashGap}
        arcsTransitionDuration={0}
        arcLabel={(d) => `${d.trip.title} · ${d.trip.start_date}`}
        onArcClick={(d) => onTripClick(d.trip)}
      />
      <canvas className="sparkles" ref={dust} />
      <div className="pins" ref={overlay} />
    </div>
  )
})

export default GlobeView
