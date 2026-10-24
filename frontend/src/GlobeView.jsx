// The 3D globe: home seal, ink arcs drawn one by one, city postmarks, and detail
// (borders, city names, clearing fog) that appears as you zoom in.
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import Globe from 'react-globe.gl'
import { MeshPhongMaterial } from 'three'
import { makeGlobeTexture, makeGouacheTexture, makeInkTexture } from './globeTexture.js'
import { homeSeal, postmark } from './stamps.js'
import { citiesOf, STYLES, tripColor } from './data.js'
import { angularDistance, createBorderLayers, loadCities, visibleCities } from './geoLayers.js'

const DRAW_MS = 1100 // how long one ink line takes to write itself
const STAGGER_MS = 650 // gap between consecutive trips when several appear at once
const isPhone = () => window.innerWidth < 720
const textures = {}
const PAINTERS = { journal: makeGlobeTexture, ink: makeInkTexture, gouache: makeGouacheTexture }
const textureFor = (style) => (textures[style] ??= PAINTERS[style]())

// Per-style globe look: halo colour and size, arc colours (start, end alpha) and line weight.
const LOOK = {
  journal: { halo: '#cbbf9f', haloSize: 0.11, alpha: ['ee', 'cc'], stroke: 0.42, fog: 1 },
  ink: { halo: '#bfbcb2', haloSize: 0.16, alpha: ['f0', '88'], stroke: 0.5, fog: 1.25 },
  gouache: { halo: '#c9cdd0', haloSize: 0.13, alpha: ['f4', 'dd'], stroke: 0.55, fog: 1.1 },
}

// Fog and blur fade out as the camera comes in: thick at the default view, gone by altitude ~0.9.
function applyFog(el, altitude, style) {
  if (!el) return // the camera can report in before the wrapper is mounted
  const t = Math.max(0, Math.min(1, (altitude - 0.9) / 2.2))
  const strength = LOOK[style].fog
  el.style.setProperty('--fog-blur', `${(t * 2.6 * strength).toFixed(2)}px`)
  el.style.setProperty('--fog-wash', (t * 0.55 * strength).toFixed(3))
}

const GlobeView = forwardRef(function GlobeView(
  { trips, home, style, picking, onPick, onTripClick, onCityClick },
  ref,
) {
  const globe = useRef()
  const wrap = useRef()
  const borders = useRef(null)
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight })
  const [tick, setTick] = useState(0) // bumps every frame while lines are being drawn
  const [labels, setLabels] = useState([])
  const cities = useRef(null)
  const lastLabelPov = useRef(null)
  const styleRef = useRef(style)
  styleRef.current = style
  const texture = useMemo(() => textureFor(style), [style])
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
      setRotating(false)
      globe.current.pointOfView({ lat, lng, altitude: 1.5 }, 1400)
    },
    lookAt({ lat, lng }, altitude = 1.2) {
      setRotating(false)
      globe.current.pointOfView({ lat, lng, altitude }, 1200)
    },
    setRotating,
  }))

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

  useEffect(() => {
    borders.current?.setColor(STYLES[style].border)
    if (globe.current) applyFog(wrap.current, globe.current.pointOfView().altitude, style)
  }, [style])

  function onReady() {
    const g = globe.current
    if (!g) return
    const controls = g.controls()
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.35
    controls.minDistance = 112 // close enough to read town names
    controls.maxDistance = 600
    controls.zoomSpeed = 0.8
    const altitude = isPhone() ? 3.6 : 2.3
    g.pointOfView({ lat: home.lat - 8, lng: home.lng, altitude }, 0)
    borders.current = createBorderLayers(g.scene(), g.getGlobeRadius(), STYLES[styleRef.current].border)
    borders.current.setAltitude(altitude)
    applyFog(wrap.current, altitude, styleRef.current)
    loadCities().then((list) => {
      cities.current = list
      onView(g.pointOfView())
    })
  }

  // Called on every camera change (including auto-rotation), so it only touches the DOM
  // directly and re-renders labels when the view has moved enough to matter.
  function onView(pov) {
    applyFog(wrap.current, pov.altitude, styleRef.current)
    borders.current?.setAltitude(pov.altitude)
    if (!cities.current) return
    const last = lastLabelPov.current
    const moved = !last || Math.abs(last.altitude - pov.altitude) > 0.08 || angularDistance(last, pov) > 4 + pov.altitude * 6
    if (!moved) return
    lastLabelPov.current = pov
    setLabels(visibleCities(cities.current, pov))
  }

  // Arcs: home -> first city -> next city ... one chain per trip, in time order.
  const arcs = useMemo(() => {
    const now = performance.now()
    const next = new Map()
    const homeKey = `${home.lat},${home.lng}`
    let newTrips = 0
    for (const trip of trips) {
      const stops = [home, ...trip.cities]
      const fresh = !arcCache.current.has(`${homeKey}:${trip.id}:0`)
      const delay = fresh ? newTrips++ * STAGGER_MS : 0
      for (let i = 0; i < stops.length - 1; i++) {
        const key = `${homeKey}:${trip.id}:${i}`
        next.set(key, arcCache.current.get(key) ?? {
          key, trip,
          // Dashes grow from the arc's end, so start/end are swapped to write outward from home.
          from: stops[i + 1], to: stops[i],
          born: now + delay + i * DRAW_MS * 0.8, gap: 1,
        })
      }
    }
    arcCache.current = next
    return [...next.values()]
  }, [trips, home])

  // Postmarks land when the first ink line reaching them is finished.
  const markers = useMemo(() => {
    const now = performance.now()
    const visited = citiesOf(trips)
    const maxCount = Math.max(1, ...visited.map((c) => c.photo_count))
    const next = new Map()
    for (const city of visited) {
      const first = city.visits[0].trip
      const px = Math.round(38 + 42 * Math.sqrt(city.photo_count / maxCount))
      const signature = `${city.visits.length}:${px}:${style}`
      let d = stampCache.current.get(city.id)
      if (!d || d.signature !== signature) {
        // The outer element is positioned by globe.gl; the inner button does the stamping animation.
        const el = document.createElement('div')
        el.className = 'marker'
        const button = document.createElement('button')
        button.className = 'postmark'
        button.style.setProperty('--size', `${px}px`)
        button.innerHTML = postmark(city, tripColor(first), style)
        button.addEventListener('click', (e) => {
          e.stopPropagation()
          handlers.current.onCityClick(el._city)
        })
        el.appendChild(button)
        const arc = arcs.find((a) => a.trip.id === first.id && a.from.id === city.id)
        button.style.animationDelay = `${arc ? Math.max(0, arc.born - now + DRAW_MS * 0.85) : 0}ms`
        d = { id: city.id, lat: city.lat, lng: city.lng, el, signature }
      }
      d.el._city = city
      next.set(city.id, d)
    }
    stampCache.current = next
    return [...next.values()]
  }, [trips, arcs, style])

  const seal = useMemo(() => {
    const el = document.createElement('div')
    el.className = 'marker seal'
    el.title = `Home · ${home.city}`
    el.innerHTML = homeSeal(home.city, style)
    return { id: 'home', lat: home.lat, lng: home.lng, el }
  }, [home, style])

  // Small map labels for nearby cities; visited cities already have a stamp, so skip them.
  const labelData = useMemo(() => {
    const stamped = new Set(markers.map((m) => `${m.lat.toFixed(1)},${m.lng.toFixed(1)}`))
    return labels
      .filter((c) => !stamped.has(`${c.lat.toFixed(1)},${c.lng.toFixed(1)}`) && Math.abs(c.lat - home.lat) + Math.abs(c.lng - home.lng) > 0.15)
      .map((c) => {
        const key = `${c.name}|${c.lat}|${c.lng}`
        let d = labelCache.current.get(key)
        if (!d) {
          const el = document.createElement('div')
          el.className = `marker city-label ${c.population >= 2e6 ? 'major' : ''}`
          el.innerHTML = `<i></i><span>${c.name}</span>`
          d = { id: key, lat: c.lat, lng: c.lng, el }
          labelCache.current.set(key, d)
        }
        return d
      })
  }, [labels, markers, home])

  // Ease each arc's dash offset from 1 (hidden) to 0 (fully drawn), then stop ticking.
  useEffect(() => {
    let raf = 0
    const step = () => {
      const now = performance.now()
      let busy = false
      for (const a of arcs) {
        const t = Math.min(1, Math.max(0, (now - a.born) / DRAW_MS))
        a.gap = Math.pow(1 - t, 3)
        if (t < 1) busy = true
      }
      setTick((n) => n + 1)
      if (busy) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [arcs])

  // A new accessor identity each tick tells react-globe.gl to re-read the gaps.
  const dashGap = useMemo(() => (d) => d.gap, [tick]) // eslint-disable-line react-hooks/exhaustive-deps
  const look = LOOK[style]

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
        globeImageUrl={texture}
        globeMaterial={material}
        showAtmosphere
        atmosphereColor={look.halo}
        atmosphereAltitude={look.haloSize}
        arcsData={arcs}
        arcStartLat={(d) => d.from.lat}
        arcStartLng={(d) => d.from.lng}
        arcEndLat={(d) => d.to.lat}
        arcEndLng={(d) => d.to.lng}
        arcColor={(d) => look.alpha.map((a) => tripColor(d.trip) + a)}
        arcStroke={look.stroke}
        arcAltitudeAutoScale={0.32}
        arcDashLength={1}
        arcDashGap={2}
        arcDashInitialGap={dashGap}
        arcsTransitionDuration={0}
        arcLabel={(d) => `${d.trip.title} · ${d.trip.start_date}`}
        onArcClick={(d) => onTripClick(d.trip)}
        htmlElementsData={[...labelData, seal, ...markers]}
        htmlLat={(d) => d.lat}
        htmlLng={(d) => d.lng}
        htmlAltitude={0.004}
        htmlTransitionDuration={0}
        htmlElement={(d) => d.el}
        htmlElementVisibilityModifier={(el, visible) => el.classList.toggle('behind', !visible)}
      />
    </div>
  )
})

export default GlobeView
