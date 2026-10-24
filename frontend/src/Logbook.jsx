import { useEffect, useState } from 'react'
import { shortDate, dateRange, jitter, photosByDay, tripColor } from './data.js'
import { postmark } from './stamps.js'
import { citiesOf, currentStyle } from './data.js'
import { paintingTitle, usePainting } from './painterly.js'

// A trip opens as a two-page journal: cover on the left, days of taped photos on the right.
export default function Logbook({ trip, base, onClose }) {
  const [photo, setPhoto] = useState(null)
  useEscape(photo ? () => setPhoto(null) : onClose)
  const color = tripColor(trip)
  const days = photosByDay(trip)
  const cover = trip.photos.find((p) => p.id === trip.cover_photo_id) ?? trip.photos[0]
  const cityName = Object.fromEntries(trip.cities.map((c) => [c.id, c.name]))
  const countries = new Set(trip.cities.map((c) => c.country_code)).size

  return (
    <div className="overlay" onClick={onClose}>
      <article className="book" style={{ '--trip': color }} onClick={(e) => e.stopPropagation()} aria-label={`${trip.title} logbook`}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>

        <section className="page cover">
          <p className="hand kicker">Logbook No.{String(trip.index + 1).padStart(2, '0')}</p>
          <h2>{trip.title}</h2>
          <p className="dates">{dateRange(trip)}</p>
          <p className="facts">
            {trip.days} days · {trip.cities.length} {trip.cities.length === 1 ? 'city' : 'cities'}{countries > 1 ? ` · ${countries} countries` : ''} · ~{trip.distance_km.toLocaleString('en-US')} km
          </p>
          {cover && (
            <figure className="taped big" style={{ '--tilt': `${jitter(cover.id, 2.5)}deg` }} onClick={() => setPhoto(cover)}>
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
          <div className="cover-stamp" dangerouslySetInnerHTML={{ __html: postmark(citiesOf([trip])[0], color, currentStyle()) }} />
        </section>

        <section className="page days">
          {days.map((day) => (
            <div className="day" key={day.date}>
              <header>
                <span className="hand day-no">Day {day.dayNumber}</span>
                <span className="day-date">{shortDate(day.date)}</span>
                <span className="day-cities">{[...new Set(day.photos.map((p) => cityName[p.city_id]).filter(Boolean))].join(' → ')}</span>
                <RouteSketch photos={day.photos} color={color} />
              </header>
              <div className="collage">
                {day.photos.map((p) => (
                  <figure key={p.id} className="taped" style={{ '--tilt': `${jitter(p.id, 3)}deg` }} onClick={() => setPhoto(p)}>
                    <Picture src={base + p.thumb} alt={`${shortDate(p.date)} ${cityName[p.city_id] ?? ''}`} loading="lazy" />
                    {currentStyle() === 'gouache' && <figcaption className="title">{paintingTitle(p)}</figcaption>}
                    {!p.has_gps && <figcaption className="hand">no location</figcaption>}
                  </figure>
                ))}
              </div>
            </div>
          ))}
        </section>
      </article>
      {photo && <Lightbox photo={photo} base={base} place={cityName[photo.city_id]} onClose={() => setPhoto(null)} />}
    </div>
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

// In the gouache style a photo is shown as a small painting made from it on this device.
export function Picture({ src, alt, ...rest }) {
  const gouache = currentStyle() === 'gouache'
  const painted = usePainting(src, gouache)
  if (!gouache) return <img src={src} alt={alt} {...rest} />
  return painted ? <img src={painted} alt={alt} {...rest} /> : <span className="painting-wait" role="img" aria-label={alt} />
}

export function Lightbox({ photo, base, place, onClose }) {
  const time = photo.taken_at.slice(11, 16)
  if (currentStyle() === 'gouache') return <PaintingCard photo={photo} base={base} place={place} time={time} onClose={onClose} />
  return (
    <div className="lightbox" onClick={(e) => { e.stopPropagation(); onClose() }}>
      <figure>
        <img src={base + photo.full} alt="" />
        <figcaption className="hand">{shortDate(photo.date)}, {time} {place ? `· ${place}` : '· no location'}</figcaption>
      </figure>
    </div>
  )
}

// The photo on top and the painting made from it below, like a page from a sketchbook.
function PaintingCard({ photo, base, place, time, onClose }) {
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
