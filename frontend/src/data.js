// Loading and shaping trips.json / stats.json (see the backend contract in the PRD).

const BASE = import.meta.env.BASE_URL

// Real data lives in public/data/, hand-written mock data in public/mock/.
// ?data=mock forces the mock; otherwise real data is used when it exists.
export async function loadData() {
  const forced = new URLSearchParams(location.search).get('data')
  const folders = forced ? [forced] : ['data', 'mock']
  for (const folder of folders) {
    try {
      const trips = await fetchJson(`${BASE}${folder}/trips.json`)
      const stats = await fetchJson(`${BASE}${folder}/stats.json`).catch(() => null)
      return { folder, base: `${BASE}${folder}/`, trips, stats }
    } catch {
      // Vite answers missing files with index.html, so a failed parse means "not there yet".
    }
  }
  throw new Error('trips.json not found')
}

async function fetchJson(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${url}`)
  return res.json()
}

// One colour per trip, cycled by trip index: muted gouache pigments (indigo, rust, ochre, sage...).
export const PALETTE = ['#34557a', '#a8473a', '#b8862a', '#4f6b52', '#6e4a63', '#2f3a45']
export const BORDER_COLOR = '#3a4552'
export const tripColor = (trip) => PALETTE[trip.index % PALETTE.length]

// Trip line timing, shared by the globe (drawing) and the timeline replay (pacing).
export const DRAW_MS = 1700 // how long one leg of a trip takes to draw itself
export const PAUSE_MS = 600 // rest at each city (the stamp lands) before the next leg starts

// The timeline runs on one continuous clock in days (day 0 = 1970-01-01, fractions = time of day).
const DAY = 86400000
export const dayNumber = (iso) => Math.round(new Date(iso + 'T00:00:00Z').getTime() / DAY)
export const isoDay = (n) => new Date(Math.floor(n) * DAY).toISOString().slice(0, 10)

// When each leg (home -> first city -> ... -> home) leaves and lands on that clock.
// Legs set off in the morning of the leaving day and land in the afternoon of the arriving day.
export function legTimes(trip) {
  const n = trip.cities.length
  const legs = []
  let ready = -Infinity
  for (let i = 0; i <= n; i++) {
    const leave = i === 0 ? trip.start_date : trip.cities[i - 1].leave ?? trip.cities[i - 1].arrive
    const land = i === n ? trip.end_date : trip.cities[i].arrive ?? leave
    const depart = Math.max(ready, dayNumber(leave) + 0.3)
    const arrive = Math.max(depart + 0.2, dayNumber(land) + 0.6)
    legs.push({ depart, arrive })
    ready = arrive
  }
  return legs
}

// The replay clock ("story time"), measured in leg-drawing times. Every leg gets the same
// stretch of the bar, so the bar moves at an even pace and a line is always exactly as far
// along as the bar is through its stretch. Dates on the bar are read off at each leg's ends.
export const STAY = PAUSE_MS / DRAW_MS // the stamp landing between two legs
export const GAP = 0.7 // the calendar running on between two trips
export function storyline(trips) {
  const legs = {} // trip id -> [{ start, end }] in story time
  const keys = [] // [story time, day number] points the bar's date is read from
  if (!trips.length) return { legs, total: 0, dayAt: () => 0 }
  keys.push([0, dayNumber(trips[0].start_date)])
  let pos = GAP
  for (const trip of trips) {
    legs[trip.id] = legTimes(trip).map((leg) => {
      keys.push([pos, leg.depart])
      const span = { start: pos, end: pos + 1 }
      keys.push([span.end, leg.arrive])
      pos = span.end + STAY
      return span
    })
    pos += GAP
  }
  const last = dayNumber(trips[trips.length - 1].end_date) + 0.99 // the date never runs past the last trip
  keys.push([pos, last])
  const dayAt = (t) => {
    let i = 1
    while (i < keys.length - 1 && keys[i][0] < t) i++
    const [t0, d0] = keys[i - 1]
    const [t1, d1] = keys[i]
    return Math.min(last, d0 + (d1 - d0) * Math.max(0, Math.min(1, (t - t0) / (t1 - t0 || 1))))
  }
  return { legs, total: pos, dayAt }
}

const R = 6371
const rad = (d) => (d * Math.PI) / 180
export function distanceKm(a, b) {
  const h = Math.sin(rad(b.lat - a.lat) / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(rad(b.lng - a.lng) / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

// When the user picks their own home, re-estimate each trip's distance the same way the
// backend does (AGENTS.md §6): one way, home -> each city in visit order, straight lines.
// With the detected home, the backend's own distance_km is used as is.
export function withHome(trips, home) {
  return trips.map((t) => {
    const path = [home, ...t.cities]
    let km = 0
    for (let i = 0; i < path.length - 1; i++) km += distanceKm(path[i], path[i + 1])
    return { ...t, distance_km: Math.round(km) }
  })
}

export const thisYear = () => String(new Date().getFullYear())

// Every calendar year that some trip touches, newest first (a trip over New Year counts for both).
export function tripYears(tripLists) {
  const years = new Set()
  for (const list of tripLists) {
    for (const t of list ?? []) {
      for (let y = +t.start_date.slice(0, 4); y <= +t.end_date.slice(0, 4); y++) years.add(String(y))
    }
  }
  return [...years].sort((a, b) => b - a)
}

// Trips that overlap the year ('all' keeps every trip).
export function inYear(trips, year) {
  if (year === 'all') return trips
  return trips.filter((t) => t.start_date <= `${year}-12-31` && t.end_date >= `${year}-01-01`)
}

// The homes entry (AGENTS.md §6) that covers most of the year (the later one on a tie);
// null for 'all' or a year no entry touches.
export function homeForYear(homes, year) {
  if (year === 'all' || !homes?.length) return null
  const first = dayNumber(`${year}-01-01`)
  const last = dayNumber(`${year}-12-31`)
  let best = null
  let bestDays = 0
  for (const h of homes) {
    const days = Math.min(last, dayNumber(h.to_date)) - Math.max(first, dayNumber(h.from_date)) + 1
    if (days > 0 && days >= bestDays) {
      best = h
      bestDays = days
    }
  }
  return best
}

// A stats.json entry in the shape summarize() returns; null if it lacks a number.
export function fromStatsFile(s) {
  const out = { trips: s?.trips, days: s?.days_away, km: s?.distance_km, cities: s?.cities, countries: s?.countries }
  return Object.values(out).every((n) => typeof n === 'number') ? out : null
}

// Every city on the globe, merged across trips so repeat visits stack on one postmark.
export function citiesOf(trips) {
  const byId = new Map()
  for (const trip of trips) {
    for (const c of trip.cities) {
      if (!byId.has(c.id)) byId.set(c.id, { ...c, photo_count: 0, visits: [] })
      const city = byId.get(c.id)
      city.photo_count += c.photo_count
      city.visits.push({ trip, arrive: c.arrive, leave: c.leave, photo_count: c.photo_count })
    }
  }
  return [...byId.values()]
}

export function summarize(trips) {
  const cities = new Set()
  const countries = new Set()
  let days = 0
  let km = 0
  for (const t of trips) {
    days += t.days
    km += t.distance_km
    t.cities.forEach((c) => {
      cities.add(c.id)
      countries.add(c.country_code)
    })
  }
  return { trips: trips.length, days, km, cities: cities.size, countries: countries.size }
}

const fmt = (n) => n.toLocaleString('en-US')

const count = (n, one, many) => `${n} ${n === 1 ? one : many}`

// The journal-style sentence under the title, e.g. "In 2025 you spent 47 days away and wandered through 6 cities."
// `year` is 'all' or a year such as '2025'.
export function sentence(year, s) {
  const current = year === thisYear()
  if (s.trips === 0) {
    if (year === 'all') return 'No trips found yet.'
    return current ? 'No trips yet this year. The globe is waiting.' : `No trips found in ${year}.`
  }
  const who = year === 'all' ? 'Over the years you' : current ? 'This year you' : `In ${year} you`
  const countries = s.countries > 1 ? ` in ${count(s.countries, 'country', 'countries')}` : ''
  return `${who} spent ${count(s.days, 'day', 'days')} away from home, wandered through ${count(s.cities, 'city', 'cities')}${countries}, and covered about ${fmt(s.km)} km.`
}

export const dotDate = (iso) => iso.replaceAll('-', '.')
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export const shortDate = (iso) => `${MONTH_NAMES[+iso.slice(5, 7) - 1]} ${+iso.slice(8, 10)}`

export function dateRange(trip) {
  const sameYear = trip.start_date.slice(0, 4) === trip.end_date.slice(0, 4)
  return `${dotDate(trip.start_date)} — ${sameYear ? dotDate(trip.end_date).slice(5) : dotDate(trip.end_date)}`
}

// Photos grouped into days, in order, for the logbook pages.
export function photosByDay(trip) {
  const days = new Map()
  for (const p of trip.photos) {
    if (!days.has(p.date)) days.set(p.date, [])
    days.get(p.date).push(p)
  }
  const start = new Date(trip.start_date + 'T00:00:00Z')
  return [...days.entries()].map(([date, photos]) => ({
    date,
    dayNumber: Math.round((new Date(date + 'T00:00:00Z') - start) / 86400000) + 1,
    photos,
  }))
}

// Small deterministic jitter so taped photos tilt the same way on every render.
export function jitter(id, range = 1) {
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) | 0
  return ((((h % 1000) + 1000) % 1000) / 1000 - 0.5) * 2 * range
}
