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

Translations live in `po/` (gettext). `make` builds them, `make pot` refreshes the template.

License: GPL-3.0-or-later (see COPYING).
