Changelog

0.2.0 — 2025-10-24

Highlights
- Local and multi‑provider LLMs: In addition to OpenAI, you can now use local models via Ollama and other providers like Gemini through LiteLLM.
- Simple AI config: Choose explicit models per task in `[AI]` — no code changes needed.
- Clearer cost logging: Costs are estimated from API usage and reported per analysis.

What’s new
- New config keys under `[AI]`:
  - `text_model_short`, `text_model_long`, and `text_threshold_words` for short/long text routing
  - `image_model` for vision/image analysis
  - `tag_model` for tag consolidation
  - `image_temperature` (default 0.8) for vision responses
- API key fallback: If `OPENAI_API_KEY` is not set, the app can read `[OPENAI-API].API-Key` from your config as a fallback.

Smoother architecture
- The old OpenAI‑specific agent classes were removed. A thin, provider‑agnostic LiteLLM wrapper is used instead. Your setup happens in the config, not the code.

Migration guide (3 steps)
1) Update dependencies (ideally in a fresh virtualenv):
   - `pip install -e .`
2) Update your config (`~/.autoPDFtagger.conf`):
   - Under `[AI]`, set the models you want. Examples:
     - `text_model_short = openai/gpt-4o`
     - `text_model_long = openai/gpt-4o-mini`
     - `text_threshold_words = 100`
     - `image_model = openai/gpt-4o` (or `gemini/gemini-1.5-pro` or `ollama/llava`)
     - `tag_model = openai/gpt-4o-mini`
     - `image_temperature = 0.8`
   - API key: Prefer environment variable `OPENAI_API_KEY`. As a fallback, you can put it under `[OPENAI-API]` → `API-Key = sk-...`.
3) Try it:
   - `autoPDFtagger ./pdfs -f -t -i -c --json ./out.json`

Notes
- If image analysis is skipped, ensure `image_model` is set and supports vision.
- Costs are logged at the end of each analysis phase.
