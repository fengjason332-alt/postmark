import { useEffect, useMemo, useRef, useState } from 'react'
import GlobeView from './GlobeView.jsx'
import { filterTrips, loadData, sentence, summarize, thisYear } from './data.js'
import { INK_FILTER } from './stamps.js'
import Logbook from './Logbook.jsx'
import CityPage from './CityPage.jsx'
import Timeline from './Timeline.jsx'

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [range, setRange] = useState('all')
  const [cursor, setCursor] = useState(null) // ISO date; trips starting after it are hidden
  const [trip, setTrip] = useState(null)
  const [city, setCity] = useState(null)
  const globe = useRef(null)

  useEffect(() => {
    loadData().then(setData).catch((e) => setError(e.message))
  }, [])

  const inRange = useMemo(() => (data ? filterTrips(data.trips.trips, range === 'year' ? thisYear() : 'all') : []), [data, range])

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

  if (error) return <div className="loading">Could not load trips: {error}</div>
  if (!data) return <div className="loading">Opening the map…</div>

  const { home } = data.trips
  const stats = summarize(visible)
  const persona = range === 'year' ? data.stats?.by_year?.[thisYear()]?.persona : data.stats?.all_time?.persona

  return (
    <div className="app">
      <div dangerouslySetInnerHTML={{ __html: INK_FILTER }} />
      <GlobeView ref={globe} trips={visible} home={home} onTripClick={openTrip} onCityClick={openCity} />

      <header className="masthead">
        <div className="brand">
          <h1>Postmark</h1>
          <span className="tagline">your camera roll, bound into a travel journal</span>
        </div>
        <div className="range" role="tablist" aria-label="Time range">
          <button role="tab" aria-selected={range === 'year'} onClick={() => { setRange('year'); setCursor(null) }}>This year</button>
          <button role="tab" aria-selected={range === 'all'} onClick={() => { setRange('all'); setCursor(null) }}>All time</button>
        </div>
      </header>

      <section className="summary">
        <p className="sentence">{sentence(range, stats)}</p>
        <p className="home-line">
          <span className="seal-dot" /> Home is {home.city}
          {persona && <> · Travel persona: {persona}<span className="aside"> (just for fun)</span></>}
        </p>
      </section>

      <Timeline trips={inRange} cursor={cursor} onCursor={setCursor} onOpen={openTrip} />

      <footer className="privacy">
        Photos are processed only on your own computer · Home is shown at city level only · City data: GeoNames (CC BY 4.0)
        {data.folder === 'mock' && <span className="badge">sample data</span>}
      </footer>

      {trip && <Logbook trip={trip} base={data.base} onClose={closeOverlay} />}
      {city && <CityPage city={city} base={data.base} onClose={closeOverlay} onOpenTrip={openTrip} />}
    </div>
  )
}
