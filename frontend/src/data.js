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
export const tripDrawMs = (trip) => (trip.cities.length + 1) * (DRAW_MS + PAUSE_MS)

const R = 6371
const rad = (d) => (d * Math.PI) / 180
export function distanceKm(a, b) {
  const h = Math.sin(rad(b.lat - a.lat) / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(rad(b.lng - a.lng) / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

// When the user picks their own home, re-estimate each trip's distance the same way the
// backend does: home -> each city in order -> home, straight lines.
export function withHome(trips, home) {
  return trips.map((t) => {
    const path = [home, ...t.cities, home]
    let km = 0
    for (let i = 0; i < path.length - 1; i++) km += distanceKm(path[i], path[i + 1])
    return { ...t, distance_km: Math.round(km) }
  })
}

export const thisYear = () => String(new Date().getFullYear())

export function filterTrips(trips, range) {
  if (range === 'all') return trips
  return trips.filter((t) => t.start_date.startsWith(range) || t.end_date.startsWith(range))
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

// The journal-style sentence under the title, e.g. "This year you spent 47 days away and wandered through 6 cities."
export function sentence(range, s) {
  if (s.trips === 0) return range === 'all' ? 'No trips found yet.' : 'No trips yet this year. The globe is waiting.'
  const who = range === 'all' ? 'Over the years you' : 'This year you'
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
