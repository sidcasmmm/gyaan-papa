# Gyaan Papa — Hindi explainers for space, science, biology, and history 🇮🇳

An automatic Hindi/Hinglish channel hosted by **Gyaan Papa**: the same cartoon dad (orange tee, black hair, big moustache), now explaining one idea from the world — why the sky is blue, what DNA is, what the Indus cities were like — in about 20 seconds.

Every run it:
1. Takes the next topic from the list in `config.yaml` (space, everyday science, school-level biology, history)
2. Has AI write a short script in Papa's voice, with a rule against invented numbers, fake quotes, medical advice, and lab steps
3. Generates an AI background for every line (sky, moon, leaf, ancient street…)
4. Records Papa's Hindi voice and animates him in the bottom-left corner
5. Adds big Hinglish captions
6. In review mode, uploads a private YouTube video and skips Instagram

Uploads are off (`uploads_enabled: false`). A run makes the video and stops. YouTube, Instagram, and Facebook are not called.

The code is meant for [sidcasmmm/gyaan-papa](https://github.com/sidcasmmm/gyaan-papa). Nothing has been pushed, and nothing is posted. When the new accounts exist, add **new** secrets on that repo. Do not copy Financial Papa's. Same names: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `IG_ACCESS_TOKEN`, `IG_USER_ID`. Instagram uses a Facebook (Meta) token; this project does not post to a Facebook Page. Turn `uploads_enabled` and `platforms` on only after those secrets are the new channel's.

Runs free on GitHub Actions. You only pay for the AI pieces (see **Monthly cost** below).

---

## Monthly cost (1 video a day ≈ 25 min of video a month)

| Item | Service | Approx. per month |
|---|---|---|
| Scene images (≈9 per video × 30) | Gemini image API, ~$0.04/image | **~₹950** |
| Script writing | Claude Haiku (or Gemini) | **~₹100–200** |
| Papa's voice | Free Microsoft voice — *or* ElevenLabs Starter ($6, ~30 min) | **₹0 – ₹520** |
| Papa animation | Done in code | **₹0** |
| Papa character | Your own artwork, animated in code | ₹0 |
| Automation | GitHub Actions free tier | ₹0 |
| **Total** | | **≈ ₹1,100 – 1,700 / month** |

Prices are the providers' list prices in USD converted at roughly ₹85–88; check each site before you subscribe. Every bill goes to **your own** card on **your own** accounts. All are prepaid / pay-as-you-go — set spending limits in each dashboard so you can never overspend. Want ₹0 images? Set `images.provider: "pexels"` (free stock photos, less "story-like").

---

## One-time setup (about 1–2 hours)

### Step 1 — Put this project on your personal GitHub
1. Create a free account at github.com (your personal one).
2. **New repository** → name `financial-papa` → **Private** → Create.
3. **uploading an existing file** → drag in everything from this folder, including the hidden `.github` folder → Commit.
   (Mac: `Cmd+Shift+.` shows hidden folders. Windows: View → Hidden items.)

### Step 2 — AI keys
- **Gemini (required — makes the images, and Papa):** aistudio.google.com → **Get API key**. Turn on billing for that Google project so image generation works, and set a budget alert (e.g. ₹1,500).
- **Claude (writes the script, best Hindi):** console.anthropic.com → add ~$5 credit → **API Keys** → Create key.
  *Prefer one key only?* Set `writer.provider: "gemini"` in `config.yaml` and skip Claude.
- **ElevenLabs (optional, better voice):** elevenlabs.io → Starter plan → Voice Library → choose a mature Hindi male voice → copy its **Voice ID** into `config.yaml` (`voice.elevenlabs_voice_id`) and set `voice.provider: "elevenlabs"`. Copy your API key too.

### Step 3 — Add secrets to GitHub
Repository → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Needed? |
|---|---|
| `GEMINI_API_KEY` | Yes |
| `ANTHROPIC_API_KEY` | Yes, unless writer uses Gemini |
| `ELEVENLABS_API_KEY` | Only for ElevenLabs voice |
| `PEXELS_API_KEY` | Only if images.provider = pexels |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | For YouTube (Step 5) |
| `IG_ACCESS_TOKEN`, `IG_USER_ID` | For Instagram (Step 6) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optional previews on your phone |

### Step 4 — Papa is already included
Your character (orange tee, black hair and moustache) is already cut out and set up for lip-sync in `assets/papa/` (made from `assets/papa/character_sheet.png` with `tools/import_sheet.py`). Nothing to do.
*Optional:* the **Create Papa (run once)** workflow can instead generate a brand-new AI character — only use it if you want a different look, as it replaces these files.

### Step 4b — Pick Papa's voice (free, 5 minutes)
**Actions → Voice test (free, no keys needed) → Run workflow.** In ~5 minutes you get 3 sample videos under **Artifacts**, spoken by real Indian voices:
- `hindi-madhur` — Hindi male (default)
- `hinglish-prabhat` — Indian-English male reading Hinglish
- `hindi-swara` — Hindi female, for comparison

Put the one you like in `config.yaml` → `voice.name` (and `voice.read: "roman"` for Prabhat).
Want it even closer to popular reels (expressive, character-like)? Use ElevenLabs (~₹520/month): browse its Voice Library for an Indian/Hinglish male storyteller voice, then set `voice.provider: "elevenlabs"` and `voice.elevenlabs_voice_id`.

### Step 5 — Connect YouTube
1. console.cloud.google.com → create project `financial-papa`.
2. **APIs & Services → Library** → enable **YouTube Data API v3**.
3. **OAuth consent screen** → External → app name + your email → add scope `.../auth/youtube.upload` → add your Gmail as test user → **Publish app** ("In production"). If you leave it in Testing, the login expires after 7 days.
4. **Credentials → Create credentials → OAuth client ID → Desktop app** → download the JSON.
5. On your computer:
   ```
   pip install google-auth-oauthlib
   python tools/get_youtube_token.py path/to/downloaded.json
   ```
   Sign in with the account that owns the channel → copy the three values into GitHub Secrets.

> ⚠️ Videos uploaded through a new, un-audited Google project are locked to **private**. Fill Google's free "YouTube API Services – Audit and Quota Extension" form to post publicly via the API (days to weeks). Until then, review mode (below) is exactly what you want anyway.

### Step 6 — Connect Instagram
1. Switch your Instagram to **Creator/Business** and link it to a **Facebook Page** (Accounts Center).
2. developers.facebook.com → **Create app** → **Business** → add **Instagram** (API with Facebook Login).
3. business.facebook.com → **Settings → Users → System users** → add one (Admin) → **Assign assets**: your Page + Instagram + app → **Generate token**, expiry **Never**, permissions `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management` → that's `IG_ACCESS_TOKEN`.
4. Graph API Explorer → with that token run `me/accounts?fields=instagram_business_account` → the number is `IG_USER_ID`.

### Step 7 — Optional Telegram previews
@BotFather → `/newbot` → token = `TELEGRAM_BOT_TOKEN`. Message your bot, open `https://api.telegram.org/bot<TOKEN>/getUpdates`, copy `chat.id` = `TELEGRAM_CHAT_ID`.

### Step 8 — Test
**Actions → Daily finance Shorts → Run workflow → tick dry run**. After ~6 minutes download the video under **Artifacts**. Happy? Run without dry run.
From then on it posts automatically every day at **6:47 PM IST** (change the `cron` line in `.github/workflows/daily-shorts.yml`; times are UTC = IST − 5:30).

---

## Review mode vs auto mode (`config.yaml` → `publish_mode`)
- `"review"` (default): YouTube upload is **private**, Instagram skipped. Check it, then make it public in YouTube Studio and post the Reel from the Telegram copy.
- `"auto"`: publishes publicly to both. Switch after 2–3 weeks of good videos and after the YouTube audit is approved.

## Customising (`config.yaml`)
- **Style:** `style.mode: "cinematic"` (AI scenes + animated Papa) or `"cartoon"` (2D Papa, completely free).
- **Topics:** `explainers.topics`. One idea per line. The list runs top to bottom, then repeats.
- **Papa's personality:** `writer.tone`. **Length:** `writer.target_seconds`.
- **Channel name / handle / colours**, **news sources**, **voice speed & pitch**.
- **Background music:** drop one royalty-free `.mp3` into `assets/music/` (e.g. YouTube Audio Library). Never film songs — copyright strikes.
- **Preview the design with no keys:** `python main.py --offline`

## Rules that keep the channel safe
- **Not advice:** the script is told never to give medical, legal, or investment advice, and never to describe a lab procedure. Biology stays at school level. Each video carries that disclaimer. Keep it that way.
- **No invented facts:** the writer may only use the facts in the topic line plus standard school knowledge it is sure of. No fake quotes, no made-up measurements. Watch the first videos in review mode anyway — models still slip.
- **No real people in images:** prompts forbid celebrities, politicians, scientists' faces, and historical portraits, plus brand logos.
- **AI disclosure:** both platforms are told the video is AI-made (`disclose_ai: true`).
- **YouTube "inauthentic content":** near-identical automated videos can be demonetised. Mix in some of your own voice/opinion videos and reply to comments.

## Troubleshooting
- Red ❌ run → click it → open the failed step; the message says which part failed.
- `invalid_grant` (YouTube) → publish the OAuth consent screen (Step 5.3) and redo 5.5.
- Image errors → check Gemini billing is on; the video still renders with plain backgrounds.
- ElevenLabs errors (credits finished) → it automatically falls back to the free voice.
- "No new stories" → normal; it'll post next run.

## Project layout
```
main.py                     the whole pipeline
config.yaml                 your settings
pipeline/news.py            RSS news + de-duplication
pipeline/market.py          live index / currency / gold data
pipeline/writer.py          AI script (Papa's voice, Hinglish captions, image prompts, no invented facts)
pipeline/images.py          AI scene images (Gemini) or free stock photos (Pexels)
pipeline/voice.py           Hindi voice (free Edge or ElevenLabs) + word timings
pipeline/papa3d.py          animates the 3D Papa (lip-sync, blink, sway)
pipeline/render_cinematic.py  the reel layout
pipeline/character.py, render.py  2D cartoon style (and fallback if Papa isn't created yet)
pipeline/youtube.py, instagram.py, notify.py   uploads + Telegram
tools/make_papa.py          creates 3D Papa once
tools/get_youtube_token.py  connects YouTube once
state/history.json          stories already posted
```
Fonts: Poppins, Lora (SIL Open Font License).
