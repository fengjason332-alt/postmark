// The 3D globe: home seal, ink arcs drawn one by one, and city postmarks.
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import Globe from 'react-globe.gl'
import { MeshPhongMaterial } from 'three'
import { makeGlobeTexture } from './globeTexture.js'
import { homeSeal, postmark } from './stamps.js'
import { citiesOf, tripColor } from './data.js'

const DRAW_MS = 1100 // how long one ink line takes to write itself
const STAGGER_MS = 650 // gap between consecutive trips when several appear at once
const isPhone = () => window.innerWidth < 720

const GlobeView = forwardRef(function GlobeView({ trips, home, onTripClick, onCityClick }, ref) {
  const globe = useRef()
  const wrap = useRef()
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight })
  const [tick, setTick] = useState(0) // bumps every frame while lines are being drawn
  const texture = useMemo(() => makeGlobeTexture(), [])
  const material = useMemo(() => new MeshPhongMaterial({ shininess: 0 }), []) // matte paper, no glare
  const arcCache = useRef(new Map()) // key -> arc datum, kept so existing lines don't redraw
  const stampCache = useRef(new Map()) // city id -> html datum
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
    setRotating,
  }))

  function setRotating(on) {
    const controls = globe.current?.controls()
    if (controls) controls.autoRotate = on
  }

  // Keep the canvas filling the window.
  useEffect(() => {
    const ro = new ResizeObserver(() => setSize({ width: wrap.current.clientWidth, height: wrap.current.clientHeight }))
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])

  function onReady() {
    const controls = globe.current.controls()
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.35
    controls.minDistance = 140
    controls.maxDistance = 600
    globe.current.pointOfView({ lat: home.lat - 8, lng: home.lng, altitude: isPhone() ? 3.6 : 2.3 }, 0)
  }

  // Arcs: home -> first city -> next city ... one chain per trip, in time order.
  const arcs = useMemo(() => {
    const now = performance.now()
    const next = new Map()
    let newTrips = 0
    for (const trip of trips) {
      const stops = [home, ...trip.cities]
      const fresh = !arcCache.current.has(`${trip.id}:0`)
      const delay = fresh ? newTrips++ * STAGGER_MS : 0
      for (let i = 0; i < stops.length - 1; i++) {
        const key = `${trip.id}:${i}`
        next.set(key, arcCache.current.get(key) ?? {
          key, trip, color: tripColor(trip),
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
    const cities = citiesOf(trips)
    const maxCount = Math.max(1, ...cities.map((c) => c.photo_count))
    const next = new Map()
    for (const city of cities) {
      const first = city.visits[0].trip
      const px = Math.round(38 + 42 * Math.sqrt(city.photo_count / maxCount))
      const signature = `${city.visits.length}:${px}`
      let d = stampCache.current.get(city.id)
      if (!d || d.signature !== signature) {
        // The outer element is positioned by globe.gl; the inner button does the stamping animation.
        const el = document.createElement('div')
        el.className = 'marker'
        const button = document.createElement('button')
        button.className = 'postmark'
        button.style.setProperty('--size', `${px}px`)
        button.innerHTML = postmark(city, tripColor(first))
        button.addEventListener('click', (e) => {
          e.stopPropagation()
          handlers.current.onCityClick(el._city)
        })
        el.appendChild(button)
        const arc = arcs.find((a) => a.trip === first && a.from.id === city.id)
        button.style.animationDelay = `${arc ? Math.max(0, arc.born - now + DRAW_MS * 0.85) : 0}ms`
        d = { id: city.id, lat: city.lat, lng: city.lng, el, signature }
      }
      d.el._city = city
      next.set(city.id, d)
    }
    stampCache.current = next
    return [...next.values()]
  }, [trips, arcs])

  const seal = useMemo(() => {
    const el = document.createElement('div')
    el.className = 'marker seal'
    el.title = `Home · ${home.city}`
    el.innerHTML = homeSeal(home.city)
    return { id: 'home', lat: home.lat, lng: home.lng, el }
  }, [home])

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

  return (
    <div className="globe" ref={wrap}>
      <Globe
        ref={globe}
        width={size.width}
        height={size.height}
        animateIn={false}
        onGlobeReady={onReady}
        backgroundColor="rgba(0,0,0,0)"
        globeImageUrl={texture}
        globeMaterial={material}
        showAtmosphere
        atmosphereColor="#cbbf9f"
        atmosphereAltitude={0.11}
        arcsData={arcs}
        arcStartLat={(d) => d.from.lat}
        arcStartLng={(d) => d.from.lng}
        arcEndLat={(d) => d.to.lat}
        arcEndLng={(d) => d.to.lng}
        arcColor={(d) => [d.color + 'ee', d.color + 'cc']}
        arcStroke={0.42}
        arcAltitudeAutoScale={0.32}
        arcDashLength={1}
        arcDashGap={2}
        arcDashInitialGap={dashGap}
        arcsTransitionDuration={0}
        arcLabel={(d) => `${d.trip.title} · ${d.trip.start_date}`}
        onArcClick={(d) => onTripClick(d.trip)}
        htmlElementsData={[seal, ...markers]}
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
