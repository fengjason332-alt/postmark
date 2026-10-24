import { useEffect, useMemo, useRef, useState } from 'react'
import GlobeView from './GlobeView.jsx'
import { filterTrips, initialStyle, loadData, sentence, setPalette, STYLES, summarize, thisYear, withHome } from './data.js'
import { loadCities, nearestCity } from './geoLayers.js'
import { INK_FILTER } from './stamps.js'
import Logbook from './Logbook.jsx'
import CityPage from './CityPage.jsx'
import Timeline from './Timeline.jsx'
import HomePicker from './HomePicker.jsx'

const HOME_KEY = 'postmark.home'

function savedHome() {
  try {
    const h = JSON.parse(localStorage.getItem(HOME_KEY))
    return h && typeof h.lat === 'number' && typeof h.lng === 'number' ? h : null
  } catch {
    return null
  }
}

function store(key, value) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value))
  } catch {
    // storage blocked (private window): the choice just won't survive a reload
  }
}

const round4 = (n) => Math.round(n * 1e4) / 1e4

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [range, setRange] = useState('all')
  const [style, setStyle] = useState(initialStyle)
  const [customHome, setCustomHome] = useState(savedHome)
  const [homeOpen, setHomeOpen] = useState(false)
  const [picking, setPicking] = useState(false)
  const [cursor, setCursor] = useState(null) // ISO date; trips starting after it are hidden
  const [trip, setTrip] = useState(null)
  const [city, setCity] = useState(null)
  const globe = useRef(null)

  setPalette(style)
  useEffect(() => {
    document.documentElement.dataset.style = style
    store('postmark.style', style)
  }, [style])

  useEffect(() => {
    loadData().then(setData).catch((e) => setError(e.message))
  }, [])

  const home = customHome ?? data?.trips.home
  const allTrips = useMemo(() => {
    if (!data) return []
    return customHome ? withHome(data.trips.trips, customHome) : data.trips.trips
  }, [data, customHome])

  const inRange = useMemo(() => filterTrips(allTrips, range === 'year' ? thisYear() : 'all'), [allTrips, range])

  // Only hand the globe a new list when the set of visible trips changes, not on every timeline tick.
  const visibleKey = inRange.filter((t) => !cursor || t.start_date <= cursor).map((t) => t.id).join('|')
  const visible = useMemo(() => inRange.filter((t) => visibleKey.split('|').includes(t.id)), [inRange, visibleKey])

  function openTrip(t) {
    setCity(null)
    globe.current?.flyTo(t)
    setTimeout(() => setTrip(t), 700)
  }

  function openCity(c) {
    globe.current?.setRotating(false)
    setCity(c)
  }

  function closeOverlay() {
    setTrip(null)
    setCity(null)
    globe.current?.setRotating(true)
  }

  function chooseHome(c) {
    const h = { city: c.name, country: c.country, country_code: c.country_code, lat: round4(c.lat), lng: round4(c.lng) }
    setCustomHome(h)
    store(HOME_KEY, h)
    setPicking(false)
    setHomeOpen(false)
    globe.current?.lookAt(h, 2)
  }

  async function pickOnGlobe(pt) {
    const cities = await loadCities()
    chooseHome(nearestCity(cities, pt))
  }

  function resetHome() {
    setCustomHome(null)
    store(HOME_KEY, null)
    setHomeOpen(false)
    setPicking(false)
    globe.current?.lookAt(data.trips.home, 2)
  }

  if (error) return <div className="loading">Could not load trips: {error}</div>
  if (!data) return <div className="loading">Opening the map…</div>

  const stats = summarize(visible)
  const persona = range === 'year' ? data.stats?.by_year?.[thisYear()]?.persona : data.stats?.all_time?.persona

  return (
    <div className="app">
      <div dangerouslySetInnerHTML={{ __html: INK_FILTER }} />
      <GlobeView
        ref={globe}
        trips={visible}
        home={home}
        style={style}
        picking={picking}
        onPick={pickOnGlobe}
        onTripClick={openTrip}
        onCityClick={openCity}
      />

      <header className="masthead">
        <div className="brand">
          <h1>Postmark</h1>
          <span className="tagline">your camera roll, bound into a travel journal</span>
        </div>
        <div className="controls">
          <div className="range" role="tablist" aria-label="Time range">
            <button role="tab" aria-selected={range === 'year'} onClick={() => { setRange('year'); setCursor(null) }}>This year</button>
            <button role="tab" aria-selected={range === 'all'} onClick={() => { setRange('all'); setCursor(null) }}>All time</button>
          </div>
          <div className="range small" role="tablist" aria-label="Look">
            {Object.entries(STYLES).map(([key, s]) => (
              <button key={key} role="tab" aria-selected={style === key} onClick={() => setStyle(key)}>{s.label}</button>
            ))}
          </div>
        </div>
      </header>

      <section className="summary">
        <p className="sentence">{sentence(range, stats)}</p>
        <p className="home-line">
          <span className="seal-dot" /> Home is {home.city}
          <button className="link change-home" onClick={() => setHomeOpen((o) => !o)}>change</button>
          {persona && <> · Travel persona: {persona}<span className="aside"> (just for fun)</span></>}
        </p>
        {homeOpen && (
          <HomePicker
            home={home}
            detected={data.trips.home}
            picking={picking}
            onPickOnGlobe={() => { setPicking((p) => !p); globe.current?.setRotating(false) }}
            onChoose={chooseHome}
            onReset={resetHome}
            onClose={() => { setHomeOpen(false); setPicking(false) }}
          />
        )}
      </section>

      <Timeline trips={inRange} cursor={cursor} onCursor={setCursor} onOpen={openTrip} />

      <footer className="privacy">
        Photos are processed only on your own computer · Home is shown at city level only · Map data: GeoNames (CC BY 4.0), Natural Earth
        {data.folder === 'mock' && <span className="badge">sample data</span>}
      </footer>

      {trip && <Logbook trip={allTrips.find((t) => t.id === trip.id) ?? trip} base={data.base} onClose={closeOverlay} />}
      {city && <CityPage city={city} base={data.base} onClose={closeOverlay} onOpenTrip={openTrip} />}
    </div>
  )
}
