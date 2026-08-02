# The C4 model — research notes

**Researched:** 2026-08-01
**Primary source:** [c4model.com](https://c4model.com/) (Simon Brown, CC BY 4.0)
**Scope of this document:** the full C4 model, with emphasis on the **System Context**, **Container** and **Component** diagrams. Recorded as reference material for this repo; it is not a skill definition.

Every quoted phrase below is from c4model.com unless attributed otherwise. Third-party claims are marked as such.

---

## 1. What C4 is

C4 is **a set of abstractions plus a hierarchy of views over them**. It is not a notation, not a tool, and not a process.

Simon Brown developed it from running software architecture workshops in the mid-2000s, where the recurring problem was that "very few people in the room, myself included, were able to understand the diagrams!" He had used UML throughout his career, but "UML usage across the industry had already started to decline" and neither workshop attendees nor consulting clients wanted it. He switched to block diagrams in Visio at multiple levels of detail.

Timeline:

| When | What |
|---|---|
| 2006–2009 | Roots — workshop sketching exercises |
| QCon London, March 2010 | Camera-lens analogy (wide angle / telephoto / macro) → "four defined levels of abstractions: systems, containers, components, and classes" |
| QCon London, 2011 | Name "C4" appears, in the talk *Designing software, drawing pictures* |
| March 2018 | Fourth C changes from **Classes** to **Code**; official CC-licensed website + InfoQ article launch, after which adoption accelerates |

Stated influences: **UML** and the **4+1 architectural view model** — C4 is "a simplified version of the underlying concepts," meant to help developers understand systems and bridge the gap between architecture and code.

Adoption: 10,000+ people trained across 40 countries; named adopters include Spotify, Decathlon and Co-op; referenced by InfoQ, Wikipedia, Open Group standards, and described in *Fundamentals of Software Architecture* (2019) as "one of the emerging standards for diagramming software architecture."

### 1.1 The governing metaphor

> "maps of your code, at various levels of detail, in the same way you would use something like Google Maps to zoom in and out of an area you are interested in"

Each level has a **fixed scope**, a **fixed set of legal element types**, and a **named audience**. You zoom by selecting exactly one element at level *N* and drawing what is inside it at level *N+1*.

### 1.2 Three properties that prevent most misuse

1. **Abstraction-first, notation-second.** C4 says *what* to draw. It is explicitly not prescriptive about "the layout, shape, colour and style of these elements" (Wikipedia's summary of the same point). Boxes-and-lines, UML, ArchiMate or something else entirely are all acceptable, provided there is a key.
2. **No process and no team structure are implied.** It is "just a way to describe a software system."
3. **You do not need all four levels** — use "only those that add value." Most teams find context + container sufficient.

### 1.3 What C4 deliberately does not cover

Only **static structure**. Workflows, state machines and data models are out of scope; supplement with UML, BPMN/BPML, ArchiMate or ERDs. It also maps cleanly onto **arc42**'s building block views at the corresponding levels.

On the "step backwards from UML?" objection, the FAQ's position is: "if you're using UML… and it's working for you, stick with it." C4 targets teams that find UML too heavy or have already abandoned it.

Stated purposes: communication inside and outside development/product teams, efficient onboarding of new staff, architecture reviews/evaluations, risk identification, and threat modelling.

---

## 2. The abstraction hierarchy

The canonical one-sentence chain:

> A **software system** is made up of one or more **containers** (applications and data stores), each of which contains one or more **components**, which are implemented by one or more **code** elements (classes, interfaces, objects, functions, etc).

Plus **people** (actors, roles, personas, named individuals) who use software systems.

### 2.1 Person

Actors, roles, personas or named individuals. Human users of the system.

### 2.2 Software system

> "the highest level of abstraction and describes something that delivers value to its users, whether they are human or not"

Covers both the system being modelled and "other software systems upon which your software system depends (or vice versa)" — i.e. internal and external.

Heuristics for where the boundary falls:

- **Team ownership** — one development team is responsible for the implementation.
- **Code access** — the team is entitled to modify the code, often in a single source repository.
- **Deployment alignment** — frequently "everything inside the boundary of a software system is deployed at the same time."

**Explicitly not software systems:** product domains, bounded contexts, business capabilities, feature teams, tribes, squads. Those are organisational structures, not deployable software entities. The site concedes that terminology varies — "application", "product", "service" are used interchangeably across organisations — which is why the definition is deliberately anchored on ownership and deployment rather than vocabulary.

### 2.3 Container

> "a container represents an **application** or a **data store**. A container is something that needs to be running in order for the overall software system to work."

> "a runtime boundary around some code that is being executed or some data that is being stored"

**Is a container:**

- Server-side web applications (Java EE, ASP.NET, Ruby on Rails, Node.js)
- Client-side web applications / SPAs (Angular, jQuery, …)
- Desktop applications (WPF, Objective-C, JavaFX)
- Mobile applications (iOS, Android, Windows Phone)
- Server-side console applications and batch processes
- Serverless functions (AWS Lambda, Azure Functions)
- Databases (MySQL, SQL Server, MongoDB, Neo4j, Cassandra)
- Blob/content stores (Amazon S3, Azure Blob Storage, CDNs)
- File systems (local or networked — SAN/NAS)
- Shell scripts

**Typically not a container:** Java JAR files, C# assemblies, DLLs, modules. These "organise the code within those applications" rather than being runtime constructs.

> ⚠️ **"Container" ≠ Docker.** The site calls out the terminology clash directly: "many software developers now associate the term 'container' with Docker." C4's usage predates containerisation and means a *logical runtime boundary*. A Docker container is a *deployment node* in a deployment diagram, not a C4 container.

### 2.4 Component

> "a grouping of related functionality encapsulated behind a well-defined interface"

For OO languages, "a collection of implementation classes behind an interface."

**The defining constraint — components are not separately deployable:**

> "it's the container that's the deployable unit"

All components within a container run in the same process space. How they are *packaged* (JAR, DLL, shared library) is a separate concern from how they are *defined architecturally*.

Across paradigms:

| Paradigm | A component is… |
|---|---|
| Object-oriented (Java, C#, C++) | Classes and interfaces |
| Procedural (C) | A collection of files in a directory |
| Functional (F#, Haskell) | A module grouping related functions and types |
| JavaScript | A module containing objects and functions |

**Common misconception:** JAR files, assemblies, DLLs and namespace folders are not necessarily components — though they *might* map 1:1 in some architectural styles (e.g. hexagonal architecture).

Worked reference: the **Spring PetClinic** walkthrough, which shows Java classes grouped into architectural components. The value is identifying which code-level elements form "units of related functionality," removing class-level noise while preserving architectural clarity.

### 2.5 Code

> "Components are made up of one or more code elements constructed with the basic building blocks of the programming language that you're using — classes, interfaces, enums, functions, objects, etc."

### 2.6 The four levels are a hard ceiling

Terminology **can** be renamed to fit your language or organisation — functional-programming teams might prefer "module" and "function" over "component" and "class." The only requirement: "ensure all team members explicitly understand whatever terminology you adopt."

Adding **levels**, however, is treated as a smell. Wanting a fifth level usually signals one of two things:

1. **Misunderstanding or misuse of the existing levels.**
2. **Modelling organisational constructs rather than true abstractions** — subsystems, bounded contexts, layers and libraries are organisational groupings, not abstraction tiers.

The site frames the model's strength as *forcing precision*: arguing over whether a database is a container or a component makes a team define exactly what it means, and that clarity is the payoff. Extra levels are "possible as an advanced practice," but only when genuinely needed and precisely defined — otherwise you are back to ad hoc abstractions and imprecise terminology.

---

## 3. Level 1 — System Context diagram

| Attribute | Value |
|---|---|
| **Scope** | One software system |
| **Primary elements** | The software system in scope |
| **Supporting elements** | "People (e.g. users, actors, roles, or personas) and software systems (external dependencies) that are directly connected to the software system in scope" |
| **Audience** | "Everybody, both technical and non-technical people, inside and outside the software development team" |
| **Recommended?** | **"Yes, a system context diagram is recommended for all software development teams."** |
| **Rot rate** | Slowest — "changes very slowly" |

"A good starting point for diagramming and documenting a software system," providing a zoomed-out view. It focuses on "people (actors, roles, personas, etc) and software systems rather than technologies, protocols and other low-level details."

Shape of the diagram: your system as a single central box, surrounded by the users and systems it interacts with. Everything outside the box is typically outside your organisation's responsibility.

Key characteristics:

- Big picture, not implementation detail
- **No technology, no protocols** at this level
- Presentable to non-technical stakeholders as-is
- Relationships and dependencies at the *system* level only

### Worked example (Big Bank plc)

- **Person:** Personal Banking Customer
- **System in scope:** Internet Banking System
- **External systems:** Mainframe Banking System; E-mail System (the internal Microsoft Exchange system)

---

## 4. Level 2 — Container diagram

| Attribute | Value |
|---|---|
| **Scope** | A single software system |
| **Primary elements** | Containers within that software system |
| **Supporting elements** | People and software systems directly connected to those containers |
| **Audience** | "Technical people inside and outside the software development team; including software architects, developers and operations/support staff" |
| **Recommended?** | **"Yes, a container diagram is recommended for all software development teams."** |
| **Rot rate** | Slow — "changes relatively slowly unless heavily using microservices" |

Purpose: zoom into one software system to show **"the high-level shape of the software architecture and how responsibilities are distributed across it,"** including the major technology choices and how containers communicate with each other.

It stays "simple, high-level technology focussed" and serves developers and operations staff equally.

Requirements at this level:

- **Every container carries its technology.**
- **Every inter-process relationship carries its protocol.**

### 4.1 It is not a deployment diagram

The container diagram "deliberately omits deployment details like clustering, load balancers, and failover mechanisms, as these vary across environments." One box = one *logical* container, regardless of how many instances run. Deployment topology belongs in a deployment diagram.

### 4.2 Worked example (Big Bank plc — Internet Banking System)

| Container | Technology | Responsibility |
|---|---|---|
| Web Application | Java, Spring MVC | Delivers the static content and the Internet banking SPA |
| Single-Page App | JavaScript, Angular | Provides all the Internet banking functionality to customers via their web browser |
| Mobile App | C#, Xamarin | Provides a limited subset of the Internet banking functionality via mobile |
| API Application | Java | Provides Internet banking functionality via API |
| Database | Relational database schema | Stores user registration information, hashed auth credentials, access logs, etc. |

Relationships (with protocols): Customer → Web App / SPA (HTTPS); Web App → delivers → SPA; SPA and Mobile App → API Application (JSON/HTTPS); API Application ↔ Database (JDBC); API Application → E-mail System (SMTP); API Application → Mainframe Banking System (XML/HTTPS).

> Note the SPA modelling: the server-side web app that *delivers* the SPA and the SPA *running in the browser* are two separate containers.

---

## 5. Level 3 — Component diagram

| Attribute | Value |
|---|---|
| **Scope** | A single container |
| **Primary elements** | Components within the container in scope |
| **Supporting elements** | Containers (within the software system in scope), plus people and software systems directly connected to the components |
| **Audience** | "Software architects and developers" |
| **Recommended?** | **"No, only create component diagrams if you feel they add value, and consider automating their creation for long-lived documentation."** |
| **Rot rate** | Fast — "may change frequently during active development" |

Purpose: "zoom in and decompose a container to describe the components that reside inside it; including their responsibilities and the technology/implementation details."

### 5.1 Why the recommendation is "no" by default

This is the first level where the official answer is *not* an unqualified yes, and the reason is **maintenance cost**. Component structure changes as teams restructure code, so hand-drawn component diagrams go stale quickly. If you want them as long-lived documentation, **generate them** — from static code analysis, annotations, or a modelling tool — rather than drawing them.

### 5.2 When it does pay off

It shows which code elements cluster into "units of related functionality," removing class-level noise while preserving architectural clarity. Useful for the most important or architecturally significant containers, for onboarding into a complex container, and for threat modelling a trust-sensitive one.

### 5.3 Worked example (Big Bank plc — inside the API Application)

| Component | Technology | Responsibility |
|---|---|---|
| Sign In Controller | Spring MVC REST controller | Allows users to sign in |
| Accounts Summary Controller | Spring MVC REST controller | Provides customers with a summary of their bank accounts |
| Reset Password Controller | Spring MVC REST controller | Allows users to reset their password |
| Security Component | Spring Bean | Provides functionality related to signing in and changing credentials → Database (JDBC) |
| E-mail Component | Spring Bean | Sends e-mail → E-mail System |
| Mainframe Banking System Facade | Spring Bean | A facade onto the mainframe banking system → Mainframe (XML/HTTPS) |

Supporting elements on the same diagram: the SPA and Mobile App containers (JSON/HTTPS inbound to the controllers), the Database container, and the Mainframe Banking System.

---

## 6. Level 4 — Code diagram

| Attribute | Value |
|---|---|
| **Scope** | A single component |
| **Primary elements** | Classes, interfaces, objects, functions, database tables, etc. within the component |
| **Audience** | Software architects and developers |
| **Notation** | UML class diagrams, entity relationship diagrams, or comparable |
| **Recommended?** | **"not recommended for anything but the most important or complex components"** |
| **Rot rate** | Immediate |

"An optional level of detail and is often available on-demand from tooling such as IDEs." Prefer IDE/UML-tool generation over hand-drawn static documentation, particularly "for long-lived documentation."

---

## 7. The three supplementary diagrams

These matter for understanding the core three, because they absorb the concerns the core three deliberately exclude.

### 7.1 System Landscape

| Attribute | Value |
|---|---|
| **Scope** | "An enterprise/organisation/department/etc" |
| **Primary elements** | "People and software systems related to the chosen scope" |
| **Audience** | "Technical and non-technical people, inside and outside the software development team" |
| **Recommended?** | "Yes, particularly for larger organisations — it's a bridge into the enterprise architecture world" |

Rationale: "The system context, container, component, and code diagrams are designed to provide a static view of a single software system but, in the real-world, software systems never live in isolation."

Relationship to the context diagram: **"A system landscape diagram is really just a system context diagram without a specific focus on a particular software system."** Portfolio-level rather than single-system.

### 7.2 Dynamic

| Attribute | Value |
|---|---|
| **Purpose** | "Show how elements in the static model collaborate at runtime to implement a user story, use case, feature, etc." |
| **Scope** | A particular feature, story or use case |
| **Elements** | Software systems, containers, or components — whichever level the story is told at |
| **Audience** | Technical and non-technical, inside and outside the team |
| **Notation** | **Numbered interactions** indicating ordering (based on UML communication diagrams); free-form arrangement |
| **Recommended?** | **"Dynamic diagrams should be used sparingly to show interesting/recurring patterns or features that require a complicated set of interactions."** |

Collaboration-style and sequence-style layouts convey identical information; pick whichever reads better.

### 7.3 Deployment

| Attribute | Value |
|---|---|
| **Scope** | "One or more software systems within a single deployment environment (e.g. production, staging, development, etc)" |
| **Primary elements** | **Deployment nodes** (physical server, VM, containerised infrastructure, execution environment — nestable), plus software system instances and container instances |
| **Supporting elements** | **Infrastructure nodes** — "DNS services, load balancers, and firewalls" |
| **Audience** | "Technical people inside and outside of the software development team; including software architects, developers, infrastructure architects, and operations/support staff" |
| **Notation** | Vendor-specific icons (AWS, Azure, …) permitted **when included in the diagram legend** |
| **Recommended?** | Yes |

This is where clustering, replicas, load balancing and failover live — the things the container diagram deliberately drops.

---

## 8. Notation

C4 mandates no colours and no shapes. It mandates **self-description**.

### 8.1 Per diagram

- **Title** stating the diagram **type and scope** — e.g. "System Context diagram for My Software System"
- **Key/legend** explaining every notational device used: shapes, colours, border styles, line styles, arrow heads, icons, sizes
- The diagram should be "mostly understood without a narrative"

### 8.2 Per element

- **Name**
- **Type explicitly stated** — Person, Software System, Container, or Component
- **Short description** giving an "at a glance" view of key responsibilities
- **Technology labelled** — required for every container and component

Conventional rendering (as produced by Structurizr's defaults; the *layout* is convention, the *content* is the C4 requirement):

```
        Accounts Summary Controller
     [Component: Spring MVC Rest Controller]

     Provides customers with a summary of
     their bank accounts.
```

### 8.3 Per relationship

- **Unidirectional lines only** — one arrow head, one direction
- **A label describing intent**, worded consistently with the arrow direction
- **"Avoid vague single-word labels like 'Uses'"**
- **Technology/protocol named** for inter-process communication
- Dependency-style ("reads from", "uses") vs data-flow-style ("customer update events") is a per-diagram choice: "Sometimes diagrams work better showing dependency relationships (e.g. uses, reads from, etc), and sometimes data flow (e.g. customer update events) works better." Be consistent, and prefer explicit verb phrasing — "sends customer update events to" over bare "customer update events."

### 8.4 Colour

C4 does not dictate a palette. Any palette is acceptable provided it is:

- Consistent within and across diagrams
- Printer-friendly
- Accessible to colourblind audiences

Corollary (community checklist phrasing): the diagram should still make sense with all colour, shape and size stripped away — "those things are to make it aesthetically pleasing, not convey necessary information."

### 8.5 Core principle

Notation should be "as self-describing as possible," and all diagrams should include an explanatory key/legend regardless of which notation is used (boxes and lines, UML, ArchiMate, or something else).

---

## 9. Review checklist (verbatim)

The official checklist is phrased as questions a **reader** should be able to answer — not as author intentions. It is the cheapest available quality gate.

**General**
- Does the diagram have a title?
- Do you understand what the diagram type is?
- Do you understand what the diagram scope is?
- Does the diagram have a key/legend?

**Elements**
- Does every element have a name?
- Do you understand the type of every element? (i.e. the level of abstraction; e.g. software system, container, etc)
- Do you understand what every element does?
- Where applicable, do you understand the technology choices associated with every element?
- Do you understand the meaning of all acronyms and abbreviations used?
- Do you understand the meaning of all colours used?
- Do you understand the meaning of all shapes used?
- Do you understand the meaning of all icons used?
- Do you understand the meaning of all border styles used? (e.g. solid, dashed, etc)
- Do you understand the meaning of all element sizes used? (e.g. small vs large boxes)

**Relationships**
- Does every arrow have a label describing the intent of that relationship?
- Does the description match the relationship direction?
- Where applicable, do you understand the technology choices associated with every relationship? (e.g. protocols for inter-process communication)
- Do you understand the meaning of all acronyms and abbreviations used?
- Do you understand the meaning of all colours used?
- Do you understand the meaning of all arrow heads used?
- Do you understand the meaning of all line styles used? (e.g. solid, dashed, etc)

---

## 10. Hard cases

### 10.1 Microservices

The answer depends on **ownership**, not on technology:

| Situation | Modelling |
|---|---|
| **One team owns all the services** | Microservices are an internal implementation detail. Each is modelled as a **group of containers** — typically an API container plus a database-schema container — inside the single software system boundary, distinguished by colour coding or grouping boxes. |
| **Separate teams own separate services** | Each service is "promoted" from a container group to a complete **software system**, with its own context and container diagrams. Reflects Conway's Law. |

Anchoring quote (Lewis & Fowler, cited by the site): "the microservice architectural style is an approach to developing a single **software system** as a suite of small services, each running in its own process."

Governing guidance: "The approach to take for diagramming a microservices architectural style depends upon the ownership of the individual services, and whether you see them as an implementation detail inside a single software system or as separate software systems."

**Serverless:** an AWS Lambda is modelled as a single stateless **container** within the system, not as a separate software system.

### 10.2 Queues and topics

Core principle: treat "each separate queue and topic as being a 'data store'" rather than modelling the broker.

| Approach | Verdict | Trade-off |
|---|---|---|
| Message bus as **one** C4 container | **Incorrect** | Obscures the actual coupling between producers and consumers |
| Each queue/topic as its **own** container | Correct — *explicit* | Coupling is transparent; can reason independently of deployment topology; more clutter |
| **Omit** queues, name them in the relationship label | Correct — *implicit* | "a visually simpler and less cluttered diagram"; queues less visible |

"Neither version of the diagrams is 'better' than the other, they are just telling the same story in a different way."

Additional notes: arrow direction can be flipped to emphasise publisher/subscriber roles rather than plain left-to-right flow. When services are modelled as separate software systems, **ownership** of each queue/topic matters — who defines the message format and the queue's operational behaviour.

### 10.3 Other cases

| Situation | Resolution |
|---|---|
| **SPA + its server** | Two containers — the server-side app that delivers the SPA, and the SPA running in the browser |
| **Shared library** | Not a container (not independently deployable). Third-party guidance: show it as a component wherever it is used |
| **External system internals** | Don't model them. Model external systems at the boundary and abstract the interaction |
| **Docker container** | A deployment node in a deployment diagram — not a C4 container |
| **Diagram too big** (30 boxes, 100 arrows) | Split into multiple diagrams, each scoped to one area or use case. C4 scales by decomposition, not density |

---

## 11. Common mistakes

Consolidated from Simon Brown's *The C4 Model — Misconceptions, Misuses & Mistakes* (GOTO 2024) and the [workingsoftware.dev write-up](https://www.workingsoftware.dev/misuses-and-mistakes-of-the-c4-model/):

| Mistake | Why it's wrong | Correction |
|---|---|---|
| "C4 forces too much text in boxes" → strip the text | Ambiguity returns | Keep the clarifying text; produce simplified variants for specific audiences instead |
| **Removing metadata** (element type, technology) | Reintroduces exactly the interpretive confusion C4 exists to remove | Retain type + technology designations |
| Showing the **decision-making process** | "Architecture diagrams show the outcomes of decisions, not the decision-making process" | Use ADRs for decisions |
| **Omitting deployment** entirely | The static three deliberately exclude operational detail, so nothing covers it | Add deployment diagrams and runtime (dynamic) views |
| **Confusing container and component** | "Containers are deployable units, while components are non-deployable elements inside a container" | Apply the deployability test |
| **Adding arbitrary abstraction levels** ("subcomponents") | Recreates the ad hoc chaos C4 replaced | Stay within the four defined levels |
| **Overusing subsystems** | Ambiguous, superficial representations | Focus on the core levels; avoid intermediate abstractions |
| **Detailing external containers** | Exposes internals you don't own; creates coupling | Model external systems at the boundary |
| **Shared libraries as containers** | Not deployable units | Represent as components across the diagrams that use them |
| **Single-container message brokers** | Obscures pub/sub and point-to-point relationships | Model individual queues/topics as containers (or as relationship labels) |
| **Mixing abstraction levels** on one diagram (database tables beside business systems) | Confuses the audience, harder to maintain | One level per diagram |

> **Observation worth recording:** the widely-copied [C4-PlantUML `bigbankplc` container sample](https://github.com/plantuml-stdlib/C4-PlantUML/blob/master/samples/C4_Container%20Diagram%20Sample%20-%20bigbankplc.puml) labels nearly every relationship `"Uses"`, which the official notation page explicitly warns against ("Avoid vague single-word labels like 'Uses'"). It is a good *structural* template and a poor *labelling* template — worth not copying wholesale.

---

## 12. Tooling

### 12.1 The decision that matters: diagramming vs modelling

**Diagramming** — the tool's domain language is "boxes and lines." Consequences: no validation, no querying, no easy element reuse; a single change requires manual updates across every diagram the element appears in. Lower barrier to entry, which is why "diagramming over modelling" has historically dominated.

**Modelling** —

> "With a modelling tool, you're building up a non-visual model of your software architecture (a single definition of all elements and the relationships between them), and then creating different views (that become diagrams) on top of that model."

Which enables: alternative visualisations for complex architectures, querying the model, export to other tools. "A model is just data!" The site's recommendation is **modelling** for long-lived architecture documentation, because it resolves diagramming's inherent maintenance problem semantically.

### 12.2 Tool-selection questions posed by the site

- Author technical level, and audience needs
- "Diagramming or modelling?"
- "Drag and drop" UI vs code-based
- Data storage — git vs cloud
- Diff-ability for pull requests
- Open vs closed format
- Licensing and hosting options

### 12.3 Concrete options

| Tool | Kind | Notes |
|---|---|---|
| **Structurizr DSL** | Modelling, text | The reference implementation. `workspace { model { … } views { … } }`; relationships via `->`; views: `systemContext`, `container`, `component`, `dynamic`, `deployment`; `include *`, `autoLayout`. Structurizr Lite runs locally |
| **C4-PlantUML** | Diagramming, text | `C4_Context.puml` / `C4_Container.puml` / `C4_Component.puml` includes; `Person()`, `System()`, `System_Ext()`, `Container()`, `ContainerDb()`, `System_Boundary()`, `Rel()` |
| **Mermaid** | Diagramming, text | `C4Context`, `C4Container`, `C4Component`, `C4Dynamic`, `C4Deployment`. PlantUML-compatible syntax. **Still flagged experimental**; no full auto-layout — position is controlled by statement order |
| **LikeC4** | Modelling, text | Newer; publishes interactive diagram sites |
| **Visual Paradigm, draw.io, Excalidraw, Visio** | Diagramming, GUI | Templates exist for the Big Bank plc example |

Minimal Structurizr DSL covering both a container and a component view:

```
workspace {
  model {
    u = person "User"
    s = softwareSystem "Software System" {
      webapp = container "Web Application" {
        c1 = component "Component 1"
        c2 = component "Component 2"
      }
      database = container "Database"
    }
    u -> c1 "Uses"
    c1 -> c2 "Uses"
    c2 -> database "Reads from and writes to"
  }
  views {
    container s { include *; autoLayout lr }
    component webapp { include *; autoLayout lr }
  }
}
```

`include *` pulls in the containers inside the view's scoped software system plus any people and software systems with a direct relationship to/from them.

### 12.4 Keeping diagrams current

Rot rate by level: context (very slow) → container (slow, faster with microservices) → component (frequent during active development) → code (immediate).

For automatic generation, the site suggests deriving diagrams from: **system catalogues, log files, OpenTelemetry data, static code analysis, and infrastructure-as-code definitions**.

---

## 13. Practical summary

- **Always draw:** system context + container. Highest value, lowest maintenance, slowest to go stale.
- **Sometimes:** component — only where it earns its keep, and prefer generating it over drawing it.
- **Rarely:** code — on demand from the IDE.
- **Plus:** deployment (recommended), system landscape (larger organisations), dynamic (sparingly, for genuinely complicated interactions).
- **Every diagram:** title with type + scope; a key; typed elements carrying technology and a one-line responsibility; unidirectional arrows with intent labels and protocols.
- **Review as a reader**, not as the author — run §9's checklist.
- **When in doubt about a boundary:** ownership and deployability decide it. Deployable alone → container. Inside one process → component. One team, one repo, deployed together → software system.

---

## 14. Sources

Official (c4model.com):
[Home](https://c4model.com/) ·
[Introduction](https://c4model.com/introduction) ·
[History](https://c4model.com/history) ·
[FAQ](https://c4model.com/faq) ·
[Abstractions](https://c4model.com/abstractions) ·
[Software system](https://c4model.com/abstractions/software-system) ·
[Container](https://c4model.com/abstractions/container) ·
[Component](https://c4model.com/abstractions/component) ·
[Code](https://c4model.com/abstractions/code) ·
[Microservices](https://c4model.com/abstractions/microservices) ·
[Queues and topics](https://c4model.com/abstractions/queues-and-topics) ·
[Abstractions FAQ](https://c4model.com/abstractions/faq) ·
[Diagrams](https://c4model.com/diagrams) ·
[System context](https://c4model.com/diagrams/system-context) ·
[Container diagram](https://c4model.com/diagrams/container) ·
[Component diagram](https://c4model.com/diagrams/component) ·
[Code diagram](https://c4model.com/diagrams/code) ·
[System landscape](https://c4model.com/diagrams/system-landscape) ·
[Dynamic](https://c4model.com/diagrams/dynamic) ·
[Deployment](https://c4model.com/diagrams/deployment) ·
[Notation](https://c4model.com/diagrams/notation) ·
[Review checklist](https://c4model.com/diagrams/checklist) ·
[Diagrams FAQ](https://c4model.com/diagrams/faq) ·
[Tooling](https://c4model.com/tooling)

Secondary:
[Simon Brown — *The C4 Model: Misconceptions, Misuses & Mistakes*, GOTO 2024](https://www.youtube.com/watch?v=mqoU2C-USP0) ·
[Misuses and Mistakes of the C4 model (workingsoftware.dev)](https://www.workingsoftware.dev/misuses-and-mistakes-of-the-c4-model/) ·
[Wikipedia: C4 model](https://en.wikipedia.org/wiki/C4_model) ·
[Structurizr DSL language reference](https://docs.structurizr.com/dsl/language) ·
[Structurizr DSL cookbook — component view](https://docs.structurizr.com/dsl/cookbook/component-view/) ·
[Mermaid C4 syntax](https://mermaid.js.org/syntax/c4.html) ·
[C4-PlantUML bigbankplc samples](https://github.com/plantuml-stdlib/C4-PlantUML/tree/master/samples) ·
[Sammancoaching — container diagrams learning hour](https://sammancoaching.org/learning_hours/architecture/simon_brown_4c_container.html)
