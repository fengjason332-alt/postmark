import { useEffect, useMemo, useRef, useState } from 'react'
import { shortDate, dateRange, photosByDay, tripColor } from './data.js'
import { postmark } from './stamps.js'
import { citiesOf } from './data.js'
import { paintingTitle, usePainting } from './painterly.js'

// A trip opens as a book: the cover, then the days, a few photos to a page, two pages to
// a spread (one on phones). However many photos a trip has, it is just more pages, and
// only the open spread's photos are loaded and painted.
const PER_PAGE = 5 // one large photo and four small ones
const TURN_MS = 800 // how long a full page turn takes when a key or button starts it

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
  const [turn, setTurn] = useState(null) // a page being turned: { from, to, dir }, spread numbers
  const turnRef = useRef(null) // the same turn, readable from event handlers and frames
  const pRef = useRef(0) // how far the sheet has turned: 0 = flat, 1 = landed on the other side
  const raf = useRef(0)
  const sheetEl = useRef(null)
  const autoPlay = useRef(false) // a turn started by a key or button plays itself; a drag is driven by the pointer
  const grab = useRef(null)
  const suppressClick = useRef(false)
  useEffect(() => () => cancelAnimationFrame(raf.current), [])
  useEscape(photo ? () => setPhoto(null) : onClose)
  const color = tripColor(trip)
  const cityName = Object.fromEntries(trip.cities.map((c) => [c.id, c.name]))
  const pages = useMemo(() => bookPages(trip), [trip])
  const perView = usePerView()
  const spreads = Math.ceil(pages.length / perView)
  const open = Math.min(Math.floor(at / perView), spreads - 1)
  const shown = pages.slice(open * perView, open * perView + perView)

  // The turning sheet is driven by one number, pRef (0 to 1), written straight to the element
  // as CSS variables so a drag does not re-render the whole book on every pointer move.
  const applyP = (p) => {
    pRef.current = p
    const el = sheetEl.current
    if (!el) return
    el.style.setProperty('--p', p)
    el.style.setProperty('--bend', Math.sin(p * Math.PI)) // the page bows most halfway through
  }
  const animateTo = (target, done) => {
    cancelAnimationFrame(raf.current)
    const from = pRef.current
    const ms = Math.max(160, TURN_MS * Math.abs(target - from))
    const t0 = performance.now()
    const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2)
    const step = (now) => {
      const t = Math.min(1, (now - t0) / ms)
      applyP(from + (target - from) * ease(t))
      if (t < 1) raf.current = requestAnimationFrame(step)
      else done()
    }
    raf.current = requestAnimationFrame(step)
  }
  const beginTurn = (dir) => {
    const t = { from: open, to: open + (dir === 'next' ? 1 : -1), dir }
    turnRef.current = t
    pRef.current = 0
    setTurn(t)
  }
  const finishTurn = (t, completed) => {
    if (completed) setAt(t.to * perView)
    turnRef.current = null
    setTurn(null)
  }
  useEffect(() => {
    if (!turn || !autoPlay.current) return
    autoPlay.current = false
    animateTo(1, () => finishTurn(turn, true))
  }, [turn]) // eslint-disable-line react-hooks/exhaustive-deps

  const go = (to) => {
    if (turnRef.current) return // one page at a time
    const next = Math.max(0, Math.min(spreads - 1, to))
    if (next === open) return
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (Math.abs(next - open) !== 1 || reduced) { // a jump from the pager slider: no page to turn
      setAt(next * perView)
      return
    }
    autoPlay.current = true
    beginTurn(next > open ? 'next' : 'prev')
  }

  // Grab a page and drag it like a real book: pull the right page left to go on, the left page
  // right to go back (either way on a phone, where one page shows). The page edge follows the
  // pointer; let go past halfway, or flick, and it lands; otherwise it falls back.
  const onDown = (e) => {
    if (turnRef.current || spreads < 2 || (e.pointerType === 'mouse' && e.button !== 0)) return
    const rect = e.currentTarget.getBoundingClientRect()
    grab.current = {
      id: e.pointerId, x0: e.clientX, y0: e.clientY, started: false, dir: null, lastP: 0, lastT: 0, v: 0,
      side: perView === 1 ? 'both' : e.clientX >= rect.left + rect.width / 2 ? 'right' : 'left',
      w: perView === 2 ? rect.width / 2 : rect.width,
    }
  }
  const onMove = (e) => {
    const g = grab.current
    if (!g || e.pointerId !== g.id) return
    const dx = e.clientX - g.x0
    if (!g.started) {
      const dy = e.clientY - g.y0
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return
      const dir = dx < 0 ? 'next' : 'prev'
      const allowed = g.side === 'both' || (g.side === 'right') === (dir === 'next')
      const exists = dir === 'next' ? open < spreads - 1 : open > 0
      if (Math.abs(dx) < Math.abs(dy) || !allowed || !exists) { // a scroll or an impossible turn: leave it alone
        grab.current = null
        return
      }
      g.started = true
      g.dir = dir
      g.x0 = e.clientX
      e.currentTarget.setPointerCapture(e.pointerId)
      beginTurn(dir)
      return
    }
    const d = g.dir === 'next' ? g.x0 - e.clientX : e.clientX - g.x0
    const p = Math.acos(Math.max(-1, Math.min(1, 1 - (2 * d) / g.w))) / Math.PI // the page edge stays under the pointer
    const now = performance.now()
    if (g.lastT) g.v = (p - g.lastP) / Math.max(1, now - g.lastT)
    g.lastP = p
    g.lastT = now
    applyP(p)
  }
  const onUp = (e) => {
    const g = grab.current
    if (!g || e.pointerId !== g.id) return
    grab.current = null
    if (!g.started) return
    suppressClick.current = true // the drag must not also count as a click on a photo
    setTimeout(() => { suppressClick.current = false }, 60)
    const t = turnRef.current
    const complete = pRef.current > 0.5 ? g.v > -0.0015 : g.v > 0.0015 // past halfway lands, unless pulled back; a flick lands
    animateTo(complete ? 1 : 0, () => finishTurn(t, complete))
  }

  // One leaf of the book: the cover, a day page, or the empty end paper after the last page.
  const leafAt = (idx) => {
    const page = pages[idx]
    if (!page) return <section key="end" className="page leaf endpaper"><p className="hand">The end of this trip. Until the next one.</p></section>
    return page.kind === 'cover'
      ? <Cover key="cover" trip={trip} base={base} color={color} onPhoto={setPhoto} />
      : <DayPage key={`${page.day.date}-${page.part}`} page={page} base={base} color={color} cityName={cityName} onPhoto={setPhoto} />
  }
  // While a page turns, the pages underneath are the ones that stay or get uncovered; the turning
  // sheet carries the old page on its front and the page that lands on the other side on its back.
  let slots = Array.from({ length: perView }, (_, i) => open * perView + i)
  let sheet = null
  if (turn) {
    const { from, to, dir } = turn
    if (perView === 2) {
      slots = dir === 'next' ? [from * 2, to * 2 + 1] : [to * 2, from * 2 + 1]
      sheet = { dir, front: dir === 'next' ? from * 2 + 1 : from * 2, back: dir === 'next' ? to * 2 : to * 2 + 1 }
    } else {
      slots = [to]
      sheet = { dir, front: from, back: null }
    }
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
        <div
          className={`spread ${turn ? 'turning' : ''}`}
          key={perView}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={onUp}
          onClickCapture={(e) => {
            if (suppressClick.current) { e.stopPropagation(); e.preventDefault() }
          }}
        >
          {slots.map((idx) => leafAt(idx))}
          {sheet && (
            <div
              className={`sheet sheet-${sheet.dir} ${perView === 1 ? 'one' : ''}`}
              aria-hidden="true"
              ref={(el) => {
                sheetEl.current = el
                if (el) applyP(pRef.current)
              }}
            >
              <div className="sheet-face front">{leafAt(sheet.front)}</div>
              <div className="sheet-face back">{sheet.back === null ? <section className="page leaf" /> : leafAt(sheet.back)}</div>
            </div>
          )}
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
