// The 3D globe: home seal, trip lines drawn one by one, city stamps, and detail
// (borders, city names, clearing fog) that appears as you zoom in.
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import Globe from 'react-globe.gl'
import { MeshPhongMaterial } from 'three'
import globeTexture from './assets/globe-gouache.webp' // painted by globeTexture.js, baked so it loads instantly
import { homeSeal, postmark } from './stamps.js'
import { createSparkles } from './sparkles.js'
import { BORDER_COLOR, citiesOf, DRAW_MS, distanceKm, STAY, tripColor } from './data.js'
import { angularDistance, createBorderLayers, createHomeRing, loadCities, visibleCities } from './geoLayers.js'

const FADED = 0.16 // how bright a leg stays once the route has moved on
const REST = 0.55 // brightness of every route once all legs have flown
const DIMMED = 0.45 // while a trip is hovered, the other routes step back to this share of their brightness
// Route line styles; ?line=pencil or ?line=stitch in the URL tries the others.
// Stroke 0.6 keeps every line thick enough to hover and click.
const LINES = {
  ink: { stroke: 0.6, dash: 1, gap: 0 }, // solid ink
  pencil: { stroke: 0.6, dash: 0.022, gap: 0.014 }, // short pencil dashes
  stitch: { stroke: 0.6, dash: 0.005, gap: 0.016 }, // dotted, like a stitched route
}
const line = LINES[new URLSearchParams(window.location.search).get('line')] ?? LINES.ink
const FLY_MS = 1200 // camera flight to a trip or a city; App opens the page once it has landed
const RING_COLOR = '#a8473a' // the home circle shares the home seal's vermilion
const isPhone = () => window.innerWidth < 720

// The city a trip is about: the one with the most photos (the earliest visit wins a tie).
function mainCity(trip) {
  return trip.cities.reduce((best, c) => (!best || c.photo_count > best.photo_count ? c : best), null)
}
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
  { trips, story, cursor, home, homeCircle, follow, picking, onPick, onTripClick, onCityClick },
  ref,
) {
  const globe = useRef()
  const wrap = useRef()
  const overlay = useRef()
  const dust = useRef() // canvas for the pigment flecks around the rim
  const sparkles = useRef(null)
  const borders = useRef(null)
  const ring = useRef(null) // dashed home circle, { lat, lng, km } from homeCircle
  const circle = useRef(homeCircle)
  circle.current = homeCircle
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
  const [hoverTrip, setHoverTrip] = useState(null) // id of the trip whose line is under the pointer

  // Both camera moves return how long the flight takes (0 if the camera didn't move).
  useImperativeHandle(ref, () => ({
    // Face the trip's main city. Averaging all its cities would land in between them
    // (Chengdu + Los Angeles averages to somewhere off Africa).
    flyTo(trip) {
      const city = mainCity(trip)
      if (!city || !globe.current) return 0
      touch()
      globe.current.pointOfView({ lat: city.lat, lng: city.lng, altitude: 1.2 }, FLY_MS)
      return FLY_MS
    },
    lookAt({ lat, lng }, altitude = 1.2) {
      if (!globe.current) return 0
      touch()
      globe.current.pointOfView({ lat, lng, altitude }, FLY_MS)
      return FLY_MS
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

  // Idle spin: the globe turns slowly only until the user first interacts with it. The first
  // press, drag, zoom or click (or a camera flight it asks for) stops it for good, so from then
  // on the globe stays exactly where the user leaves it. Hovering a pin or a line only pauses
  // it, so the target holds still to be clicked. App can switch it off too (e.g. while a page
  // is open or a home is being picked).
  const spin = useRef({ allowed: true, hover: false, arcHover: false, touched: false, replay: false })
  spin.current.replay = follow // only while the replay is actually playing, not when paused on the bar
  function halt() {
    const controls = globe.current?.controls()
    if (controls) controls.autoRotate = false
  }
  function touch() {
    spin.current.touched = true
    halt()
  }
  function setRotating(on) {
    spin.current.allowed = on
    if (!on) halt()
  }
  useEffect(() => {
    const id = setInterval(() => {
      const g = globe.current
      if (!g) return
      const s = spin.current
      const controls = g.controls()
      if (s.touched) {
        controls.autoRotate = false
        clearInterval(id) // the user has taken over; the spin never comes back
        return
      }
      if (s.hover && !overlay.current?.querySelector('.pin:hover')) s.hover = false // pin went away under the pointer
      const altitude = g.pointOfView().altitude
      controls.autoRotate = s.allowed && !s.hover && !s.arcHover && !s.replay
      controls.autoRotateSpeed = 0.35 * Math.max(0.2, Math.min(1, altitude / 2.3)) // gentler when close
    }, 300)
    return () => clearInterval(id)
  }, [])

  // Hovering a line lights up its whole trip (and holds the spin so it can be clicked).
  function hoverArc(arc) {
    spin.current.arcHover = !!arc
    if (arc) halt()
    setHoverTrip(arc ? arc.trip.id : null)
  }

  // Keep the canvas filling the window.
  useEffect(() => {
    const ro = new ResizeObserver(() => wrap.current && setSize({ width: wrap.current.clientWidth, height: wrap.current.clientHeight }))
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])

  useEffect(() => () => {
    borders.current?.dispose()
    ring.current?.dispose()
  }, [])

  // Redraw the home circle when its centre or radius changes (the camera doesn't move).
  const ringLat = homeCircle?.lat
  const ringLng = homeCircle?.lng
  const ringKm = homeCircle?.km
  useEffect(() => {
    ring.current?.set(ringLat == null ? null : { lat: ringLat, lng: ringLng }, ringKm)
  }, [ringLat, ringLng, ringKm])

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
    ring.current = createHomeRing(g.scene(), g.getGlobeRadius(), RING_COLOR)
    ring.current.set(circle.current, circle.current?.km)
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
      const px = Math.round(46 + 32 * Math.sqrt(city.photo_count / maxCount))
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
        el._tag = document.createElement('span')
        el._tag.className = 'tag'
        el.appendChild(el._tag)
        const button = document.createElement('button')
        button.className = 'postmark'
        button.innerHTML = postmark(city, tripColor(first)) + (stop ? `<b class="stop-no">${stop}</b>` : '')
        // Listen on the whole pin so the dot, the stamp and a folded stamp are all clickable.
        el.addEventListener('click', (e) => {
          e.stopPropagation()
          openStamp(el)
        })
        // Hovering a pin holds the globe still so it can be clicked.
        el.addEventListener('pointerenter', () => { spin.current.hover = true; halt() })
        el.addEventListener('pointerleave', () => { spin.current.hover = false })
        el.appendChild(button)
                d = { key: `stamp:${city.id}`, lat: city.lat, lng: city.lng, el, signature, kind: 'stamp', rank: 1e9 + city.photo_count, w: px, h: px * 0.95, tagW: 22 + city.name.length * 7.6 }
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
    // Stamps grow a little as you zoom in and shrink as the camera pulls back, so far away
    // they don't cover their neighbours.
    const zs = Math.max(0.6, Math.min(1.2, 1.3 - g.pointOfView().altitude * 0.25))
    overlay.current.style.setProperty('--zs', zs.toFixed(3))
    const placed = [] // { x, y, w, h, host } boxes already claimed on screen
    const hit = (r) => placed.find((q) => r.x < q.x + q.w && q.x < r.x + r.w && r.y < q.y + q.h && q.y < r.y + r.h)
    const sorted = [...pinsRef.current].sort((a, b) => b.rank - a.rank)
    const shown = []
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
      shown.push(p)
    }

    // Stamps in three steps, so names stay readable as long as possible:
    // 1. a stamp that touches no other stamp is shown whole;
    // 2. the others become small name tags next to their dots (above, beside or below),
    //    biggest first, where they fit;
    // 3. the rest fold into the stamp or tag they bump into, which becomes a numbered bubble.
    // Dots always stay on their exact spot.
    const overlaps = (r, q) => r.x < q.x + q.w && q.x < r.x + r.w && r.y < q.y + q.h && q.y < r.y + r.h
    const stamps = shown.filter((p) => p.kind === 'stamp')
    for (const p of stamps) {
      const { x, y } = p.el._xy
      const w = p.w * zs
      const h = p.h * zs
      p.full = { x: x - w / 2, y: y - h - 8, w, h: h + 8, host: p }
      const W = p.tagW
      p.tags = [
        ['above', { x: x - W / 2, y: y - 30, w: W, h: 30, host: p }],
        ['right', { x: x + 8, y: y - 11, w: W, h: 22, host: p }],
        ['left', { x: x - 8 - W, y: y - 11, w: W, h: 22, host: p }],
        ['below', { x: x - W / 2, y: y + 6, w: W, h: 26, host: p }],
      ]
    }
    const mode = new Map()
    for (const p of stamps) {
      if (stamps.some((q) => q !== p && overlaps(p.full, q.full))) continue
      mode.set(p, 'full')
      placed.push(p.full)
    }
    for (const p of stamps) {
      if (mode.has(p)) continue
      const free = p.tags.find(([, r]) => !hit(r)) // above the dot first, then beside or below it
      if (!free) continue
      mode.set(p, 'tag')
      p.el.dataset.side = free[0]
      placed.push(free[1])
    }
    for (const p of stamps) {
      if (mode.has(p)) continue
      const host = hit(p.tags[0][1])?.host ?? p
      mode.set(p, host === p ? 'tag' : 'mini')
      if (host === p) placed.push(p.tags[0][1])
      else {
        host.el._members.push(p.el._city)
        placed.push({ x: p.el._xy.x - 6, y: p.el._xy.y - 6, w: 12, h: 12, host })
      }
    }
    // A stamp that picked up folded neighbours shows as a tag ("Montreal +1") too.
    for (const p of stamps) if (p.el._members.length && mode.get(p) === 'full') mode.set(p, 'tag')
    for (const p of stamps) {
      if (mode.get(p) === 'tag' && !p.el.dataset.side) p.el.dataset.side = 'above'
      p.el.classList.toggle('tagged', mode.get(p) === 'tag')
      p.el.classList.toggle('mini', mode.get(p) === 'mini')
    }

    // Then the home seal (it gives way to stamps, leaving its red dot) and map labels.
    for (const p of shown) {
      if (p.kind === 'stamp') continue
      const { x, y } = p.el._xy
      const r = p.kind === 'label' ? { x: x - 3, y: y - p.h / 2, w: p.w, h: p.h } : { x: x - p.w / 2, y: y - p.h - 8, w: p.w, h: p.h + 8 }
      const crowded = !!hit(r)
      p.el.classList.toggle(p.kind === 'label' ? 'crowded' : 'mini', crowded)
      if (!crowded || p.kind === 'seal') placed.push(crowded ? { x: x - 6, y: y - 6, w: 12, h: 12 } : r)
    }
    // A crowd reads as its biggest city's tag plus a count ("New York +2"); the folded dots
    // stay on their exact spots but step back, and clicking the tag zooms in until they separate.
    for (const p of sorted) if (p.kind === 'stamp') p.el.classList.remove('clustered')
    for (const p of stamps) {
      const group = [p.el, ...p.el._members.map((c) => stampCache.current.get(c.id)?.el).filter(Boolean)]
      for (const el of group.slice(1)) el.classList.add('clustered')
      p.el.classList.toggle('has-more', group.length > 1)
      const label = group.length > 1 ? `${p.el._city.name} +${group.length - 1}` : p.el._city.name
      if (p.el._tag.textContent !== label) p.el._tag.textContent = label
      p.el._tag.title = group.length > 1 ? group.map((el) => el._city.name).join(' · ') : ''
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
  // The hovered trip shows at full strength and the others step back.
  const hovered = hoverTrip && trips.some((t) => t.id === hoverTrip) ? hoverTrip : null // ignore a trip that left the view
  const arcColor = useMemo(() => (d) => {
    const c = tripColor(d.trip)
    let glow = d.glow ?? 1
    if (hovered) glow = d.trip.id === hovered ? 1 : glow * DIMMED
    return [hexAlpha(c, glow * 0.96), hexAlpha(c, glow * (d.homeward ? 0.6 : 0.86))]
  }, [tick, cursor, hovered]) // eslint-disable-line react-hooks/exhaustive-deps
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
        onArcHover={hoverArc}
        onArcClick={(d) => onTripClick(d.trip)}
      />
      <canvas className="sparkles" ref={dust} />
      <div className="pins" ref={overlay} />
    </div>
  )
})

export default GlobeView
