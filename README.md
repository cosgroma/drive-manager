# Drive Manager

A local drive review page and durable background service for this Windows/WSL machine.

Open **http://localhost:8871** in the Windows browser or inside WSL. Windows reserves
ports 8693–8792 on this machine, including the original 8765 choice; 8871 is verified
reachable from Windows. The service binds only to Linux loopback and uses WSL's
normal localhost forwarding. No hosting account or cloud storage is involved.

## What it does

- Records file metadata and directory coverage in SQLite WAL. Each directory is a
  checkpoint. One scan worker per drive; one transfer/comparison worker. Scans
  release the drive between directories so approved operations can take a turn.
- Continues indexing while you select proposals in the review inbox. Selected
  checkboxes persist through live updates. Review up to 100 transfers per batch.
- Offers metadata-only checkbox decisions for missing registrations in
  `~/workspace/.wksp.json`. A dedicated worker executes these decisions while
  transfers continue. Each decision preserves the exact registration and a full
  registry preimage, checks that the checkout is still absent, and uses the
  workspace manager's supported remove command. No files or branches are deleted;
  removing a registration does not mean its missing data has been recovered.
- Accepts explicit copy/move proposals and standing source/destination folder
  policies. Policies discover new indexed files in batches during maintenance.
- Copies into a job-specific partial file, verifies an existing partial against
  the source before resuming, checks SHA-256 on both sides, and publishes without
  overwriting another destination. The source is checked again before finalization.
- Retains move originals in `.drive-manager-recovery/<job>/<filename>` on their
  original drive. Removing a recovery original is a **separate, explicit checkbox
  approval** and re-verifies the destination. Until removal, a move does not free
  source space. Receipt files record hashes, original identities and recovery paths.
- Rejects symlinks, multiply linked files, virtual disks, protected system folders,
  encrypted/offline/reparse files and files with alternate NTFS data streams in the
  ordinary transfer workflow. Open Windows files are checked with an exclusive
  access probe; open Linux descriptors are checked too. Originals remain on error.
- Shows largest indexed files/folders, scan errors, and name-and-size duplicate
  leads. Content comparison runs only when requested. Equal names/sizes alone are
  never evidence for deletion. WSL distributions and backups need dedicated review.
  Folder sizes roll up indexed descendants. Inventory aggregates refresh about
  every 15 seconds; live jobs and approvals refresh every 4 seconds. Duplicate
  lists show at most six example paths per group, with the full copy count.
- Keeps recurring inventory schedules across restarts (daily model inventory,
  weekly drive and archive inventory). Failed or capacity-held transfers can be
  resumed from Operations. Cancelling stops further work and retains partials and
  any already-published verified files for inspection.

## Models on F:

F: is a Samsung 860 EVO SATA SSD. D: is a 12 TB HGST HDD. F: currently has about
75 GiB free; new copies preserve **100 GiB** of headroom and will remain blocked
until space is available. Existing SSD copies can be used without adding model data.

Two ComfyUI configurations have a managed routing block that prepends F: model
paths, with D: fallback for missing models. Existing configuration outside the block
is preserved. These take effect on the next app start:

- `D:\models\extra_model_paths.yaml`
- `%APPDATA%\ComfyUI\extra_models_config.yaml`

Original configuration bytes and paths are in the state directory's
`config-backups/`. Standalone Windows and WSL profiles are under `profiles/`.

LM Studio keeps its `D:\models` library setting. The existing-model SSD policy
uses load history to find matching publisher/repository folders on D: and F:.
It automatically considers repositories up to **2 GiB**; larger ones enter the
checkbox inbox. Previously used files missing on F: get reviewed copy proposals;
they retain the HDD source and wait for SSD headroom. Before routing, the worker:

1. Requires identical file sets and sizes, with no nested links.
2. Verifies every file on both drives with SHA-256 and checks the snapshots again.
3. Requires no loaded LM Studio models and no running ComfyUI process.
4. Retains the original D: folder in recovery storage and creates a native Windows
   directory junction from its old location to the existing F: folder.
5. Verifies the junction's actual target and reads/hash-checks through the old
   application path. Applications keep their paths and read SSD bytes.

This adds no large files to F: and downloads nothing. It does not permanently
delete a model original. Model routing receipts live under `model-routes/`.
The small-repository policy can be removed in Standing permissions. Already
authorized jobs remain queued and can separately be paused or cancelled.

## Running and maintenance

The service is installed as a systemd user service, enabled with user lingering.
It runs while this WSL distribution is running and resumes after WSL starts again.
It does not keep WSL alive through a Windows shutdown or start Windows itself.

```bash
systemctl --user status drive-manager
systemctl --user restart drive-manager
journalctl --user -u drive-manager -n 50 --no-pager
```

Source: `/home/cosgroma/workspace/projects/drive-manager`.
State: `/home/cosgroma/.local/share/drive-manager` (private to the user).
Unit: `/home/cosgroma/.config/systemd/user/drive-manager.service`.
The backend uses only Python's standard library; no production package install is needed.
Native Windows operations use Windows PowerShell and the existing LM Studio CLI.
The reinstallable unit is `deploy/drive-manager.service`; install it under
`~/.config/systemd/user/`, run `systemctl --user daemon-reload` and
`systemctl --user enable --now drive-manager`, and enable user lingering with
`loginctl enable-linger "$USER"` if work should continue after logout.

For a manual launch, stop the user service first. A filesystem lock prevents two
servers from owning the same state directory:

```bash
cd ~/workspace/projects/drive-manager
python3 -m drive_manager.server --port 8871
```

The API accepts only loopback peers and localhost Host headers. State-changing
requests require the page's per-process token, with same-origin checks. The page
uses a restrictive content policy and renders filenames as text. It is a local
single-user tool, not a shared multiuser service or backup replacement.

## Recovery

Pause the affected operation before inspecting files. Never remove a recovery
folder or a partial to make a blocked job appear successful.

For an ordinary file move, its `receipts/<job>.json` identifies the verified
destination, recovery original and SHA-256. If you need the source back, first
verify the recovery file against that hash, then copy it back without overwriting
an existing source. Keep recovery storage until the restored path is verified.

For a model route, its `model-routes/<job>.json` records every original file hash,
the recovery folder and the SSD target. Close model applications. A rollback must
remove **only the junction**, then rename the recovery directory to its original
path. Do not recursively remove the junction: that risks operating on its target.
Use the native lexical Windows source path from the receipt. `wslpath` resolves
existing junctions to their target and must not be used to choose what to remove.

To undo a ComfyUI config change, use the matching `config-backups/*/metadata.json`
to locate its saved `original`. Review later edits before restoring it wholesale;
alternatively remove only the marked `BEGIN/END DRIVE MANAGER MODEL ROUTING` block.

## Verification

```bash
cd ~/workspace/projects/drive-manager
python3 -m unittest discover -s tests -v
python3 -m compileall -q drive_manager
node --check drive_manager/static/app.js
```

Tests cover stale/atomic approvals, changed sources, collisions, capacity holds,
partial verification, restart recovery, policy execution, durable schedules,
content comparisons, model routing/rollback on junction failure, loopback request
guards, and separate approval for permanent recovery removal.

Machine checks additionally exercised disposable NTFS files on D:/H:, disposable
native junctions on D:/F:, Windows browser reachability, the installed ComfyUI
loader with Windows path semantics, and desktop/mobile browser interactions.
An isolated browser scenario is in `tests/browser_scenario.py`; it requires
Playwright and an installed Chromium, independent of the production service.

## Scope and practical limits

Inventory is a changing metadata view, not an atomic filesystem snapshot. Errors
are shown and coverage grows as jobs finish. Indexed sizes exclude recovery
folders and skipped links; drive capacity comes directly from the filesystem.
File fingerprints use size, mtime and identity, then full hashes during execution.
Exclusive-access probes do not prevent a noncooperating app from opening a file
after a probe; final identity checks and retained originals protect the workflow.
Transfers are for ordinary files, not full NTFS ACL/ADS/EFS backup or WSL migration.
Permanent model-recovery folder removal and WSL compaction/migration are not
implemented as unattended actions. They remain separate review work.

## Workspace consolidation review

The local `/workspace-review` page serves a generated, read-only report from
`~/.local/share/drive-manager/workspace-review/report.html`. Its private audit
and comparison JSON files stay in the state directory. The audit compares local
repository identity, refs and working-tree status across current and historical
workspace roots; it does not fetch, move, merge or delete repositories.
Matching commit objects do not establish complete backup equivalence. Ignored
files, submodules, LFS payloads, reflogs and repository configuration require
separate preservation before consolidation. Concrete transfers still use the
existing approval inbox and verification machinery.

Workspace consolidation is governed by `CONSOLIDATION.md`; its completion criteria
cover full working data and dependency recovery, beyond Git history bundles.
`/workspace-archive` provides a searchable, live history-snapshot catalog.
Its source search also combines bounded discovery reports, the current curated
workspace registry, history safeguards, full-file manifests and archival receipts.
Search paths (including Windows drive paths), project names, recorded branches
and commits; filter by drive, primary workspace or recorded evidence, with bounded
pagination. Registry roles are retained as recorded. Old Git status observations
are dated and incomplete checks are never shown as clean. Physical archive paths
are grouped with their original source, including later restoration, while each
manifest retains its actual input path. Source search is read-only and grants no
move or retirement authority. A manifest is not an independent backup.
Additive history jobs share the durable worker queue, support pause/resume, restore
into an independent empty Git repository, validate all recorded refs and HEAD, run
`git fsck`, and record SHA-256 receipts. Atomic no-overwrite publication is required.
The catalog explicitly identifies these as history-only safeguards, not complete
workspace backups or permission to delete originals.

Full file manifests are available in the same archive catalog. A separate durable
workspace worker inventories the entire visible tree without Git ignore rules,
records native Windows attributes and owner/group/DACL permissions, hashes named
NTFS streams, and hashes regular-file payloads through no-follow handles. Native
reparse points are recorded without traversal and require review. Metadata and
file identities are checked again before completion. Stable completed file hashes
are reused on resume; changing or unreadable trees remain blocked. The catalog
supports searching paths within an individual manifest (100 results per request).
Manifests may read the primary `~/workspace/` as well as configured drives; this
does not expand ordinary transfer permissions. Windows SACL audit rules and
external dependency closure remain outside manifest proof. A manifest never
constitutes a verified independent backup or permission to reclaim source space.

For WSL-specific validation with disposable D: folders, run:
`PYTHONPATH=. python3 tests/native_manifest_check.py`.
Native ADS hashes use read-only Win32 handles; forced PowerShell content reads can
change hidden-file metadata and are deliberately avoided. Working-tree payload
comparisons exclude Git internals, retain bounded difference samples, and bind
both input manifest digests. Comparison evidence is shown in the catalog and does
not grant source-retirement authority.

The snapshot comparison form also offers a full-tree mode. It includes Git
internals, ignored files, empty directories, recorded link targets and named
streams, verifies both manifest database digests, and reports payload and recorded
metadata differences separately. Device/inode/ctime are excluded from portable
metadata matching. Unrecorded metadata, external dependencies and recovery remain
outside proof; matching recorded data does not authorize retiring a source.
Working-payload mode retains its explicit `.git` exclusion.

New native captures enumerate and hash named streams on both files and directories
through read-only Win32 handles. The capture profile is recorded; older native
manifests remain labeled as legacy file-stream captures. Native archival moves
also verify expected named streams through the original compatibility path. Build
fresh manifests before using older native captures for complete stream-retention
decisions. Existing resumable default-stream hash checkpoints may be reused only
when their recorded file identities still agree; native streams and metadata are
read again on every capture.

Whole-tree archival relocations keep the complete original directory on the same
volume and replace its legacy location with a compatibility junction. These moves
reclaim zero space. They bind a completed manifest, refuse any existing destination,
verify complete content/native metadata before and after moving, and verify old-path
payload access and Git refs. Linked worktrees, object alternates, active hooks and
path-dependent local Git configuration require a separate plan. Only narrowly
qualified self-contained bare archives can be authorized automatically under the
consolidation goal. Historical working-tree roles require checkbox review.
Automatic collection layouts include `repos/*.git` and one level below the
observed `repos/apps`, `repos/atc`, `repos/docs`, `repos/jhu`, `repos/libs`,
`repos/utils`, and `repos/opt` collections.
Collections with an enclosing Git boundary are rejected; backup containers,
unknown collection names and deeper layouts retain their review requirement.
The archive catalog records phases and offers an explicit, verified restoration of
the physical original folder. Unexpected verification or junction failures trigger
rollback and a full check of the restored source. This is separate from ordinary
file-move recovery and does not authorize permanent removal of archive data.

Native relocation/recovery regression check:
`PYTHONPATH=. python3 tests/native_relocation_check.py`.

If an archive receives new work after relocation, restoration holds when the tree
no longer matches its recorded manifest. That preserves the newer data and leaves
the compatibility path usable. In its archive card, expand **Restore an archive
that has newer work**, build a fresh restoration manifest, and select the completed
manifest to prepare a checkbox proposal. Cancel a held restoration job before
preparing its replacement. Approval restores the complete current tree, including
newer commits and untracked data; content and native metadata are checked before
and after publication. Any further edits or an occupied original location hold
the operation. Both the original archive manifest and the reviewed restoration
manifest remain recorded, with durable authorization for interrupted restoration.
Current native moves never delete a full archive or reclaim its space.

History preservation also supports repositories whose symbolic HEAD does not
resolve while other refs remain readable. The exporter selects readable refs
explicitly, records the unresolved symbolic HEAD and Git warnings, and never
chooses a replacement branch or repairs malformed source refs. Independent
restoration uses an empty repository on the local Linux filesystem, isolated from
global templates, hooks and object-directory environment settings. Receipts bind
refs, HEAD state and bundle SHA-256 to a private capture intent. Failed attempts
are retained under a distinct name on retry. This preserves readable history;
raw invalid refs and other excluded repository data still need full-file archival.

**Full-file backups** create additive GNU tar PAX archives of one to eight sibling
Linux folders using completed, sealed full-tree manifests. Select all members of
a linked-worktree group together. The default archive destination is H:; sources
remain in place. This workflow captures ignored/untracked files, Git internals,
symlink targets, ACLs and extended attributes. It rejects Windows sources, mixed
ownership, special files and regular-file hardlinks pending separate plans.

The preservation worker checks complete source membership, metadata and identities,
copies every explicitly listed entry without following links, audits tar member
names/types and every file hash, extracts to an independent empty Linux directory,
and compares every restored payload, link, permission, timestamp and extended
attribute. It checks source stability and archive SHA-256 again before atomic
publication. A private verified receipt binds publication and restart recovery;
failed partial attempts are retained under distinct names on retry. Capacity
reserves apply to both the archive drive and local restore filesystem.

The original `.git` files and worktree metadata are preserved byte for byte.
Recovery at a different location may require a coordinated Git worktree repair;
the verification never invokes Git through restored pointers to original paths.
External symlink targets, filesystem flags, atime/ctime and full dependency closure
are outside this proof. A verified copy never authorizes source retirement.

The local page queues full-file backups and shows their live receipts. Both source
folders are searchable under **Verified full-file backups**. The read-only endpoint
is `/api/workspace/snapshots`; token-protected `POST /api/workspace/snapshot` accepts
`{"manifests":["completed-job-id", "second-completed-job-id"],"archive_root":"/mnt/h/archive/workspaces"}`.

Large bare repositories can use `drive_manager.object_cache` for verified local
object staging before export. `prepare` binds a completed source manifest, checks
exact object-store membership/identities, copies without hardlinks, verifies every
copied SHA-256, and preserves readable tips plus unresolved HEAD semantics in an
isolated Linux mirror. External/partial object stores and unsupported dependencies
require separate plans. Caches preserve default Git object bytes; native streams,
security descriptors and complete raw repository metadata remain in the source.

`benchmark` builds a bundle from that mirror and independently restores it into
an empty repository with full Git integrity and exact-tip/HEAD verification. A
private proof binds the artifact to the unchanged source. `handoff` can then reserve
the original blocked history job (or an explicitly recorded automation hold),
copy and hash the artifact to its original destination, and queue the daemon's
existing reconciliation. It never marks a history job complete itself. Cancelled,
active or user-paused jobs are not replaced, existing destinations are not overwritten,
and previous generated attempts are retained. A per-job lock and preparation
journal preserve ownership of an interrupted handoff. This workflow needs no
daemon restart and can run while the full-file backup worker continues.

Worker dispatch polls idle queues without a database writer lock, rechecks job
ownership in a short claim transaction, and retries SQLite busy/locked responses.
Inventory subtree cleanup uses the indexed path range instead of full-table
prefix scans. These changes preserve unrelated path prefixes and prevent inventory
contention from silently stopping an idle worker. Existing running processes need
a safe service reload to adopt changed worker code.


### Reviewed recovery of a damaged Git object

A `git_object_repair` proposal requires a completed sealed full manifest and a
recovered loose object whose SHA-256 matches its original manifest entry and whose
Git object identity is valid. It is always a checkbox decision; standing policies
cannot approve it. Approval binds the damaged bytes, native metadata, recovery
artifact and repository refs. The worker stages and verifies the recovered copy,
retains the damaged native file through a same-volume quarantine rename, installs
without overwriting another file, and verifies full repository integrity. Failed
verification restores the damaged original where safe; newer concurrent data is
retained for review. Durable phase receipts support interruption and replay.
A fresh full manifest is queued after successful repair. Recovery artifacts and
quarantine originals are retained, and no space is reclaimed by this operation.


When Windows cannot assign a historical security descriptor to a new file, an
object repair may instead bind an explicitly reviewed native staging preview.
Only that security-descriptor difference is permitted; all other recorded file
metadata must match. The damaged original retains its historical owner/ACL in
native quarantine. The approval inbox loads control state independently of slow
inventory summaries, so indexing does not delay review controls.


The legacy `~/drive-manager` path is retained as a compatibility symlink to the canonical workspace project. Service state remains in `~/.local/share/drive-manager`.

### Refreshing an archival review baseline

A pending archival checkbox can be rebound to a new completed full-tree manifest
using `POST /api/workspace/archive/refresh` with `id`, `manifest`, and
`previous_manifest`. The manifest must describe the same source and its root
identity must still match. Dependency and destination checks run again. The
operation retains the candidate ID, reason, destination and review status; it
does not approve a move. Queued, approved and automatic proposals cannot be
refreshed. Concurrent approval prevents replacement, and an event records both
manifest IDs and seals. Execution still verifies every payload and native entry.
