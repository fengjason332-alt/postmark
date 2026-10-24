import { useEffect, useMemo, useState } from 'react'
import { loadCities } from './geoLayers.js'

// Lets the viewer set their own home city. Only the city centre is stored, in this browser.
export default function HomePicker({ home, detected, picking, onPickOnGlobe, onChoose, onReset, onClose }) {
  const [cities, setCities] = useState(null)
  const [query, setQuery] = useState('')

  useEffect(() => {
    loadCities().then(setCities)
  }, [])

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!cities || q.length < 2) return []
    const starts = []
    const contains = []
    for (const c of cities) {
      const name = c.name.toLowerCase()
      if (name.startsWith(q)) starts.push(c)
      else if (name.includes(q)) contains.push(c)
      if (starts.length >= 8) break
    }
    return [...starts, ...contains].slice(0, 8)
  }, [cities, query])

  const isCustom = home.city !== detected.city || home.lat !== detected.lat

  return (
    <div className="home-picker" role="dialog" aria-label="Set your home city">
      <div className="hp-head">
        <h3>Where is home?</h3>
        <button className="close small" onClick={onClose} aria-label="Close">×</button>
      </div>
      <label htmlFor="home-search" className="hp-label">Search for a city</label>
      <input
        id="home-search"
        type="search"
        autoFocus
        autoComplete="off"
        placeholder={cities ? 'e.g. Shanghai, Boston, Paris' : 'Loading cities…'}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {matches.length > 0 && (
        <ul className="hp-results">
          {matches.map((c) => (
            <li key={`${c.name}${c.lat}${c.lng}`}>
              <button onClick={() => onChoose(c)}>
                {c.name}
                <span>{c.country}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <button className={`hp-globe ${picking ? 'on' : ''}`} onClick={onPickOnGlobe}>
        {picking ? 'Click anywhere on the globe…' : 'Or pick it on the globe'}
      </button>
      {isCustom && (
        <button className="link hp-reset" onClick={onReset}>
          Use the home found in my photos ({detected.city})
        </button>
      )}
      <p className="hp-note">
        Home is kept to a city centre and saved only in this browser. Trips are still the ones found from your
        photos; distances are re-measured from the new home.
      </p>
    </div>
  )
}
