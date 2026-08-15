# X Analyzer — Telegram Bot

Send a Solana contract address (in a group, or via `/analyze <address>`) and the
bot replies with the token's name/ticker, its latest relevant X/Twitter post,
real engagement stats, and a short AI-generated summary.

## How it works

1. **`app/dexscreener.py`** — looks up the contract on DexScreener, returns
   name, ticker and social links (including the X/Twitter profile URL).
2. **`app/x_provider.py`** — the *only* file that talks to an X data API.
   Ships with a [twitterapi.io](https://twitterapi.io) implementation
   (`TwitterAPIIOProvider`) that fetches the account's latest non-reply post:
   text, image, likes, replies, views, and the post URL. Swap providers by
   editing this file only — everything else in the bot is provider-agnostic.
3. **`app/ai_summary.py`** — sends the post text to the Gemini API and
   gets back one short, factual sentence.
4. **`app/formatter.py`** — builds the Telegram message. **Never invents
   data**: if a stat (likes/comments/views) or a post isn't available, that
   line/field is simply omitted instead of faked.
5. **`app/bot.py`** — Telegram wiring: detects contract addresses in group
   messages via regex, handles `/analyze`, and includes a simple in-memory
   TTL cache (avoids repeat API calls for the same contract) and a per-chat
   rate limiter (avoids spam). No database — an in-process dict is enough
   since the bot runs as a single Render instance.

The bot runs as a **Render Web Service using a Telegram webhook** (not
polling): Telegram pushes updates directly to the service's public HTTPS
URL instead of the bot repeatedly asking Telegram for new messages. This
is the recommended setup for services that stay up continuously, like a
Render web service.

## Project structure

```
x-analyzer-bot/
├── app/
│   ├── bot.py            # Telegram handlers + orchestration
│   ├── cache.py           # TTL cache + rate limiter (in-memory)
│   ├── config.py           # env var loading
│   ├── dexscreener.py       # DexScreener API client
│   ├── x_provider.py        # X/Twitter data client (swappable)
│   ├── ai_summary.py        # AI summary via Gemini API
│   └── formatter.py         # builds the Telegram message
├── main.py                  # entry point
├── requirements.txt
├── .env.example
└── render.yaml
```

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | from [@BotFather](https://t.me/BotFather) |
| `GEMINI_API_KEY` | yes | for the AI summary |
| `GEMINI_MODEL` | no | defaults to `gemini-3.5-flash-lite` |
| `X_API_KEY` | yes | your [twitterapi.io](https://twitterapi.io) key (or your alternate provider's key) |
| `X_API_BASE_URL` | no | defaults to `https://api.twitterapi.io` |
| `CACHE_TTL_SECONDS` | no | default `600` — how long a result is cached per contract |
| `RATE_LIMIT_SECONDS` | no | default `5` — min seconds between requests per chat |
| `USE_WEBHOOK` | no | default `true`. Set `false` to run with polling instead (e.g. locally) |
| `WEBHOOK_SECRET` | yes, if `USE_WEBHOOK=true` | random string validated on every incoming webhook request. Render can auto-generate this (see `render.yaml`), or generate your own: `openssl rand -hex 32` |
| `WEBHOOK_URL` | no | only needed if hosting outside Render — your service's public https base URL |
| `PORT` | no | default `10000`. Render sets this automatically |

On Render, the service's public URL (`RENDER_EXTERNAL_URL`) is injected
automatically — you don't set it yourself.

## Run locally

Local development defaults to **polling** so you don't need a public URL:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# In .env: fill in TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, X_API_KEY
# and set USE_WEBHOOK=false
export $(grep -v '^#' .env | xargs)
python main.py
```

If you want to test webhook mode locally, expose your machine with a tool
like `ngrok`, set `USE_WEBHOOK=true`, `WEBHOOK_URL=https://<ngrok-id>.ngrok.app`,
and `WEBHOOK_SECRET` to any random string, then run `python main.py`.

## Deploy to Render (Web Service + webhook)

**Option A — using `render.yaml` (recommended)**

1. Push this project to a GitHub repo.
2. In Render: **New +** → **Blueprint** → connect the repo. Render reads
   `render.yaml` and creates a **Web Service** automatically, with
   `WEBHOOK_SECRET` auto-generated for you.
3. Fill in the secret env vars it prompts for (`TELEGRAM_BOT_TOKEN`,
   `GEMINI_API_KEY`, `X_API_KEY`).
4. Deploy. On startup the bot calls Telegram's `setWebhook` itself, pointed
   at `https://<your-service>.onrender.com/<your-bot-token>`. Check the
   logs for `X Analyzer bot starting (webhook) on port ... -> https://...`.

**Option B — manual setup**

1. In Render: **New +** → **Web Service**.
2. Connect your repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `python main.py`
5. Under **Environment**, add: `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`,
   `X_API_KEY`, `USE_WEBHOOK=true`, and `WEBHOOK_SECRET` (any long random
   string — Render can generate one for you when adding the variable).
   Leave `PORT` and the public URL alone; Render supplies both automatically.
6. Deploy.

**Why a Web Service instead of a Background Worker:** webhook mode means
Telegram sends updates to the bot over HTTPS, so the service needs to
accept inbound requests on the port Render assigns it — that's exactly
what a Web Service is for. No polling loop runs, and the bot registers its
webhook URL with Telegram automatically on startup (via
`python-telegram-bot`'s `run_webhook`, using the bot token as the URL path
and `WEBHOOK_SECRET` as a header check so random internet traffic can't
trigger the bot).

**Note on the free/starter plan:** if the service spins down during
inactivity, Telegram will simply retry delivering updates once it's back
up — there's no polling loop to restart, since Telegram is doing the
pushing. A paid always-on plan avoids any delay from cold starts.

## Swapping the X data provider

Everything X-related is isolated in `app/x_provider.py`. To use a different
API, write a new class implementing `XProvider.get_latest_post(twitter_url) -> XPost`
and point `get_default_provider()` at it. `XPost` fields (`text`, `url`,
`image_url`, `likes`, `comments`, `views`) can each be `None` if the
provider doesn't have that data — the formatter already handles that.

## Notes on accuracy

- If DexScreener has no listing for an address, the bot says so — it does
  not guess.
- If a token has no X/Twitter link, or the linked account/post can't be
  found, the bot sends token info with a plain explanation instead of a
  fabricated post.
- Engagement numbers are only shown if the X provider actually returned
  them.
