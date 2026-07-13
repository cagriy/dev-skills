# dev-skills

A Claude Code plugin that streamlines the end-to-end development process, from rough idea to committed, tested code. It aims for **right-first-time code**: every feature travels through brainstorm → design → plan → implementation with clarification gates at each step, and the result is scored for bloat, duplication, inefficiency, and security issues before it ships.

## Three principles

Everything in this plugin follows three principles for generating clean, working code with AI:

1. **Break the requirement down into smaller deliverables.** Large prompts produce large, wrong code. The chain splits a feature into a design, then a staged plan, then one small committable stage at a time, with each stage reviewed and tested before the next begins.
2. **Check your own work.** Every skill self-reviews its output before presenting it: designs are checked for functional, security, and efficiency gaps, and implemented stages for bloat, duplication, dead code, and inefficiency. Two eval skills score the finished work so quality is measured, not assumed.
3. **Test-driven development.** Every plan stage is executed test-first: write the test, watch it fail, implement, watch it pass. One commit per green stage, and the run halts rather than build on an already-red suite.

## Getting started

### Install

Inside Claude Code:

```
/plugin marketplace add cagriy/ai-tools
/plugin install dev-skills@ai-tools
```

### Build your first feature

Start with `/dev:feature-storm` when the requirement is still vague and needs shaping at the product layer, or jump straight to `/dev:feature-design` when you know what you want and just need the technical design. Each skill offers to chain into the next. Or simply describe the feature in a normal prompt, and the plugin's dispatcher will offer to route you to the right entry point.

A typical session:

```text
/dev:feature-storm Add reminders to the todo app   # 1. brainstorm (optional)
/dev:feature-design                                # 2. lock the technical design
/dev:feature-plan                                  # 3. stage it as a TDD plan
/dev:feature-implement                             # 4. build it, one commit per stage
                                                   # 5. accept the closing offer to score
                                                   #    the result with the eval suite
```

### Let the skills improve themselves

The skills record improvement observations as they run. Occasionally, around every 15–20 features, run `/dev:lessons-learn <skill-name>` to review the accumulated lessons and apply the high-signal ones to the skill itself.

## Architecture

**[Interactive architecture diagram](https://cagriy.github.io/dev-skills/diagram/)**: every skill, step, gate, loop-back, and hook in one navigable page.

## Documentation

Full documentation lives in the **[wiki](https://github.com/cagriy/dev-skills/wiki)**: getting started in depth, a reference for every skill, the architecture, the bug workflow, the evals and lessons system, and contributor notes.

## License

[MIT](LICENSE)
