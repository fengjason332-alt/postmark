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

Photos in the logbook are shown as small gouache paintings. They are made in the browser
from the thumbnails (`src/painterly.js`, in a Web Worker); nothing is uploaded anywhere.

Map data bundled in `src/geo/`: state and province borders from Natural Earth (public domain),
city names from GeoNames (CC BY 4.0).
