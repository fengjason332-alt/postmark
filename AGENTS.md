# Postmark — Rules for Humans and AI Agents / 给人和 AI 的协作规则

> **Every AI agent working in this repo must read this whole file before doing anything.**
> **所有在这个仓库里工作的 AI，动手之前必须先读完这个文件。**
>
> This file is the single source of truth for scope, ownership and the data contract.
> If a request conflicts with this file, **stop and ask the human** instead of guessing.
> 本文件是分工、边界和数据格式的唯一标准。如果收到的指令和本文件冲突，**停下来问人**，不要自己猜。
>
> Chat-only AIs (Grok, DeepSeek, etc.): the human should paste this whole file at the start of the chat.
> 只在网页聊天里用的 AI（Grok、DeepSeek 等）：开始对话时，把整个文件贴进去。

---

## 1. What we are building / 项目是什么

**Postmark turns a phone photo library into a rotatable travel globe.** We read each photo's time and GPS,
automatically detect past trips with a spatio-temporal clustering algorithm, group photos into one logbook per trip,
and show everything on a hand-drawn, journal-style 3D globe.

**Postmark 把手机相册变成一个可以旋转的旅行地球。** 读取每张照片的时间和 GPS，用时空聚类算法自动识别过去的旅程，
每次旅程整理成一本 logbook，放在一个手帐风格的 3D 地球上回看。

- Event / 比赛：BU Spark! DS+X Hackathon, Oct 24–25, 2026 · Track / 赛道：**ArtHack**
- Judging / 评分：Idea 25% · **Data Science 25%** · Technical 20% · Design 10% · Ethics 10% · Presentation 10%
- "Calling an API or LLM does not count as data science." Our core must be **our own algorithm + validation**.
  手册明确说：只调用 API 或 LLM 不算数据科学。核心必须是**我们自己的算法和验证**。

## 2. Deadlines / 时间关口

| Time (EDT) / 时间 | Gate / 关口 |
| --- | --- |
| Sat 12:15 / 周六 12:15 | Data contract agreed; mock `trips.json` handed to frontend / 数据格式定稿，假数据交给前端 |
| **Sat 18:00 / 周六 18:00** | **Real trips show on the globe** / **真数据显示在地球上** |
| Sun 09:00 / 周日 9:00 | **Feature freeze** — bug fixes only / **功能冻结**，只修 bug |
| **Sun 11:00 / 周日 11:00** | **Devpost submission (hard deadline)** / **Devpost 提交（硬截止）** |

Before 18:00 Saturday, work on **P0 only** (see §9). 周六 18:00 前只做 P0。

All project code must be written during the event. 所有项目代码必须在比赛期间写。

## 3. Team and ownership / 分工与边界

| Area / 区域 | Owner / 负责人 | Who may edit / 谁能改 |
| --- | --- | --- |
| `backend/` (except the three data science scripts below), `data/` | **Jason (backend)** | Jason and Jason's AI agents only / 只有 Jason 和他的 AI |
| `backend/validate.py`, `backend/tag_clip.py`, `backend/fill_gps.py`, `notebooks/`, `results/` | **Data science teammate / 数据科学队友** | Data science teammate and their AI agents only / 只有数据科学队友和他的 AI |
| `frontend/` (except `frontend/public/data/` and `frontend/public/mock/`) | **Frontend teammate** | Frontend teammate and their AI agents only / 只有前端和他的 AI |
| `frontend/public/data/`, `frontend/public/mock/` | **Backend writes, frontend only reads** / 后端写，前端只读 | Backend only / 只有后端 |
| `AGENTS.md`, `CLAUDE.md`, `.kiro/` | Both / 两人共管 | Only after both humans agree / 两人都同意后才能改 |
| `README.md`, `.gitignore` | Both / 两人共管 | Either, small edits, mention it in chat / 谁都能小改，改了在群里说一声 |

**AI agents: never edit files outside your human's area.** If a change is needed in the other area, stop and tell
your human what to ask the teammate for.
**AI 不准改自己负责人区域以外的文件。** 需要对方改东西时，停下来告诉你的负责人，让他去和队友说。

## 4. Hard rules — NEVER / 红线：绝对不能做

1. **Never commit real data.** No photos, no `data/`, no `frontend/public/data/`, no CSV with GPS, no `.heic`/`.mov`, no `.env`.
   Run `git status` before every commit and add files by path (`git add backend/clean.py`), **not** `git add .` / `git add -A`.
   **绝不提交真实数据。** 照片、`data/`、`frontend/public/data/`、带 GPS 的 CSV、`.heic`/`.mov`、`.env` 都不能进 Git。
   每次提交前先 `git status`，按文件名添加，**不要**用 `git add .`。
2. **Never send photos or GPS data to any external service** — no cloud vision API, no uploading to LLM chats, no online EXIF tools.
   All processing (including CLIP) runs locally.
   **绝不把照片或定位发到任何外部服务**：不用云端识图 API，不传给 AI 聊天，不用在线 EXIF 网站。所有处理（包括 CLIP）都在本机。
3. **Never change the data contract (§6) silently.** Changes need all three humans to agree, a `schema_version` bump, and an update to §6 in the same commit.
   **绝不偷偷改数据格式（§6）。** 改之前两人同意，同时升 `schema_version`，并在同一个提交里更新 §6。
4. **Never rewrite Git history.** No `git push --force`, no `git reset --hard` on shared commits, no rebasing `main`. Never delete someone else's files.
   **绝不改写 Git 历史。** 不 force push，不 reset 已推送的提交，不 rebase main，不删别人的文件。
5. **Never invent results.** Any F1 / precision / recall / accuracy number must come from an actual run of `backend/validate.py` and be saved in `results/`.
   **绝不编造结果。** 所有 F1、准确率等数字都必须来自真实运行 `backend/validate.py` 的输出，并保存在 `results/`。
6. **Never commit secrets** (API keys, tokens, passwords). 绝不提交密钥、token、密码。
7. **Never add a dependency silently.** Add it to `backend/requirements.txt` or `frontend/package.json` and mention it in the commit message.
   新增依赖必须写进 `requirements.txt` 或 `package.json`，并在提交信息里写明。
8. **No hard-coded personal paths** like `/Users/jasonfeng/...`. Use paths relative to the repo root.
   不要写死个人电脑路径，一律用相对仓库根目录的路径。

## 5. Repo structure / 仓库结构

```text
postmark/                     repo root / 仓库根目录
├── AGENTS.md                 this file / 本文件
├── CLAUDE.md                 points to AGENTS.md (Claude Code)
├── .kiro/steering/           points to AGENTS.md (Kiro)
├── backend/                  Jason
│   ├── extract.sh            ExifTool → data/raw/photos_raw_<person>.csv
│   ├── clean.py              filter + dedupe → data/processed/photos_clean.csv
│   ├── thumbnails.py         HEIC/JPG → WebP (_s 400px, _l 1600px), EXIF stripped
│   ├── segment.py            stay points, home detection, trip segmentation
│   ├── geocode.py            GeoNames + BallTree reverse geocoding (offline)
│   ├── validate.py           precision / recall / F1 vs ground truth + baseline
│   ├── build_json.py         writes frontend/public/data/trips.json + stats.json
│   ├── tag_clip.py           P1: local CLIP tags
│   └── requirements.txt
├── frontend/                 frontend teammate
│   ├── src/
│   └── public/
│       ├── mock/             fake data, committed / 假数据，可以提交
│       └── data/             real data, NOT committed / 真数据，不提交
├── data/                     NOT committed / 不提交
│   ├── raw/  processed/  geonames/
│   └── ground_truth.csv      columns: person,start_date,end_date,cities
├── results/                  F1 tables + charts for Devpost / 验证结果
└── README.md
```

Run every script from the repo root, e.g. `python backend/segment.py`. 所有脚本都从仓库根目录运行。

## 6. Data contract (backend → frontend) / 数据格式约定

The **only** interface between backend and frontend is these files. 前后端**唯一**的交接方式就是这些文件：

- Real data / 真数据：`frontend/public/data/trips.json`, `frontend/public/data/stats.json`, `frontend/public/data/thumbs/`
- Mock data / 假数据：`frontend/public/mock/` (same shape / 格式完全相同)
- Frontend loads `/data/trips.json` and falls back to `/mock/trips.json` if it is missing.
  前端优先读 `/data/trips.json`，读不到就用 `/mock/trips.json`。

### Conventions / 约定

| Item / 项目 | Rule / 规则 |
| --- | --- |
| Coordinates / 坐标 | Keys are **`lat` and `lng`** only (never `lon`/`long`). Decimal degrees, 4 decimals. |
| Dates / 日期 | `"YYYY-MM-DD"` in the photo's **local** time. |
| Timestamps / 时间 | ISO 8601 with offset: `"2026-03-14T15:32:08-04:00"`. |
| Distances / 距离 | Kilometres, integers, keys end with `_km`. |
| IDs | Stable strings: `trip_…`, `city_…`, `p_…`. Photo id = first 10 hex chars of the file content hash. Same input → same ids. |
| Nulls / 空值 | Empty list → `[]`; unknown → `null`. Never omit a key. 不省略字段。 |
| Order / 排序 | `trips` by `start_date` ascending; `photos` by `taken_at` ascending. |
| Images / 图片 | WebP only: `_s` = 400px wide (grids), `_l` = 1600px long edge (viewer). No EXIF. No originals. |
| Home / 家 | City-centre coordinates only, never the real address. 只给城市中心坐标。 |
| Visuals / 视觉 | Colours, stamp sizes, animation = frontend. Backend only gives numbers like `index`, `photo_count`. |
| Version / 版本 | Top-level `schema_version`. Current: **`"1.0"`**. |

### trips.json

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-10-24T18:00:00-04:00",
  "home": {"city": "Boston", "country": "United States", "country_code": "US", "lat": 42.3601, "lng": -71.0589},
  "trips": [
    {
      "id": "trip_20260314_newyork",
      "index": 0,
      "title": "New York",
      "start_date": "2026-03-14",
      "end_date": "2026-03-17",
      "days": 4,
      "distance_km": 306,
      "photo_count": 86,
      "cover_photo_id": "p_a1b2c3d4e5",
      "tags": ["food", "city"],
      "cities": [
        {"id": "city_newyork_us", "name": "New York", "country": "United States", "country_code": "US",
         "lat": 40.7128, "lng": -74.0060, "arrive": "2026-03-14", "leave": "2026-03-17", "photo_count": 86}
      ],
      "photos": [
        {"id": "p_a1b2c3d4e5", "taken_at": "2026-03-14T15:32:08-04:00", "date": "2026-03-14",
         "lat": 40.7580, "lng": -73.9855, "has_gps": true, "city_id": "city_newyork_us",
         "thumb": "thumbs/p_a1b2c3d4e5_s.webp", "full": "thumbs/p_a1b2c3d4e5_l.webp",
         "width": 1600, "height": 1200, "tags": ["city"]}
      ]
    }
  ]
}
```

A photo with no GPS but taken during a trip's dates is still included: `"has_gps": false`, and `lat`, `lng`, `city_id` are `null`.
`tags` is `[]` until CLIP (P1) is done.
没有 GPS、但拍摄日期在旅程内的照片也放进这次旅程：`has_gps` 为 `false`，`lat`、`lng`、`city_id` 为 `null`。CLIP 做完之前 `tags` 为 `[]`。

### stats.json

```json
{
  "schema_version": "1.0",
  "all_time": {"trips": 14, "cities": 21, "countries": 5, "days_away": 96, "distance_km": 28400,
               "photos_total": 9812, "photos_with_gps": 8120, "top_tags": [["food", 0.31], ["nature", 0.24]], "persona": "Food Explorer"},
  "by_year": {
    "2026": {"trips": 6, "cities": 11, "countries": 3, "days_away": 47, "distance_km": 12840,
             "photos_total": 2431, "photos_with_gps": 1980, "top_tags": [["food", 0.35]], "persona": "Food Explorer"}
  }
}
```

Numbers above are examples only. 以上数字只是示例。The "This year / All time" toggle reads `by_year["<year>"]` and `all_time`.

## 7. Tech stack and commands / 技术栈与命令

### Backend / 后端 (Python)

- Python 3.10+, **venv + pip + `backend/requirements.txt`**.
- Libraries / 库：pandas, numpy, scikit-learn, pillow, pillow-heif, matplotlib (P1: open_clip_torch or transformers).
- `.gitignore` ignores every `*.csv` except `results/*.csv` (scores only, no GPS). 除了 `results/` 里只含分数的表，所有 CSV 都不进 Git。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Read photo metadata (replace `jason` with the person's name) / 读取照片元数据：

```bash
exiftool -csv -n -r -ext heic -ext jpg -ext jpeg -FileName -DateTimeOriginal -OffsetTimeOriginal -GPSLatitude -GPSLongitude -ImageWidth -ImageHeight data/raw/jason/ > data/raw/photos_raw_jason.csv
```

City database / 城市数据库：`cities15000.zip` from https://download.geonames.org/export/dump/ → unzip into `data/geonames/` (CC BY 4.0, credit GeoNames).

### Algorithm defaults / 算法默认参数 (tune with `validate.py`)

| Step / 步骤 | Default / 默认值 |
| --- | --- |
| Stay point / 停留点 | consecutive photos within 1 km and 3 h are merged |
| Home / 家 | area with the most photos between 22:00–06:00, recomputed per quarter |
| Trip / 旅程 | > 100 km from home **and** overnight; returning home ends the trip |
| Match for validation / 验证命中 | ≥ 50% date overlap with a ground-truth trip |
| Baseline / 基线 | "any day with a photo > 100 km from home is a travel day" |

### Frontend / 前端

- **Vite + React (JavaScript) + `react-globe.gl`** (React wrapper of globe.gl / Three.js).
- Node 18+. Dev server: `http://localhost:5173`.
- Deploy: Vercel or GitHub Pages, **only with sanitized demo data** (see §8).

## 8. Privacy and ethics / 隐私与伦理

- All processing is local; photos never leave the owner's laptop. 所有处理在本机完成。
- Each teammate runs validation on their own laptop and shares **only the scores**, never raw photos or GPS.
  验证时每人在自己电脑上跑，只交出分数，不交换照片和 GPS。
- Public demo: consenting teammate's data only; home blurred to city centre; landscape/food photos only, no people; thumbnails only.
  公开 demo：只用同意公开的队员数据；家模糊到城市级；只放风景和美食照，不放人像；只放缩略图。
- The "travel persona" is playful text, not a personality judgment. No leaderboards.
  "旅行人格"只是好玩的描述；不做排行榜。
- Credit data sources in the README and Devpost: GeoNames (CC BY 4.0), CLIP (MIT).
- Jason may share a coarse copy (2-decimal coordinates, no file names) privately with the data science teammate; it must not be committed or posted, and is deleted after the event. Transfer it directly (e.g. AirDrop or USB), not through cloud or chat services.
  Jason 可以私下给数据科学队友一份粗略副本（坐标保留 2 位小数，不含文件名）；不能提交到 Git、不能发布，比赛结束后删除。请直接传输（如 AirDrop 或 U 盘），不要通过云盘或聊天软件。

## 9. Scope / 范围

- **P0 (must ship / 必须完成)**：import folder → read time + GPS · detect home and trips · city names (offline) · 3D globe with home, arcs, stamps · trip logbook · "This year / All time" filter · local-only processing.
- **P1 (after 18:00 / 18:00 后再做)**：CLIP tags + persona · year summary card + image export · timeline replay · merge/split trips · city page · local FastAPI (`localhost:8000`) for live import, returning exactly the same JSON as §6.
- **Out of scope / 不做**：native mobile app, live GPS tracking, accounts, cloud sync, social features, trip planning, importing from WeChat.

## 10. Git workflow / Git 协作

- Everyone pushes directly to `main`; conflicts are avoided by folder ownership (§3). 直接推 main，靠文件夹分工避免冲突。
- Before you start and before you push / 开始前和推送前：`git pull`.
- Commit often, push at least every hour. 小步提交，至少每小时推一次。
- Commit message prefix / 提交信息前缀：`[backend]`, `[ds]`, `[frontend]`, `[docs]`, `[data-contract]`.
  Example / 例：`[backend] add stay-point detection`.
- If `git pull` reports a conflict in a file you don't own, **stop and ask the humans**. 遇到不属于你的文件冲突，停下来问人。

## 11. How AI agents should behave / AI 的工作方式

1. Read this file first. Stay inside your human's area (§3). 先读本文件，只在负责区域内工作。
2. Before 18:00 Saturday, do P0 only. Prefer the simplest thing that works. 周六 18:00 前只做 P0，能跑就行。
3. Ask the human before: deleting files, adding big dependencies, changing §6, or anything that can't be undone.
   删除文件、加大依赖、改 §6、做不可撤销的操作之前，先问人。
4. Never read, print or paste the contents of `data/` or real photos into a chat or external tool. Work with column names and small synthetic samples instead.
   不要把 `data/` 里的内容或真实照片打印、粘贴到聊天或外部工具里。需要例子时用列名或自己造的小样本。
5. Code, identifiers and code comments in **English**. UI text in English (judges). Docs bilingual.
   代码、变量名、注释用**英文**；界面文字用英文（给评委看）；文档中英双语。
6. When you finish a task, tell your human: what changed, which files, how to run it, and anything left undone.
   完成后告诉负责人：改了什么、哪些文件、怎么运行、还有什么没做完。
