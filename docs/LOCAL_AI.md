# Local AI on your own computer

Exodus can use AI models that run on your own computer instead of a paid
cloud service. Nothing leaves your home, there's no per-message cost, and it
becomes the **Shared AI** everyone can pick in Settings → Account → Your AI.

This guide is written for a computer with **36 GB of memory**, such as an
Apple silicon Mac.

## How big a model fits

On an Apple silicon Mac, memory is shared between the processor and the
graphics chip. Exodus (and macOS) count about **two-thirds of the memory** as
usable for AI, so a 36 GB Mac has about **24 GB** for a model. Leave the rest
for Exodus, the browser and macOS.

| Model size | Fits? | Feels like |
|---|---|---|
| 7–9 billion parameters, 4–8 bit (5–10 GB) | Easily | Fast; good for quick helpers (titles, summaries) |
| 12–16 billion, 4–5 bit (8–14 GB) | Yes | A solid everyday assistant |
| 24–32 billion, 4 bit (14–20 GB) | Yes, one at a time | The best quality that fits |
| "MoE" models such as *30B-A3B* | Yes, at 4 bit | Big-model quality and much faster, because only a small part works on each word |
| 70 billion and larger | No | Use a cloud model for these |

"4-bit" (often written Q4 or 4bit) is a compressed copy of the model: a little
less precise, about a quarter of the size. It's the usual choice.

## 1. Install a model server (on the 36 GB computer)

On a Mac, Docker can't use the graphics chip, so the model runs in a normal
app next to Exodus. Pick one:

- **LM Studio** (easiest; lmstudio.ai): download models with a search box. It
  runs both **MLX** models (made for Apple silicon, usually fastest) and
  **GGUF** models. To serve:
  1. Open the **Developer** tab.
  2. Load a model.
  3. Press **Start Server**. It listens on port **1234**.
- **Ollama** (ollama.com): command-line. It uses GGUF models.
  1. Run `ollama pull <model>`.
  2. Start it so Docker can reach it with `OLLAMA_HOST=0.0.0.0:11434 ollama serve`.
  3. It listens on port **11434**.

Both speak the same "OpenAI-compatible" language Exodus uses.

## 2. Pick models with Exodus's model-fit tool

Exodus ranks models for your exact computer in the **Cookbook** (sidebar →
Tools → Cookbook), on its model list:

1. Press the **refresh** button ("Refresh selected server hardware and
   cached models"). It detects the 36 GB and downloads today's model list
   from Hugging Face. **Rescan** re-checks the hardware.
2. Turn on **Official only**, then sort by **Fit** or **Score**, and filter by
   use: general, coding, reasoning, or multimodal (reads pictures).
3. Prefer models marked **perfect** or **good** fit. Official releases and
   `mlx-community` conversions of them are fine.
4. Skip "abliterated" or "uncensored" variants. Those have their safety
   training removed, which isn't what you want for family.

A good starting set (two models loaded at once still fit):

- **Main assistant:** the best-scoring *general* model around **14–20 GB** at
  4 bit, or a *30B-A3B* MoE model for speed.
- **Quick helper:** a *7–8B* model at 4 bit (about 5 GB), for titles,
  summaries and background tasks.
- **Coding (optional):** a *Coder 30B-A3B* model at 4 bit, when you use Code.

When we ran the model-fit tool for a 36 GB Apple computer on 2026-10-24, the
top official picks that fit included:

- *Qwen 3.x 27B* at 4 bit, about 16 GB;
- *Gemma 27B / 31B* (QAT) at 4–6 bit, 16–25 GB;
- *Mistral Small 24B*, 19–27 GB;
- *Qwen3-Coder-30B-A3B* at 4 bit, about 25 GB, for coding.

New models come out every month, so trust the model-fit screen over this list.

## 3. Connect it to Exodus (admin)

Settings → **Added Models** → **Add Models** → connect a local model:

- **Address**, from inside Docker:
  - LM Studio: `http://host.docker.internal:1234/v1`
  - Ollama: `http://host.docker.internal:11434/v1`
- Leave it **shared with everyone**, so it appears as **Shared AI** for each
  person.
- Press **Test**, then save. Exodus lists the models the server offers.
- **Tools:** local models can already use notes, calendar and search through
  Exodus's safe text-based method. If the model supports native tool calling
  (most recent ones do; check `ollama show <model>`, or the model's page),
  set its **Tools** profile next to the model in Added Models to *compact*
  or *full* for more reliable tool use.

Then Settings → **AI Defaults**: choose the main assistant as the default
model, and the quick helper as the *utility* model.

## 4. If the AI computer isn't the Exodus server

If Exodus runs on a separate home server (`docs/HOME_SERVER.md`), the server
reaches the 36 GB computer over Tailscale:

1. In LM Studio, turn on **Serve on Local Network**. For Ollama, it already
   listens on `0.0.0.0`.
2. On the server, add the connection as
   `http://<ai-computer>.<tailnet>.ts.net:1234/v1` (or `:11434/v1`).
3. The AI only works while that computer is **on and awake**. On a Mac:
   System Settings → Energy → *Prevent automatic sleeping when the display is
   off*.

Only devices in your Tailscale network can reach it. Never forward these
ports on your router.

## Good to know

- **Cost:** local models count as **$0** toward each person's monthly AI
  cap (Settings → Account → Your AI).
- **Speed:** the first answer after loading a model is slower. 4-bit
  27–32B models are comfortable for chat. Use the quick helper for anything
  that runs often.
- **Memory:** loading a second big model can push the computer into
  swapping. Unload models you aren't using (LM Studio's eject button, or
  `ollama stop <model>`).
- **Privacy:** prompts and answers stay on your computers. Web search still
  goes through SearXNG, and cloud models (if anyone uses one) still go to that
  provider.

## Checklist

- [ ] The model server runs, and its **Test** in Settings → Added Models passes.
- [ ] A chat with the shared model answers.
- [ ] With tools on, "What's on my calendar this week?" uses the calendar.
- [ ] Settings → Account → Your AI → Shared AI lists the connection by name.
