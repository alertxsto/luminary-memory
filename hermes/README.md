# luminary-memory — Hermes Skill

Standalone-installable Hermes skill (`SKILL.md`). No need to clone the full repo to add the skill.

## Install

Copy into your Hermes skills directory (adjust path to your Hermes setup):

```bash
cp hermes/SKILL.md ~/.hermes/skills/luminary-memory.md
# or
mkdir -p ~/.hermes/skills && cp hermes/SKILL.md ~/.hermes/skills/luminary-memory/SKILL.md
```

Or via Hermes CLI if you have it:

```bash
hermes skill install https://raw.githubusercontent.com/alertxsto/luminary-memory/main/hermes/SKILL.md
```

## What's included

- Frontmatter: `name`, `description`, `version`, `author`, `license`, `platforms`
- Agent usage: ingest a durable fact, recall into the system prompt, lifecycle via cron

See `hermes/SKILL.md` for the full skill body.

## Release asset

On each `v*` tag, CI builds `luminary-memory-skill.zip` (containing `hermes/SKILL.md` + this README) and attaches it to the GitHub Release — installable without cloning.

## Verify frontmatter

```bash
python3 -c "import pathlib, re; t=pathlib.Path('hermes/SKILL.md').read_text(); assert 'name: luminary-memory' in t; assert 'description:' in t; print('frontmatter OK')"
```
