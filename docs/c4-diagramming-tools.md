# C4 diagramming — concepts, tooling evaluation, and a route to an interactive-diagram skill

**Researched:** 2026-08-01
**Companion document:** [`c4-model.md`](./c4-model.md) — the model itself (abstractions, the three core diagrams, notation, checklist)
**Question this document answers:** what should a `dev-skills` skill use to produce **interactive** C4 diagrams like [c4model.com/example](https://c4model.com/example/#SystemContext)?

**Two headline findings:**

1. **The reference artefact is a Structurizr static site export, and that export is mechanically trivial** — copy ~23 fixed asset files, then write one file containing `const jsonAsString = '<base64 of the workspace JSON>';`. Every asset is Apache-2.0 / MIT / MPL-2.0 and vendorable, and the viewer lays out in the browser. So it is reproducible with no Java, Node, Docker or network — the only work is emitting valid Structurizr workspace JSON. (§2, §3, §5)

2. **But we do not need it.** This repo already contains a working renderer of the same shape — `templates/workflow-diagram.html` positions nodes in HTML and draws SVG edges over them by measuring the DOM, in 114 KB with zero dependencies. The only capability C4 needs that it lacks is automatic graph layout, and for C4-sized graphs (4–20 elements) with C4's strong layout conventions, model-authored coordinates beat an algorithm. (§6)

**Recommendation: hand-rolled HTML** following the existing template pattern, with the data file kept **Structurizr-workspace-JSON compatible** so the interop escape hatch survives. (§6.4)

> **Revision note (2026-08-01):** this document originally recommended vendoring the Structurizr viewer (Option A) and dismissed hand-rolled HTML (Option D) as "highest effort, lowest fidelity." That assessment was made before reading `templates/workflow-diagram.html`, which already implements most of the hard parts. §6 has been rewritten; §2–§5 are unchanged and remain the factual record of how the Structurizr route works, which is still a live fallback.

---

## 1. C4's own position on diagramming

Recap of the concepts that constrain tool choice (full detail in [`c4-model.md`](./c4-model.md) §8, §9, §12).

### 1.1 Diagramming vs modelling — the decision that matters

c4model.com's [tooling page](https://c4model.com/tooling) splits every tool into two categories, and lists **"Modelling (recommended)"** first.

**Diagramming** — the tool's domain language is "boxes and lines." No validation, no querying, no element reuse; a change means manually editing every diagram the element appears in.

**Modelling** —

> "With a modelling tool, you're building up a non-visual model of your software architecture (a single definition of all elements and the relationships between them), and then creating different views (that become diagrams) on top of that model."

Benefits listed: alternative visualisations for large/complicated architectures, model querying, export to other tools. **"A model is just data!"**

Structurizr's [AI page](https://docs.structurizr.com/ai) sharpens this into a claim relevant to us: "diagrams as code" tools (PlantUML, Mermaid) and UI-driven tools score ❌ for LLM generation because they "don't understand the C4 model and don't respect its rules," whereas "models as code" is text-based, version-controllable, diff-friendly, and keeps styling and descriptions consistent across views.

**Implication for a skill:** generate a *model* once, derive *views* from it. Do not generate N independent diagrams — that guarantees drift between the context, container and component views, which is exactly what `evals-e2e-run`-style consistency scoring would flag.

### 1.2 Tool-selection questions the site poses

- Author technical level, and audience needs
- Diagramming or modelling?
- Drag-and-drop UI vs code-based
- Data storage — git vs cloud
- Diff-ability for pull requests
- Open vs closed format
- Licensing and hosting options

### 1.3 Non-negotiables any output must satisfy

From the [notation page](https://c4model.com/diagrams/notation) and [review checklist](https://c4model.com/diagrams/checklist) — these become acceptance criteria for a skill:

- Title stating diagram **type and scope**
- A **key/legend** covering every shape, colour, border style, line style, arrow head, icon and size used
- Every element: name, **explicit type**, short description, and **technology** (containers + components)
- Every relationship: **unidirectional**, an intent label matching the direction, protocol for inter-process communication, and **no bare "Uses"**
- Consistent, printer-friendly, colourblind-safe palette
- Diagram still readable with all colour/shape/size stripped

---

## 2. The reference artefact, dissected

`https://c4model.com/example/#SystemContext` — what it actually is, verified by fetching and decoding it.

### 2.1 Asset inventory (measured 2026-08-01)

| File | Size | Licence |
|---|---:|---|
| `js/jointjs-Core-4.1.3.js` | 1198 KB | MPL-2.0 |
| `js/structurizr-diagram.js` | 321 KB | Apache-2.0 |
| `css/bootstrap-5.3.7.min.css` | 227 KB | MIT |
| `js/dagre-1.1.8.js` | 115 KB | MIT |
| `js/jquery-3.7.1.min.js` | 85 KB | MIT |
| `js/bootstrap-5.3.7.min.js` | 79 KB | MIT |
| `js/crypto-js-4.1.1.min.js` | 47 KB | MIT |
| `js/structurizr-workspace.js` | 43 KB | Apache-2.0 |
| `js/structurizr-ui.js` | 30 KB | Apache-2.0 |
| `js/graphlib-2.2.4.min.js` | 29 KB | MIT |
| `js/structurizr-tooltip.js` | 15 KB | Apache-2.0 |
| `css/structurizr.css` | 13 KB | Apache-2.0 |
| `js/structurizr-quick-navigation.js`, `structurizr-navigation.js`, `structurizr-util.js`, `structurizr.js`, `jointjs-DirectedGraph`, `css/structurizr-static.css` | ~19 KB total | Apache-2.0 / MPL-2.0 |
| **Total viewer assets** | **~2.2 MB** | |
| `workspace.js` (this example's payload) | 221 KB | CC BY 4.0 content |
| `index.html` (the shell) | 26 KB | Apache-2.0 |

**Verified: `index.html` contains zero external `src`/`href` URLs.** The bundle is fully offline and works over `file://`.

For comparison, this repo's existing `diagram/index.html` is a **114 KB single self-contained file with no external scripts at all** — see §6.0 and §6.5.

### 2.2 The workspace payload format

`workspace.js` is a single line:

```js
const jsonAsString = '<base64-encoded Structurizr workspace JSON>';
```

and `index.html` line 120 does exactly:

```js
structurizr.workspace = new structurizr.Workspace(JSON.parse(decodeBase64(jsonAsString)));
```

That is the **entire** contract between generator and viewer.

### 2.3 Decoded structure of the example workspace

```
top level : configuration, description, documentation, id, lastModifiedDate,
            model, name, properties, views
model     : people, softwareSystems (→ containers → components), deploymentNodes, properties
views     : systemLandscapeViews, systemContextViews, containerViews, componentViews,
            dynamicViews, deploymentViews, imageViews, configuration
```

Model content: 3 people (Personal Banking Customer, Customer Service Staff, Back Office Staff); 4 software systems (Internet Banking System with 5 containers, plus Core Banking System, ATM, Amazon Web Services Simple Email Service).

Views present:

| View key | Elements | Relationships | Auto-layout? |
|---|---:|---:|---|
| `SystemLandscape` | 7 | 9 | no (manual x/y) |
| `SystemContext` | 4 | 4 | no |
| `Containers` | 8 | 9 | no |
| `Components` | 12 | 14 | no |
| `Dynamic-Collaboration` | 4 | 6 | no |
| `Deployment-Development` | 20 | 6 | no |
| `Deployment-Live` | 24 | 10 | no |

Simon Brown hand-laid all seven out — every view carries explicit `elements: [{id, x, y}]` plus `dimensions: {width, height}`. That is *not* a requirement (see §3.6).

**Element shape** (component example):

```json
{
  "id": "18",
  "name": "Sign In API",
  "description": "API endpoint for customer sign in.",
  "technology": "Spring MVC",
  "tags": "Element,Component",
  "documentation": {},
  "properties": { "structurizr.dsl.identifier": "internetBankingSystem.backend.signinApi" },
  "relationships": [
    { "id": "28", "sourceId": "18", "destinationId": "22",
      "description": "Validates credentials using", "tags": "Relationship" }
  ]
}
```

**View shape** (system context):

```json
{
  "key": "SystemContext",
  "name": "System Context View: Internet Banking System",
  "description": "The system context diagram for a fictional Internet Banking System | …",
  "softwareSystemId": "7",
  "elements": [ {"id":"1","x":124,"y":60}, … ],
  "relationships": [ {"id":"8"}, {"id":"9"}, … ],
  "animations": [ {"order":1,"elements":["7"]},
                  {"order":2,"elements":["1"],"relationships":["8"]}, … ],
  "dimensions": { "width": 1710, "height": 1415 },
  "enterpriseBoundaryVisible": true,
  "order": 2
}
```

Note `animations` — that is the step-through feature (`,` / `.` keys), driven purely by data.

**Styling is tag-driven**, in `views.configuration.styles.elements[]`:

```json
{ "tag": "Person",    "shape": "Person",     "fontSize": 22 }
{ "tag": "Container", "color": "#1168bd",    "stroke": "#1168bd" }
{ "tag": "Component", "shape": "Component",  "color": "#1168bd", "stroke": "#1168bd" }
{ "tag": "Element",   "shape": "RoundedBox", "strokeWidth": 7 }
{ "tag": "Relational Database Schema", "shape": "Cylinder" }
{ "tag": "Infrastructure Node",        "shape": "Ellipse" }
{ "tag": "Directory",                  "shape": "Folder" }
```

Elements carry `"tags": "Element,Container,<custom>"` and pick up every matching style. Semantics: **model = data, tags = the join key, styles = presentation.** Cleanly separable, which is ideal for a generator.

### 2.4 Interactivity inventory

What the static export gives you for free (per [the static-site docs](https://docs.structurizr.com/export/static-site), corroborated by the shell's source):

- **Double-click drill-down** between levels — the shell calls `findContainerViewsForSoftwareSystem`, `findComponentViewsForContainer`, `findDynamicViewsForElement`, `findImageViewsForElement`. This is the "zoom in" that makes it a C4 *browser* rather than a picture.
- **Zoom / pan** — `+`, `-`, mouse scroll
- **Quick navigation** — spacebar
- **Keyboard toggles** — `i` diagram key, `t` tooltips, `d` element descriptions, `m` metadata, `p` perspectives
- **Animation steps** — `,` and `.`
- **Perspectives** — switchable overlays (the example tags `Ownership: Team C` on elements)
- **URL parameters** — `?diagram=`, `?perspective=`, `?introduction=false`
- **Intro modal**, suppressible via the workspace property `structurizr.introduction = false`

Known removals: the static export **clears all documentation and decision records** — it is a diagram browser, not a docs site.

---

## 3. Structurizr — evaluation

[docs.structurizr.com](https://docs.structurizr.com/) — "the reference implementation" for the C4 model, and the only tool on c4model.com's list described as "The original tool designed to support the C4 model - models as code, manual layout, AI friendly."

### 3.1 ⚠️ The product was just consolidated — most guides on the internet are stale

The [end-of-life page](https://docs.structurizr.com/eol) lists these as **end of life, "replaced by the new consolidated tooling"**:

| End-of-life | Replacement |
|---|---|
| Structurizr **Lite** | the `local` command |
| Structurizr **CLI** | individual commands — `pull`, `push`, `export` |
| Structurizr **on-premises** | the `server` command |
| Structurizr **cloud service** | **no replacement** |

This matters directly: nearly every blog post, tutorial and existing agent skill targets `structurizr-cli` or `structurizr/structurizr-lite` Docker images. **A skill written against those is written against dead tooling.** Current release at time of research: **2026.06.28**.

### 3.2 Distribution and requirements

| Channel | Detail |
|---|---|
| Docker | `docker pull structurizr/structurizr`. Tags: hardened Temurin 21 Alpine (production), Temurin 21 Noble (general), Playwright-for-Java Noble (PNG/SVG export), preview (experimental) |
| Java `.war` | `java -jar structurizr.war <command> [parameters]` — **requires Java 21** |
| Homebrew | unofficial, "not maintained by us" |

**Licensing:** the [`structurizr/structurizr`](https://github.com/structurizr/structurizr) repo is **Apache-2.0** (322 stars, last push 2026-06-29). "All Structurizr commands are free to use from these binaries except for `server`, which requires a license."

> Note the discrepancy: c4model.com's tooling list categorises Structurizr under **paid/closed source**. The source is Apache-2.0 and every command except `server` is free — the categorisation reflects the commercial `server` tier, not the codebase.

### 3.3 Commands

`playground`, `local`, `server`, `export`, `push`, `pull`, `branches`, plus others.

- **`local`** — "provides a way to view diagrams and modify their layout," free and open source, for individual use. Looks for `workspace.dsl` / `workspace.json` in the data directory, whichever it finds first; auto-reflects file changes on browser refresh; **`localhost`-only access**; no auth/collaboration.
- **`server`** — the licensed, publishable, multi-user tier.
- **`export`** — see below.

### 3.4 Export formats

Via `export -workspace <file> -format <fmt> [-output <dir>]`:

| Format | Output |
|---|---|
| `plantuml`, `plantuml/structurizr`, `plantuml/c4plantuml` | PlantUML source |
| `mermaid` | Mermaid source |
| `websequencediagrams` | dynamic views |
| **`static`** | **"creates a static HTML site"** ← the reference artefact |
| `png`, `svg` | images via the browser-based renderer (needs the Playwright image) |
| `json` | Structurizr JSON |
| `theme` | JSON theme from workspace styles |
| *(FQCN)* | custom exporters |

Caveat from the docs: "the export formats do not support all available shapes/features when compared to Structurizr playground, local, and server."

### 3.5 The static site export is trivially reproducible

The whole implementation is [`StaticSiteExporter.java`](https://github.com/structurizr/structurizr/blob/main/structurizr-application/src/main/java/com/structurizr/command/StaticSiteExporter.java) — ~90 lines. In full, it:

1. Inlines theme styles into the workspace.
2. Copies `static.html` → `index.html`, plus 16 JS files, 4 CSS files and 3 images — **a fixed, hardcoded list**.
3. Clears workspace documentation and every element's documentation.
4. Writes `workspace.js` as `const jsonAsString = '<base64(json)>';`

That's it. No templating, no per-view generation, no computation.

**Consequence:** the Java binary is a *convenience*, not a dependency. Vendor the assets once and the generation step is "serialise JSON, base64 it, write one line."

Assets live at `structurizr-application/src/main/resources/static/static/` in the Apache-2.0 repo and are individually fetchable from `raw.githubusercontent.com`.

### 3.6 Layout — the browser does it

Verified in `structurizr-diagram.js`:

```js
if (view.automaticLayout) {
    structurizr.diagram.applyAutomaticLayout(
        view.automaticLayout.rankDirection,
        view.automaticLayout.rankSeparation,
        view.automaticLayout.nodeSeparation,
        view.automaticLayout.edgeSeparation,
        view.automaticLayout.vertices);
}
```

backed by `joint.layout.DirectedGraph.layout(...)` — i.e. **dagre, client-side**. So a generator does **not** need to compute coordinates; emit an `automaticLayout` object per view and the browser lays it out on load.

Confirmed by the docs: "JSON workspaces preserve manual layout information, while DSL versions rely on automatic layout."

**Trade-off to record.** `structurizr-diagram.js:355`:

```js
if (editable === false || view.automaticLayout !== undefined) { … }
```

Auto-laid-out views are **not draggable**. So it is either *good-enough automatic layout, not user-adjustable*, or *hand-authored x/y that the user can nudge*. A generator realistically ships auto-layout; if a user wants to fine-tune, they open the workspace in `structurizr local`, drag, and save the coordinates back.

### 3.7 MCP server

[docs.structurizr.com/ai/mcp](https://docs.structurizr.com/ai/mcp) — free and open source, standalone, stateless HTTP transport.

```
docker pull structurizr/mcp
docker run -it --rm -p 3000:3000 -e PORT=3000 structurizr/mcp <parameters>
```

Parameters select which tool groups are exposed: `-dsl`, `-plantuml`, `-mermaid`, `-server-create|read|update|delete`.

Tools: **validate/parse DSL**, **inspect for violations**, **export views to Mermaid / PlantUML / C4-PlantUML**, and workspace CRUD against a `server`.

A **public instance runs at `mcp.structurizr.com`** with DSL, PlantUML and Mermaid tools enabled.

Client config shown for Claude Desktop:

```json
{ "mcpServers": { "structurizr-mcp": {
    "command": "npx", "args": ["mcp-remote", "http://localhost:3000/mcp"] } } }
```

**Relevance:** the *inspection* tool is the interesting part — it is a C4-rules linter usable as a verification step. But wiring an MCP server into a plugin skill adds a network/Docker dependency, and MCP servers are configured per-user, not shipped by a plugin. Better treated as an **optional** validation path than a core dependency.

### 3.8 LLM generation guidance

[docs.structurizr.com/ai](https://docs.structurizr.com/ai) argues Structurizr suits LLM generation because the DSL is text-based, version-controllable, diff-friendly, and model-based ("consistent views onto a single model"). Two documented approaches: converting an existing hand-drawn diagram to DSL, and generating from a prompt.

Honest caveat from the docs: "a little cleanup is required, but it's a good starting point." No system prompt, no pitfalls list, no validation procedure is published — **so a skill has to bring its own validation** (see §7.4).

---

## 4. The alternatives

Full list from [c4model.com/tooling](https://c4model.com/tooling), extracted from the page's own data (22 tools), plus LikeC4 which is not listed there.

### 4.1 Modelling (the recommended category)

| Tool | Licence | Description |
|---|---|---|
| **Structurizr** | Apache-2.0 (listed "paid/closed") | "The original tool designed to support the C4 model - models as code, manual layout, AI friendly" |
| Archi | open source | ArchiMate modelling toolkit with a C4 viewpoint |
| C4InterFlow | open source | Architecture-as-Code framework, generates diagrams and analyses application architecture |
| Gaphor | open source | Modelling/documentation app |
| Isoflow | paid/closed | "Create interactive diagrams. In minutes." |
| Model | open source | Architecture models and diagrams in **Go** |
| Overarch | open source | Data model for holistic system description; C4 + UML via PlantUML |
| PyStructurizr | open source | **Python** DSL inspired by Structurizr, generates C4 diagrams |
| RDB modeling | open source | Simplified C4 in **YAML** |
| pumla | open source | Systematic re-use of PlantUML model elements |

### 4.2 Diagramming

| Tool | Licence | Description |
|---|---|---|
| C4-PlantUML | open source | PlantUML + C4 macros; the most widely copied option |
| Mermaid | open source | `C4Context` / `C4Container` / `C4Component` / `C4Dynamic` / `C4Deployment` |
| draw.io | open source | Client-side general diagram editor with C4 shapes |
| **BAC4 Standalone** | open source | "interactive web-based C4 modelling tool built with React… Runs completely standalone in any browser — no server, no installation, no dependencies!" |
| C4 Modelizer | open source | React visual editor for C4 |
| Keadex Mina | open source | "serverless IDE to easily code and organize at a scale C4 model diagrams" |
| Archinsight | open source | Architecture-as-code "Insight" language for C4 |
| C4Sharp | open source | **.NET** library for building C4 diagrams |
| CUE4Puml4C4 | open source | C4 as data in **CUE**, rendered via PlantUML |
| Diagrams | open source | Cloud architecture in **Python** |
| c4builder | open source | **Node.js** CLI for building/sharing a text-based architecture project |
| EasyC4 Diagram Creator | open source | Converts PlantUML-C4 / Mermaid-C4 text into `.drawio` |

### 4.3 LikeC4 — the strongest non-Structurizr option

Not on c4model.com's list, but the most active project in this space.

| Attribute | Value |
|---|---|
| Repo | [likec4/likec4](https://github.com/likec4/likec4) — **MIT**, 5,315 stars, pushed 2026-08-01 (vs Structurizr's 322 stars) |
| npm | `likec4@1.59.2`, **engines: node >= 22.22.3**, 17 dependencies |
| DSL | Own `.c4` / `.likec4` language; markets itself as "LLM-friendly", "AI agents understand natively" |
| Interactive output | **Yes** — `likec4 build` produces a deployable interactive static site |
| **Single file** | **Yes** — `likec4 build --output-single-file` |
| Embedding | Vite plugin, React components, Web Components |
| Other outputs | `export png/jpg` (Playwright), `export json`, `export drawio`, `gen mmd/dot/d2/plantuml/react/webcomponent` |
| Dev loop | `likec4 serve` with hot reload; `validate`, `format`, `lsp` |

**Trade-off vs Structurizr:** LikeC4 is more actively developed, MIT, and can emit a genuine single-file interactive artefact — but it needs **Node ≥ 22 in the target project**, uses a **non-C4-canonical DSL**, and its "views" model is its own rather than the reference C4 one.

### 4.4 Why Mermaid is the wrong choice here despite being tempting

Mermaid is already renderable in this repo's ecosystem (Artifacts render `mermaid` fences natively), which makes it superficially attractive. But:

- Mermaid's C4 support is **explicitly still experimental**
- **No real auto-layout** — "the position of shapes is adjusted by changing the order in which statements are written"
- Interactivity is essentially nil — no drill-down between levels, which is the whole point of the reference artefact
- Structurizr's own comparison: diagrams-as-code tools "don't understand the C4 model and don't respect its rules"

Useful as a *secondary* export (readable in a PR, embeddable in markdown), not as the primary artefact.

---

## 5. Feasibility proof

Carried out during this research, in the scratchpad:

1. Fetched all 23 static assets from `raw.githubusercontent.com/structurizr/structurizr/main/structurizr-application/src/main/resources/static/static/` → **24 files, 2.3 MB**.
2. Hand-authored a small `dev-skills` workspace JSON (2 people/systems + 2 containers, 2 views, tag styles, `automaticLayout` on both views) — **2,256 bytes**.
3. Base64-encoded it into `workspace.js` — **3,032 bytes**.

Result: a complete, self-contained, offline C4 diagram browser assembled **without Java, Node, Docker or the Structurizr binary**.

Location: `/private/tmp/claude-501/-Users-cagri-Git-dev-skills/20180645-…/scratchpad/poc/index.html`

> **Not yet verified:** that it renders correctly. No browser was available in this environment, so the proof is structural (asset list matches `StaticSiteExporter`, payload matches the `jsonAsString` contract, `index.html` has zero external references) rather than visual. The scratchpad is session-scoped, so regenerate if it has been cleaned up.

**Status after the §6 revision:** this proves the *fallback* route (Option B) is viable, not the recommended one. It stays in the record because it is the evidence that vendoring works if hand-rolled layout disappoints — and because opening it in a browser is still the fastest way to see the interaction target that Option A must match.

---

## 6. Options for the skill

### 6.0 The prior art already in this repo

`templates/workflow-diagram.html` → `diagram/index.html` (via `/dev:diagram-update`) is **114 KB, one file, zero dependencies, and interactive**. Its rendering technique, read from source:

- **Nodes are HTML.** Divs in normal document flow inside cards, or positioned from generator-supplied coordinates — the overview nodes use `left: n.x%` / `top: n.y px`, authored by the skill into the `{{OVERVIEW_NODES}}` token.
- **Edges are SVG drawn over the top.** `drawEdges()` (`:576`) measures each endpoint with `getBoundingClientRect()`, picks the box edges to connect based on relative centres, emits a bezier `path` with `marker-end` for the arrowhead, and places a `<text>` label at the midpoint.
- **Redraw on resize** (`:843`), debounced.

That is a working C4-style renderer in everything but the C4 vocabulary. It reframes the build/buy question entirely, because it means the "hand-roll" option starts from a proven base rather than from zero.

### 6.1 Capability-by-capability cost of hand-rolling

| Capability | Cost |
|---|---|
| Element boxes: name, type, technology, description | CSS. Trivial |
| C4 shapes — Person, Cylinder, RoundedBox, Component, Folder, Ellipse | ~50 lines of CSS using pseudo-elements |
| **Boundary boxes** (system / container groupings, dashed border + label) | A bordered div wrapping its children — **easier in HTML than in SVG-based tooling** |
| Drill-down between levels | Swap which `<section>` is visible; deep-link with `#hash`. ~20 lines, and more discoverable than Structurizr's double-click |
| Legend / key (mandatory per C4 notation) | Static HTML |
| Tooltips, keyboard toggles (`d` descriptions, `m` metadata, `i` key) | ~40 lines |
| Zoom / pan | CSS `transform: scale()` + drag handlers, ~30 lines. Or omit — HTML reflows, an SVG canvas does not |
| Edge lines, arrowheads, midpoint labels | **Already solved** at `workflow-diagram.html:576` |
| Animation steps (`,` / `.`) | Ordered element-id lists driving CSS classes. Easy if wanted |
| **Automatic graph layout** | The only genuinely hard part — see §6.2 |

### 6.2 The layout question, which is the whole decision

Three findings argue that model-authored coordinates beat an algorithm here:

1. **C4 diagrams are tiny.** System context 4–8 elements, container 5–15, component 10–20. Dagre solves arbitrary graph layout; this is not that problem.
2. **The canonical example is hand-laid-out.** Verified while decoding it (§2.3): all seven views carry explicit `elements: [{id, x, y}]` and `dimensions`, and **not one uses `automaticLayout`**. The reference artefact for "a good C4 diagram" was manually positioned by the model's author.
3. **C4 layout is conventional, not topological.** Users at the top, the system in the middle, datastores at the bottom, externals to the side. That convention carries meaning. A dagre rank assignment is topologically correct and convention-blind — presumably why Brown did not use it. An LLM authoring the model already knows where a database belongs; dagre does not.

Reinforcing this: Structurizr's own auto-layout is a one-way door — `structurizr-diagram.js:355` disables dragging on any view with `automaticLayout` (§3.6). So the vendored-bundle route yields layout that is neither conventional nor adjustable, whereas generator-authored coordinates are both, and are edited by changing numbers in a JSON array.

**Middle option if model-authored placement proves unreliable:** vendor **only dagre + graphlib — 144 KB, MIT** — and hand-roll everything else. That is 6% of the 2.3 MB bundle. JointJS (1198 KB), `structurizr-diagram.js` (321 KB) and Bootstrap CSS (227 KB) are the bulk and none of it is load-bearing for our needs.

### 6.3 The four options

#### Option A — Hand-rolled HTML, following the `workflow-diagram.html` pattern ✅ recommended

A new `templates/c4-diagram.html` owning all presentation; the skill authors data into tokens, as `/dev:diagram-update` already does.

| | |
|---|---|
| ➕ | House-style fit: one self-contained file, ~100 KB, no third-party code, no `NOTICE` file, no vendored-asset refresh procedure |
| ➕ | Most of the hard rendering is already written and proven in this repo |
| ➕ | Boundary nesting and responsive reflow are *easier* in HTML than in the SVG tooling |
| ➕ | Full control over C4 notation enforcement — mandatory technology labels, no bare "Uses", mandatory legend — which we want anyway |
| ➕ | Layout is conventional and user-editable (§6.2) |
| ➖ | Edge routing will be worse than JointJS's at the tail; probably invisible at 20 nodes |
| ➖ | We own every shape and every bug |
| ➖ | No interop by default — mitigated by the §6.4 refinement |
| ➖ | Layout quality depends on the model placing nodes sensibly; needs testing across real repos |

#### Option B — Vendor the Structurizr static viewer, generate workspace JSON

Ship the ~2.2 MB asset bundle in `templates/`; write `index.html` + `workspace.js`.

| | |
|---|---|
| ➕ | Byte-identical to c4model.com/example — drill-down, zoom, tooltips, animation, perspectives, shortcuts |
| ➕ | No toolchain in the target project; generation is `json.dumps` + base64 |
| ➕ | Output is a real Structurizr workspace — `structurizr local`, PlantUML/Mermaid/PNG export all work |
| ➕ | Licences all permissive and vendorable |
| ➖ | 2.3 MB / 24 files of third-party code (jQuery, Bootstrap, JointJS, dagre, graphlib, crypto-js) in the plugin repo |
| ➖ | Needs periodic refresh against upstream, plus attribution files |
| ➖ | Auto-laid-out views are not draggable (§3.6, §6.2) |
| ➖ | We still own workspace-JSON correctness |

Remains the best **fallback** if hand-rolled layout quality disappoints. If chosen, inline everything into a single ~2.4 MB HTML file to preserve the one-file rule and satisfy the Artifacts CSP; `crypto-js` (47 KB, only for encrypted workspaces) and Bootstrap CSS (227 KB, if the chrome is restyled) are the trim candidates.

#### Option C — Shell out to the Structurizr binary

Write `workspace.dsl`, run `docker run structurizr/structurizr export -workspace workspace.dsl -format static`.

| | |
|---|---|
| ➕ | DSL is compact and human-editable; upstream owns correctness and layout |
| ➕ | Zero vendored assets |
| ➖ | **Requires Java 21 or Docker in the target project** — a dependency this plugin has never imposed |
| ➖ | Fails offline and in restricted CI |
| ➖ | Produces the same 2.3 MB bundle anyway |

#### Option D — LikeC4 single-file build

Write `.c4` sources, run `npx likec4 build --output-single-file`.

| | |
|---|---|
| ➕ | Genuine single-file interactive artefact |
| ➕ | MIT, far more actively developed, explicitly LLM-oriented |
| ➖ | **Requires Node ≥ 22.22.3** in the target project |
| ➖ | Non-canonical DSL and view model |
| ➖ | `npx` pulls from the network on first run |

### 6.4 Recommendation

**Option A — hand-rolled HTML**, with two refinements:

1. **Keep the data file Structurizr-workspace-JSON compatible.** Render it ourselves, but store it in the documented schema (§7.1). Costs nothing at authoring time and preserves the whole interop escape hatch: a user who wants `structurizr local` to nudge layout, or a PNG/PlantUML/Mermaid export, can run the binary against our own data file. This converts Option B from a competing choice into a free downstream capability.
2. **Offer a Mermaid C4 secondary export** for PR review and markdown embedding — derivable from the same model, and readable where a 100 KB HTML file is not.

Rationale: the constraint that actually separates the options is dependencies in the target project, and A, B and the refinement all satisfy it. Between A and B, A wins on ~100 KB vs 2.3 MB, one file vs 24, no vendored third-party code, better layout for C4-shaped graphs, and consistency with `workflow-diagram.html` and `feature-tracker.html`. What B buys — battle-tested edge routing and free interop — is partly recovered by refinement 1 and partly not needed at C4 scale.

### 6.5 House-style comparison

| | Existing repo artefacts | Option A (hand-rolled) | Option B (Structurizr bundle) |
|---|---|---|---|
| Files | 1 | 1 | 24 |
| Size | 114 KB (`diagram/index.html`) | ~100 KB (est.) | 2.3 MB |
| Third-party code | none | none | jQuery, Bootstrap, JointJS, dagre, graphlib, crypto-js |
| Generation | token substitution | token substitution | JSON serialise + base64 |
| Layout | generator-authored coordinates | generator-authored coordinates | dagre in the browser, not draggable |

Option A is the only one that leaves the repo's conventions untouched.

---

## 7. What a skill would actually have to produce

### 7.1 Minimal working workspace JSON

```json
{
  "name": "My System",
  "description": "…",
  "model": {
    "people": [
      { "id": "1", "name": "Developer", "description": "…", "tags": "Element,Person",
        "relationships": [
          { "id": "10", "sourceId": "1", "destinationId": "2",
            "description": "Runs feature-* skills in", "tags": "Relationship" } ] }
    ],
    "softwareSystems": [
      { "id": "2", "name": "dev-skills plugin", "description": "…",
        "tags": "Element,Software System",
        "relationships": [
          { "id": "11", "sourceId": "2", "destinationId": "3",
            "description": "Reads and writes artefacts in",
            "technology": "Filesystem", "tags": "Relationship" } ],
        "containers": [
          { "id": "4", "name": "Skill definitions", "description": "…",
            "technology": "Markdown", "tags": "Element,Container" } ] },
      { "id": "3", "name": "Target project repo", "description": "…",
        "tags": "Element,Software System" }
    ]
  },
  "views": {
    "systemContextViews": [
      { "key": "SystemContext", "softwareSystemId": "2",
        "name": "System Context: dev-skills", "description": "…",
        "elements": [ {"id":"1","x":120,"y":60}, {"id":"2","x":120,"y":520},
                      {"id":"3","x":700,"y":520} ],
        "relationships": [ {"id":"10"}, {"id":"11"} ],
        "dimensions": { "width": 1200, "height": 900 } }
    ],
    "containerViews": [ … ],
    "componentViews": [ … ],
    "configuration": { "styles": { "elements": [
      { "tag": "Element",        "shape": "RoundedBox", "color": "#ffffff" },
      { "tag": "Person",         "shape": "Person",     "background": "#08427b" },
      { "tag": "Software System","background": "#1168bd" },
      { "tag": "Container",      "background": "#438dd5" },
      { "tag": "Component",      "background": "#85bbf0", "color": "#000000" }
    ], "relationships": [] } }
  }
}
```

### 7.2 Invariants a generator must hold

- **IDs are strings, globally unique** across people, systems, containers, components and relationships.
- **Relationships are declared on the source element**, carrying `sourceId` + `destinationId`; views reference them by `id` only.
- **Every element carries `tags`** including `Element` plus its type — that is how styles bind.
- **`technology` is required on containers and components** (C4 notation rule, §1.3) and on inter-process relationships.
- **A view lists only the elements it shows** — the model is complete, the view is a subset. This is the modelling-not-diagramming property, and it is what keeps the three levels consistent by construction.
- **`softwareSystemId` scopes** context and container views; `containerId` scopes component views.
- Nesting: `softwareSystems[].containers[].components[]`.
- **Coordinates:** per §6.2 the generator authors `x`/`y` per view element plus a view `dimensions`. Emitting `automaticLayout` instead is valid Structurizr but only takes effect in a Structurizr viewer — our own renderer needs real coordinates, and the two are mutually exclusive in Structurizr anyway (auto-layout overrides and disables dragging).
- If a `workspace.js` is also emitted for Structurizr-viewer compatibility, its base64 must be of the UTF-8 JSON bytes, single-quoted.

### 7.3 What the HTML template additionally needs

Under Option A the workspace JSON is the *data*; `templates/c4-diagram.html` is the *presentation*, filled by token substitution exactly as `workflow-diagram.html` is. Following that precedent the tokens would be roughly:

| Token | Content |
|---|---|
| `{{C4_WORKSPACE}}` | the workspace JSON inline as a JS object literal — one token, since the renderer walks the model itself |
| `{{C4_DEFAULT_VIEW}}` | view key to open on load |
| `{{GENERATED_AT}}`, `{{PLUGIN_VERSION}}` | as in the existing templates |

The renderer then, per view: place a positioned div per element (shape class from tags, and name / type / technology / description inside), wrap grouped elements in boundary divs, and call the `drawEdges()`-equivalent to stroke SVG paths between measured boxes. Views become `<section>`s; drill-down swaps visibility and updates the hash.

Ownership rule, mirroring `diagram-update`: **the template owns all presentation; the skill authors data only.**

### 7.4 Validation the skill should do itself

Upstream publishes no LLM-generation validation guidance, so we bring our own. Free static checks, all testable in `tests/`:

- Every `sourceId` / `destinationId` resolves to a real element
- Every view element/relationship `id` exists in the model
- No duplicate IDs
- Every container and component has non-empty `technology`
- No relationship description is a bare `"Uses"` / `"Use"` / empty (the notation rule)
- Every element has a non-empty `description`
- Component views only reference components of their `containerId`
- Every view element has `x`/`y`, and no two boxes in a view overlap given their rendered size
- Every view has a title, and the rendered page has a legend (C4 checklist, §1.3)

Optional deeper validation via the public **`mcp.structurizr.com`** inspection tool, or `structurizr export -format json` if the binary happens to be present — both as opt-in enhancements, never as requirements. These stay available precisely because §6.4 refinement 1 keeps the data file schema-compatible.

### 7.5 Where the artefact should live

Under Option A the output is two files, so this is far less constrained than it was under the vendored-bundle plan:

```
<wherever>/
  c4-workspace.json     ← source of truth: diff-friendly, committable, Structurizr-compatible
  c4-diagram.html       ← self-contained rendered view (~100 KB, no assets alongside)
```

Two plausible homes, and they are not exclusive:

- **Per repo** — `docs/architecture/` or a top-level `c4/`. Right for "what is this system", the dominant C4 use case, and the natural fit for the context + container views that C4 says every team should have.
- **Per feature** — `features/feature-v<N>-<desc>/c4/`, consistent with the mockups precedent. Right for "how does this feature change the architecture", where the value is the *delta*.

At ~100 KB there is no longer a storage argument against doing both; the argument is about which one is the source of truth when they disagree.

---

## 8. Open questions to settle before building

1. **Layout quality from model-authored coordinates** (§6.2) — the load-bearing assumption of Option A. Test across several real repos before committing; falling back to vendored dagre + graphlib (144 KB, MIT) is the cheap hedge, and Option B is the expensive one.
2. **Per repo, per feature, or both?** (§7.5) — and which is authoritative if both exist.
3. **Where does the model come from?** Codebase grounding (like `feature-design` Step 4), user interview (like `feature-mockup`), or both? A C4 model of an existing repo is largely *derivable* — manifests, service definitions, IaC, imports. Note the ownership/deployability heuristics in [`c4-model.md`](./c4-model.md) §2.2–§2.4 are what turn a dependency graph into a C4 model; the mapping is not mechanical.
4. **Which views to generate?** C4's advice is context + container always, component only where it adds value ([`c4-model.md`](./c4-model.md) §5, §13). Default to the first two; component views opt-in per container.
5. **Regeneration semantics** — wholesale overwrite (like `diagram-update`) or merge? Under Option A the user's hand-edits live in `c4-workspace.json` coordinates, so overwrite would discard them. Regenerating the HTML from an existing JSON, and only regenerating the JSON on explicit request, is probably the right split.
6. **Naming and chain position** — standalone `/dev:c4-diagram`, or a step inside `feature-design` alongside `feature-mockup`? The parallel is exact: `feature-mockup` shows what a feature will *look* like, a C4 skill shows how the system is *structured*. Both are "show before you write it down."
7. **Do we emit `workspace.js` too?** Costs ~1 line and makes the output openable in a Structurizr viewer as well as ours. Cheap insurance, or redundant clutter.
8. **Mermaid C4 secondary export** (§6.4 refinement 2) — in scope for v1 or later?

*Resolved by the §6 revision, retained for the record:* whether to vendor 2.3 MB of third-party assets (no — Option A), and whether a `NOTICE`/attribution file and refresh procedure are needed (not under Option A; required if Option B is ever adopted).

---

## 9. Sources

**C4 model:**
[Tooling](https://c4model.com/tooling) ·
[Notation](https://c4model.com/diagrams/notation) ·
[Review checklist](https://c4model.com/diagrams/checklist) ·
[Diagrams FAQ](https://c4model.com/diagrams/faq) ·
[Interactive example](https://c4model.com/example/#SystemContext)

**Structurizr:**
[Docs home](https://docs.structurizr.com/) ·
[End of life](https://docs.structurizr.com/eol) ·
[Binaries](https://docs.structurizr.com/binaries) ·
[local](https://docs.structurizr.com/local) ·
[export](https://docs.structurizr.com/export) ·
[static site export](https://docs.structurizr.com/export/static-site) ·
[AI + MCP](https://docs.structurizr.com/ai) ·
[MCP server](https://docs.structurizr.com/ai/mcp) ·
[DSL language reference](https://docs.structurizr.com/dsl/language) ·
[github.com/structurizr/structurizr](https://github.com/structurizr/structurizr) (Apache-2.0) ·
[`StaticSiteExporter.java`](https://github.com/structurizr/structurizr/blob/main/structurizr-application/src/main/java/com/structurizr/command/StaticSiteExporter.java)

**Alternatives:**
[LikeC4](https://likec4.dev/) · [likec4/likec4](https://github.com/likec4/likec4) (MIT) · [LikeC4 CLI](https://likec4.dev/tooling/cli/) ·
[Mermaid C4](https://mermaid.js.org/syntax/c4.html) ·
[C4-PlantUML](https://github.com/plantuml-stdlib/C4-PlantUML) ·
[BAC4 Standalone](https://github.com/DavidROliverBA/bac4-standalone) ·
[Keadex Mina](https://keadex.dev/en/projects/keadex-mina) ·
[Archinsight](https://archinsight.org) ·
[draw.io C4](https://www.drawio.com/blog/c4-modelling)
