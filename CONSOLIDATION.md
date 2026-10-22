# Workspace consolidation execution plan

## Governing objective

Consolidate active development work into `~/workspace/` and maintain a coherent,
searchable archive of historical workspaces across D:, E:, and H:. Preserve unique
files, Git history, local changes, and working dependencies. Perform high-confidence,
reversible moves autonomously, with content verification and an audit trail. Present
uncertain actions as specific checkbox approvals in the local dashboard while
independent indexing and approved operations continue. Reclaim space only after
archive integrity and recovery have been verified.

## Completion requirements

- Every discovered workspace, including non-Git folders, has an evidence-backed
  disposition: active, archived, independent backup, or verified redundant.
- Active projects resolve coherently beneath `~/workspace/`; registry entries,
  linked worktrees, submodules, tool configuration and working dependencies work.
- Archives preserve unique tracked, untracked and required ignored files, repository
  configuration, all relevant Git history, submodule state and LFS payloads.
- A searchable origin-to-archive catalog records manifests, verification, recovery
  tests, moves, retained originals, reference changes and user decisions.
- High-confidence operations run without per-file permission requests; uncertain
  actions have concrete, bounded checkbox proposals. Independent work continues.
- Reclamation requires verified full archives and recovery, with separate approval
  for permanent deletion. History-only bundles never authorize retirement.

## Evidence and current state

The private bounded audit is in the service state directory under
`workspace-review/`. It found 990 Git boundaries: 58 current and 932 historical,
with 221 historical dirty results and 110 incomplete historical status checks.
Depth-limited discovery is not exhaustive. Non-Git data, deeper repositories,
ignored files and Windows metadata still require examination. Read current sources
before mutations; historical reports are leads, not authorization evidence.

Registry validation reports missing paths and a non-worktree `pgm/smake` entry.
Keep curated fields and user changes intact; repair using the workspace manager's
supported commands, after checking actual Git worktree relationships.

## Execution stages

1. **Preservation foundations (in progress).** Add durable, additive Git history
   snapshots with exact refs/HEAD, source stability checks, standalone restoration,
   Git integrity validation, SHA-256 receipts, restart reconciliation and searchable
   catalog. Begin with old D: gencor and sm, E: seed, H: notes and private.
2. **Complete archive manifests.** Inventory complete file trees, including ignored
   content and nested Git boundaries. Record symlinks, permissions, NTFS streams,
   LFS and external Git object dependencies. Separate rebuildable outputs from
   unique work using evidence. Preserve inaccessible or unsupported content.
3. **Reviewable dispositions.** Persist canonical counterparts and active/archive/
   backup roles. Present exact uncertain folder actions and reference changes in
   checkbox approvals; decisions remain bound to the reviewed manifest.
4. **Consolidate and reconcile.** Execute verified, non-overwriting archival copies
   and reversible moves. Repair missing active-workspace registry paths and tool
   references; preserve linked worktree relationships using Git tooling.
5. **Recover and reclaim.** Test full restoration, verify destination manifests,
   maintain independent backups, and only then propose redundant-source retirement.
   Refresh search and catalog after every operation.

## Guardrails for history-only jobs

These jobs do not fetch, merge, clean, reset, delete source files, or change source
refs. Bundles cover named refs and HEAD, including detached HEAD. They do not claim
to preserve reflog-only objects, configuration, working files or LFS payloads.
Sources remain authoritative for those until a full snapshot is verified.
Interrupted generated staging data may be recreated by its own job. Publication
must be atomic and refuse any existing destination. Failures remain visible and
can be resumed through the dashboard.

## Preservation run 2026-10-18T04:45:38.339529+00:00

The snapshot worker and searchable `/workspace-archive` catalog are installed.
All 32 existing service tests and five new archive tests pass; the new session
endpoint also passes the HTTP action/guard test. Native D: publication and collision
refusal were exercised on disposable directories. Desktop/mobile catalog rendering
and search were checked in Chromium.

- `d6fcfede3c144fb4a678387d25122389`: completed; `/mnt/e/repos/seed.git` → `/mnt/d/archive/workspaces/e/repos/seed.git/history/20261018T044305Z-d6fcfede3c14`.
- `8e94cfebd93c40008af8c6c04c2184b7`: completed; `/mnt/d/wksp/sergeant/comp/sm` → `/mnt/d/archive/workspaces/d/wksp/sergeant/comp/sm/history/20261018T044306Z-8e94cfebd93c`.
- `2ec7f09be90b40748ce3805a5953476d`: completed; `/mnt/d/workspace/sergeant/engines/gencor` → `/mnt/d/archive/workspaces/d/workspace/sergeant/engines/gencor/history/20261018T044306Z-2ec7f09be90b`.
- `f0b797fd919741a2b56562fd6b240eb1`: running; `/mnt/h/wksp/private` → `/mnt/d/archive/workspaces/h/wksp/private/history/20261018T044307Z-f0b797fd9197`.
- `0335e95618ab4dc1a320b53f9cea26d9`: pending; `/mnt/h/repos/comfyui-notes.git` → `/mnt/d/archive/workspaces/h/repos/comfyui-notes.git/history/20261018T044308Z-0335e95618ab`.

History jobs leave source workspaces untouched. This run has not approved or
performed any original-source retirement, working-tree merge or space reclamation.
Next: complete file manifests and dependency inventories, reconcile canonical paths,
and create exact uncertain archive/relocation proposals for checkbox review.

## Full-tree manifests (in progress)

All five initial history safeguards completed standalone restoration and Git
integrity verification. Full-tree manifest jobs now cover those five sources plus
the active `~/workspace/sergeant/designs/t1tl/comp/sm` counterpart. Manifests retain
ignored content, Git internals, native attributes, owner/group/DACL permissions,
named-stream hashes and POSIX identities. Reparse points are not followed. A second
inventory verifies membership and native metadata before completion. The private
per-job SQLite files checkpoint hashes and are browsable/searchable in the local
catalog. The primary Linux workspace is a read-only workspace-job source; ordinary
transfer roots remain unchanged.

The first two manifests completed: old D: sm (172 files, 33,501,829 logical bytes)
and E: seed.git (250 files, 175,478 logical bytes). Native tests independently
confirmed an ADS payload's SHA-256 and ACL recording, and that a junction target
is not traversed. POSIX tests cover added files, permission changes, ignored and
untracked files, nested Git configuration, links, and interrupted-work hash reuse.

`workspace-review/dependency-review.json` contains an informational inspection of
Git directories, common directories, registered worktrees and object alternates
for the first five sources. All five have one registered location and no external
Git directories or alternate-object files found. This is not full dependency
closure: external LFS configuration, build/tool references and non-Git dependencies
still require inspection before retirement.

Next, compare the old sm checkout's file manifest with its current counterpart,
resolve remaining dependencies, and prepare a manifest-bound archival relocation
proposal with rollback and compatibility-path verification. No full working-tree
retirement or reclamation has been authorized by these history/manifest jobs.

## Completed manifest batch and next consolidation actions

Six full-tree manifests completed (2,859 regular files, 1,378,868,257 logical bytes):
the five historical sources above plus the current t1tl/sm counterpart. All six
reported zero named streams. The current/old sm payload comparison excludes Git
internals: 89 identical payloads, 28 differing payloads, 29 entries only in the
older tree, and 40 only in the current tree. Older-only entries include source and
test files, as well as four cache files. Preserve this as a historical version;
matching history objects do not justify discarding its working tree.

Comparison reports live under private state `workspace-comparisons/` and appear
in the archive catalog. They are tied to both input manifest digests and do not
prove metadata equivalence or authorize retirement. Individual manifest files are
searchable in the browser; desktop and mobile searches were checked successfully.

The suite of 43 tests passed before the added comparison test; all seven manifest
and comparison tests then passed. A native regression harness is retained at
`tests/native_manifest_check.py`. It verifies hidden NTFS files, an ADS SHA-256,
ACL recording, no source identity/timestamp change, and junction no-follow behavior.
A disposable test exposed PowerShell's forced hidden-stream reader changing ctime;
that reader was replaced with read-only Win32 handles. Existing six real manifests
had zero ADS payloads, so they did not exercise that problematic reader.

Next bounded execution:

1. Implement and verify same-volume native archival relocation with compatibility
   junctions, no overwrites, complete pre/post manifest verification, durable recovery
   states, and tested rollback. It must retain NTFS metadata and logical references.
2. Start with E: seed.git as a high-confidence, self-contained bare archive: one
   registered bare location, no external Git/common directories or object alternates,
   restored history and a complete file manifest. Keep its legacy repository URL
   working through a verified compatibility junction; reclaim zero bytes.
3. Prepare a separate checkbox proposal for old D: sm because the historical working
   tree's role is uncertain. Bind the exact source, destination and manifest digest;
   preserve the whole historical version rather than merging files into active code.
4. Continue coverage and dependency review across the remaining workspace roots,
   reconcile the primary registry, and retain independent backups before reclamation.

## First physical archival relocations 2026-10-18T05:27:29.150389+00:00

The archival relocation executor is installed. It binds a complete manifest digest,
checks source dependencies and all payload/native metadata before the move, performs
a native same-volume no-overwrite rename, retains a compatibility junction, then
checks all archived payloads/native metadata and every legacy-path file read. Git
refs must agree through both paths. Failures automatically restore the physical
source folder and verify it; an explicit Restore control supports a later verified
return to the original physical location. No source-tree cleanup or space reclamation
is performed by these actions.

- `/mnt/d/wksp/sergeant/comp/sm` → `/mnt/d/archive/workspaces/d/wksp/sergeant/comp/sm/tree/20261018T052024Z-d353c54f4b2d`: proposal `d353c54f4b2d44f0ba78a7d78bd80735`, status `review`, job `None` (None).
- `/mnt/e/repos/seed.git` → `/mnt/e/archive/workspaces/e/repos/seed.git/tree/20261018T052027Z-36b0cbf91aba`: proposal `36b0cbf91aba479bbe189eeee055ed22`, status `completed`, job `58f49578c603483cb9eb0707333e1392` (completed).
- `/mnt/h/repos/comfyui-notes.git` → `/mnt/h/archive/workspaces/h/repos/comfyui-notes.git/tree/20261018T052359Z-f9840738b567`: proposal `f9840738b56747b39446096b756346f8`, status `completed`, job `be951370cf8b43e09ccc8bbe05576da5` (completed).

E: seed.git and H: comfyui-notes.git were automatically authorized under the goal
as self-contained bare archives: no external Git directories, registered secondary
worktrees, object alternates, active hooks or path-dependent local configuration.
Automatic eligibility accepts only a small set of repository/filesystem flags.
Old D: sm remains a checkbox proposal: its historical-working-tree role is uncertain.
Its complete original folder stays in place until approved.

Validation: 50 tests passed, followed by six targeted recovery tests after adding
post-rollback verification. The native regression checked hidden files, ADS, ACLs,
legacy-URL cloning, Windows Git refs and full physical restoration on disposable
D: data. A browser fixture approved copy, file move and archival relocation through
checkboxes while indexing was running. Production catalog controls render on desktop
and mobile; the real sm checkbox is enabled but has not been clicked by the agent.
The real archived E: seed repository was independently cloned through its original
URL with hard links disabled and passed fsck with all refs matching.

Five additional E: bare repositories (config, dev-notes, mpt, notes, scripts) now
have history safeguards and full manifests queued or running. Inspect their actual
terminal results and dependency gates before considering further moves. Continue
coverage across remaining roots and reconcile the active workspace registry. The
full goal remains incomplete; initial discovery was bounded and most sources still
lack a disposition or complete preservation evidence.

## Expanded verified batch

Seven bare archives are now physically reorganized on their existing volumes:
E: seed, config, dev-notes, mpt, notes and scripts; H: comfyui-notes. Each has a
verified compatibility junction at its original path, complete pre/post content
and native-metadata checks, legacy-path payload verification, and zero reclaimed
bytes. Their separate Git history safeguards on D: passed independent restoration.
Ten history safeguards and eleven complete file manifests now exist in total.

The automatic gate was extended only for observed filesystem/name-handling flags
(`core.ignorecase`, `core.symlinks`, `core.precomposeunicode`); these remain unchanged
on the same volume. It still rejects arbitrary local configuration. Working-tree
relocations also reject path-dependent Git settings and parent-relative remote URLs,
including repeated remote URLs whose earlier value is relative. A targeted regression
for that repeated-URL case passes. Current old sm has a parent-independent origin URL.

The current restore control verifies the recorded manifest before returning the
physical folder. If subsequent user work changes an archive, the hold preserves
that work and its legacy path; a fresh reviewed baseline is needed before restoring
that modified tree. Extend that workflow before claiming complete general recovery
coverage for evolving archives.

Next work must continue beyond this batch: catalog the remaining physical sources
without treating compatibility aliases as duplicate copies; prioritize active
workspace registry reconciliation and broader preservation/disposition coverage.
Old sm remains proposal d353c54f4b2d44f0ba78a7d78bd80735 awaiting the user's checkbox.
Do not approve that working-tree role on the user's behalf. No permanent source
retirement has been performed.

## Canonical workspace reconciliation and next preservation batch

The primary registry now points AM, CC and OS to their existing `sergeant/comp/`
checkouts. The obsolete MBSE pathname and two already-pruned GENCOR worktree
registrations were removed using the supported workspace-manager CLI. Earlier
successful prune logs and surviving branch refs establish the latter decisions;
the fresh main GENCOR history safeguard also contains both branch tips. Curated
project IDs, roles, statuses, tags, summaries and vault settings were retained.
Derived branch/dirty facts were refreshed without switching branches or changing
the user's working files.

PGM's empty registered smake submodule was restored from an existing local checkout
at its exact index gitlink `14dec784a6da689d831babc3aa9567346c9a2953`. The copy uses
neither hard links nor alternates and retains the canonical upstream URL. Parent
HEAD, index and status, and the source checkout's status were verified unchanged.
This verifies the dependency restoration, not a full hardware build. Private
receipts and preimages live under `registry-reconciliation/` in service state.

Three missing dormant MBSE supporting registrations remain explicit check failures:
`mbse-mvp-smoke-models`, `mbse-release-smoke-models`, and `mbse-sgt`. Metadata-only
review proposals retain the original entries and registry backups if approved;
they do not recover missing files or delete source data. The first two have
historical reports of untracked work without a HEAD or remote. Do not silently
replace them with fresh clones or claim that their data is safely archived.
The vault plan and sync dry run were inspected; no broad vault bootstrap was
applied to the user's dirty notes checkout.

All twenty repositories listed in private `workspace-review/next-preservation-batch.json`
have completed history safeguards and full-tree manifests. Together with earlier
work, there are 31 completed history jobs and 31 completed manifest jobs. These
are different preservation scopes, not 62 distinct repositories. The three simple
top-level E: bare archives `atc_hw.git`, `envision.git`, and `sublime.git` have
goal-authorized relocation jobs; inspect their terminal receipts before reporting
physical moves complete. Nested repository collections remain subject to the
existing stricter automatic gate. Broader discovery and disposition remain open.

Missing-registration decisions use a dedicated worker, so approved metadata
changes need not wait behind history copies or physical relocations. Exact
preimage backups and decision receipts are retained in `registry-backups/` and
`registry-decisions/`; restoring metadata later must preserve subsequent unrelated
edits rather than overwriting the entire current registry with an old preimage.

The three new top-level E: relocations subsequently completed. Ten bare archives
are now physically reorganized in total, with verified compatibility paths and
zero space reclaimed. Their receipts report completed archival verification.
The registry worker is deployed; health reports all eight workers alive. The
full 55-test regression suite passed. A browser integration fixture executed a
metadata checkbox while indexing and a deliberately busy transfer continued,
and verified that only the missing registry entry changed and its backup remained.
Production browser checks found the three metadata checkboxes enabled and unchecked,
the registry catalog visible, no JavaScript errors, and no horizontal overflow at
1440px or 390px. Private `registry-reconciliation/verification-summary.json` records
the observed preservation counts and decision states. Broader E: envision discovery
also found no additional Git boundaries within the bounded five-level search;
that observation does not establish preservation of its non-Git files.

## Nested collections, broader discovery, and duplicate-snapshot evidence

The automatic collection gate now includes exactly one level below the observed
`repos/apps`, `repos/atc`, `repos/docs`, and `repos/jhu` collections, as well as the
original top-level `repos/*.git` layout. Both collection ancestors must lack Git
boundaries. Unknown layouts, backup containers and deeper nesting remain outside
this authorization. All previous bare-repository, configuration, hook, alternates,
worktree, manifest, payload and metadata gates still apply.

The 17 already-preserved bare repositories in these collections now have durable
goal-authorized relocation jobs, recorded in private
`workspace-review/nested-relocation-batch.json`. Inspect terminal receipts rather
than inferring completion from this queue. The focused relocation suite passed
all 10 tests, including nested archival/restoration, enclosing-repository rejection,
and unknown/backup-layout rejection. The native nested fixture also passed hidden
file, ADS, ACL, legacy-URL clone, Windows Git and full restoration checks. These
checks supplement the previously passed 55-test suite; a new full-suite run has
not been claimed.

Private `workspace-review/additional-discovery.json` records 289 additional Git
boundaries: 269 under D: sgt, 15 under E: northrop outside the previously audited
workspace root, two under D: openvpx, two dependency caches/templates under H: home,
and one under D: lab. Discovery is bounded to six levels and leaves 2,977 unexpanded
frontiers, plus generated/vendor exclusions. Boundaries inside an enclosing archive
must not be independently rearranged without coordinated dependency assessment.
The initial 990-boundary audit remains dated evidence, not a current disposition
for all historical sources. A timestamped supplement on `/workspace-review` shows
the additional boundaries and constraints, with a link to the live archive catalog.
Private `refresh_status.py` refreshes the supplement while retaining the original
audit HTML. Its desktop/mobile rendering was checked with the discovery expanded;
long paths now wrap without page overflow.

D: and E: each contain `.backups/20141206161730/workspace` with 12,603 indexed entries
and 931,835,198 indexed logical bytes. This is a duplicate lead only. Full-tree
manifests `899290c71411403db5492387d5bda7a6` and
`8b19e89fa7fe4ca091d8c30e5bc70f14` are queued/running, preserving each snapshot as
a unit. Matching content, metadata/dependency scope, independent recovery and an
explicit retention decision remain prerequisites to any space reclamation.
Additional E: documentation repositories are entering a separate read-only
preservation batch; inspect `northrop-docs-preservation-batch.json` for its actual
jobs and holds. No working-tree relocations are authorized by that batch.

The documentation batch queued 14 history safeguards and 14 full-tree manifests
with an estimated 770.4 MiB scope. The remaining `docs.new` source has no readable
HEAD; its separate full-file manifest is `eb4d2588d7f2436e806437998fbf10b1`, with no
Git-history safeguard claimed. Preserve this source pending its full assessment.
Recorded validation logs and source hashes live in private
`validation/nested-collections/`. At the latest recorded observation, nine of the
17 nested archival jobs were completed, one was running and seven were pending;
19 archival relocations were complete overall, with no blocked jobs. Completed
batch receipts were checked for full payload/native metadata/legacy-read flags
and zero reclaimed bytes. These counts are a timestamped observation, not a claim
that the remaining jobs or the full consolidation goal are complete.

## Restore archives that have received newer work

The changed-tree restoration gap now has a concrete workflow. The archive card
can queue a fresh manifest of the current physical archive, select that completed
manifest and prepare a `workspace_restore_review` checkbox proposal. A held old
restoration must be cancelled before preparing a replacement. No automatic policy
or consolidation-goal authorization can approve this new kind of restoration.

The proposal binds the original archival receipt, exact source/legacy paths,
current archive root identity and fresh manifest digest. Dependency gates run
again. Execution checks every current payload/native entry against that approved
baseline before moving and checks the entire restored tree afterward. Changed
files, replaced aliases, occupied originals, conflicting restore jobs and rejected
baselines hold rather than overwrite or discard data. A private
`workspace-restorations/<job>.json` authorization record supports reconciliation
after physical publication. Both the original archival manifest and the restoration
manifest remain in the original relocation receipt; no archive data is retired.

Four targeted tests passed for stale-baseline holds, explicit approval, preservation
of newer commits/untracked files, later edits, collisions, rejection retention and
interruption after publication. The native Windows fixture passed a changed-tree
restoration while preserving hidden files, ADS, ACLs and newly added data/refs.
The browser fixture selected a fresh manifest, prepared an unchecked proposal,
approved it and observed the restored newer data while another drive was still
indexing. Desktop/mobile layouts fit and no JavaScript errors were reported.
The broader regression suite is required before production deployment.

All 27 archival relocations and all 45 queued history safeguards have now completed;
the 27 terminal receipts were checked for full payload/native/legacy-path flags
and zero reclaimed bytes. The full-file manifest queue is still working through
the two 2014 snapshots and newer documentation batch. Two additional older working
trees, D: `workspace/sergeant/engines/gencor` and H: `wksp/private`, passed Git
dependency gates and have review-only archival proposals. Their source folders
remain in place; current full-tree revalidation is recorded separately in private
`working-tree-proposal-validation.json`. Their roles are not inferred from clean
or dirty status. The missing MBSE metadata decisions and old sm proposal also
remain separate, unapproved user choices.

The restoration update is deployed. Validation includes the full 62-test suite,
six focused recovery scenarios, a latest-source authorization/alias-resumption
check, native Windows restoration and browser checkbox/indexing checks. The
last two interruption guards were added after the full-suite import and were
covered by focused tests; these results do not claim a single run of all 64
current tests. Durable logs, source hashes and this scope distinction are saved
under private `validation/reviewed-restoration/`. Service health reports all eight
workers live after deployment, and scans/manifests resume from checkpoints.

The two working-tree proposals were independently revalidated against their
complete original manifests: 1,482 D: GENCOR files and 565 H: private files, including
native metadata. They remain review-only. The separate headless bare source
`/mnt/e/repos/sergeant.git` reports no Git objects or named refs and no readable
HEAD. It has full-file manifest job `1cf44a5705a04311baf83e3708bd2d38`, with no
history snapshot or relocation authorized. Its metadata/files remain preserved
at the original location; the empty Git object report is not disposal authority.

Next snapshot-retention work must compare all content, including Git internals,
ignored files and named streams, and assess metadata, dependencies and independent
recovery. The existing working-payload comparison deliberately excludes Git
internals and cannot by itself justify retiring either 2014 backup snapshot.
Broader discovery, active-project roles, historical archive dependency groups and
final retention decisions remain incomplete. No source retirement is authorized
by these recorded tests or by a successful history bundle alone.

## Searchable source and preservation catalog

The top of `/workspace-archive` now searches known source paths across both dated
discovery reports, the current curated registry and live preservation metadata.
At deployment it contains 1,290 known paths, including 27 recorded whole-tree
archival moves, 45 sources with history safeguards, 31 with completed full-file
manifests and six awaiting checkbox decisions. Counts overlap and do not represent
distinct physical copies, recovered data or freeable space. Most sources still
lack complete preservation evidence; current primary working trees are not thereby
authorized for historical relocation.

Search supports project names, paths (including native Windows drive paths),
recorded branch names and commit IDs. Location/evidence filters and pagination
bound each response to at most 100 sources. Old status observations retain their
dates; incomplete status and absent change counts never become clean-worktree
claims. Current registry roles/statuses remain explicit and unchanged. Enclosing
archive groups and dependency caches are labeled for appropriate assessment.

Physical archive paths are associated with their original source, including later
restoration, using bound relocation receipts. Each file manifest retains its actual
input path. Selecting a source's preservation records also finds manifests made
at its physical archive path. Mismatched history receipts are not counted as
verified. A completed manifest remains distinct from an independent backup, and
no search result grants retirement or move authority. This read-only endpoint
does not traverse source folders, refresh Git status, fetch remotes or create jobs.

Four catalog tests passed for pagination, Windows paths, project/branch search,
curated-field preservation, unknown status, alias/restore grouping, live decision
updates, receipt binding and HTTP limits. A browser fixture verified search,
filters, pagination, physical-archive links, disclosure/filter preservation through
refresh, desktop/mobile fit, no JavaScript errors and no job/registry mutations.
Production search/pagination and both layouts also passed. Existing destructive
operation paths were not changed; a repeat of the full transfer suite was not
needed for this read-only addition. Validation artifacts and hashes are stored
under private `validation/source-catalog/`.

Next preservation work must continue beyond discovery/search: capture unique
current working data, assess whole archive/dependency groups, compare the complete
2014 snapshots when both manifests finish, and obtain specific role/retention
decisions. Source search's "unassessed" filter is an evidence gap, not an instruction
to move every matching path. The full goal remains active and incomplete.

## Complete recorded-tree comparisons and expanded NTFS stream capture

The comparison form now supports full recorded trees as well as the older
working-payload comparison. Full mode includes Git internals, ignored files,
empty directories, link targets and recorded named streams. Both input database
digests and entry counts must match their completed manifest receipts before a
comparison is published. Bounded difference samples distinguish payloads,
membership/type changes and recorded metadata. Copied-file device/inode/ctime
are excluded from portable metadata matching; recorded permissions, xattrs,
NTFS attributes/owner/group/DACL and mtime remain compared. Full metadata
equivalence, external dependencies, independent recovery and retirement authority
are never inferred from equal comparison fields.

An actual full comparison of old D: sm and primary T1TL sm found 89 equal recorded
payloads, 28 different payloads, 80 left-only entries, 46 right-only entries and one
type change. Counts include Git internals and directories, not just working files.
Their metadata formats differ and the native input has a legacy stream profile.
This reinforces preservation of the complete historical version; it does not
authorize merging, discarding Git internals or retiring the source.

The earlier native enumerator captured named file streams but omitted directory
streams. New captures use Win32 FindFirstStreamW/FindNextStreamW for both kinds,
with read-only stream handles and explicit errors instead of silently dropping
unsupported enumeration. New receipts record `named_stream_scope`; old receipts
remain legacy captures rather than being relabeled. Directory stream hashes also
participate in comparisons. Unknown capture profiles never imply complete stream
coverage. Reference: https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-findfirststreamw

Native regression tests created root and child-directory streams and checked
their hashes, source mtime/ctime/identity preservation, ACLs and junction no-follow
behavior. The relocation/recovery fixture also verified root-directory and file
streams through the original compatibility path after native publication, then
preserved them through reviewed restoration of newer work. New relocations record
`legacy_named_streams_verified`. Older completed moves retain their original
recorded verification scope; no permanent retirement is authorized by it.

The D: 2014 snapshot completed its original 10,927-file manifest under the legacy
profile. It needs a fresh native capture before complete stream retention analysis.
Private `workspace-review/recheck_manifest.py` prepares a separate recheck, binds
and validates the old manifest database digest, seeds only same-source default
hash checkpoints and leaves normal fresh metadata/stream/identity verification
mandatory. A disposable test proved unchanged payloads reused their hash and a
subsequently edited file was rehashed. Generated cache provenance records both
manifest identities; the original manifest is never edited or upgraded in place.
The helper uses a non-runnable preparation state and publishes a validated cache
before making its job pending, preserving cancellation and preventing concurrent
workers from using a half-prepared cache.

The comparison/stream update is deployed. The broad regression run passed 75
tests. After tightening unknown-profile handling, eight comparison tests and four
source-catalog tests passed. The latest native checks also covered the final
protected-directory guard: offline/encrypted directories are classified before
ordinary directories and are not traversed or stream-read. Both native capture
and native archival/reviewed-restoration fixtures passed on the latest source.
The broad suite preceded those final small guards; no single run of all 76
current tests is claimed. A browser fixture and production checks passed full vs
working-only comparisons, difference samples, profile warnings, persistent manifest
choices, both layouts and no source/job mutations or JavaScript errors.

D: fresh capture job `3ee69f9d8cc34577a789602318a30887` is queued using a validated
12,604-entry cache from the completed D: snapshot. It seeds 10,927 default-stream
hash checkpoints; each still requires an agreeing file identity, while all native
streams and metadata are read anew. Its `cache-provenance.json` records the old
manifest and digest. E: snapshot job `8b19e89fa7fe4ca091d8c30e5bc70f14` resumed under
the expanded capture code. Keep both originals and wait for the complete fresh
scope results before making a snapshot-retention proposal. Validation artifacts,
source hashes and scope notes are retained in `validation/full-tree-comparisons/`.

## Preservation update — 2026-10-18

Both fresh 2014 snapshot manifests above are complete. Full recorded payload
comparison found 10,927 matching file payloads and 1,677 matching directories,
with no membership or type differences. Permissions (SDDL) differ on all 12,604
entries; modification times differ on 1,540. Both originals remain intact and
retirement is not authorized. These are matching recorded payloads with distinct
metadata, not interchangeable verified recovery copies.

The library preservation batch now has 25 completed full-tree manifests and
22 verified history snapshots. Two Linux repositories have readable refs but an
unresolved symbolic default HEAD; `.QtBooty.git` has an empty `develop` ref file.
History export now supports explicitly selected readable refs, records warnings
and unresolved HEAD state, and verifies an isolated restoration without changing
source metadata or choosing a replacement commit. Invalid ref quarantine remains
a manual checkbox decision, separate from preserving readable history. The batch
journal in private state records live job IDs; counts here are dated evidence.

The active notes workspace and maintenance worktree share a Git directory and
contain roughly 43.3 GiB of files including local changes and links. Their initial
read-only assessment is recorded; coordinated full-file recovery protection is
still outstanding. History bundles alone do not satisfy this requirement.

The readable-history exporter is deployed. QtBooty's retry completed with an
independent restore and SHA-256 verification; its empty ref file is unchanged and
the receipt records the Git warning. The library batch therefore has 23 verified
history snapshots. Linux jobs `996c181bfd2a43dea636049997b77e3c` and
`158af73ba3bf4e489405cee251a4e1b7` are queued/running; completion remains unproven.
The live catalog shows seven workspace decisions awaiting review. Validation
artifacts are in `validation/readable-history/`: 17 history/catalog tests passed
before the final non-recursive symbolic HEAD read, followed by three edge/review
tests and five catalog tests on the final implementation. The final browser check
covered unresolved HEAD, source warnings, both viewport sizes and unchanged source
metadata. No new whole-tree move or permanent deletion was performed in this slice.

## Direct library archival batch — 2026-10-18

Read-only assessment found 11 direct bare repositories under E: `repos/libs`,
`repos/utils` and `repos/opt` with no enclosing repository boundary, additional
worktrees, active hooks, object alternates or path-dependent configuration. All
11 have completed native full-tree manifests and independently restored history
bundles; their published bundle hashes were checked again before authorization.
The observed one-level collection allowlist now includes these three collections;
deeper libraries, working trees and unknown collections remain excluded.

Three targeted layout/round-trip tests and a disposable native Windows
relocation/restoration check passed. The native fixture preserved hidden files,
file and directory streams, permissions, legacy Git clone access and newer work
through a reviewed fresh-baseline restoration. Evidence and code hashes are in
`validation/library-relocations/`.

Eleven goal-authorized moves are recorded in
`workspace-review/library-relocation-assessment.json`. They retain every complete
original tree on E: and provide legacy-path junctions; they reclaim zero bytes.
The two Linux history jobs were temporarily held for deployment and the smaller
move batch. Resume them after this batch reaches a terminal state. Consult live
receipts and job states before claiming any queued move has completed.

All eleven library moves have now completed. The live searchable catalog reports
38 archived source repositories in total, retaining their original paths. The
Linux history jobs have resumed: linux-adi is actively creating its bundle and
odroid is pending behind it. Seven uncertain workspace decisions remain in the
dashboard. No source was retired and no archival space was reclaimed.

## Coordinated active-workspace preservation — 2026-10-18

The active GENCOR checkout contains 77,368 regular files, 33 links and about
2.53 GB, including its GNAT toolchain and documentation environment. Manifest
`69cc77863bbf459dae2d723bd193c662` covers the whole current tree for comparison
with the historical D: manifest. The notes worktrees contain 46,522,020,318 bytes
combined and share the main checkout's Git directory. Their pending manifests are
`ddfcd88423c04ac2a3c87e2098f4cb52` (maintenance) and
`4dd239ca347848f0a3ebb75b1d570488` (main). None of these read-only captures is an
independent backup. The primary registry still has only the three previously
reviewed missing MBSE paths; curated fields and existing local edits are intact.

An additive POSIX full-file archive workflow is being validated before deployment.
It combines sibling trees in a PAX tar archive, retains complete Git internals and
working/ignored files, preserves links and ACLs/xattrs, and independently extracts
and compares all recorded payloads and portable metadata. Recovery proof does not
invoke Git through copied worktree pointers into original paths; activation at a
different location remains a coordinated follow-up. The original pointers and
shared Git metadata remain byte-preserved. Capacity reserves apply to H: and local
restore space. Partial attempts are retained on retry and private verification
evidence binds publication. Duplicate pending requests are coalesced.

The disposable round-trip tests caught a directory ordering issue for names that
sort before `.`: listing each source root before its children fixes recovery of
root timestamps without weakening metadata comparison. Seven snapshot tests,
six source-catalog tests and a browser flow passed before the final duplicate/
hardlink guards; two guard tests cover those additions. Broad regression validation
is still running. Do not start a real full-file archive until its completed
manifests and deployment gates are verified. The batch journal is
`workspace-review/primary-preservation-batch.json`.

Validation completed: all 97 Python regression tests passed in 604.595 seconds.
The final browser flow also covered an unavailable backend (backup controls stay
disabled until ready), successful queueing/recovery/search, persistent selections,
both viewport sizes and unchanged sources. A disposable archive on the real H:
drive passed publication/replay plus independent recovery of binary xattrs, modes,
nanosecond timestamps, links and empty directories. Evidence and code hashes are
retained in `validation/full-file-snapshots/`.

The GENCOR full comparison is complete: 1,321 matching payloads, 117 differing
payloads, 53 old-only entries and 80,502 current-only entries (full trees include
Git internals and directories). Working-only comparison specifically found
39 old-only working files and 108 differing working payloads. The existing
GENCOR checkbox description now includes those counts; it remains unapproved.
Both comparison records are visible in the catalog. The maintenance notes manifest
is complete; the main notes manifest is still running as of this update.

To avoid interrupting the large Linux export, transient local user service
`drive-manager-full-file-deploy.service` runs the one-time guarded deployment
helper `workspace-review/deploy_full_file_backups.py`. Its durable journal is
`workspace-review/full-file-backup-deployment.json`. It requires unchanged validated
source hashes, passing regression/browser/native checks and both completed notes
manifests. Once those manifests are ready it holds only pending history exports
while the active export finishes; no active preservation/move job is interrupted.
At an idle point it restarts the daemon, queues a coordinated notes snapshot to
H:, and releases only its own temporary pending-job holds. Explicit user pauses,
cancellations and checkbox decisions stay intact. The monitor is bounded to eight
hours and reports any failure to its journal; inspect its live unit/journal before
starting another deployment. No production full-file snapshot is claimed complete.

## D: synchronization-tree role assessment — 2026-10-18

Both notes manifests are now complete: 18,094 main files (45,431,095,264 bytes)
and 2,447 maintenance files (1,090,925,054 bytes). Their original source folders
remain untouched. The guarded deployment monitor is live and waiting for active
preservation work to finish; the next queued history exports are temporarily held
by that monitor. Do not restart the daemon solely because observation is slow.

Read-only inspection found that `/mnt/d/sgt/sergeant` carries a documented canonical
server synchronization contract for `/srv/sgt/sergeant`, excludes nested `.git`
directories from client sync, and has distinct source/build/runtime profiles. This
does not prove the D: copy is a live server tree: `/srv/sgt/sergeant` is absent on
this host, and no remote system was contacted. Keep this group in place while
reconciling its role with `~/workspace/`. The adjacent `sergeant.archive` has its
own pending disposition log, and `.rsync-backups` contains retained recovery
generations. Neither is an automatic duplicate or relocation candidate.

All five local sync profiles passed a read-only path check with zero missing or
unsafe entries. Policy hashes and the bounded role evidence are recorded in
`workspace-review/sgt-role-assessment.json` and shown on the dated review page.
The separate `magellan-qemu-testing` repository has seven working-status entries
and 68 visible files (208,800 bytes), with no observed links or enumeration errors.
It is not assumed dormant. Full manifest `d9bc2856df5f482195e42f87fb222214` and
history job `ffc6860713ed4990bc0e7b468a8e4546` are queued for additive preservation;
no move is authorized. Its operational dependencies and final active/archive role
still need assessment. Source scripts, sync profiles, archive disposition records
and remote systems were not changed.

The first large Linux export reached its 30-minute source-side bundle limit with
only a header written; its source and attempt remain retained. The second large
export is deliberately held for a method change, rather than being treated as a
verified archive. Completed native manifests record two/four object-pack artifacts
totaling 1,397,936,432 and 1,491,474,021 bytes. The next export investigation should
test a private Linux object cache populated with fresh identity/SHA verification,
then independent bundle restoration; do not retry the same source-side operation
unchanged. Details are in `workspace-review/large-linux-export-diagnostic.json`.

The guarded deployment completed after this terminal job and the QEMU manifest.
Its initial HTTP readiness probe ran before the listener bound; a subsequent probe
of the same daemon succeeded. No extra restart was performed for that observation
failure. The one-time helper now polls listener readiness for future reuse.
Coordinated notes snapshot `91f8dbadd47f406b8348e574bea596bb` is actively copying
both source trees to H:. It is not verified yet: tar audit, independent extraction,
restored payload/metadata checks and final source stability checks remain. Inspect
that live job and its process before resuming or restarting anything.

QEMU manifest `d9bc2856df5f482195e42f87fb222214` completed all 68 files, and history
`ffc6860713ed4990bc0e7b468a8e4546` completed independent restore verification.
Its seven working-status entries are still retained. Bounded text inspection found
canonical-root, parent-relative and remote/container tool references; these are
dependency leads, not a closure proof. No QEMU move proposal is authorized. There
are now 79 completed file manifests and 69 completed history safeguards. The final
production browser check confirmed backup availability, both source paths, no
premature verified-copy claim, responsive layouts and no writes/JavaScript errors.

## Local-object exports and worker-contention repair — 2026-10-18

Both large Linux sources now have independently restored history artifacts using
verified local object mirrors. linux-adi's 1,397,936,432 object bytes copied and
rehash-verified in 38.90 seconds; its 1,283,766,968-byte bundle built in 108.39
seconds and restored/fsck-verified in 202.60 seconds. odroid's 1,491,474,021 object
bytes took 47.65 copy/hash seconds; its 1,134,502,660-byte bundle built in 119.05
seconds and restored/fsck-verified in 196.38 seconds. All 2 and 1,439 recorded
readable tips respectively, and the unresolved symbolic HEAD states, were verified
without choosing a replacement default branch or changing source files.

The exact source-manifest object membership/identities and copied SHA-256 values
bind the mirrors. Private proofs bind bundle identity and recovery. The handoff
reserves the original history job in a non-runnable preparation state, retains
previous generated attempts, copies/hashes the bundle to its original destination,
publishes atomically, and queues the existing daemon reconciliation. Per-job locks,
ownership tokens and journals guard interruption, cancellation, explicit user
pauses and destination collisions. No independent production workers were started.
Both original history jobs are pending reconciliation, not yet counted complete.
Caches and prior attempts are retained; no retirement is authorized. Evidence is in
`validation/local-object-history/` and `workspace-history-imports/`.

The daemon's transfer worker and scan-h worker actually exited after an uncaught
SQLite writer-lock timeout in job claiming (service journal at 02:55:48). This is
an observed worker failure, not an observation timeout. The notes preservation
worker remained alive. The repair keeps idle polls read-only, retries busy/locked
claim transactions, prevents duplicate claims, and replaces inventory subtree
full-table prefix scans with indexed ranges that preserve prefix siblings.
Five targeted contention/index tests passed, followed by all 112 regression tests
in 993.317 seconds. Application source hashes and evidence are retained in
`validation/worker-contention/`. The new worker code is not loaded into the old
running daemon yet.

Transient service `drive-manager-worker-repair.service` runs the one-time helper
`workspace-review/repair_workers_after_backup.py`. Its journal is
`workspace-review/worker-repair-deployment.json`. It verifies the frozen tested
source, waits for the notes backup and all other non-scan preservation/preparation
jobs to finish or be explicitly held, then briefly holds only pending jobs, restarts
the daemon, polls the same listener for readiness, and releases its own holds.
Waiting checks are read-only and writer-lock contention retries safely. Explicit
user pauses/cancellations remain intact. It is bounded to eight hours. Inspect
the actual live unit/job/process before restarting anything; the active notes
archive must not be recopied merely to recover the idle transfer worker.

The notes data-copy process has exited and the 46,564,167,680-byte staged tar is
being read for verification (read-only archive FD observed beyond 41 GB). The job
still requires tar audit, independent extraction and all final checks before a
verified full-file backup can be claimed. All original notes and kernel sources
remain in place; no storage has been reclaimed.

## Documentation batch and existing-payload recovery — 2026-10-18

Current assessment covered 41 bare repositories under
`/mnt/e/repos/sergeant/docs/`, totaling about 11.25 GB of recorded Git storage.
Thirty-three have current tip objects not found at previously verified archive
heads. All 41 full native manifests are queued, alongside 33 history jobs. Eight
larger exports carry explicit automation holds until their native manifests are
complete and local-object staging can be verified; the remaining 25 are pending
ordinary history capture. No source move or retirement is authorized by this batch.
The batch journal is `workspace-review/sergeant-docs-preservation-batch.json`.

The other eight histories were freshly recovered from existing payloads: notes,
power analysis, hardware/interfaces/open/system architecture, test plan and trade
studies. Each selected payload was SHA-256 checked before and after restoration;
an independent empty repository received only the wanted source refs/HEAD state
and passed full fsck plus exact state comparison. Source refs remained stable.
These eight duplicate exports were avoided. Raw metadata, reflog-only/dangling data
and source-specific live catalog registration are still outstanding; none of the
eight sources is marked retired or fully backed up. Recovery recipes and payload
bindings are in `workspace-review/sergeant-docs-history-reuse-proofs.json`, with logs
under `validation/sergeant-docs/`. The dated review page displays the batch and
recovered sources explicitly.

The notes tar membership/default-payload audit passed; the same live job has moved
on to independent extraction and portable metadata/payload verification. Its
restoration process is active, so do not interrupt/restart it to refresh workers.
The worker-repair monitor is still live and waiting for the safe endpoint.

The D: whole-drive scan also became blocked with `database is locked` under the
old daemon. After the validated repair loads and the two published kernel artifacts
reconcile, recheck job `9e034b5ef4cb4723939795d4b0694106`. If it is still blocked
solely by this lock error, resume that same checkpointed scan; preserve user pauses,
cancellations and other error holds. Do not retry it under the old worker code.
Prioritize the queued workspace-preservation evidence over unrelated generated
toolchain inventory when scheduling further indexing.


## First verified full-file backup and linked GENCOR group — 2026-10-18

Notes job `91f8dbadd47f406b8348e574bea596bb` is now completed. The published
archive at `/mnt/h/archive/workspaces/posix-snapshots/20261018T094235Z-91f8dbadd47f`
contains 20,541 files, 46,522,020,318 payload bytes and 46,564,167,680 archive
bytes. Membership/payload audit, independent extraction, recorded portable
metadata comparison, final archive digest and source-stability checks passed.
SHA-256: `c5a57ad7e15128b30d627301d7c49914345b016c196dab2f0d015d56bd8ed39b`.
The private snapshot result binds both completed manifests and their seals.
Both original notes worktrees remain authoritative; alternate-path Git activation
and external dependency closure are not yet demonstrated. No space was reclaimed.

Fresh GENCOR assessment confirms two registered active worktrees: main GENCOR
and its sibling `gencor-doc-refactor`. They share main `.git`; the secondary
`ext` link resolves to the main installed toolchain. Preserve both in one group.
The secondary tree records 21,624 regular files / 226,079,490 bytes, 1,651
directories and four links, with no hardlinked regular files or inventory errors.
Its manifest `e9ef5440990947c0a265b11d856ef90b` is queued. Both current Git
statuses were clean. An external system Python link remains a recovery dependency.
The transient `drive-manager-gencor-backup.service` coordinator waits for both
full manifests and successful validated worker repair, rechecks shared Git and
link relationships, then queues one coordinated backup. It does not start an
independent production worker or authorize relocation. Evidence/journals:
`workspace-review/gencor-linked-preservation-group.json` and
`workspace-review/gencor-backup-coordination.json`.


The completed documentation manifests for `flight_test.git` and `images.git`
allow their two large history artifacts to proceed through the previously tested
local-object preparation, independent restoration and guarded publication path.
Private helper `workspace-review/prepare_ready_doc_histories.py` is running under
an observed exec session; its log is `/tmp/drive-manager-ready-doc-histories.log`.
It checks the original automation holds, reuses only private matching records,
and never starts a production worker. At this checkpoint flight-test object
payloads and readable tips passed staging verification; its bundle build is
active. Do not claim either history job completed until proof publication and
authoritative daemon reconciliation finish. All original sources remain intact.


Worker repair scheduling now drains at the next operation boundary: the notes
backup is complete, so the monitor temporarily holds pending non-scan jobs while
the already-active `programs.git` manifest finishes. Previously the FIFO worker
could claim another manifest before each idle poll. This changes only the private
deployment helper, not the frozen tested application sources. The original monitor
had no holds when stopped; its transient unit was recreated after syntax checking.
The new live journal records its held job IDs. Source data operations are never
interrupted, and the helper releases only its own exact-marker pauses after restart
or on error, retaining explicit user pauses and cancellations. Eight original
large-export automation holds were not overwritten. Flight-test independent
restoration is running concurrently outside the production worker loop.


## Worker repair deployed and kernel safeguards reconciled — 2026-10-18

The programs manifest completed without interruption. The guarded monitor then
restarted the daemon at an idle preservation boundary, loaded the frozen tested
worker fixes, and released all 56 temporary pending-job holds. The new daemon
PID was 318908 and the deployment journal phase is `completed`; no temporary
repair-marker holds remained. Both original Linux history jobs
`996c181bfd2a43dea636049997b77e3c` and
`158af73ba3bf4e489405cee251a4e1b7` are now authoritatively `completed` after
daemon reconciliation. Their original source repositories remain intact.

Flight-test history bundle generation and independent exact-ref/HEAD restoration
passed (1,135,060,717 bundle bytes; 23.01 seconds build and 85.60 seconds restore).
It is published for daemon reconciliation, still pending at this checkpoint.
The images artifact is undergoing independent restoration and is not yet claimed
published or complete. Records are in `workspace-review/flight_test-*.json` and
the original history-import journals.

The guarded one-time `drive-manager-d-scan-recovery.service` helper confirmed
both kernel jobs complete and the exact original `database is locked` hold, then
resumed the same D: scan checkpoint. It changes no user-held or cancelled job and
starts no independent worker. Journal: `workspace-review/d-scan-recovery.json`.


## Remaining large documentation history coordination — 2026-10-18

Both flight-test and images original history jobs are now completed following
independent restoration and daemon reconciliation. The first two-object preparation
helper exited successfully. Six large histories remain on their original automation
holds; programs already has a completed full manifest. Transient unit
`drive-manager-remaining-doc-histories.service` now advances programs, references,
security-temp, security, system and systems_engineering sequentially as manifests
complete. The private helper is bounded to eight hours, checks the original hold
during copying/restoration, uses the tested object-cache provenance and capacity
gates, publishes only after independent exact-ref/HEAD restoration, and delegates
completion to the production daemon. Changed user states are never overridden.
It does not run another production worker or authorize source retirement.
Journal: `workspace-review/remaining-doc-history-coordination.json`.
The recorded review page now shows batch-specific manifest/history status counts
instead of a permanently queued summary. Full manifests are still required before
any broader raw-metadata or relocation decision.


## Saturn mixed workspace preservation — 2026-10-18

Bounded read-only metadata discovery of `/mnt/d/lab/systems/saturn/workspace`
visited 30 directories through depth three, observing 89 regular files and
16,379,430,673 bytes. This is a lower bound: eleven directory frontiers remain
unexpanded. No Git boundary appeared within this scope; deeper boundaries remain
unproven. The group includes data captures, a large tools archive, boot/FPGA
artifacts, VxWorks IDE/kernel material and a Python environment. No payload was
opened, project script executed or source changed. Preserve these related folders
as a complete group pending dependency and active-role assessment.

A full native manifest is now queued behind existing preservation work; its ID,
bounded file metadata and unexpanded frontiers are recorded in
`workspace-review/saturn-workspace-assessment.json`. It includes non-Git material
that reachable-history bundles cannot protect. The scan is not a redundancy or
retirement proof, and no relocation or deletion is authorized by this assessment.


## Historical D: project checkout preservation — 2026-10-18

Six immediate checkouts under `/mnt/d/workspace/projects` had no previous
preservation jobs: correlation-simulator, database-tools, nav-cache, ngira,
python-file-manager and sergeant-design-manager. No same-named folder exists in
the immediate primary `~/workspace/projects` listing; that does not rule out a
renamed/nested counterpart. Their active versus archival roles remain unknown.
Fresh read-only Git checks found respectively 0, 0, 1, unknown, 10 and 1 status
entries. Ngira status reached the 60-second observation limit and its process
was terminated; no clean/dirty claim is made and no retry is forced.
All six now have additive history safeguards and full native manifests queued.
Raw working changes, ignored files and Git metadata remain in place, with full
manifests required before disposition. No source changes, automatic moves or
retirement decisions were made. The durable batch with source/job bindings is
`workspace-review/d-projects-preservation-batch.json`.


## Notes alternate-path Git recovery verified — 2026-10-18

Supplemental recovery from the published notes tar passed. The helper extracted
only archived `.git` metadata into a new private directory, compared all 2,089
selected members against the full manifest payload hashes, and rebound only the
copied secondary `.git` pointer and copied administration back-pointer. Before
Git activation it rejected unexpected topology, object alternates and configured
activation dependencies. Full `git fsck --full --no-reflogs` then passed; both
recovered worktrees resolve to the copied common directory and the worktree list
contains only their two isolated paths. Recovered HEADs are
`05a0ac2474ccdd13c5173b2c8e4f925ee8c56d7f` and
`3c67e80c53a89d24cf969b4fecf56ecbd6754a5b`, with 13 readable refs.
Both original full manifest seals were separately recomputed and matched the
snapshot receipt. No live source pointer or working file was modified.

Proofs: `workspace-review/notes-git-recovery.json` and
`workspace-review/notes-git-recovery-manifest-binding.json`. The supplemental
metadata-only recovery is retained under `snapshot-git-recovery-checks/`.
Working-file restoration was covered separately by the original completed full
snapshot test; external runtime dependencies and application behavior remain
unverified, and no source retirement is authorized by either test.


## Ngira canonical-counterpart evidence — 2026-10-18

Recorded remote identity comparisons against 57 primary Git boundaries found a
candidate for historical `/mnt/d/workspace/projects/ngira` at
`~/workspace/sergeant/tools/ngira`; the other five D: projects had no match within
that dated scope. Fresh local remote configuration confirmed the Ngira match.
Both current repositories expose five readable refs and the same named-tip object
set; the primary status check is clean. No fetch, merge, source edits or old-D:
status retry occurred. A primary full manifest is queued, ID
`95e50197a88f4c299c0fa4afa46cdf2f`, to pair with the already queued D: manifest.
The historical D: working status remains unknown after its earlier timeout.
Matching tips are not full-history, working-file, ignored-content or metadata
redundancy proof. Keep both sources until full comparison and role/dependency
checks support a specific reviewable disposition. Evidence:
`workspace-review/d-projects-counterpart-leads.json` and
`workspace-review/ngira-counterpart-assessment.json`.


## Deeper historical library relocation assessment — 2026-10-18

Fresh dependency checks covered eleven completed manifests under the Python and
SDR historical library collections. Ten repositories have self-contained bare
Git layouts, simple permitted local configuration, readable refs, no enclosing
Git ownership boundary through the historical repos ancestors, and completed
independent history recovery receipts. The malformed `.QtBooty.git` remains held
for its existing explicit checkbox decision and was not repaired. The ten passing
sources have not been moved: their deeper collection layouts remain outside the
current automatic policy. Extending that policy requires bounded explicit layout
recognition, all-ancestor ownership checks and validation before proposing moves.
Assessment: `workspace-review/deep-library-relocation-assessment.json`.
These checks do not authorize retirement or reclaim any space.


## Deeper collection policy implementation in validation — 2026-10-18

Automatic layout recognition now explicitly adds only `repos/libs/python`,
`repos/libs/python/modules` and `repos/libs/sdr`. Every intervening ancestor up to
`repos` is checked for a working/bare Git ownership boundary; unrecognized deeper
layouts remain rejected. The change is on disk, not yet deployed to the daemon.
Relocation regression tests now exercise a deepest-library move/restore plus each
ancestor boundary and unknown-layout rejection. A disposable Windows-native
fixture is running in the same deepest layout to verify hidden payloads, file
and directory ADS, permissions, legacy-path cloning and recovery.
Private validation/deployment preparation is in
`validation/deep-library-relocations/` and
`workspace-review/deploy_deep_library_moves.py`. No real source move has been queued
from the new policy yet. Deployment requires both checks to finish successfully
with unchanged frozen sources and an idle preservation boundary.


The deeper-library validation passed: all twelve relocation regression tests in
90.135 seconds and the disposable native Windows fixture, including file/directory
streams, hidden files/ACLs, legacy-path clone compatibility and stale/fresh restore
checks. Logs are retained in `validation/deep-library-relocations/`. A live guarded
`drive-manager-deep-library-deployment.service` now waits for the current operation
boundary, holds only pending non-scan work, restarts the daemon with unchanged
validated sources, releases only its own holds, and prepares the ten assessed
bare-repository archival proposals. Each production move still revalidates full
payload/native metadata, dependencies and readable refs; no deletion/reclamation
is queued. Journal: `workspace-review/deep-library-deployment.json`; batch results
will be recorded in `workspace-review/deep-library-relocation-batch.json`.
The original malformed-reference checkbox remains untouched.


The deeper-library policy is now deployed (daemon PID 334182). All 19 temporary
deployment holds were released; zero exact-marker holds remained. Ten eligible
bare library repositories are queued through the production transfer lane, with
full source/destination/candidate/job bindings in the batch journal. The first
QtBooty archive reached post-move data/native-metadata/legacy-path verification;
no completed-move claim is made yet for this batch. The separate hidden malformed
`.QtBooty.git` was not included. Each move retains an original-path compatibility
junction and recovery receipt, with zero space reclamation.


## References object mismatch held for recovery assessment — 2026-10-18

The first deeper-library QtBooty archive completed with its legacy path verified;
the other independent moves continue. Separately, references history staging
stopped on loose object `e65770a20147c018abea87b33329b87d721dfce5` (20,647,077
bytes). Fresh Linux and Windows SHA-256 reads agree with the retained failed copy
but disagree with the completed manifest hash, while recorded source identity
fields still match. Zlib decompression fails its checksum. No assumption is made
about the underlying cause or when the data diverged. The source and prior sealed
manifest are retained, with diagnostic proof in
`workspace-review/references-object-copy-diagnostic.json` and the failed private
object cache. Original history job `769348d4923c413d8c228a977a7a0972` remains
paused with an explicit diagnostic hold; no source repair is authorized.
A read-only full Git integrity check is running into `references-fsck.log`.
Independent remaining documentation exports resumed through
`drive-manager-remaining-doc-histories-recovery.service`, preserving this changed
hold instead of retrying references. The original automation never marked its
failed copy verified or published it.


Windows native SHA-256 confirmed the same current references object bytes as
Linux. Read-only full Git fsck exited 3 and reported this one corrupt/missing blob;
its detailed log is retained privately. Seven of ten deeper-library moves had
completed when checked, with one verifying and two pending. An isolated recovery
attempt is testing the exact blob identity against the previously independently
verified Northrop references history bundle (SHA checked before use). Recovery
results will be in `workspace-review/references-blob-recovery.json`; no original
object is modified or replacement inferred from a different branch or filename.


## Ten deeper-library moves completed — 2026-10-18

All ten deeper Python/SDR archival jobs are completed, with receipts in phase
`archived` binding full payload/native-metadata and original-path read checks.
A fresh independent check confirmed every original path remains a native junction
to its recorded destination. This batch preserves 1,637 files / 653,517,756 bytes.
Proof: `workspace-review/deep-library-completion-proof.json`. No space reclaimed;
all archived data remains available at its legacy path and in the searchable catalog.

The damaged references object was mapped to one historical tree path. None of
four expected related working locations contained that file. The related verified
Northrop history bundle lacked the exact object; raw-deflate salvage also failed
exact Git identity, so neither is offered as a replacement. The source remains
held without repair. A bounded lookup of completed manifest object locations is
now checking for an independently preserved loose copy. Evidence is retained in
`references-working-payload-recovery.json`, `references-blob-recovery.json`,
`references-raw-deflate-recovery.json` and `references-object-other-manifests.json`.


## Exact references object recovered and independently archived — 2026-10-18

The retained failed copy yielded a byte-exact recovery. A bounded single-byte
Adler-32 correction was accepted only by the full pre-existing Git object SHA-1
and stored checksum; three recovery tests cover wraparound, wrong identities and
multi-byte damage rejection. Independent Git hash-object/fsck and presentation
ZIP CRC checks passed. Git's newly generated compressed object also exactly
matches the original sealed manifest SHA-256
`5d7031dc24340d76a56d1b59403be9073a54275a10e6763735186638b40038a2`.
An exclusive additive copy is now retained under H:
`archive/workspaces/git-object-recoveries/`, with Linux and Windows SHA verification
and a receipt. This preserves the exact original object independently without
changing the damaged source repository or weakening the original manifest.

Proofs: `references-single-byte-recovery.json` and
`references-recovered-object-archive.json`; recovery tests/log:
`recover_single_byte_blob.py` and `/tmp/drive-manager-references-single-byte.log`.
The repository history job remains on its diagnostic hold. A concrete unapproved
repair plan is in `references-object-repair-plan.json`. An executable reviewed
repair must preserve the damaged native file/metadata and allow rollback before
installing the exact recovered bytes. That checkbox workflow is still outstanding;
no original repair, deletion or retirement has been performed.


## Reviewed Git object repair workflow — implementation and validation

New `object_repairs.py` adds a dedicated checkbox-only candidate. Approval binds
the original sealed manifest, damaged bytes/current native metadata, byte-exact
recovery artifact and current refs. It rejects standing-policy authorization,
changed sources/artifacts and unresolved ownership dependencies. Staging preserves
native streams/SDDL/mtime/attributes before any source mutation; the damaged file
is retained by a same-volume rename. Installation refuses collisions, verifies
full Git fsck/ref stability and queues a fresh complete manifest. Receipts support
replay/rollback without overwriting newer concurrent work. No permanent deletion
or automatic production repair is authorized.

The initial nine focused tests passed; a native fixture passed hidden-file, ADS,
SDDL, mtime, full-fsck and replay checks. A disposable browser fixture approved and
executed only its own test repair with no runtime errors. The current code is
running the broader repair/service/dispatch/reviewed-restore regression selection.
A frozen-source guarded deployment helper is prepared in
`workspace-review/deploy_object_repair_review.py`; after passing checks and an idle
preservation boundary it will deploy and create the real candidate in `review`
state. It never approves that candidate. Evidence: `validation/object-repairs/`.


The 51-test repair/service/dispatch/reviewed-restore regression selection passed
in 656.944 seconds; checkpointed manifest reuse also passed. The daemon deployed,
but a simultaneous real-file preflight found Set-Acl could not assign the historical
security descriptor. The unapproved strict proposal was immediately held without
running a repair. Native CopyFile's replacement descriptor differs from the source.
The original remained unchanged throughout.

The final workflow now allows that one explicit security-descriptor difference
only when a real staged preview is bound into the checkbox proposal. Every other
recorded native metadata field must match. The original file, including its
historical owner/ACL, is still preserved through native quarantine; the installed
file must exactly match the approved replacement descriptor. Actual native staging
passed with only `sddl` different. Additional focused tests and a native fixture
are validating this explicit path before a replacement review proposal is created.
No privileged owner change or automatic source repair is attempted.


The explicit-security path passed four focused tests in 47.529 seconds and a
native Windows complete repair/quarantine/fsck/replay test in 32.414 seconds.
The real references staging preview passed with only `sddl` different and the
original signature/data unchanged. Deployment completed; all temporary holds
were released, and D:/E: scans plus the same Saturn checkpointed manifest resumed.
The obsolete strict candidate `bf9a8d147af14b4590771b151fd0931f` remains on an
implementation hold, with no job. The replacement executable proposal
`cd8a4781bf35475b87618cc615e74335` is in review, with no job and no approval.
Its reason explicitly describes the staged security-descriptor difference and
retention of historical owner/ACL on the native original. No production repair
has run. The private source hashes and scoped test/browser/native evidence are
retained in `validation/object-repairs/`.


## Responsive real repair approval verified — 2026-10-18

The real browser check exposed a separate bottleneck: initial rendering waited
for whole-inventory aggregation and exceeded sixty seconds. The dashboard now
loads bounded control/approval state through `/api/control-state` independently
of the slower inventory summary, which refreshes separately. Unknown inventory
is labelled loading rather than shown as a completed empty result. Three targeted
HTTP/cache tests passed, and a disposable browser completed a reviewed repair
while `/api/state` was deliberately stalled.

The service restart command observation timed out, but the actual new daemon
PID 358414 was confirmed active, all production workers alive, frozen sources
matched, and the new control endpoint returned in about 0.01 seconds. This was
reconciled from authoritative health/state without issuing another restart.
No temporary deployment holds remain. The real repair checkbox was then visually
verified enabled and unchecked on the live page; candidate
`cd8a4781bf35475b87618cc615e74335` remains `review` with no job. The original
object remains unchanged. Evidence: `validation/object-repairs/real-review-proof.json`,
`browser-stalled-inventory-proof.json`, responsive control tests and live card
screenshot. Background indexing continues while this specific decision awaits
the user's checkbox approval.


## Documentation bare-repository archival batch — 2026-10-18

All 41 historical documentation sources were freshly assessed after their full
manifests completed. Thirty repositories passed simple self-contained bare Git,
readable refs/HEAD, all-ancestor ownership boundaries and source-specific completed
independent history recovery gates. They contain 3,098 files / 9,267,586,659 bytes.
Eleven remain held for the pending exact-object repair, unresolved HEAD, local
configuration or source-specific registration of reused history recovery proofs.
Assessment: `workspace-review/sergeant-docs-relocation-assessment.json`.

Automatic layout recognition adds only four observed collection paths:
`sergeant/docs`, `sergeant/docs/presentations`,
`sergeant/docs/systems_engineering`, and its `architecture` subcollection.
Every ancestor remains checked for Git ownership boundaries; unknown deeper
layouts remain rejected. All thirteen relocation tests passed in 92.206 seconds.
The deepest-layout Windows fixture passed full native data/streams/permissions,
legacy clone and reviewed recovery checks. Evidence is retained in
`validation/sergeant-docs-relocations/`.

Transient unit `drive-manager-sergeant-doc-archival.service` uses a frozen-source
guard to deploy at a safe boundary and queue the thirty eligible moves. Data moves,
copies and backups must finish first; read-only manifest indexes may checkpoint
and resume using signature-bound cached hashes. Restart observation verifies a
new actual service PID and live workers, rather than treating a command timeout
as service failure. Temporary pending-job holds preserve user decisions. Each
production move still verifies full payload/native metadata and original-path
access, retains compatibility junctions, and reclaims zero bytes. The specific
references repair checkbox remains independent and unapproved.


The documentation layout deployment is complete. All thirty eligible proposals
were queued with no proposal-generation holds, and the temporary deployment
holds are fully released. Actual new service PID and all live workers were
verified by the guarded restart. Production moves are now performing full
verification; authoritative per-job states are in the live archive catalog and
`workspace-review/sergeant-docs-relocation-status.json`. The original-path aliases
and recovery receipts remain required; no space is reclaimed. The eleven held
sources and the unapproved references repair decision remain untouched.

Saturn full native manifest `4c6ca9010b874dfc895a883d0d071caf` completed with
9,560 files / 17,052,068,109 bytes. This supersedes the bounded lower-bound count
for content coverage, but is not an independent backup or active-role/dependency
proof. The whole group remains in place pending that work. Primary/historical
project manifests are continuing in the workspace lane.


## Primary workspace-manager safeguard verified — 2026-10-18

A separate immutable safeguard of the primary manager now preserves its curated
metadata roots and complete local `.git` directory, including ignored data inside
those selected roots. It contains 769 files / 3,538,383 bytes. GNU tar preserves
POSIX permissions/ownership/times, ACLs and xattrs; every scoped member/payload and
link was audited, independently extracted and compared. Recovered Git refs and
local working status match the captured source, and full Git fsck passed. The
current `.wksp.json` and `docs/RUNBOOK.md` modifications remain intact in source
and recovery. Final source membership/identities and refs/status remained stable.

The published package is under H: `archive/workspaces/metadata-safeguards/`, with
manifest, archive digest and recovery receipt; the folder has a protected Windows
ACL for the current Windows user, SYSTEM and Administrators. Source data was not
modified. This is the declared workspace-manager scope, not a full backup of
all nested projects or external dependencies. A partial-directory scope does not
assert matching directory link counts, atime/ctime or complete dependency closure.
Evidence: `workspace-review/workspace-manager-safeguard.json`, with retained
independent extraction under `metadata-safeguards/` in private state. No source
retirement or space reclamation is authorized.


Database-tools full manifest encountered a transient main inventory writer-lock
error. Only that exact lock-only blocked checkpoint was requeued, preserving its
local manifest database and signature-bound cached hashes. User pauses/cancellations
were not changed. Journal: `workspace-review/database-tools-manifest-recovery.json`.
Monitor for recurrence before broader writer-contention changes; originals remain
untouched and independent archival work continues.


The enterprise_architect documentation move encountered a transient native WSL
vsock timeout during verification. The engine restored the complete original
folder and fully verified its payload/native metadata before recording
`rolled_back`. Only that exact blocked job/error was requeued, with source intact
and no destination collision. No source edits, data loss or user-decision override
occurred. Recovery journal: `enterprise-architect-relocation-recovery.json`.


All thirty documentation moves are now complete, including the safely retried
enterprise_architect move. A fresh independent completion audit checked every
job status, archived-phase receipt, full payload/native-metadata/legacy-read
flags and current native junction target. All thirty passed, preserving 3,098
files / 9,267,586,659 bytes. Durable proof:
`workspace-review/sergeant-docs-archival-completion-proof.json`. No space reclaimed;
no held source or unapproved repair was executed by this batch.


## Worker write contention and active-tool consolidation — 2026-10-18

The pre-move health gate prevented moving the tool while scan-d, scan-e and
workspace workers were actually stopped. Their journal traces show SQLite busy
failures in job execution/progress followed by another busy failure in the error
handler. No source move or backup began before this gate. The new fix retries
short progress/event/final-status/error-recording transactions, requeues only the
same still-running checkpoint after a busy operation, and preserves user pauses
and cancellations. Directory inventory reserves its writer before reading the
transaction snapshot. All 43 worker/service tests passed in 96.348 seconds,
including actual lock contention and failing error-recording scenarios.
Evidence: `validation/worker-write-retry/`. A guarded one-time deployment uses
actual new PID and live-worker verification, with resumable read-only indexes
checkpointed and data-mutating jobs allowed to finish.

The active Drive Manager code is planned for canonical
`~/workspace/projects/drive-manager`, retaining `~/drive-manager` as a compatibility
link. A disposable real-filesystem atomic exchange and reversal passed. Before
any real move, the entire code tree must be independently backed up/restored,
then exact source content/inodes and uninterrupted service verified. The supported
workspace registration CLI has been dry-run with explicit non-Git acceptance;
no Git repository or commits will be invented for this currently local-only tool.


## Active Drive Manager consolidated into primary workspace — 2026-10-18

After the writer-retry fix deployed, every production worker was verified alive.
The complete tool source was independently archived/restored on H: before moving.
An atomic same-filesystem directory/compatibility-link exchange placed the actual
source under `~/workspace/projects/drive-manager` and retained `~/drive-manager`
as a legacy symlink without a missing-source interval. Exact content, portable
metadata and source inodes passed verification. The running service kept the same
PID and its actual cwd now resolves to the canonical directory; no restart was
needed for the move. State remains in `~/.local/share/drive-manager`.

Both installed and reinstallable unit definitions now use the canonical directory.
The workspace CLI registered `projects/drive-manager` as an active local service;
an explicit reason documents its intentional non-Git tree. No repository or commits
were invented. Comparison against the registry preimage confirmed all unrelated
curated fields unchanged. Workspace check still reports only the three previously
known missing MBSE paths, with the new local exception accepted. Main metadata Git
still has only `.wksp.json` and `docs/RUNBOOK.md` modified; the project remains
ignored by the metadata repository. A fresh canonical-tool full manifest is queued.

Evidence: `workspace-review/drive-manager-consolidation.json` plus independent H:
`tool-source-safeguards/` source package, canonical configuration overlay and move
proof. The workspace-manager safeguard was refreshed after registration, so the
new canonical registry entry is also independently restored/verified on H:. No
user source was deleted and no space was reclaimed.


## Independent archive audit-state safeguard — 2026-10-18

A read-only SQLite backup captured the live archive database consistently while
writers continued. All 124 completed manifest databases in that snapshot were
individually backed up and verified against their recorded row seals. The package
includes 737 files, including 485 control/recovery artifacts, current canonical
service configuration and workspace registry. Raw source/model/history payloads
and temporary object caches remain at their recorded locations.

The full package was independently extracted, every artifact SHA-256 checked,
the restored database integrity checked, and completed-manifest bindings compared.
A protected H: copy was then independently SHA-256 verified and published at
`/mnt/h/archive/workspaces/audit-safeguards/20261018T142903Z-f3c5f16acc92`.
Compressed size: 204,630,978 bytes. No control artifact was skipped. Evidence:
`workspace-review/archive-audit-safeguard.json`; repeatable preparation helper:
`workspace-review/backup_archive_audit.py`. This is a point-in-time operational
metadata safeguard, not a copy of every underlying source or payload archive.

Only generated local snapshot/extraction copies were removed after both local
and H: archives reverified. The live operational state and both verified compressed
archives remain. No original workspace content was deleted or retired.

### Declared Hatch dependency lockfiles — 2026-10-18

The archival preflight now distinguishes a narrow class of dependency lockfiles
from operational locks: a regular file directly under `locks/`, a matching
`locks/{env_name}.lock` declaration in `pyproject.toml` Hatch environments, and
the hatch-pip-compile generated header are all required. Unknown lockfiles and
Git operational locks remain blocked. These dependency files remain part of the
sealed full-tree manifest and undergo the same payload and metadata checks as
other files; neither tracked nor untracked files are omitted. Working-tree
relocations still require explicit dashboard approval.

The Sergeant Design Manager sealed manifest (262 files, 12,218,917 bytes) passes
this classification for its four untracked dependency lockfiles. This preflight
does not constitute a relocation or runtime verification. Production deployment
must wait for the relocation regression checks and a safe service boundary.

### Unreadable POSIX directory reporting — 2026-10-18

POSIX enumeration now finishes listing a directory before emitting its success
record. An unreadable directory produces one error record, preserving the
explicit permission hold instead of failing later on duplicate manifest paths.
The read-only MBSE Lab preflight contains 1,643 unique paths and one inaccessible
PostgreSQL data directory. No permissions were changed and no database backup
or complete MBSE preservation is claimed. This source change awaits a safe
production deployment boundary.

Both preflight fixes were deployed through the guarded service restart on 2026-10-18. New daemon PID 418095 passed all worker health checks, pending jobs were released, and no active backup or move was interrupted. MBSE Lab was queued to replace the old duplicate-path failure with an explicit preservation result.

### Explicit mixed-file ownership snapshots — 2026-10-18

The snapshot endpoint accepts `preserve_mixed_ownership: true` for an explicit
privileged capture and exact-owner restoration workflow. Default requests still
reject mixed ownership. The selected sealed manifests must contain ordinary
readable trees: hardlinked files, mixed-owner directories or symlinks, setuid or
setgid metadata, and file capabilities remain separate preservation holds.

Both GNU tar capture and independent restoration use noninteractive privileges;
this is necessary because `--atime-preserve=system` also requires privilege to
read a file owned by another user without changing its access time. Archive
membership and payload audits, restored ownership/mode/xattr/timestamp checks,
capacity reserves, final source stability checks and source-retention rules are
unchanged. Numeric ownership and privilege use are recorded in the receipt.
The implementation has passed real mixed-owner fixture capture/recovery and
privileged process cancellation checks. The production os manifest contains 21
root-owned regular build files among approximately 510 MB of source-tree data.
No original ownership or permissions are rewritten by this workflow.

### Independent backup of externally shared hardlinked files

`materialize_external_hardlinks: true` is an explicit additive backup mode for
files whose other hardlink aliases are outside the selected trees. It rejects
any hardlink group with multiple selected paths, so internal alias relationships
cannot be silently flattened. Capture writes independent payloads, restoration
verifies link counts of one for those copied files, and source verification still
requires every original identity and link count to remain unchanged.

An `external-hardlinks.json` sidecar records original source paths, device/inode
identities, link counts and content hashes. Its SHA-256 is bound into the receipt
and checked at publication and reconciliation. External alias paths are neither
followed nor recreated, and every original must remain retained. This mode proves
self-contained payload recovery, not recovery of the original external sharing
or permission to retire a source. Default requests continue to reject hardlinks.


### Protected PostgreSQL 15 cold-cluster snapshots

The explicit `/api/workspace/postgres-snapshot` endpoint accepts a digest-bound
full protected-tree seal in the private `validation/protected-cluster` directory.
It queues the normal workspace snapshot lane; helpers never run production
Store workers. The source must be a canonical Linux workspace cluster with
PostgreSQL 15 metadata, regular files/directories only, and no PID or recovery
signals. Privilege is required for capture and exact numeric ownership verification
of both files and directories; no source permissions are changed.

The worker rehashes all source files before capture, audits every tar member and
payload before extraction, independently restores and verifies membership,
ownership, modes, link counts, modification times, extended attributes and content,
and reads the restored control file with a pinned matching control reader. Only
a clean shutdown state is accepted. The entire source seal and archive digest
are checked again before atomic publication. Published artifacts reconcile only
against a matching private verified receipt and unchanged archive/seal digests.

New Windows archive staging folders receive protected native ACLs for the current
Windows user, SYSTEM and Administrators before any cluster data is written. Linux
staging is private mode 0700. Failed attempts and exact-owner restore copies are
retained. Runtime activation, locales, extensions and logical recovery remain
separate requirements: this worker never starts PostgreSQL and never authorizes
retirement or space reclamation. Its catalog receipt states that distinction.


The protected endpoint also accepts an explicit canonical `cluster_relative`
(default `.`) to archive a complete Linux project containing a nested PostgreSQL
15 cluster. The entire project still requires a full privileged payload seal,
regular files/directories only, exact source revalidation and independent
restoration. Cluster version, PID/recovery-signal rejection and control-state
verification use only the selected subtree. The receipt records the relative
cluster path and distinguishes whole-project scope from a cluster-only archive.
Other services' runtime or transaction consistency is not implied by the selected
PostgreSQL clean-shutdown proof. Ordinary manifests and snapshot defaults remain
unchanged; original permissions and files are retained.


### Registered active external sources

Workspace jobs may read an external checkout under the current user's home only
when its exact canonical root appears as active under `externalProjects` in the
original regular curated registry and its containing project is active. External
Git storage must be an ordinary in-tree `.git` directory, with the worktree root
and common directory matching that source and no object alternates. Linked or
redirected storage requires a coordinated preservation plan. Dormant, unregistered,
symlinked and descendant paths do not expand the source exception. Existing
configured roots keep their normal behavior.

This exception enables additive history/manifests/full-file backup only. Transfer
and destination validation still use the configured roots; it does not authorize
moving an external checkout or reading all of HOME. Symlink payloads are preserved
without following external targets; those target dependencies need separate
coverage. Full POSIX snapshot staging now applies the existing protected native
Windows ACL before writing payloads to Windows drives; Linux staging stays private
0700. The new receipt records whether a Windows archive ACL was protected.


### Versioned Python runtime dependencies

A canonical `~/.pyenv/versions/<major>.<minor>.<patch>` prefix is a read-only
workspace source only while an active, registered, self-contained external
checkout directly references its native interpreter through `.venv/bin/python`.
The referring checkout must pass the existing source gate, its virtualenv parents
must not be redirected, and the target must be the exact in-prefix ELF interpreter
with a regular in-prefix standard-library `os.py`. The parent versions directory,
other versions, prefix descendants and generic home paths are not granted.
Dormancy, a changed link or a redirected prefix invalidates the dependency source.

This permits additive manifests and verified full-file capture of the runtime
required by the registered checkout. It does not follow other external links,
expand destinations, move user files or activate the interpreter. Capture and
restore verification remain required; dynamic operating-system libraries and
actual activation of a disposable recovered environment are separate checks.


## Windows file payload recovery and native inventory

`POST /api/workspace/native-file-snapshot` takes a completed native `manifest`
and optional `archive_root`. It queues the existing workspace snapshot lane;
there is no parallel production worker or source mutation. Current eligibility
is ordinary files and directories, no named streams, and no file hardlinks.
Reparse points, protected files, special entries and unsupported streams fail
closed rather than being omitted. Existing POSIX snapshot behavior is unchanged.

The archive includes every file payload, empty directories and the complete
sealed native inventory, including recorded Windows security descriptors,
attributes and modification times. Staging has a protected Windows ACL before
payload writing. Source identity and native membership checks surround capture;
archive membership and hashes are audited before an independent extraction and
full restored-payload comparison. The source catalog and archive cards identify
this as file payload recovery with native metadata retained.

This format does not activate Windows owner/ACL metadata, capture SACL audit
rules, or prove runtime dependencies. Its receipt explicitly records these
limits and never authorizes source retirement or space reclamation. Original
sources remain until those additional recovery requirements are satisfied.

### Explicit legacy WSL file-link recovery

The optional `preserve_wsl_file_links: true` field on the manifest and native-file-snapshot APIs enables a separate recovery scope for legacy NTFS WSL file links (tag `0xa000001d`, version 2). Both requests must select this mode. Existing jobs and the default ordinary-file format keep their existing refusal behavior.

A supported link must have a relative UTF-8 target resolving directly to an inventoried regular file inside the enclosing source. Escaping targets, chains, directory links, unsupported tags, protected entries, extra native link stream data, ordinary-file ADS and hardlinks remain refused. Native inventories read each raw link record twice without following it and seal the raw bytes, source identity and complete membership.

Captures retain raw records in the inventory and relative symlinks in the archive. Archive auditing checks each link type and target before extraction; a separate private Linux restoration checks complete membership, every regular payload and every symlink target. Final source enumeration and identities must remain stable before publication. Counts distinguish regular files from WSL links.

The resulting scope is `full-visible-windows-file-payloads-wsl-file-links-and-native-inventory`. It does not establish Windows owner/ACL activation, native link security capture, SACL capture, environment activation or source retirement. Those limitations appear in receipts and source-catalog descriptions. Existing originals remain retained. Crash recovery requires an exact private verified receipt and published artifact binding, as for the ordinary native format.

### Native link records (isolated development)

The explicit `preserve_native_link_records: true` manifest and native snapshot
mode preserves bounded raw link reparse and WSL UID/GID/mode EA streams as inert
inventory data alongside every regular file payload. It is mutually exclusive
with `preserve_wsl_file_links`. Default capture rules remain unchanged.

This mode accepts only the tested legacy WSL version 2 link records and bounded
relative Windows symlink records with matching print/substitute targets, plus
exactly the `$LXUID`, `$LXGID`, `$LXMOD` EAs. Unknown streams or native attributes,
changed identities, mismatching Linux metadata, and internal targets absent from
the sealed direct file/directory inventory block capture. Absolute historical
WSL targets remain verbatim records; their dependencies are not followed.

Independent restore materializes regular files and directories, while preserving
link bytes and Linux ownership/mode metadata inside the exact sealed inventory.
It creates no filesystem links. The receipt uses the distinct
`full-visible-windows-file-payloads-inert-link-records-and-native-inventory`
scope, `links_materialized: false`, and `link_records`. Windows link security
metadata, owner/ACL activation, SACLs and dependency closure remain unverified.
Originals remain retained; no reclamation or source retirement is authorized.

The inert-link mode permits at most 500,000 entries and 512 MiB of serialized
inventory metadata. Both limits are checked before archive payload processing;
manifest loading also checks its running byte and entry totals. Existing native
formats retain their 100,000-entry limit. These are bounded capture budgets,
not permission to omit entries from an oversized workspace.
