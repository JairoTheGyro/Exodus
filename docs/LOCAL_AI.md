# Local AI on your own computer

Exodus can use AI models that run on a computer you own instead of a paid
cloud service. Nothing leaves your home, there's no per-message cost, and it
becomes the **Shared AI** everyone can pick in Settings → Account → Your AI.

What you can run depends on **how much memory the AI computer has**. Exodus
measures it for you.

## 1. See what fits your computer

Open **Settings → Account → Local AI** (admins). It shows:

- the computer's memory;
- how much of it AI models can use;
- what size of model fits, and the best official models for it, ranked by
  the Cookbook;
- the three setup steps below.

If the AI will run on a different computer than Exodus, open **The AI will
run on a different computer**, choose the kind of computer, type its memory,
and press **Check this computer**.

### Exodus in Docker: measure the whole computer

On a Mac or a Windows PC, Docker only gets part of the computer's memory, so
Exodus can't see the rest by itself. Local AI says so when this happens. To
fix it, open a terminal on the computer itself (not inside Docker), go to the
Exodus folder and run:

```
python3 scripts/host_hardware.py
```

It saves the computer's memory, processor and graphics to
`data/host-hardware.json`. Local AI and the Cookbook then use the whole
computer, and say when it was measured. `scripts/update_local.py` refreshes it
on every update; run it again yourself after changing hardware. Nothing is
sent anywhere.

When Exodus runs without Docker (`start-macos.sh`), or on Linux, it already
sees the whole computer.

### Rough guide by memory

How much memory AI can use:

- **Mac with an Apple chip:** memory is shared with the graphics chip, which
  can use about two-thirds of it on 16 GB Macs, three-quarters up to 64 GB,
  and four-fifths above that.
- **PC with an NVIDIA graphics card:** the card's own graphics memory
  (8, 12, 16 or 24 GB, for example) is what counts.
- **PC without a graphics card:** models run on the processor using about
  60% of the memory. It works, but slowly.

| Memory AI can use | What fits | Feels like |
|---|---|---|
| Under 6 GB (an 8 GB Mac) | Small models, up to about 8 billion parameters, only just | Quick helpers; a cloud AI is better for chat |
| 6–12 GB (a 16 GB Mac, an 8 GB card) | Up to about 8 billion | Quick helpers and simple chat |
| 12–20 GB (a 24 GB Mac, a 12–16 GB card) | Up to about 14 billion | A solid everyday assistant |
| 20–40 GB (a 32–48 GB Mac, a 24 GB card) | Up to about 32 billion, or "30B-A3B" models | The best quality most homes can run |
| 40–80 GB (a 64–96 GB Mac) | Up to about 70 billion | Close to cloud quality |
| Over 80 GB (a 128 GB+ Mac) | 100 billion and more | Very large models |

Sizes assume **4-bit** versions (often written Q4 or 4bit): compressed copies
that are a little less precise and about a quarter of the size. That's the
usual choice. "MoE" models such as *30B-A3B* are big-model quality and much
faster, because only a small part works on each word. Leave the rest of the
memory for Exodus, the browser and the operating system.

## 2. Install a model server (on the AI computer)

On a Mac, Docker can't use the graphics chip, so the model runs in a normal
app next to Exodus. Pick one:

- **LM Studio** (easiest; lmstudio.ai): download models with a search box. On
  a Mac it runs both **MLX** models (made for Apple chips, usually fastest)
  and **GGUF** models. To serve:
  1. Open the **Developer** tab.
  2. Load a model.
  3. Press **Start Server**. It listens on port **1234**.
- **Ollama** (ollama.com): command-line. It uses GGUF models.
  1. Run `ollama pull <model>`.
  2. Start it so Docker can reach it with `OLLAMA_HOST=0.0.0.0:11434 ollama serve`.
  3. It listens on port **11434**.

Both speak the same "OpenAI-compatible" language Exodus uses.

## 3. Pick models

Local AI shows the top five. For the full list, press **All models in
Cookbook** (or sidebar → Tools → Cookbook):

1. Press the **refresh** button ("Refresh selected server hardware and
   cached models"). It checks the hardware and downloads today's model list
   from Hugging Face. **Rescan** re-checks the hardware.
2. Turn on **Official only**, then sort by **Fit** or **Score**, and filter by
   use: general, coding, reasoning, or multimodal (reads pictures).
3. Prefer models marked **perfect** or **good** fit. Official releases and
   `mlx-community` conversions of them are fine.
4. Skip "abliterated" or "uncensored" variants. Those have their safety
   training removed, which isn't what you want for family.

A good starting set, if both fit together:

- **Main assistant:** the best-scoring *general* model that uses no more than
  about **two-thirds** of the memory AI can use, so a second model still fits.
- **Quick helper:** a *7–8B* model at 4 bit (about 5 GB), for titles,
  summaries and background tasks. On small computers, use just one model.
- **Coding (optional):** a *Coder* model, when you use Code.

New models come out every month, so trust Local AI and the Cookbook over any
list written down.

## 4. Connect it to Exodus (admin)

Settings → **Added Models** → **Add Models** → connect a local model
(Local AI's **Open Added Models** goes there):

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

## 5. If the AI computer isn't the Exodus server

If Exodus runs on a separate home server (`docs/HOME_SERVER.md`), the server
reaches the AI computer over Tailscale:

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
- **Speed:** the first answer after loading a model is slower. Local AI
  shows a rough speed for each model. Use the quick helper for anything that
  runs often.
- **Memory:** loading a second big model can push the computer into
  swapping. Unload models you aren't using (LM Studio's eject button, or
  `ollama stop <model>`).
- **Privacy:** prompts and answers stay on your computers. Web search still
  goes through SearXNG, and cloud models (if anyone uses one) still go to that
  provider.

## Checklist

- [ ] Local AI shows the computer's real memory (not only Docker's share).
- [ ] The model server runs, and its **Test** in Settings → Added Models passes.
- [ ] A chat with the shared model answers.
- [ ] With tools on, "What's on my calendar this week?" uses the calendar.
- [ ] Settings → Account → Your AI → Shared AI lists the connection by name.
