# Contributing

Thanks for helping. This repo is a portable skill pack for Eero Alvar’s one-to-one teaching loop. PRs that make agents *actually teach better* beat PRs that add more files.

Credit stays with **[Eero Alvar — How I Use AI to Learn Things](https://youtu.be/kzcI5F4tGiU)**. We implement the method. We do not claim his original Pi extensions.

## What to send

**Wanted**

- Tighter `SKILL.md` instructions (agents follow them more often)
- Quiz-UI coverage for a harness we missed or renamed
- Fixes so `./install.sh` / `npx` / `npx skills add` land in the right folders
- One missing specialist skill that the loop actually needs
- Transcript / attribution corrections

**Usually skip**

- A sixth copy of the philosophy in a new file
- Framework wrappers, dashboards, or a web app
- “Recommended” on the correct quiz answer
- Markdown A/B/C/D quizzes as a fallback
- Session dumps from `.alvar/` (those are the learner’s, not the pack’s)

## Ground rules

1. **One home per fact.** Philosophy lives in `skills/teach/references/philosophy.md`. Process in `process.md`. Quiz tools in `quiz-ui.md`. Point at those files; don’t restate them.
2. **Native quiz UI only.** Probe and lock-in quizzes must call the harness tool (`ask_user_question`, `AskUserQuestion`, `question`, Pi `quiz` / `ask_user`). Never paste A/B/C/D in chat. Details: [`skills/teach/references/quiz-ui.md`](skills/teach/references/quiz-ui.md).
3. **Do not leak the answer.** No `(Recommended)` on the right option. No “correct choice first.”
4. **Struggle stays in the material.** Skills absorb logistics (order, files, verify, diagrams).
5. **Portable `SKILL.md`.** [Agent Skills](https://agentskills.io/specification) frontmatter only: `name`, `description`, optional `license` / `metadata`. `name` must match the folder. `description` ≤ 1024 chars and must include trigger phrases.
6. **Keep skills short.** Put detail in `references/` one level under the skill. Don’t nest reference chains.

## Repo map

```text
skills/<name>/SKILL.md     # what agents load
skills/teach/references/   # shared method (philosophy, process, quiz UI, files)
skills/*/assets/           # templates the skill writes
install.sh                 # copies skills into harness dirs
source/                    # credited transcript
templates/                 # human-facing copies
```

Canonical source is this repo. `./install.sh` *copies* into `~/.claude/skills`, `~/.grok/skills`, etc. Edit here, then reinstall.

## Edit a skill

```bash
git clone https://github.com/vasanthsreeram/Alvarmethod.git
cd Alvarmethod
# edit skills/<name>/SKILL.md (and references if needed)
./install.sh --list          # confirm targets
./install.sh                 # or --project / --claude / --grok …
```

Then open a **learning folder** (not this repo) and run `/teach` or “teach me X.” Check:

- [ ] Quiz picker opens (not letters in the transcript)
- [ ] Probe writes `.alvar/maps/<topic>.md`
- [ ] Plan is a mermaid DAG *before* teaching
- [ ] Teaching is one node, then a lock-in quiz
- [ ] No invented citations (`learn-verify` when unsure)

If you only changed Claude paths, still skim `quiz-ui.md` so Grok/Codex/OpenCode/Pi stay named correctly.

## Add a skill

1. Folder `skills/<name>/` with `name` matching the directory: `^[a-z0-9]+(-[a-z0-9]+)*$`
2. `SKILL.md` with YAML frontmatter + a body an agent can execute
3. Add `<name>` to the `SKILLS=(...)` array in `install.sh`; if it ships `scripts/alvar`, also to
   `RUNTIME_SKILLS=(...)` so the installed copy gets the runtime (a test checks both)
4. One line in the README skills table
5. Do not duplicate `philosophy.md` / `process.md` — link them

Ask first if the new skill isn’t part of probe → plan → teach (or visual / verify / profile). Extra skills that never get invoked are noise.

## Installer

`install.sh` is the compatibility layer. If a harness moved its skill dir, fix the script and the README table together.

```bash
./install.sh --list
./install.sh --uninstall   # removes copies only, not this repo
```

Don’t commit anything under a contributor’s `~/.claude` or `.alvar/`.

## Attribution

- Method and spoken ideas: Eero Alvar. Link the video. Don’t paraphrase him as if we invented the loop.
- Transcript in `source/` is auto-captions, lightly cleaned. Fix wording if you check against the video; don’t silently rewrite the argument.
- Code, skills, and docs in this repo: MIT (see `LICENSE`).

## Pull requests

1. Branch from `main`. Small, one-concern PRs.
2. Describe what an *agent* will do differently, not just what you edited.
3. Note which harnesses you actually ran (`grok`, `claude`, `codex`, `opencode`, `pi`).
4. No secrets, no learner maps, no force-push to `main`.

### PR checklist

- [ ] `name` matches folder; description has triggers
- [ ] Quiz path still goes through [quiz-ui.md](skills/teach/references/quiz-ui.md)
- [ ] `./install.sh --list` is still right
- [ ] README / installer updated if you added a skill or path
- [ ] Eero credit intact

Issues and PRs: [github.com/vasanthsreeram/Alvarmethod](https://github.com/vasanthsreeram/Alvarmethod).
