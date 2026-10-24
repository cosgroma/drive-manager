"""Read-only, bounded search across discovery and recorded preservation evidence."""
from __future__ import annotations
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
import re

from . import registry
from .snapshot_comparisons import named_stream_scope


@lru_cache(maxsize=8)
def cached_report(path,mtime,size):
    return json.loads(Path(path).read_text())


def report(path):
    if not path.exists():return None
    stat=path.stat()
    return cached_report(str(path),stat.st_mtime_ns,stat.st_size)


def registrations():
    try:_,_,data=registry.read_registry()
    except FileNotFoundError:return []
    groups=[('projects',data.get('projects',[])),('externalProjects',data.get('externalProjects',[]))]
    groups += [('sergeant.'+key,data.get('sergeant',{}).get(key,[])) for key in ('components','designs','engines')]
    output=[]
    for group,projects in groups:
        for project in projects:
            for collection in ('worktrees','relatedRepositories','submodules'):
                for entry in project.get(collection,[]):
                    output.append({'path':entry['path'],'project_id':project['id'],'project_name':project.get('name',project['id']),
                                   'group':group,'collection':collection,'role':entry.get('role'),
                                   'status':entry.get('status',project.get('status')),'branch':entry.get('branch'),
                                   'last_reviewed':entry.get('lastReviewed',data.get('lastReviewed'))})
    return output


def scope(path):
    primary=str(Path.home()/'workspace')
    if path==primary or path.startswith(primary+'/'):return 'primary'
    for drive in ('d','e','h'):
        if path.startswith('/mnt/'+drive+'/'):return '/mnt/'+drive
    return 'other'


def search(store,query='',root='all',coverage='all',offset=0,limit=50):
    if not isinstance(query,str) or len(query)>2048:raise ValueError('Search must be at most 2048 characters')
    if root not in ('all','primary','/mnt/d','/mnt/e','/mnt/h','other'):raise ValueError('Unknown workspace scope')
    if coverage not in ('all','unassessed','history','manifest','snapshot','archived','review'):raise ValueError('Unknown evidence filter')
    try:offset,limit=int(offset),int(limit)
    except (ValueError,TypeError):raise ValueError('Invalid search pagination')
    if not 0<=offset<=1000000 or not 1<=limit<=100:raise ValueError('Use an offset from 0–1000000 and a limit from 1–100')
    with store.db() as db:
        histories=db.execute('SELECT a.*,j.status FROM workspace_archives a JOIN jobs j ON j.id=a.job_id').fetchall()
        manifests=db.execute('SELECT a.*,j.status FROM workspace_manifests a JOIN jobs j ON j.id=a.job_id').fetchall()
        candidates=db.execute("SELECT c.*,j.status job_status FROM candidates c LEFT JOIN jobs j ON j.id=c.job_id WHERE c.kind IN ('workspace_archive','registry_remove','workspace_restore_review','move')").fetchall()
    relocations={};aliases={}
    for c in candidates:
        if c['kind']!='workspace_archive':continue
        path=store.state/'workspace-relocations'/((c['job_id'] or c['id'])+'.json')
        receipt=json.loads(path.read_text()) if path.exists() else {}
        bound=all(receipt.get(k)==value for k,value in [('job',c['job_id']),('candidate',c['id']),('source',c['source']),('destination',c['destination'])])
        item={'candidate':c['id'],'job':c['job_id'],'status':c['status'],'job_status':c['job_status'],
              'destination':c['destination'],'phase':receipt.get('phase'),'verified_at':receipt.get('verified_at'),
              'recorded_verification':bound and c['status']=='completed' and receipt.get('phase')=='archived' and
                  all(receipt.get(k) for k in ('payloads_verified','native_metadata_verified','legacy_payload_reads_verified'))}
        relocations.setdefault(c['source'],[]).append(item)
        # A fresh manifest of a moved tree belongs to the same source, not a
        # second discovered copy. Keep each evidence record's actual input path.
        if bound and receipt.get('phase') in ('moved','linked','archived','restore_published','restored','rolled_back'):
            aliases[c['destination']]=c['source']
    rows={};haystacks={}
    def row(path):
        path=aliases.get(path,path)
        if path not in rows:
            rows[path]={'path':path,'scope':scope(path),'discovery':[],'registrations':[],'canonical_matches':[],
                        'history':[],'manifests':[],'snapshots':[],'relocations':[],'reviews':[],'retirement_authorized':False}
            haystacks[path]=[path]
        return rows[path]
    discovery_scopes=[]
    directory=store.state/'workspace-review'
    initial=report(directory/'comparison.json') or report(directory/'inventory.json')
    supplemental=report(directory/'additional-discovery.json')
    for label,data in [('initial',initial),('additional',supplemental)]:
        if not data:continue
        discovery_scopes.append({'name':label,'created':data.get('created'),'depth':data.get('discovery_depth',data.get('depth')),
                                 'boundaries':len(data.get('repositories',[])),
                                 'unexpanded_frontiers':len(data.get('unexpanded_frontiers',[])),
                                 'limitations':data.get('limitations',[])})
        for old in data.get('repositories',[]):
            r=row(old['path'])
            r['discovery'].append({'report':label,'observed_at':data.get('created'),'root':old['root'],'bare':old.get('bare'),
                                   'head':old.get('head'),'status_complete':old.get('status_complete'),
                                   'change_count':len(old['changes']) if old.get('changes') is not None else None,
                                   'ref_count':len(old.get('refs',[]))})
            for match in old.get('canonical_matches',[]):
                if match['path'] not in r['canonical_matches']:r['canonical_matches'].append(match['path'])
            haystacks[r['path']].extend([old.get('head') or '',*old.get('refs',[]),*r['canonical_matches']])
    for entry in registrations():
        r=row(entry['path']);r['registrations'].append(entry)
        haystacks[r['path']].extend(str(entry.get(k) or '') for k in ('project_id','project_name','role','branch'))
    for h in histories:
        r=row(h['source']);receipt=json.loads(h['receipt']) if h['receipt'] else {}
        r['history'].append({'job':h['job_id'],'input_source':h['source'],'destination':h['destination'],'status':h['status'],
                             'verified':h['status']=='completed' and receipt.get('restored_and_fsck_verified',False) and
                                 receipt.get('job')==h['job_id'] and receipt.get('source')==h['source'] and receipt.get('destination')==h['destination'],
                             'verified_at':receipt.get('verified_at'),'sha256':receipt.get('sha256'),
                             'head_state':receipt.get('head_state'),
                             'source_ref_warnings':receipt.get('source_ref_warnings',[]),
                             'scope':'Git history only; excludes working files and reflog-only objects'})
        haystacks[r['path']].append(h['destination'])
        haystacks[r['path']].extend(name+' '+sha for name,sha in receipt.get('refs',{}).items())
        haystacks[r['path']].append(str(receipt.get('head_state',{}).get('symbolic_ref') or ''))
    for m in manifests:
        r=row(m['source']);result=json.loads(m['result']) if m['result'] else {}
        r['manifests'].append({'job':m['job_id'],'input_source':m['source'],'status':m['status'],
                               'verified':m['status']=='completed' and result.get('job')==m['job_id'] and result.get('source')==m['source'],
                               'verified_at':result.get('verified_at'),
                               'files':result.get('files'),'sha256':result.get('sha256'),
                               'named_stream_scope':named_stream_scope(result),
                               'independent_copy_verified':result.get('archive_copy_verified',False)})
        haystacks[r['path']].append(m['source'])
    for source,items in relocations.items():
        r=row(source);r['relocations'].extend(items)
        haystacks[r['path']].extend(i['destination'] for i in items)
    from .snapshots import catalog as full_file_snapshots
    for snapshot in full_file_snapshots(store):
        receipt=snapshot['receipt'] or {}
        stream_data=receipt.get('scope')=='full-visible-windows-file-payloads-named-stream-data-and-native-inventory'
        inert_links=receipt.get('scope')=='full-visible-windows-file-payloads-inert-link-records-and-native-inventory'
        native_links=receipt.get('scope')=='full-visible-windows-file-payloads-wsl-file-links-and-native-inventory'
        native_files=receipt.get('scope') in ('full-visible-windows-file-payloads-and-native-inventory','full-visible-windows-file-payloads-wsl-file-links-and-native-inventory','full-visible-windows-file-payloads-inert-link-records-and-native-inventory','full-visible-windows-file-payloads-named-stream-data-and-native-inventory')
        native_verified=(native_files and (not stream_data or (receipt.get('named_streams_as_data') is True and receipt.get('native_stream_activation_verified') is False and type(receipt.get('named_stream_payloads')) is int and receipt['named_stream_payloads']>=0 and type(receipt.get('named_stream_bytes')) is int and receipt['named_stream_bytes']>=0)) and (not inert_links or (receipt.get('links_materialized') is False and receipt.get('link_security_metadata_captured') is False and type(receipt.get('link_records')) is int and receipt['link_records']>=0)) and (not native_links or receipt.get('link_security_metadata_captured') is False) and receipt.get('native_metadata_activation_verified') is False and receipt.get('sacl_captured') is False and receipt.get('source_retained') is True and receipt.get('retirement_authorized') is False)
        verified=(snapshot['status']=='completed' and receipt.get('restored_and_verified') is True
                  and (receipt.get('scope')=='full-visible-posix-trees' or native_verified) and receipt.get('job')==snapshot['id']
                  and receipt.get('sources')==snapshot['sources'] and receipt.get('destination')==snapshot['destination'])
        for source in snapshot['sources']:
            r=row(source);r['snapshots'].append({'job':snapshot['id'],'status':snapshot['status'],'verified':verified,
                                               'destination':snapshot['destination'],'verified_at':receipt.get('verified_at'),
                                               'native_metadata_activation_verified':receipt.get('native_metadata_activation_verified'),
                                               'scope':('Windows file payloads and named stream bytes as sealed data; native stream and owner/ACL activation not verified; source retained' if stream_data else 'Windows file payloads and inert raw link/WSL EA records; links not materialized; external dependencies and native owner/ACL activation unverified; source retained' if inert_links else 'Windows file payloads, relative WSL file links and raw records; native link security and owner/ACL activation not verified; source retained' if native_links else 'Windows file payloads and recorded native inventory; native owner/ACL activation not verified; source retained' if native_files else 'Full visible POSIX trees; source retained; external dependencies need review')})
            haystacks[r['path']].append(snapshot['destination'])
    for c in candidates:
        if c['status'] not in ('review','queued'):continue
        source=c['source']
        if c['kind']=='move':
            parents=[path for path in rows if source.startswith(path+'/')]
            if not parents:continue  # Installer/media moves are not workspace sources.
            source=max(parents,key=len)
        r=row(source);r['reviews'].append({'id':c['id'],'kind':c['kind'],'status':c['status'],'job_status':c['job_status'],
                                         'source':c['source'],'destination':c['destination'],'reason':c['reason']})
    counts=Counter();matched=[]
    # Native drive paths work in search as well as their WSL equivalents.
    query=re.sub(r'(?i)\b([deh]):[\\/]',lambda m:'/mnt/'+m[1].lower()+'/',query).replace('\\','/')
    terms=query.casefold().split()
    for path,r in rows.items():
        parts=Path(path).parts[:-1]
        r['constraint']=('Primary workspace; registry roles are explicit, filesystem status is not refreshed here' if r['scope']=='primary' else
                         'Dependency cache/template; role needs assessment' if any(p in ('.cargo','.cookiecutters','node_modules','.cache') for p in parts) else
                         'Preserve enclosing archive/backup group; coordinated assessment required' if any(p.casefold() in ('archive','.archive','_archive','backup','backups','.backups') or p.casefold().endswith('.archive') for p in parts) else
                         'Working role and external dependencies require assessment')
        flags={'history':any(h['verified'] for h in r['history']),'manifest':any(m['verified'] for m in r['manifests']),
               'snapshot':any(s['verified'] for s in r['snapshots']),
               'archived':any(a['recorded_verification'] for a in r['relocations']),'review':any(c['status']=='review' for c in r['reviews'])}
        flags['unassessed']=not any(flags[k] for k in ('history','manifest','snapshot','archived'))
        r['evidence']=flags
        counts.update(k for k,v in flags.items() if v)
        if root!='all' and r['scope']!=root:continue
        if coverage!='all' and not flags[coverage]:continue
        haystack='\n'.join(haystacks[path]).casefold()
        if not all(term in haystack for term in terms):continue
        matched.append(r)
    matched.sort(key=lambda r:r['path'].casefold())
    return {'total_known':len(rows),'total_matched':len(matched),'offset':offset,'limit':limit,'items':matched[offset:offset+limit],
            'evidence_counts':dict(counts),'discovery_scopes':discovery_scopes,'retirement_authorized':False,
            'limitations':['Discovery and Git status observations are dated and depth-limited, not a fresh filesystem audit.',
                           'A full-file manifest is not an independent backup. A history safeguard omits working files.',
                           'Matching names, identities or commits do not prove redundant files or authorize retirement.']}
