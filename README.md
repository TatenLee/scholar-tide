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
| deployed site | GitHub Pages | static card feed of all articles |