import { useEffect, useMemo, useRef, useState } from 'react'
import { shortDate, dateRange, photosByDay, tripColor } from './data.js'
import { postmark } from './stamps.js'
import { citiesOf } from './data.js'
import { paintingTitle, usePainting } from './painterly.js'

// A trip opens as a book: the cover, then the days, a few photos to a page, two pages to
// a spread (one on phones). However many photos a trip has, it is just more pages, and
// only the open spread's photos are loaded and painted.
const PER_PAGE = 5 // one large photo and four small ones

function bookPages(trip) {
  const pages = [{ kind: 'cover' }]
  for (const day of photosByDay(trip)) {
    const parts = Math.ceil(day.photos.length / PER_PAGE)
    for (let i = 0; i < parts; i++) pages.push({ kind: 'day', day, part: i, parts, photos: day.photos.slice(i * PER_PAGE, (i + 1) * PER_PAGE) })
  }
  return pages
}

const usePerView = () => {
  const query = '(max-width: 720px)'
  const [one, setOne] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const on = () => setOne(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return one ? 1 : 2
}

export default function Logbook({ trip, base, onClose }) {
  const [photo, setPhoto] = useState(null)
  const [at, setAt] = useState(0) // first page on show, so the place survives a switch between one and two pages
  const [dir, setDir] = useState('next')
  useEscape(photo ? () => setPhoto(null) : onClose)
  const color = tripColor(trip)
  const cityName = Object.fromEntries(trip.cities.map((c) => [c.id, c.name]))
  const pages = useMemo(() => bookPages(trip), [trip])
  const perView = usePerView()
  const spreads = Math.ceil(pages.length / perView)
  const open = Math.min(Math.floor(at / perView), spreads - 1)
  const shown = pages.slice(open * perView, open * perView + perView)

  const go = (to) => {
    const next = Math.max(0, Math.min(spreads - 1, to))
    if (next === open) return
    setDir(next > open ? 'next' : 'prev')
    setAt(next * perView)
  }
  // Arrow keys turn the pages (unless a photo is open).
  useEffect(() => {
    if (photo) return undefined
    const onKey = (e) => {
      if (e.target.closest?.('input')) return // the pager slider handles its own arrows
      if (e.key === 'ArrowRight') go(open + 1)
      if (e.key === 'ArrowLeft') go(open - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const current = shown.find((p) => p.kind === 'day')
  return (
    <div className="overlay" onClick={onClose}>
      <article className={`book ${perView === 1 ? 'single' : ''} ${spreads > 1 ? 'paged' : ''}`} style={{ '--trip': color }} onClick={(e) => e.stopPropagation()} aria-label={`${trip.title} logbook`}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        <div className={`spread turn-${dir}`} key={`${open}-${perView}`}>
          {shown.map((page, i) =>
            page.kind === 'cover'
              ? <Cover key="cover" trip={trip} base={base} color={color} onPhoto={setPhoto} />
              : <DayPage key={`${page.day.date}-${page.part}`} page={page} base={base} color={color} cityName={cityName} onPhoto={setPhoto} side={i} />,
          )}
          {shown.length < perView && <section className="page leaf endpaper"><p className="hand">The end of this trip. Until the next one.</p></section>}
        </div>
        {spreads > 1 && (
          <>
            <button className="turn prev" onClick={() => go(open - 1)} disabled={open === 0} aria-label="Previous pages">‹</button>
            <button className="turn next" onClick={() => go(open + 1)} disabled={open === spreads - 1} aria-label="Next pages">›</button>
            <footer className="pager">
              <span>{current ? `Day ${current.day.dayNumber} · ${shortDate(current.day.date)}` : 'Cover'}</span>
              <input type="range" min={0} max={spreads - 1} value={open} onChange={(e) => go(+e.target.value)} aria-label="Page" />
              <span>{open + 1} / {spreads}</span>
            </footer>
          </>
        )}
      </article>
      {photo && <Lightbox photo={photo} base={base} place={cityName[photo.city_id]} onClose={() => setPhoto(null)} />}
    </div>
  )
}

function Cover({ trip, base, color, onPhoto }) {
  const cover = trip.photos.find((p) => p.id === trip.cover_photo_id) ?? trip.photos[0]
  const countries = new Set(trip.cities.map((c) => c.country_code)).size
  return (
    <section className="page leaf cover">
      <p className="hand kicker">Logbook No.{String(trip.index + 1).padStart(2, '0')}</p>
      <h2>{trip.title}</h2>
      <p className="dates">{dateRange(trip)}</p>
      <p className="facts">
        {trip.days} days · {trip.cities.length} {trip.cities.length === 1 ? 'city' : 'cities'}{countries > 1 ? ` · ${countries} countries` : ''} · ~{trip.distance_km.toLocaleString('en-US')} km · {trip.photo_count} photos
      </p>
      {cover && (
        <figure className="taped big" onClick={() => onPhoto(cover)}>
          <Picture src={base + cover.thumb} alt={`${trip.title} cover`} />
        </figure>
      )}
      <ol className="route">
        {trip.cities.map((c) => (
          <li key={c.id}>
            <span className="hand">{shortDate(c.arrive)}</span> {c.name}
            <span className="muted"> · {c.photo_count} photos</span>
          </li>
        ))}
      </ol>
      {trip.cities.length > 0 && <div className="cover-stamp" dangerouslySetInnerHTML={{ __html: postmark(citiesOf([trip])[0], color) }} />}
    </section>
  )
}

// One page of a day: the day's heading on its first page, then one large photo and up to four small.
function DayPage({ page, base, color, cityName, onPhoto }) {
  const { day, part, parts, photos } = page
  return (
    <section className="page leaf day-page">
      <header className="day-head">
        <span className="hand day-no">Day {day.dayNumber}</span>
        <span className="day-date">{shortDate(day.date)}</span>
        {part === 0
          ? <span className="day-cities">{[...new Set(day.photos.map((p) => cityName[p.city_id]).filter(Boolean))].join(' → ')}</span>
          : <span className="day-cities">continued</span>}
        {parts > 1 && <span className="muted page-part">{part + 1} of {parts}</span>}
        {part === 0 && <RouteSketch photos={day.photos} color={color} />}
      </header>
      <div className={`plate n${photos.length}`}>
        {photos.map((p, i) => (
          <figure key={p.id} className="taped" onClick={() => onPhoto(p)}>
            <Picture src={base + p.thumb} alt={`${shortDate(p.date)} ${cityName[p.city_id] ?? ''}`} />
            {i === 0 && <figcaption className="title">{paintingTitle(p)}</figcaption>}
            {!p.has_gps && <figcaption className="hand">no location</figcaption>}
          </figure>
        ))}
      </div>
    </section>
  )
}

// A tiny pen sketch of the day's route from the GPS points, in order.
function RouteSketch({ photos, color }) {
  const pts = photos.filter((p) => p.has_gps)
  if (pts.length < 2) return null
  const lats = pts.map((p) => p.lat)
  const lngs = pts.map((p) => p.lng)
  const [minLat, maxLat, minLng, maxLng] = [Math.min(...lats), Math.max(...lats), Math.min(...lngs), Math.max(...lngs)]
  const span = Math.max(maxLat - minLat, maxLng - minLng, 0.01)
  const xy = pts.map((p) => [8 + ((p.lng - minLng) / span) * 54, 62 - ((p.lat - minLat) / span) * 54])
  return (
    <svg className="sketch" viewBox="0 0 70 70" aria-hidden="true">
      <polyline points={xy.map((p) => p.join(',')).join(' ')} fill="none" stroke={color} strokeWidth="1.4" strokeDasharray="3 2" strokeLinecap="round" />
      {xy.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={i === 0 ? 2.6 : 1.8} fill={color} />)}
    </svg>
  )
}

// Photos are shown as small paintings made from them on this device. A photo is only
// loaded and painted once it is about to scroll into view.
export function Picture({ src, alt, loading, ...rest }) {
  const [near, setNear] = useState(loading !== 'lazy')
  const holder = useRef(null)
  useEffect(() => {
    if (near || !holder.current) return undefined
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setNear(true), { rootMargin: '300px' })
    io.observe(holder.current)
    return () => io.disconnect()
  }, [near])
  const painted = usePainting(src, near)
  return painted ? <img src={painted} alt={alt} {...rest} /> : <span ref={holder} className="painting-wait" role="img" aria-label={alt} />
}

// The photo on top and the painting made from it below, like a page from a sketchbook.
export function Lightbox({ photo, base, place, onClose }) {
  const time = photo.taken_at.slice(11, 16)
  const painted = usePainting(base + photo.full)
  return (
    <div className="lightbox gouache-card" onClick={(e) => { e.stopPropagation(); onClose() }}>
      <figure>
        <img className="original" src={base + photo.full} alt="The original photo" />
        {painted ? <img className="painting" src={painted} alt="A gouache painting made from the photo" /> : <span className="painting-wait big" />}
        <figcaption>
          <strong>{paintingTitle(photo)}</strong>
          <span>{shortDate(photo.date)}, {time} {place ? `· ${place}` : '· no location'}</span>
        </figcaption>
      </figure>
    </div>
  )
}

export function useEscape(fn) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && fn()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fn])
}
