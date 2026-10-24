import { useEffect, useMemo, useRef, useState } from 'react'
import GlobeView from './GlobeView.jsx'
import { fromStatsFile, homeForYear, inYear, loadData, sentence, storyline, summarize, tripYears, withHome } from './data.js'
import { loadCities, nearestCity } from './geoLayers.js'
import { PAINT_FILTER } from './stamps.js'
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
  const [year, setYear] = useState('all') // 'all' or a year such as '2025'
  const [radius, setRadius] = useState(null) // home-circle radius key ("50"); set from the data's default on load
  const [customHome, setCustomHome] = useState(savedHome)
  const [homeOpen, setHomeOpen] = useState(false)
  const [picking, setPicking] = useState(false)
  const [cursor, setCursor] = useState(null) // replay position in story time (see storyline); null = everything shown
  const [playing, setPlaying] = useState(false) // timeline replay running: the globe follows the lines
  const [replayOpen, setReplayOpen] = useState(false) // explore by default; the timeline only shows for a replay
  const [trip, setTrip] = useState(null)
  const [city, setCity] = useState(null)
  const [selectedId, setSelectedId] = useState(null) // last trip the user opened (named on the timeline)
  const globe = useRef(null)
  const pending = useRef(0) // page waiting for the camera to land

  useEffect(() => {
    loadData()
      .then((d) => {
        setData(d)
        setRadius(d.trips.default_radius_km == null ? null : String(d.trips.default_radius_km))
      })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => () => clearTimeout(pending.current), [])

  const home = customHome ?? data?.trips.home
  // Trips at the chosen home-circle radius (contract 1.1), else the plain 1.0 list.
  const allTrips = useMemo(() => {
    if (!data) return []
    const list = data.trips.trips_by_radius?.[radius] ?? data.trips.trips
    return customHome ? withHome(list, customHome) : list
  }, [data, radius, customHome])

  // Years come from every radius list, so the menu doesn't change when the radius does.
  const years = useMemo(
    () => (data ? tripYears([data.trips.trips, ...Object.values(data.trips.trips_by_radius ?? {})]) : []),
    [data],
  )

  const inRange = useMemo(() => inYear(allTrips, year), [allTrips, year])

  const story = useMemo(() => storyline(inRange), [inRange])

  // The globe may idle-spin only while nothing is open on top of it and no home is being picked.
  useEffect(() => {
    globe.current?.setRotating(!trip && !city && !picking)
  }, [trip, city, picking])

  // Pages cover the globe, so each one opens only once the camera has landed on its place.
  // A newer click replaces a page that is still waiting.
  function afterFlight(ms, open) {
    clearTimeout(pending.current)
    pending.current = setTimeout(open, ms)
  }

  function openTrip(t) {
    setCity(null)
    setSelectedId(t.id)
    afterFlight(globe.current?.flyTo(t) ?? 0, () => setTrip(t))
  }

  function openCity(c) {
    afterFlight(globe.current?.lookAt(c, 0.8) ?? 0, () => setCity(c))
  }

  function closeOverlay() {
    clearTimeout(pending.current)
    setTrip(null)
    setCity(null)
  }

  // Closing the replay shows every stamp and line in full again.
  function closeReplay() {
    setReplayOpen(false)
    setCursor(null)
    setPlaying(false)
  }

  // A new year or radius shows a different set of trips: close any page (or one still waiting
  // for the camera), clear the selection and stop a running replay. The camera stays put.
  function resetView() {
    clearTimeout(pending.current)
    setTrip(null)
    setCity(null)
    setSelectedId(null)
    setCursor(null)
    setPlaying(false)
  }

  function chooseYear(y) {
    setYear(y)
    resetView()
  }

  function chooseRadius(r) {
    setRadius(r)
    resetView()
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
  if (!data) return <div className="loading">Unfolding memories…</div>

  // Totals for the whole selection, not a running count while the timeline plays. stats.json
  // is used when it has this radius and year (the top-level all_time/by_year belong to the
  // default radius); otherwise, or with a custom home (distances re-measured), they are
  // counted from the trips shown.
  const defaultRadius = data.trips.default_radius_km == null ? null : String(data.trips.default_radius_km)
  const radiusOptions = data.trips.radius_options_km ?? []
  const statsSet = data.stats?.by_radius?.[radius] ?? (radius === defaultRadius ? data.stats : null)
  const statsEntry = year === 'all' ? statsSet?.all_time : statsSet?.by_year?.[year]
  const stats = (!customHome && fromStatsFile(statsEntry)) || summarize(inRange)
  const persona = statsEntry?.persona ?? null

  // The dashed home circle: around the chosen home, else the homes entry for the year, else home.
  const circleHome = customHome ?? homeForYear(data.trips.homes, year) ?? data.trips.home
  const homeCircle = { lat: circleHome.lat, lng: circleHome.lng, km: Number(radius) }

  return (
    <div className="app">
      <div dangerouslySetInnerHTML={{ __html: PAINT_FILTER }} />
      <GlobeView
        ref={globe}
        trips={inRange}
        story={story}
        cursor={cursor}
        home={home}
        homeCircle={homeCircle}
        follow={playing}
        picking={picking}
        onPick={pickOnGlobe}
        onTripClick={openTrip}
        onCityClick={openCity}
      />

      <header className="masthead">
        <div className="brand">
          <h1><img src="/postmark-logo.png" alt="Postmark" /></h1>
          <span className="tagline">your camera roll, unfolded into a travel journal</span>
        </div>
        <div className="controls">
          <select className="year-filter" aria-label="Show trips from" value={year} onChange={(e) => chooseYear(e.target.value)}>
            <option value="all">All time</option>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          {radiusOptions.length > 0 && (
            <div className="circle-control" role="group" aria-labelledby="circle-label">
              <span id="circle-label" className="control-label">Home circle<span className="unit-inline"> · km</span></span>
              <div className="range seg">
                {radiusOptions.map((r) => (
                  <button key={r} aria-pressed={String(r) === radius} aria-label={`${r} km`} onClick={() => chooseRadius(String(r))}>
                    {r}
                  </button>
                ))}
              </div>
              <span className="unit" aria-hidden="true">km</span>
            </div>
          )}
        </div>
      </header>

      <section className="summary">
        <p className="sentence">{sentence(year, stats)}</p>
        <p className="home-line">
          <span className="seal-dot" /> Home is {home.city}
          <button className="link change-home" onClick={() => { setHomeOpen((o) => !o); setPicking(false) }}>change</button>
          {persona && <> · Travel persona: {persona}<span className="aside"> (just for fun)</span></>}
        </p>
        {homeOpen && (
          <HomePicker
            home={home}
            detected={data.trips.home}
            picking={picking}
            onPickOnGlobe={() => setPicking((p) => !p)}
            onChoose={chooseHome}
            onReset={resetHome}
            onClose={() => { setHomeOpen(false); setPicking(false) }}
          />
        )}
      </section>

      {/* A new year or radius remounts the timeline, so it starts fresh and stopped. */}
      {inRange.length > 0 && (replayOpen ? (
        <Timeline
          key={`${year}|${radius}`}
          trips={inRange}
          story={story}
          cursor={cursor}
          selectedId={selectedId}
          onCursor={setCursor}
          onOpen={openTrip}
          onPlaying={setPlaying}
          onClose={closeReplay}
        />
      ) : (
        <button className="replay-open" onClick={() => setReplayOpen(true)}>
          <span aria-hidden="true">▶</span> Replay
        </button>
      ))}

      <footer className="privacy">
        Photos are processed only on your own computer · Home is shown at city level only · Map data: GeoNames (CC BY 4.0), Natural Earth
        {data.folder === 'mock' && <span className="badge">sample data</span>}
      </footer>

      {trip && <Logbook trip={allTrips.find((t) => t.id === trip.id) ?? trip} base={data.base} onClose={closeOverlay} />}
      {city && <CityPage city={city} base={data.base} onClose={closeOverlay} onOpenTrip={openTrip} />}
    </div>
  )
}
