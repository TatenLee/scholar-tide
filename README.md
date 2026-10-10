# Scholar Tide

A personalised daily newspaper of academic papers and web news.
*Your* current — chosen by you, not by a recommendation algorithm.

A refactor of the `infiv` project: same idea, cleaner structure.

## Usage

```bash
# 1. install (gives you the `scholar-tide` command + python -m engine)
pip install -e ".[all]"          # .[embed] = 不要 rss 依赖
# or: make setup

# 2. build the daily newspaper (two equally valid spellings)
scholar-tide build                 # same as: python -m engine build
scholar-tide build --use-embed     # + personalised re-ranking (needs OPENAI_API_KEY)
# or: make build / make build-plain

# 3. preview the web page locally
scholar-tide serve                 # http://127.0.0.1:8000

# helper
scholar-tide spiders               # list registered spiders
```

## Configuration

Everything you can change lives in two YAML files under `config/`.
No code edits are needed to change behaviour.

### `config/source.yaml` — what to fetch

Top-level settings:

| key | type | enum / example | default | meaning |
|---|---|---|---|---|
| `retry.max_retries` | int | 0..n | `3` | attempts per source before giving up |
| `retry.base_delay` | float | seconds | `10.0` | first backoff interval |
| `retry.factor` | float | > 1 | `2.0` | backoff growth between attempts |
| `retry.jitter` | bool | `true` / `false` | `true` | randomise delays to avoid thundering herd |
| `embedding.use_embed` | bool | `true` / `false` | `false` | enable personalisation (also `--use-embed`) |
| `embedding.model` | str | any embedding model id | `text-embedding-v4` | model used for vectors |
| `embedding.dimensions` | int | 768/1536/2048… | `2048` | vector length |
| `max_items_per_source` | int | 1..n | `200` | total report cap ≈ value × source count |

The `sources` list is the heart of the config. Each entry accepts:

| key | type | enum / example | default | meaning |
|---|---|---|---|---|
| `spider` | str | see enum below | *(required)* | which spider to run |
| `url` | str | free-form | `""` | what the spider should hit |
| `subject` | str | any label, e.g. `paper`, `feed`, `coding` | `unclassified` | report section this lands in |
| `enabled` | bool | `true` / `false` | `true` | comment/disable a source without deleting it |
| `kwargs` | map | per-spider options | `{}` | extra spider arguments |

**`spider` enum** (run `scholar-tide spiders` for the live list):

| value | data source | what `url` should be | extra `kwargs` |
|---|---|---|---|
| `arxiv` | arXiv papers | category id, e.g. `cs.CV`, `cs.CL`, `cs.RO` | — |
| `biorxiv` | bioRxiv | collection URL, e.g. `https://www.biorxiv.org/collection/biochemistry` | — |
| `rss` | any RSS/Atom feed (incl. RSSHub) | feed URL | `html_summary: true` if the summary is HTML |
| `zhihu` | Zhihu timeline | `https://www.zhihu.com/` (needs `ZHIHU_COOKIE`) | `max_items: 10` |
| `bilibili` | Bilibili recommendations | `https://www.bilibili.com/` (needs `BILIBILI_COOKIE`) | `max_items: 10` |

Example with a disabled source and spider-specific kwargs:

```yaml
sources:
  - spider: arxiv
    url: cs.CV
    subject: paper
  - spider: rss
    url: https://example.com/feed.xml
    subject: coding
    kwargs:
      html_summary: true
  - spider: biorxiv
    url: https://www.biorxiv.org/collection/biochemistry
    subject: biology
    enabled: false        # fetched only when true
```

### `config/preference.yaml` — what you like (personalisation)

Used only when personalisation is on (`.embedding.use_embed` or `--use-embed`). The engine
embeds your titles, builds a direction vector `mean(likes) − mean(dislikes)`, scores every
article, and sorts each `subject` by score.

| key | type | example | meaning |
|---|---|---|---|
| `rank.likes` | list\<str\> | paper titles you are into | pulls similar articles to the top |
| `rank.dislikes` | list\<str\> | titles/headlines you dislike | pushes similar articles down |
| `rank.proj_embedding_json` | str \| null | `./config/proj_embedding.json` | optional precomputed vector, skips live API calls |

**What goes in `likes` / `dislikes`**: any free-form string — the simplest working
values are the **exact titles of papers/articles you care about** (e.g. from arxiv
or the config file itself). The engine compares embedding directions, so:
- add titles whose *topic/style* you want to surface more (`likes`) or bury (`dislikes`);
- order does not matter; you can grow/shrink both lists freely;
- language-agnostic — Chinese and English titles both work;
- `dislikes` is optional: with only `likes`, the vector is just `mean(likes)`.

### Available URLs by spider

**`arxiv`** — use a plain category id (no `http://` needed):

```
cs.CV   cs.CL   cs.AI   cs.LG   cs.RO   cs.NE   cs.LO   cs.CR
cs.CE   cs.GR   cs.IR   cs.MM   cs.SD   cs.SE   cs.PL   cs.DC
math.NT  math.OC  stat.ML  eess.IV  physics.class-ph  q-bio.GN
```

**`biorxiv`** — a bioRxiv collection page:

```
https://www.biorxiv.org/collection/biochemistry
https://www.biorxiv.org/collection/bioinformatics
https://www.biorxiv.org/collection/genomics
https://www.biorxiv.org/collection/neuroscience
```

**`rss`** — any RSS/Atom feed URL, including RSSHub endpoints and self-hosted feeds:

```
https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml        # GitHub trending
https://rsshub.app/arxiv/cs.CV                                      # arXiv via RSSHub
https://rsshub.app/nature/research                                  # Nature
https://example.com/feed.xml                                        # your own feed
```

> Note: the public `rsshub.app` instance can be slow/unreliable — if you depend on
> RSSHub, self-host it (or run your own local instance) and point here at that URL.

**`zhihu`** — the Zhihu home page (needs `ZHIHU_COOKIE` env):

```
https://www.zhihu.com/
```

**`bilibili`** — the Bilibili home page (needs `BILIBILI_COOKIE` env):

```
https://www.bilibili.com/
```

## What gets produced

| output | destination | purpose |
|---|---|---|
| `output.md` | project root | plain-text report (issues, newsletters…) |
| `data/report.json` | project root | latest build, data source for the web page |
| `data/report-YYYY-MM-DD.json` | project root | daily archive (history browser) |
| `data/index.json` | project root | manifest of archived days |
| `data/search-index.json` | project root | compact, deduplicated title/tag catalogue for historical search |
| deployed site | GitHub Pages | static card feed of all articles |

## Reading papers without a server or API key

The site works on GitHub Pages without a custom domain. Click an arXiv paper title or
**双语阅读** to open the reader. English source text and Chinese translation appear
side by side, paired by paragraph in a single scrolling area. **英中对照 / 仅英文 /
仅中文 / PDF 对照** switch the view. The source text is extracted from arXiv's HTML
version of the same paper, which preserves paragraph order more reliably than PDF
text extraction. The original PDF remains available in **PDF 对照** or a separate tab.
When HTML is unavailable, the reader falls back to the daily report's abstract.

The daily GitHub Actions build pretranslates new arXiv titles and abstracts with the
offline Argos English-to-Chinese model. They load immediately from the static JSON;
no API key is needed. The workflow caches the model between runs. To run the same
step locally, install `pip install -e ".[translate]"` and run
`python -m engine.translate_archive` after a build.
The Argos model derives from OPUS-MT by Jörg Tiedemann and Santhosh Thottingal
and is licensed CC BY 4.0; see the model package README for attribution.

Chinese titles and abstracts are displayed first when a translation is present. The
English title remains below the Chinese title, and the English abstract can be shown
with **显示英文摘要**. Older entries without pretranslation can still use the browser's
translation button. Each night, a separate backfill step translates up to 200 older
arXiv titles and abstracts, so historical results gradually become Chinese-first too.

At 14:37, 22:37, and 06:37 Beijing/Hong Kong time, `nightly-translate.yaml` uses
four parallel GitHub Actions jobs in a public repository to download available arXiv
HTML and translate the full text offline. The first pass follows the daily discovery
build. It publishes paired English and Chinese text as
`data/papers/<arxiv-id>.json` on GitHub Pages; the reader loads complete translations
directly, without waiting for a browser model. Each job spends at most 300 minutes
translating, below GitHub's six-hour job limit. It saves finished papers and partial
paragraph checkpoints to the repository; later runs skip finished papers and resume
partial ones. Papers from the last 21 days are eligible, and stored translation files
are kept for at most 21 days or 256 MiB. To run one paper locally:

```sh
pip install -e ".[translate]"
python -m engine.translate_papers --id 2610.12469v1
```

The same workflow also supports manual dispatch with a `paper_id` input when one
specific paper should be translated before the next night.

arXiv does not provide usable HTML for every paper. Those papers still show the
pretranslated abstract, and the browser reader can attempt its local translation
when HTML becomes available. GitHub Pages is static hosting: it cannot translate a
paper at the moment a visitor clicks it. The night job is bounded by GitHub's runner
time and Pages size limits, so a large daily batch may finish over several nights.

For older reports without pretranslation, **翻译标题与摘要** and **翻译当前列表标题**
use the browser's built-in English-to-Chinese `Translator` API. The full-paper reader
shows pretranslated abstracts immediately when available and falls back to browser
translation when no nightly full-paper file exists. Translate the next four
paragraphs on demand, or let the rest translate in the background. Browser-generated
translations are cached in IndexedDB so revisiting a paragraph does not repeat the
work. Chrome 138+ on desktop supports this API when the device and language pack are
available; the first use may download a language pack. Other browsers and mobile
devices can still browse the original PDF and read pretranslated abstracts. No model
key is included in the site or sent to the browser. The browser fallback reports an
error if model preparation exceeds 60 seconds or one text chunk exceeds 30 seconds,
so the page does not remain stuck on “翻译中” indefinitely. Technical terms and equations
should be checked against the PDF.

The bilingual text view scrolls both languages together by paragraph. **PDF 对照**
shows the original PDF beside the Chinese text, with separate scroll areas. The
translation is not a page-perfect PDF. Some arXiv HTML conversions may omit or alter
mathematical layout, figures, and tables.

## Historical search and growth

The daily build generates `data/search-index.json` from the archive. **全部历史** reads
that compact catalogue instead of downloading every full daily report. It searches
paper titles and tags. Opening a result's abstract loads only its original daily
report. The feed renders 60 results at a time. Date and date-range views still read
the selected daily reports and can search their abstracts too.

This avoids running a database server on GitHub Pages. If the catalogue later grows
too large for a single browser download, the next step is to shard it by year or
subject and load shards on demand. SQLite FTS can help during the GitHub Actions build,
but a SQLite file alone does not add server-side queries to a static Pages site.
