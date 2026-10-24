import { useState } from 'react'
import { dateRange, jitter, tripColor } from './data.js'
import { Lightbox, Picture, useEscape } from './Logbook.jsx'

const TIMES = ['', 'Once', 'Twice', 'Three times', 'Four times', 'Five times']

// Clicking a postmark: every photo taken in this city, grouped by visit.
export default function CityPage({ city, base, onClose, onOpenTrip }) {
  const [photo, setPhoto] = useState(null)
  useEscape(photo ? () => setPhoto(null) : onClose)
  const n = city.visits.length

  return (
    <div className="overlay" onClick={onClose}>
      <article className="book single" onClick={(e) => e.stopPropagation()} aria-label={`${city.name}`}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        <section className="page">
          <p className="hand kicker">{TIMES[n] ?? `${n} times`} in {city.name}</p>
          <h2>{city.name}</h2>
          <p className="facts">{city.country} · {city.photo_count} photos</p>
          {city.visits.map((v) => {
            const photos = v.trip.photos.filter((p) => p.city_id === city.id)
            return (
              <div className="day" key={v.trip.id} style={{ '--trip': tripColor(v.trip) }}>
                <header>
                  <span className="hand day-no">{dateRange(v.trip)}</span>
                  <button className="link" onClick={() => onOpenTrip(v.trip)}>Open the {v.trip.title} logbook →</button>
                </header>
                <div className="collage">
                  {photos.map((p) => (
                    <figure key={p.id} className="taped" style={{ '--tilt': `${jitter(p.id, 3)}deg` }} onClick={() => setPhoto(p)}>
                      <Picture src={base + p.thumb} alt={`${city.name} ${p.date}`} loading="lazy" />
                    </figure>
                  ))}
                </div>
              </div>
            )
          })}
        </section>
      </article>
      {photo && <Lightbox photo={photo} base={base} place={city.name} onClose={() => setPhoto(null)} />}
    </div>
  )
}
