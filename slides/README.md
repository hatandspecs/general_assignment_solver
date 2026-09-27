# Planner talk

`planner-talk.md` — a [Marp](https://marp.app) deck, 15 slides, about 10–15
minutes. **Audience: program managers who would use the planner**, not
engineers — the MILP stays a black box that lands the targets and says when it
cannot.

Assertion-evidence: every headline is a full sentence making a claim, and the
body of the slide is the evidence for it.

## Previewing it

The styling lives in the deck's own front matter, so there is nothing to
register or configure.

- **VS Code** — install the *Marp for VS Code* extension (`marp-team.marp-vscode`)
  and open the file.
- **Command line** — `npx @marp-team/marp-cli@latest planner-talk.md --preview`

## Exporting it

```sh
npx @marp-team/marp-cli@latest planner-talk.md --pdf --allow-local-files
```

`--allow-local-files` is required, or every image comes out blank. There is
also a container route that needs no Node:

```sh
docker run --rm --init -v "$PWD/..:/home/marp/app" -e MARP_USER="$(id -u):$(id -g)" \
  marpteam/marp-cli slides/planner-talk.md --pdf --allow-local-files -o slides/planner-talk.pdf
```

## Images

`img/` holds screenshots cropped from `docs/images/grist_tutorial/` — the Grist
chrome and sidebar are trimmed so the working panel is legible at projector
size. Regenerate them from the originals if the tutorial screenshots change.

`img/monthly-cycle.svg` is hand-drawn, and mirrors the mermaid diagram at the
top of `docs/09-planner-tutorial.md`. Marp does not render mermaid, which is
why it is an SVG rather than a fenced diagram. If the cycle in the tutorial
changes, change this too.
