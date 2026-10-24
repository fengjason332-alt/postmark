# Postmark frontend

Vite + React + react-globe.gl. Reads `public/data/trips.json` (real data, not committed)
and falls back to `public/mock/trips.json` (written by the backend).

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run build    # static site in dist/
```

Add `?data=mock` to the URL to force the mock data.

Pick the look with the Journal / Ink wash switch, `?style=ink` in the URL, or
`VITE_DEFAULT_STYLE=ink` at build time.

Map data bundled in `src/geo/`: state and province borders from Natural Earth (public domain),
city names from GeoNames (CC BY 4.0).
