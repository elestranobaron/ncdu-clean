# ncdu-clean

Separate program that deletes files found with [ncdu](https://dev.yorhel.nl/ncdu),
keeps a journal of everything removed, and puts quarantined files back where
they came from.

    ncdu -e -o scan.json /var       # 1. scan (-e adds modification dates)
    ncdu-clean browse scan.json     # 2. Space: mark; x: delete / quarantine / save list
    ncdu-clean log                  # 3. what was deleted?
    ncdu-clean restore              # 4. undo a quarantine, in whole or in part

With an export, a file modified since the scan, or a directory that gained
files, is refused. `ncdu-clean rm` without `--export` skips that check and
warns. The journal entry is written before the removal. Actions are simulated
first; nothing happens without confirmation.

## Suggestion

`suggest` asks the command in `NCDU_CLEAN_AI` for a plan. That command reads
a JSON summary on standard input (`root`, `disks`, and `items` with `path`,
`type` and `size`) and writes a JSON object on standard output:

```json
{"items": [{"path": "/var/tmp/old.log", "action": "delete", "reason": "old log"}]}
```

`action` is `delete` or `quarantine`. A large export sends the largest
entries, forty at most: the first level, then the biggest names inside those.
Paths absent from the export are
dropped, and so are a top-level path, the home directory and the scan root.
A directory is dropped when the plan gives another action to something inside
it. The suggestion writes lists when you ask for them. It also reads the mounted
disks, their free space, and disks that are present but not mounted, and it
asks the model for one quarantine folder. A removable disk is used first. A
folder on the scan disk is not kept while a removable disk is mounted.
On a terminal the wait shows the phase, a running clock and those disks.
The model's text is drawn on that screen as it is written.
The plan lists the paths and the quarantine folder. The bottom line shows
the arrows, F1, and q. F1 lists the keys. `t` moves the selected line
from Delete to Quarantine, or the other way. `-` takes that line out of the
plan. `d` deletes the lines under Delete, `m` moves the lines under
Quarantine into the folder (created when it does not exist). q or Esc quits
and returns the terminal at once. Enter returns to the file list.
`d` and `m` still ask for `yes`, with the same checks.

```sh
ncdu-clean suggest scan.json --delete-list delete.list --quarantine-list quarantine.list
ncdu-clean rm -r -e scan.json --from delete.list
ncdu-clean rm -r -e scan.json --from quarantine.list --trash ~/q
```

In the browser, `p` opens the same plan. F1 lists its keys.

`examples/suggest-openai.py` is a command for an OpenAI-compatible endpoint
(Ollama, Grok, Gemini, and others). It reads `NCDU_CLEAN_AI_URL`,
`NCDU_CLEAN_AI_MODEL` and, when the endpoint requires one, `NCDU_CLEAN_AI_KEY`.
The key is sent only to that endpoint. `NCDU_CLEAN_AI_THINK=1` asks the model
to think first, on its own. The wait screen shows how long that took, then the
JSON plan. The thinking text stays in `~/.local/state/ncdu-clean/suggest.log`.

Translations live in `po/` (gettext). `make` builds them, `make pot` refreshes the template.

License: GPL-3.0-or-later (see COPYING).
