---
name: arcrho-json-contract
description: Keep ArcRho dataset sidecar JSON, reserving-class index.json, frontend JSON writers/readers, and ResQ data migration behavior consistent. Use when refining or changing dataset JSON sidecars/sidercars, data storage formats, JSON field names or structures, python-api/migration/resq_data_migration.py output, ResQ migration behavior, or any cross-component data storage contract.
---

# ArcRho JSON Contract

## Overview

Use this skill to preserve ArcRho's JSON contract when migration code, frontend-generated JSON, dataset sidecars, or reserving-class indexes change.

## Core Rule

When changing dataset sidecar JSON or reserving-class `index.json` formats, structures, or field names, keep every producer and consumer of that contract in sync. Producers of the same persisted file must emit the exact same full parsed payload for the same logical inputs, including identical schema/version, field inclusion and omission, defaults, normalization, timestamp representation, and deterministic list order. Treat these as cross-component changes unless the user explicitly scopes the request to investigation only.

## Required Coordination

- Coordinate changes to `python-api/migration/resq_data_migration.py` with the frontend app code that writes or reads dataset sidecars and per-reserving-class `index.json` files.
- If the user asks to revise JSON emitted by `python-api/migration/resq_data_migration.py`, proactively update the corresponding frontend JSON writers/readers in the same task unless the user explicitly limits the scope to migration-only exploration.
- Follow [references/persisted-json-rules.md](references/persisted-json-rules.md) in full. It holds the mandatory rules for index.json producers and reads, the on-disk JSON text layout, and the import of generated datasets; read it before making any change.
- In the current phase, do not add legacy-format compatibility unless explicitly requested. Prefer a clean, coordinated refactor across all producers and consumers of the JSON contract.
- Use the ResQ API examples in `python-api/migration/references` when migration tasks need ResQ API behavior guidance.
- Keep the macro source files in `python-api/macros` in sync with `python-api/migration/resq_data_migration.py` when changing ResQ migration behavior.
- After adding or editing a macro in `python-api/macros`, follow the copy and publish steps under "ArcRho Macro Source" in root `AGENT_GUIDELINES.md`.

## Workflow

1. Read the applicable repository instructions first, including root `AGENT_GUIDELINES.md`; read `frontend/FRONTEND_AGENT_GUIDELINES.md` before changing files under `frontend/`.
2. Identify the JSON contract surface: migration output, dataset sidecar files, reserving-class `index.json`, frontend writers, frontend readers, and any macro behavior that mirrors the migration.
3. Make the contract change across producers and consumers together.
4. Remove clearly obsolete code in the touched area when fixing a bug, but ask before broader cleanup or cleanup with behavior risk.
5. Add an exact full-payload parity test that exercises every producer with the same logical inputs and verifies path-alias independence, plus a no-rebuild test proving that reading a valid current index performs no sidecar/method scan and no index write.
6. Validate with targeted checks, preferring Python 3.10 and the bundled frontend Node/npm runtime where applicable.

## Data Access Reminder

When inspecting on-disk ArcRho Server project metadata, obey the project data access restrictions in root `AGENT_GUIDELINES.md`. Do not use this skill as permission to inspect non-default project metadata.

- If the task needs existing sidecars, method JSON, dataset JSON, or related project files, inspect the paths allowed by root `AGENT_GUIDELINES.md` when needed.
- If the user mentions a specific dataset name but does not provide an explicit reserving-class data path, use the default ArcRho Server data folder from root `AGENT_GUIDELINES.md` and look for that dataset there.
- If the user does not mention a dataset or path but the task requires concrete on-disk examples, use the default ArcRho Server data folder from root `AGENT_GUIDELINES.md`.
- If the dataset appears to belong to a non-default ArcRho Server project, ask for session-specific permission before reading that project's on-disk metadata JSON files.
