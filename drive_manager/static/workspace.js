'use strict';
let archives=[], token='', polling=false;
const find=id=>document.getElementById(id);
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function archiveSourceMatches(path,query){return path.toLowerCase().includes(query)||knownRelocations.some(r=>r.kind==='workspace_archive'&&r.source.toLowerCase()===query&&r.destination===path);}
function render(){const query=find('archive-search').value.toLowerCase();const visible=archives.filter(a=>JSON.stringify([a.source,a.destination,a.receipt?.refs,a.receipt?.head_state]).toLowerCase().includes(query)||archiveSourceMatches(a.source,query));find('archive-summary').textContent=`${visible.length} of ${archives.length} snapshots · ${archives.filter(a=>a.status==='completed'&&a.receipt?.restored_and_fsck_verified).length} verified · originals retained`;find('archive-results').replaceChildren();for(const a of visible){const card=node('article',undefined,'review-card');const body=node('div');body.append(node('h3',a.status==='completed'?(a.receipt?.source_ref_warnings?.length?'Verified readable Git history · source warnings':'Verified Git history'):a.status),node('div','FROM '+a.source,'path'),node('div','ARCHIVE '+a.destination,'path'),node('p',a.message||'Waiting for archive worker'));if(a.receipt){if(a.receipt.source_ref_warnings?.length)body.append(node('p','Source Git warnings recorded; readable tips verified. Original ref metadata was not repaired.'),node('pre',a.receipt.source_ref_warnings.join('\n'),'archive-refs'));body.append(node('p',`${Object.keys(a.receipt.refs).length} ${['unborn','unresolved'].includes(a.receipt.head_state?.kind)?'named refs · unresolved default HEAD ('+a.receipt.head_state.symbolic_ref+')':'refs including HEAD'} · ${(a.receipt.bytes/1024/1024).toFixed(1)} MiB · ${new Date(a.receipt.verified_at*1000).toLocaleString()}`),node('div','SHA-256 '+a.receipt.sha256,'path'));const details=node('details');details.append(node('summary','Preserved branches, tags, and refs'));const listing=node('pre',Object.entries(a.receipt.refs).map(([name,sha])=>name+'  '+sha).join('\n'),'archive-refs');details.append(listing);body.append(details);}card.append(body);find('archive-results').append(card);}if(!visible.length)find('archive-results').append(node('p','No matching snapshots yet.'));}
async function refresh(){if(polling)return;polling=true;try{const response=await fetch('/api/workspace/catalog');if(!response.ok)throw Error('Could not load archive catalog');archives=await response.json();render();}catch(e){find('archive-summary').textContent=e.message;}finally{polling=false;}}
find('archive-search').addEventListener('input',render);
find('history-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const button=form.querySelector('button');button.disabled=true;const notice=find('archive-notice');try{if(!token){const state=await fetch('/api/session');token=(await state.json()).token;}const response=await fetch('/api/workspace/history',{method:'POST',headers:{'Content-Type':'application/json','X-Drive-Token':token},body:JSON.stringify({source:form.elements.source.value})});const result=await response.json();if(!response.ok){token='';throw Error(result.error);}notice.textContent='History snapshot queued. Original working files stay in place.';notice.hidden=false;await refresh();}catch(e){notice.textContent=e.message;notice.hidden=false;}finally{button.disabled=false;}});
refresh();setInterval(refresh,4000);

let manifests=[], activeManifest='', fileGeneration=0, fileTimer;
function renderManifests(){const query=find('archive-search').value.toLowerCase();find('manifest-results').replaceChildren();for(const m of manifests.filter(m=>archiveSourceMatches(m.source,query))){const card=node('article',undefined,'review-card');const body=node('div');body.append(node('h3',m.status==='completed'&&m.result?'Verified file manifest':m.status),node('div',m.source,'path'),node('p',m.message||'Waiting for manifest worker'));if(m.result)body.append(node('p',`${m.result.files} files · ${(m.result.bytes/1024/1024).toFixed(1)} MiB · ${m.result.named_streams} named streams · ${m.result.named_stream_scope||(m.result.native_metadata===true?'legacy file-stream capture':m.result.native_metadata===false?'POSIX xattrs/links':'unrecorded capture scope')}`),node('div','Manifest SHA-256 '+m.result.sha256,'path'));const browse=node('button','Browse files');browse.type='button';browse.addEventListener('click',()=>{activeManifest=m.job_id;find('file-browser').hidden=false;find('file-source').textContent=m.source;find('file-search').value='';loadFiles();find('file-browser').scrollIntoView({block:'start'});});body.append(browse);if(m.result&&m.status==='completed'&&m.source.startsWith('/mnt/')&&!m.source.includes('/archive/')&&!knownRelocations.some(r=>r.source===m.source&&['review','queued','completed'].includes(r.status))){const archive=node('button','Review archival relocation');archive.type='button';archive.addEventListener('click',async()=>{try{await archivePost('archive',{manifest:m.job_id});find('archive-notice').textContent='Concrete archival proposal added to the Drive Manager checkbox review inbox. No move has been approved.';find('archive-notice').hidden=false;await refreshRelocations();}catch(e){find('archive-notice').textContent=e.message;find('archive-notice').hidden=false;}});body.append(archive);}card.append(body);find('manifest-results').append(card);}}
async function loadFiles(){const generation=++fileGeneration;try{const response=await fetch('/api/workspace/manifest/files?id='+encodeURIComponent(activeManifest)+'&q='+encodeURIComponent(find('file-search').value));const data=await response.json();if(!response.ok)throw Error(data.error);if(generation!==fileGeneration)return;find('file-status').textContent=`${data.items.length} entries shown (limit 100) · ${data.complete?'Verified manifest':'Incomplete manifest; preservation work remains'}`;find('file-results').replaceChildren();for(const f of data.items){const card=node('div',undefined,'panel');card.append(node('div',f.path,'path'),node('p',`${f.kind} · ${f.size} bytes · ${f.streams.length} named streams`));if(f.sha256)card.append(node('div',f.sha256,'path'));find('file-results').append(card);}}catch(e){find('file-status').textContent=e.message;}}
find('file-search').addEventListener('input',()=>{clearTimeout(fileTimer);fileTimer=setTimeout(loadFiles,250);});
find('archive-search').addEventListener('input',renderManifests);
async function refreshManifests(){try{const response=await fetch('/api/workspace/manifests');if(!response.ok)return;manifests=await response.json();renderManifests();renderComparisonChoices();renderSnapshotChoices();}catch(e){/* The main catalog retains its connection status. */}}
find('manifest-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const button=form.querySelector('button');button.disabled=true;try{const state=await fetch('/api/session');token=(await state.json()).token;const response=await fetch('/api/workspace/manifest',{method:'POST',headers:{'Content-Type':'application/json','X-Drive-Token':token},body:JSON.stringify({source:form.elements.source.value})});const data=await response.json();if(!response.ok)throw Error(data.error);find('archive-notice').textContent='Full file manifest queued. Original files remain in place.';find('archive-notice').hidden=false;await refreshManifests();}catch(e){find('archive-notice').textContent=e.message;find('archive-notice').hidden=false;}finally{button.disabled=false;}});
refreshManifests();setInterval(refreshManifests,4000);
let comparisonBusy=false,comparisonChoiceSignature='';
const comparisonOpen=new Set();
function renderComparisonChoices(){
  const complete=manifests.filter(m=>m.status==='completed'&&m.result);
  const signature=JSON.stringify(complete.map(m=>[m.job_id,m.source,m.result.sha256,m.result.named_stream_scope,m.result.native_metadata,m.result.verified_at]));
  if(signature!==comparisonChoiceSignature){
  for(const id of ['comparison-left','comparison-right']){
    const select=find(id),value=select.value;select.replaceChildren();
    const placeholder=node('option','Choose a completed manifest');placeholder.value='';select.append(placeholder);
    for(const m of complete){const scope=m.result.named_stream_scope||(m.result.native_metadata===true?'legacy file streams':m.result.native_metadata===false?'POSIX xattrs/links':'unrecorded scope');const option=node('option',m.source+' · '+evidenceDate(m.result.verified_at)+' · '+scope);option.value=m.job_id;option.title=m.job_id;select.append(option);}
    if(complete.some(m=>m.job_id===value))select.value=value;
  }
  comparisonChoiceSignature=signature;
  }
  find('comparison-submit').disabled=comparisonBusy||complete.length<2;
}
function preserveComparisonDisclosure(details,key){
  details.open=comparisonOpen.has(key);
  details.addEventListener('toggle',()=>{if(details.open)comparisonOpen.add(key);else comparisonOpen.delete(key);});
}
async function refreshComparisons(){
  try{
    const response=await fetch('/api/workspace/comparisons');if(!response.ok)return;
    const comparisons=await response.json();find('comparison-results').replaceChildren();
    for(const c of comparisons){
      const full=c.comparison_kind==='full-tree'||c.scope?.startsWith('Full recorded trees'),card=node('article',undefined,'panel');
      card.append(node('h3',full?'Full-tree comparison':'Working-file comparison'),node('div',c.left+' ↔ '+c.right,'path'),node('p',c.scope));
      card.append(node('p',`${c.counts.same_payload} same recorded payloads · ${c.counts.different_payload} different · ${c.counts.only_left} only in the first tree · ${c.counts.only_right} only in the second · ${c.counts.different_kind} type changes`));
      if(full){
        card.append(node('p',`${c.counts.same_directory} matching directories · ${c.counts.same_recorded_metadata} matching recorded metadata entries · ${c.counts.different_recorded_metadata} recorded metadata differences`));
        if(typeof c.all_recorded_payloads_equal==='boolean')card.append(node('p',(c.all_recorded_payloads_equal?'All recorded payloads and membership match. ':'Recorded payloads or membership differ. ')+(c.compared_metadata_equal?'Compared metadata fields match.':'Compared metadata differs or its formats are incompatible.')));
        if(c.directory_stream_capture_complete===false)card.append(node('p','Some inputs lack verified directory-stream capture coverage. Build fresh manifests before a complete NTFS retention comparison.'));
        if(c.manifest_digests_verified)card.append(node('p','Both manifest database digests verified against their completed receipts.'));
      }else card.append(node('p','Git internals and directories are excluded. This is not a complete snapshot comparison.'));
      card.append(node('p','Recorded points in time only. Dependency closure, independent recovery and unrecorded metadata remain outside proof. No retirement authorized.'));
      const differences=node('details');differences.append(node('summary','Recorded differences (bounded samples)'));
      for(const key of ['different_payload','only_left','only_right','different_kind','different_recorded_metadata']){
        const paths=c.samples?.[key]||[];if(paths.length)differences.append(node('h3',key.replaceAll('_',' ')),node('pre',paths.join('\n'),'archive-refs'));
      }
      preserveComparisonDisclosure(differences,c.checked_at+':differences');card.append(differences);
      const scope=node('details');scope.append(node('summary','Manifest IDs and comparison limits'),node('div',c.left_manifest+' ↔ '+c.right_manifest,'path'));
      for(const limit of c.limitations||[])scope.append(node('p',limit));
      preserveComparisonDisclosure(scope,c.checked_at+':limits');card.append(scope);
      find('comparison-results').append(card);
    }
    if(!comparisons.length)find('comparison-results').append(node('p','Comparisons appear after two full manifests have been verified and compared.'));
  }catch(e){/* Preserve the last evidence view during transient connection failures. */}
}
find('comparison-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget;comparisonBusy=true;renderComparisonChoices();
  try{
    if(form.elements.left.value===form.elements.right.value)throw Error('Choose two different manifests');
    await archivePost('compare',{left:form.elements.left.value,right:form.elements.right.value,scope:form.elements.scope.value});
    restorationNotice('Snapshot comparison recorded. No move or deletion has been approved.');await refreshComparisons();
  }catch(e){restorationNotice(e.message);}finally{comparisonBusy=false;renderComparisonChoices();}
});
refreshComparisons();setInterval(refreshComparisons,15000);
async function archivePost(action,data){const session=await fetch('/api/session');const fresh=await session.json();const response=await fetch('/api/workspace/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Drive-Token':fresh.token},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(result.error);return result;}
let knownRelocations=[];
const restoreSelections=new Map();
function restorationNotice(text){find('archive-notice').textContent=text;find('archive-notice').hidden=false;}
function restorationControls(card,r){
  const restore=node('button','Restore original physical location');restore.type='button';
  restore.addEventListener('click',async()=>{restore.disabled=true;try{await archivePost('restore',{id:r.job_id});restorationNotice('Restoration queued; archive integrity will be checked before restoring the physical folder.');}catch(e){restorationNotice(e.message);}finally{restore.disabled=false;}});
  card.append(restore);
  const details=node('details');details.append(node('summary','Restore an archive that has newer work'));
  details.append(node('p','Build a fresh manifest of the complete current archived tree, then prepare a checkbox review. Newer files and Git refs stay in the tree. Cancel any held restoration job before preparing a replacement.'));
  const build=node('button','Build fresh restoration manifest');build.type='button';
  build.addEventListener('click',async()=>{build.disabled=true;try{await archivePost('manifest',{source:r.destination});restorationNotice('Fresh restoration manifest queued for '+r.destination+'. This does not approve a move.');}catch(e){restorationNotice(e.message);}finally{build.disabled=false;}});
  details.append(build);
  const choices=manifests.filter(m=>m.source===r.destination&&m.status==='completed'&&m.result);
  if(choices.length){
    const form=node('form'),label=node('label','Fresh manifest of this archived tree'),select=node('select');
    select.setAttribute('aria-label','Restore manifest for '+r.source);select.required=true;
    for(const m of choices){const option=node('option',m.job_id+' · '+m.result.files+' files');option.value=m.job_id;select.append(option);}
    if(choices.some(m=>m.job_id===restoreSelections.get(r.job_id)))select.value=restoreSelections.get(r.job_id);
    select.addEventListener('change',()=>restoreSelections.set(r.job_id,select.value));
    label.append(select);const submit=node('button','Review restoration with fresh manifest');form.append(label,submit);
    form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{await archivePost('restore/review',{id:r.job_id,manifest:select.value});restorationNotice('Fresh-baseline restoration is ready in the Drive Manager checkbox inbox. No move has been approved.');await refreshRelocations();}catch(e){restorationNotice(e.message);}finally{submit.disabled=false;}});
    details.append(form);
  }
  // Keep this disclosure open through catalog refreshes while the user works.
  details.open=restoreSelections.has('open:'+r.job_id);
  details.addEventListener('toggle',()=>{if(details.open)restoreSelections.set('open:'+r.job_id,true);else restoreSelections.delete('open:'+r.job_id);});
  card.append(details);
}
async function refreshRelocations(){
  try{
    const response=await fetch('/api/workspace/relocations');if(!response.ok)return;
    const rows=await response.json();knownRelocations=rows;renderManifests();find('relocation-results').replaceChildren();
    for(const r of rows){
      const card=node('article',undefined,'panel');
      const heading=r.kind==='workspace_restore_review'?(r.job_status||r.status)+' · reviewed restoration':r.receipt?.phase||r.job_status||r.status;
      card.append(node('h3',heading),node('div',r.source+' → '+r.destination,'path'),node('p',r.reason),node('p',r.message||'Awaiting checkbox approval in Drive Manager'));
      if(r.receipt?.verified_at)card.append(node('p','Verified '+new Date(r.receipt.verified_at*1000).toLocaleString()+' · zero space reclaimed'));
      if(r.kind==='workspace_archive'&&r.receipt?.phase==='archived')restorationControls(card,r);
      find('relocation-results').append(card);
    }
    if(!rows.length)find('relocation-results').append(node('p','Verified archival moves and pending relocation proposals appear here.'));
  }catch(e){/* Keep the existing catalog during transient disconnects. */}
}
refreshRelocations();setInterval(refreshRelocations,4000);
async function refreshRegistry(){try{const response=await fetch('/api/workspace/registry');if(!response.ok)return;const rows=await response.json();find('registry-results').replaceChildren();for(const r of rows){const card=node('article',undefined,'panel');card.append(node('h3',r.job_status||r.status),node('div',r.source,'path'),node('p',r.reason));if(r.message)card.append(node('p',r.message));find('registry-results').append(card);}if(!rows.length)find('registry-results').append(node('p','No missing-registration decisions prepared.'));}catch(e){/* Retain existing evidence through transient disconnects. */}}
refreshRegistry();setInterval(refreshRegistry,4000);

let sourceOffset=0,sourceGeneration=0,sourceTimer;
const sourceOpen=new Set();
function evidenceDate(value){if(!value)return 'date unavailable';const date=new Date(typeof value==='number'?value*1000:value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString();}
async function loadSources(){
  const generation=++sourceGeneration;
  find('source-prev').disabled=true;find('source-next').disabled=true;
  const params=new URLSearchParams({q:find('source-query').value,root:find('source-root').value,coverage:find('source-coverage').value,offset:sourceOffset,limit:20});
  try{
    const response=await fetch('/api/workspace/sources?'+params),data=await response.json();
    if(!response.ok)throw Error(data.error||'Could not load workspace sources');
    if(generation!==sourceGeneration)return;
    if(data.total_matched&&data.offset>=data.total_matched){sourceOffset=0;loadSources();return;}
    const start=data.items.length?data.offset+1:0,end=data.items.length?data.offset+data.items.length:0;
    find('source-summary').textContent=`Showing ${start}–${end} of ${data.total_matched} matches · ${data.total_known} known source paths`;
    find('source-coverage-summary').textContent=`All locations: ${data.evidence_counts.archived||0} recorded whole-tree archival moves · ${data.evidence_counts.history||0} sources with history safeguards · ${data.evidence_counts.manifest||0} with full-file manifests · ${data.evidence_counts.unassessed||0} without completed preservation evidence. A manifest is not an independent backup.`;
    find('source-results').replaceChildren();
    for(const r of data.items){
      const card=node('article',undefined,'panel');card.append(node('div',r.path,'path'),node('p',r.constraint));
      const labels=[];
      if(r.evidence.archived)labels.push('Recorded whole-tree archive verification');
      if(r.evidence.history)labels.push('Git history safeguard verified');
      if(r.evidence.snapshot)labels.push('Full-file backup independently restored and verified');
      if(r.evidence.manifest)labels.push('Full-file manifest complete; independent copy not implied');
      if(r.evidence.review)labels.push('Awaiting checkbox decision');
      if(r.evidence.unassessed)labels.push('No completed preservation evidence');
      card.append(node('p',labels.join(' · ')));
      if(r.registrations.length)card.append(node('p',r.registrations.map(e=>`${e.project_name} · registered ${e.status||'status unspecified'} · ${e.role||e.collection}`).join('; ')));
      if(r.canonical_matches.length)card.append(node('div','Dated identity matches: '+r.canonical_matches.join('; '),'path'));
      const details=node('details');details.append(node('summary','Recorded observations and preservation scope'));
      details.open=sourceOpen.has(r.path);details.addEventListener('toggle',()=>{if(details.open)sourceOpen.add(r.path);else sourceOpen.delete(r.path);});
      for(const d of r.discovery)details.append(node('p',`${d.report} discovery · ${evidenceDate(d.observed_at)} · ${d.bare?'bare Git boundary':'working Git boundary'} · ${d.ref_count} recorded refs · ${d.change_count===null?'working changes not established':d.change_count+' recorded status entries'}. This is not a current status check.`));
      for(const h of r.history)details.append(node('div',`${h.status} · ${h.scope} · ${evidenceDate(h.verified_at)} · ${h.destination}${['unborn','unresolved'].includes(h.head_state?.kind)?' · unresolved default HEAD: '+h.head_state.symbolic_ref:''}${h.source_ref_warnings?.length?' · source Git warnings recorded; no repair performed':''}`,'path'));
      for(const s of r.snapshots||[])details.append(node('div',`${s.status} full-file backup · ${evidenceDate(s.verified_at)} · ${s.destination} · ${s.scope}`,'path'));
      for(const m of r.manifests)details.append(node('div',`${m.status} file manifest · ${m.files??'unknown'} files · ${evidenceDate(m.verified_at)} · input ${m.input_source} · ${m.job} · ${m.named_stream_scope}`,'path'));
      for(const a of r.relocations)details.append(node('div',`${a.phase||a.status} archival record · ${evidenceDate(a.verified_at)} · ${a.destination}`,'path'));
      for(const decision of r.reviews){details.append(node('div',decision.status+' '+decision.kind+': '+decision.source+' → '+decision.destination,'path'),node('p',decision.reason));}
      card.append(details);
      if(r.history.length||r.manifests.length){const show=node('button','Show preservation records');show.type='button';show.addEventListener('click',()=>{find('archive-search').value=r.path;find('archive-search').dispatchEvent(new Event('input'));find('archive-search').scrollIntoView({block:'center'});});card.append(show);}
      find('source-results').append(card);
    }
    if(!data.items.length)find('source-results').append(node('p','No matching known sources. Discovery is incomplete; this does not establish that a missing source is lost.'));
    find('source-prev').disabled=data.offset===0;find('source-next').disabled=data.offset+data.items.length>=data.total_matched;
    find('source-limitations').replaceChildren();
    for(const scope of data.discovery_scopes)find('source-limitations').append(node('p',`${scope.name}: ${scope.boundaries} boundaries · depth ${scope.depth} · ${evidenceDate(scope.created)} · ${scope.unexpanded_frontiers} recorded unexpanded frontiers`));
    for(const limit of data.limitations)find('source-limitations').append(node('p',limit));
  }catch(e){if(generation===sourceGeneration)find('source-summary').textContent=e.message;}
}
find('source-form').addEventListener('submit',event=>{event.preventDefault();sourceOffset=0;loadSources();});
find('source-query').addEventListener('input',()=>{clearTimeout(sourceTimer);sourceOffset=0;++sourceGeneration;sourceTimer=setTimeout(loadSources,250);});
for(const id of ['source-root','source-coverage'])find(id).addEventListener('change',()=>{sourceOffset=0;loadSources();});
find('source-prev').addEventListener('click',()=>{sourceOffset=Math.max(0,sourceOffset-20);loadSources();});
find('source-next').addEventListener('click',()=>{sourceOffset+=20;loadSources();});
loadSources();setInterval(loadSources,15000);

let snapshotChoiceSignature='',snapshotBusy=false,snapshotAvailable=false;
function renderSnapshotChoices(){
  const complete=manifests.filter(m=>m.status==='completed'&&m.result?.native_metadata===false);
  const signature=JSON.stringify(complete.map(m=>[m.job_id,m.result.sha256]));
  if(signature!==snapshotChoiceSignature){
    const select=find('snapshot-manifests'),selected=new Set([...select.selectedOptions].map(o=>o.value));select.replaceChildren();
    for(const m of complete){const option=node('option',m.source+' · '+evidenceDate(m.result.verified_at));option.value=m.job_id;option.selected=selected.has(m.job_id);select.append(option);}
    snapshotChoiceSignature=signature;
  }
  find('snapshot-submit').disabled=snapshotBusy||!snapshotAvailable||!complete.length;
}
async function refreshSnapshots(){
  try{
    const response=await fetch('/api/workspace/snapshots');snapshotAvailable=response.ok;
    const coverage=find('source-coverage').querySelector('option[value="snapshot"]');if(coverage)coverage.disabled=!snapshotAvailable;
    renderSnapshotChoices();
    if(!response.ok){find('snapshot-notice').textContent='Full-file backups are preparing. Existing operations continue.';return;}
    if(find('snapshot-notice').textContent==='Full-file backups are preparing. Existing operations continue.')find('snapshot-notice').textContent='';
    const rows=await response.json();
    find('snapshot-results').replaceChildren();
    for(const item of rows){
      const card=node('article',undefined,'panel');card.append(node('h3',item.status==='completed'&&item.receipt?.restored_and_verified?(item.receipt.scope==='full-visible-windows-file-payloads-named-stream-data-and-native-inventory'?'Verified file and named stream payloads · native activation unverified':item.receipt.scope==='full-visible-windows-file-payloads-inert-link-records-and-native-inventory'?'Verified file payloads and inert link records · link activation and dependencies unverified':item.receipt.scope==='full-visible-windows-file-payloads-wsl-file-links-and-native-inventory'?'Verified file payload and WSL link recovery · native activation unverified':item.receipt.scope==='full-visible-windows-file-payloads-and-native-inventory'?'Verified file payload recovery · native metadata retained':'Verified full-file backup'):item.status));
      for(const source of item.sources)card.append(node('div','FROM '+source,'path'));
      card.append(node('div','ARCHIVE '+item.destination,'path'),node('p',item.message||'Waiting for preservation worker'));
      if(item.receipt){card.append(node('p',`${item.receipt.files} files · ${(item.receipt.bytes/1024**3).toFixed(2)} GiB · originals retained`),node('div','SHA-256 '+item.receipt.sha256,'path'));for(const limit of item.receipt.limitations)card.append(node('p',limit));}
      find('snapshot-results').append(card);
    }
    if(!rows.length)find('snapshot-results').append(node('p','No full-file backups recorded yet. File manifests and history safeguards remain separate evidence.'));
  }catch(e){find('snapshot-notice').textContent=e.message;}
}
find('snapshot-form').addEventListener('submit',async event=>{
  event.preventDefault();if(snapshotBusy)return;snapshotBusy=true;renderSnapshotChoices();
  try{
    const form=event.currentTarget;
    const result=await archivePost('snapshot',{manifests:[...find('snapshot-manifests').selectedOptions].map(o=>o.value),archive_root:form.elements.archive_root.value});
    find('snapshot-notice').textContent='Full-file backup queued. All original sources remain in place.';await refreshSnapshots();
  }catch(e){find('snapshot-notice').textContent=e.message;}
  finally{snapshotBusy=false;renderSnapshotChoices();}
});
refreshSnapshots();setInterval(refreshSnapshots,4000);
