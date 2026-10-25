<p align="center">
  <img src="docs/assets/banner.svg" alt="Alvarmethod — probe, plan, teach" width="960" />
</p>

<p align="center">
  <strong>One teacher. One mind.</strong><br/>
  Portable agent skills that run Eero Alvar’s AI learning loop.
</p>

<p align="center">
  <a href="https://github.com/vasanthsreeram/Alvarmethod/stargazers"><img src="https://img.shields.io/github/stars/vasanthsreeram/Alvarmethod?style=flat-square&color=c9a227" alt="stars" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2d6a4f?style=flat-square" alt="MIT" /></a>
  <a href="https://agentskills.io"><img src="https://img.shields.io/badge/Agent%20Skills-SKILL.md-111827?style=flat-square" alt="Agent Skills" /></a>
  <a href="https://youtu.be/kzcI5F4tGiU"><img src="https://img.shields.io/badge/method-Eero%20Alvar-b45309?style=flat-square" alt="Eero Alvar" /></a>
</p>

```bash
npx skills add vasanthsreeram/Alvarmethod -g --all
```

That’s the install. Works in **Claude Code**, **Codex**, **Grok**, **Pi**, **OpenCode**, Cursor, and the rest of the [skills CLI](https://skills.sh) agents.

Then open a **learning folder** (not this repo) and say:

```text
/teach I want a solid introduction to <topic>
```

You should get a **quiz picker** (not A/B/C/D in chat) → a mermaid DAG → **one** reasoning step → a lock-in quiz.

---

## Quick install

### `npx skills` (preferred)

The [open skills CLI](https://github.com/vercel-labs/skills). Discovers every `skills/*/SKILL.md` in this repo.

```bash
# global, every detected agent, no prompts
npx skills add vasanthsreeram/Alvarmethod -g --all

# list what’s in the pack
npx skills add vasanthsreeram/Alvarmethod --list

# one skill
npx skills add vasanthsreeram/Alvarmethod --skill teach -g -y

# one harness
npx skills add vasanthsreeram/Alvarmethod -g -y -a claude-code -a grok -a pi -a opencode -a codex
```

Update later:

```bash
npx skills update -g
```

### `npx` this repo

No extra CLI — runs [`install.sh`](install.sh) from GitHub:

```bash
npx github:vasanthsreeram/Alvarmethod
npx github:vasanthsreeram/Alvarmethod --list
npx github:vasanthsreeram/Alvarmethod --claude --grok
```

### Clone

```bash
git clone https://github.com/vasanthsreeram/Alvarmethod.git
cd Alvarmethod
./install.sh          # all known agent dirs
./install.sh --project
./install.sh --uninstall
```

| Agent | Global path |
|-------|-------------|
| Codex | `~/.codex/skills` + `~/.agents/skills` |
| Claude Code | `~/.claude/skills` |
| Grok | `~/.grok/skills` |
| Pi | `~/.pi/agent/skills` |
| OpenCode | `~/.config/opencode/skills` |

---

## The method

Credit: **[Eero Alvar — *How I Use AI to Learn Things*](https://youtu.be/kzcI5F4tGiU)** (2026-08-14). This pack implements that loop as Agent Skills. It is not his original Pi quiz / Obsidian setup. Captions: [`source/eero-alvar-how-i-use-ai-to-learn-things.md`](source/eero-alvar-how-i-use-ai-to-learn-things.md).

Many-to-many learning leaks:

| Direction | Waste |
|-----------|--------|
| One outlet → many students | Never fitted to *your* edge |
| One student → many outlets | Switching cost + the brain hedges on sources it does not trust |

Fix: **one interface, many sources.** Trust is engineered (verify). Struggle stays in the material. The system eats logistics.

```mermaid
flowchart LR
  A[Probe<br/>edge of this mind] --> B[Plan<br/>mermaid DAG]
  B --> C[Teach<br/>one node]
  C --> D[Lock-in quiz]
  D -->|pass| C
  D -->|fail| E[Insert prereq]
  E --> C
```

1. **Probe** — graded MCQ in the harness picker, start wide, binary-search every strand
2. **Plan** — mermaid DAG for *this* mind, shown *before* teaching, with stable node ids
3. **Teach** — one reasoning step, picture if needed, quiz tagged to that node, next node

The map is what makes it repeatable: strands, the plan DAG with `s`/`n` ids, a ledger of tagged checks, and a graph of propositions that survives the session. Rules in [`skills/teach/references/map.md`](skills/teach/references/map.md).

---

## Skills

| Skill | Job |
|-------|-----|
| `teach` | Full loop: probe → plan → one-step teaching |
| `probe` | Understanding map only |
| `learn-profile` | Write `.alvar/LEARNER.md` |
| `learn-visual` | One SVG, look at it, fix it |
| `learn-verify` | Fact-check a claim before it is taught as fact |
| `learn-graph` | Read and write the persistent knowledge graph |
| `learn-practice` | New problems on taught ideas, graded against keys written in advance |
| `learn-review` | Spaced retrieval of practice failures and edge evidence (SM-2) |
| `learn-import` | Import `.md` / `.txt` / `.pdf` as citable, chunked resources |
| `learn-dashboard` | Read-only local browser view of the plan, graph, practice and reviews |

Quizzes **must** use the native picker:

| Agent | Tool |
|-------|------|
| Grok / Codex | `ask_user_question` |
| Claude Code | `AskUserQuestion` |
| OpenCode | `question` |
| Pi | `quiz` / `ask_user` / `askUserQuestion` |

If the agent pastes A/B/C/D, say **“use the quiz tool.”** If it dumps a textbook, say **“one node only.”**

Session files land in the learning folder:

```text
.alvar/LEARNER.md
.alvar/alvar.db            # SQLite: plan, tagged checks, graph, mastery evidence
.alvar/graph.md            # propositions and reasoning chains, carried across sessions
.alvar/maps/<topic>.md
.alvar/sessions/<date>-<topic>.md
.alvar/resources/…         # copies of imported documents
.alvar/visuals/…
.alvar/backups/alvar-<timestamp>.db
```

Progress is not a flag in a file. The plan, the tagged checks and the graph live in SQLite through a
small standard-library runtime, so `/teach` resumes from evidence instead of memory. `./install.sh`
bundles the runtime into the skills that need it. Practice, review, import and the dashboard read and
write the same database; `alvar doctor` checks it and prints the fix for anything wrong. Details:
[docs/runtime.md](docs/runtime.md). Tests: `npm test` (28 tests, no network).

Point Obsidian at `.alvar/` if you want LaTeX preview.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Edit skills **here**, then reinstall. Don’t patch the copies under `~/.claude` / `~/.grok`.

## License

MIT for the skills, installer, and docs.

The video and spoken method are **Eero Alvar’s**. Watch the original: [youtu.be/kzcI5F4tGiU](https://youtu.be/kzcI5F4tGiU).
