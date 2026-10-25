import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { PageFlip } from 'page-flip'
import { shortDate, dateRange, photosByDay, tripColor } from './data.js'
import { postmark } from './stamps.js'
import { citiesOf } from './data.js'
import { paintingTitle, prepare, usePainting } from './painterly.js'
import { coverPaper, pagePaper } from './paper.js'

// A trip opens as a book: the cover, then the days, a few photos to a page, and an end paper.
// However many photos a trip has, it is just more pages, and only the pages on show are
// loaded and painted. The pages turn like paper (page-flip, MIT): drag a page or its corner,
// click a corner, swipe on a phone, or use the arrow keys, the buttons and the pager.
const PER_PAGE = 5 // one large photo and four small ones
const PAGE_RATIO = 0.78 // page width / height

function bookPages(trip) {
  const pages = [{ kind: 'cover', key: 'cover' }]
  for (const day of photosByDay(trip)) {
    const parts = Math.ceil(day.photos.length / PER_PAGE)
    for (let i = 0; i < parts; i++) pages.push({ kind: 'day', key: `${day.date}-${i}`, day, part: i, parts, photos: day.photos.slice(i * PER_PAGE, (i + 1) * PER_PAGE) })
  }
  pages.push({ kind: 'end', key: 'end' })
  return pages
}

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

// Turn one page from code (keys, buttons). page-flip treats these as clicks on a corner, and
// with "corner clicks only" on it can miss the corner of a single page, so lift that briefly.
function turnPage(pf, dir) {
  if (!pf) return
  const settings = pf.getSettings()
  const was = settings.disableFlipByClick
  settings.disableFlipByClick = false
  try {
    if (dir > 0) pf.flipNext('bottom')
    else pf.flipPrev('bottom')
  } finally {
    settings.disableFlipByClick = was
  }
}

export default function Logbook({ trip, base, onClose }) {
  const [photo, setPhoto] = useState(null)
  const [at, setAt] = useState(0) // the page index page-flip reports as open
  const flip = useRef(null)
  const moved = useRef(false)
  useEscape(photo ? () => setPhoto(null) : onClose)
  const color = tripColor(trip)
  const cityName = Object.fromEntries(trip.cities.map((c) => [c.id, c.name]))
  const pages = useMemo(() => bookPages(trip), [trip])
  const openPhoto = (p, el) => setPhoto({ p, el }) // el: the thumbnail the photo grows out of

  // Arrow keys turn the pages (unless a photo is open or the pager slider has focus).
  useEffect(() => {
    if (photo) return undefined
    const onKey = (e) => {
      if (e.target.closest?.('input')) return
      if (e.key === 'ArrowRight') turnPage(flip.current, 1)
      if (e.key === 'ArrowLeft') turnPage(flip.current, -1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [photo])

  const renderPage = (page) =>
    page.kind === 'cover' ? <Cover trip={trip} base={base} color={color} onPhoto={openPhoto} />
      : page.kind === 'end' ? <section className="page leaf endpaper"><p className="hand">The end of this trip. Until the next one.</p></section>
        : <DayPage page={page} base={base} color={color} cityName={cityName} onPhoto={openPhoto} />

  const current = pages[at]?.kind === 'day' ? pages[at] : pages[at + 1]?.kind === 'day' && at > 0 ? pages[at + 1] : null
  const last = pages.length - 1
  return (
    <div className="overlay" onClick={onClose}>
      <article className="book flipping" style={{ '--trip': color }} onClick={(e) => e.stopPropagation()} aria-label={`${trip.title} logbook`}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        <div
          className="book-stage"
          // A drag that turned a page must not also open the photo it started on.
          onPointerDown={(e) => { moved.current = { x: e.clientX, y: e.clientY } }}
          onPointerMove={(e) => {
            const m = moved.current
            if (m && m !== true && Math.hypot(e.clientX - m.x, e.clientY - m.y) > 6) moved.current = true
          }}
          onClickCapture={(e) => {
            if (moved.current === true) { e.stopPropagation(); e.preventDefault() }
            moved.current = false
          }}
        >
          <FlipBook pages={pages} renderPage={renderPage} apiRef={flip} onFlip={setAt} />
        </div>
        <button className="turn prev" onClick={() => turnPage(flip.current, -1)} disabled={at === 0} aria-label="Previous page">‹</button>
        <button className="turn next" onClick={() => turnPage(flip.current, 1)} disabled={at >= last - (flip.current?.getOrientation?.() === 'landscape' ? 1 : 0)} aria-label="Next page">›</button>
        <footer className="pager">
          <span>{current ? `Day ${current.day.dayNumber} · ${shortDate(current.day.date)}` : at === 0 ? 'Cover' : 'The end'}</span>
          <input type="range" min={0} max={last} value={at} onChange={(e) => { flip.current?.turnToPage(+e.target.value); setAt(+e.target.value) }} aria-label="Page" />
          <span>{at + 1} / {pages.length}</span>
        </footer>
      </article>
      {photo && <Lightbox photo={photo.p} base={base} place={cityName[photo.p.city_id]} onClose={() => setPhoto(null)} />}
    </div>
  )
}

// The paper book itself. page-flip owns the page elements (it moves and clips them as they
// turn), so they are made here by hand and React only renders each page's contents into them.
function FlipBook({ pages, renderPage, apiRef, onFlip }) {
  const stage = useRef(null)
  const [slots, setSlots] = useState(null)
  const [size, setSize] = useState(null)

  // Fit the pages to the space: two side by side when they fit, otherwise one.
  useLayoutEffect(() => {
    const measure = () => {
      const el = stage.current
      if (!el) return
      const h = el.clientHeight - 16
      const w = el.clientWidth - 24
      let pageH = Math.min(h, 720)
      let pageW = Math.round(pageH * PAGE_RATIO)
      const two = w >= pageW * 2
      if (!two) { // one page at a time (phones): use the full width and let the page grow taller
        pageW = Math.min(w, 560)
        pageH = Math.min(h, Math.round(pageW / 0.6))
      }
      setSize((s) => (s && s.pageW === pageW && s.pageH === pageH && s.two === two ? s : { pageW, pageH, two }))
    }
    measure()
    let t = 0
    const onResize = () => { clearTimeout(t); t = setTimeout(measure, 200) }
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); clearTimeout(t) }
  }, [])

  useLayoutEffect(() => {
    if (!size) return undefined
    const host = document.createElement('div')
    host.className = 'flipbook'
    const st = stage.current.style
    for (let k = 0; k < 3; k++) st.setProperty(`--paper-${k}`, `url(${pagePaper(k)})`)
    st.setProperty('--paper-cover', `url(${coverPaper()})`)
    host.style.width = `${size.two ? size.pageW * 2 : size.pageW}px`
    stage.current.appendChild(host)
    const els = pages.map((p, i) => {
      const el = document.createElement('div')
      // All pages are soft paper so the cover turns as smoothly as the rest. page-flip rewrites
      // each page's inline style, so the paper comes from a class (see the --paper vars below).
      el.className = `bk-page kind-${p.kind} ${p.kind === 'day' ? `paper-${i % 3}` : 'paper-cover'}`
      host.appendChild(el)
      return el
    })
    const start = Math.min(apiRef.current?.getCurrentPageIndex?.() ?? 0, pages.length - 1)
    const pf = new PageFlip(host, {
      width: size.pageW, height: size.pageH, size: 'stretch',
      minWidth: 200, maxWidth: size.pageW, minHeight: 200 / PAGE_RATIO, maxHeight: size.pageH,
      showCover: true, usePortrait: true, startPage: start,
      drawShadow: true, maxShadowOpacity: 0.3, flippingTime: reducedMotion() ? 1 : 850,
      mobileScrollSupport: false, swipeDistance: 24,
      disableFlipByClick: true, // a click only turns the page from its corner, so photos stay clickable
      showPageCorners: true,
    })
    pf.loadFromHTML(els)
    pf.on('flip', (e) => onFlip(e.data))
    apiRef.current = pf
    onFlip(pf.getCurrentPageIndex())
    setSlots(els)
    return () => {
      setSlots(null)
      if (apiRef.current === pf) apiRef.current = null
      try { pf.destroy() } catch { host.remove() }
    }
  }, [pages, size]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flip-stage" ref={stage}>
      {slots && pages.map((p, i) => slots[i] && createPortal(renderPage(p), slots[i], p.key))}
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
        <figure className="taped big" onPointerEnter={() => prepare(base + cover.full)} onPointerDown={() => prepare(base + cover.full)} onClick={(e) => onPhoto(cover, e.currentTarget)}>
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
          <figure key={p.id} className="taped" onPointerEnter={() => prepare(base + p.full)} onPointerDown={() => prepare(base + p.full)} onClick={(e) => onPhoto(p, e.currentTarget)}>
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
// It eases in when opened and eases out before closing.
export function Lightbox({ photo, base, place, onClose }) {
  const time = photo.taken_at.slice(11, 16)
  const sketch = usePainting(base + photo.thumb) // already made for the thumbnail, shown until the big one is ready
  const painted = usePainting(base + photo.full) ?? sketch
  const ratio = photo.width && photo.height ? photo.width / photo.height : 4 / 3
  const box = useRef(null)
  const card = useRef(null)
  const closing = useRef(false)
  useLayoutEffect(() => {
    if (reducedMotion()) return
    box.current.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 240, easing: 'ease-out' })
    card.current.animate([{ opacity: 0, transform: 'translateY(12px) scale(0.96)' }, { opacity: 1, transform: 'none' }],
      { duration: 300, easing: 'cubic-bezier(0.2, 0.8, 0.3, 1)' })
  }, [])
  const close = () => {
    if (closing.current) return
    closing.current = true
    if (reducedMotion()) { onClose(); return }
    const opts = { duration: 200, easing: 'ease-in', fill: 'forwards' }
    card.current.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(8px) scale(0.97)' }], opts)
    box.current.animate([{ opacity: 1 }, { opacity: 0 }], opts).onfinish = onClose
  }
  return (
    <div className="lightbox gouache-card" ref={box} onClick={(e) => { e.stopPropagation(); close() }}>
      <figure ref={card} style={{ '--ar': ratio }}>
        <img className="original shot" src={base + photo.full} alt="The original photo" />
        {painted ? <img className="painting shot" src={painted} alt="A gouache painting made from the photo" /> : <span className="painting-wait shot" />}
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
