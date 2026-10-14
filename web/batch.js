/* Local bulk upload. No files leave the local application. */
let batchFiles=[], batchDetails=new Map(), batchRunning=false, batchCancel=false;
const batchStatuses=new Map();
function suggestedFile(file){
  const path=(file.webkitRelativePath||file.name).replaceAll('\\','/'),parts=path.split('/');
  const stem=parts.pop().replace(/\.pdf$/i,'').replace(/[_-]+/g,' ').trim();
  const parent=parts.join('/');let role='test';
  if(/\b(answer\s*sheet|image\s*sheet|images?|supplements?|stations?|notes?)\b/i.test(stem))role='supplement';
  else if(/\b(answer\s*key|keys?|solutions?|answers?)\b/i.test(stem))role='key';
  const base=stem.replace(/\b(answer\s*sheet|image\s*sheet|answer\s*key|question\s*paper|question\s*sheet|keys?|solutions?|answers?|tests?|exams?|papers?|questions?|images?|supplements?|stations?|notes?)\b/gi,' ').replace(/\s+/g,' ').trim();
  // Keep folders separate: many archives name every paper "test.pdf".
  const group=(parent?parent+(base?' / '+base:''):base||'Unnamed test');
  return {file,path,role,group};
}
function batchDefaults(group){return {division:$('#batch-division').value,eventId:$('#batch-event').value,year:Number($('#batch-year').value),competition:$('#batch-competition').value.trim()||group,sourceUrl:$('#batch-source').value.trim()};}
function batchEventOptions(division,selected){return (events[division]||[]).map(e=>`<option value="${esc(e.id)}" ${e.id===selected?'selected':''}>${esc(e.name)}</option>`).join('');}
function populateBatchEvents(){const previous=$('#batch-event').value;$('#batch-event').innerHTML=batchEventOptions($('#batch-division').value,previous);}
function packetGroups(){const groups=new Map();for(const item of batchFiles){if(item.role==='skip')continue;const name=item.group.trim();if(!groups.has(name))groups.set(name,[]);groups.get(name).push(item);}return groups;}
function packetIssues(name,files){const issues=[];if(!name)issues.push('Enter a group name.');const tests=files.filter(f=>f.role==='test').length,keys=files.filter(f=>f.role==='key').length;if(tests!==1)issues.push(`Needs exactly one test PDF (has ${tests}).`);if(keys>1)issues.push('More than one answer key: separate the packets or exclude a duplicate.');if(files.reduce((n,f)=>n+f.file.size,0)>100*1024*1024)issues.push('Over 100 MB: use the inbox for this packet.');const m=batchDetails.get(name);if(m){if(!m.competition.trim()||!m.eventId||!m.sourceUrl.startsWith('https://'))issues.push('Complete the competition, event and HTTPS source link.');if(!Number.isInteger(m.year)||m.year<1984||m.year>2027)issues.push('Choose a valid competition year.');}return issues;}
function addBatchFiles(files){if(batchRunning)return;let ignored=0,duplicates=0;const known=new Set(batchFiles.map(f=>[f.path,f.file.size,f.file.lastModified].join('|')));for(const file of files){if(!/\.pdf$/i.test(file.name)){ignored++;continue;}const item=suggestedFile(file),identity=[item.path,file.size,file.lastModified].join('|');if(known.has(identity)){duplicates++;continue;}known.add(identity);const existingGroup=batchFiles.find(f=>f.group.toLowerCase()===item.group.toLowerCase())?.group;if(existingGroup)item.group=existingGroup;batchStatuses.delete(item.group);batchFiles.push(item);}$('#batch-confirm').checked=false;renderBatchFiles();renderBatchGroups();toast(`${files.length-ignored-duplicates} PDFs added${ignored?`; ${ignored} non-PDF files ignored`:''}${duplicates?`; ${duplicates} duplicate selections skipped`:''}. Check their pairings below.`);}
function renderBatchFiles(){
 $('#batch-workspace').classList.toggle('hidden',!batchFiles.length);$('#batch-count').textContent=`${batchFiles.length} PDF files selected`;
 $('#batch-file-list').innerHTML=batchFiles.map((item,i)=>`<div class="batch-file-row"><div class="batch-filename"><b>${esc(item.file.name)}</b><small>${esc(item.path)} · ${(item.file.size/1024/1024).toFixed(1)} MB</small></div><label>Test group<input data-batch-file="${i}" data-edit="group" value="${esc(item.group)}" ${batchRunning?'disabled':''}></label><label>File type<select data-batch-file="${i}" data-edit="role" ${batchRunning?'disabled':''}>${[['test','Test paper'],['key','Answer key'],['supplement','Supporting sheet'],['skip','Exclude file']].map(([v,t])=>`<option value="${v}" ${item.role===v?'selected':''}>${t}</option>`).join('')}</select></label></div>`).join('');
 $('#batch-file-list').querySelectorAll('[data-batch-file]').forEach(el=>el.onchange=()=>{const item=batchFiles[Number(el.dataset.batchFile)];batchStatuses.delete(item.group);item[el.dataset.edit]=el.value;batchStatuses.delete(item.group);$('#batch-confirm').checked=false;renderBatchGroups();});
}
function renderBatchGroups(){
 const groups=packetGroups();let ready=0;
 $('#batch-groups').innerHTML=[...groups].map(([name,files],i)=>{if(!batchDetails.has(name))batchDetails.set(name,batchDefaults(name));const m=batchDetails.get(name),issues=packetIssues(name,files),result=batchStatuses.get(name),done=result?.done;if(!issues.length&&!done)ready++;return `<article class="panel batch-packet" data-packet="${i}"><div class="section-heading"><h3>${esc(name||'Unnamed group')}</h3><span class="tag ${done?'approved':issues.length?'missing_answers':'queued'}">${done?'Uploaded / already queued':issues.length?'Fix pairing':'Ready to upload'}</span></div><p class="muted">${files.length} files · ${(files.reduce((n,f)=>n+f.file.size,0)/1024/1024).toFixed(1)} MB${files.some(f=>f.role==='key')?'':' · No key: answers will be flagged for review'}</p>${issues.length?`<p class="error">${issues.map(esc).join('<br>')}</p>`:''}${result?`<p class="${done?'muted':'error'}">${esc(result.message)}</p>`:''}<div class="form-grid"><label>Competition<input data-packet-field="competition" value="${esc(m.competition)}"></label><label>Year<input data-packet-field="year" type="number" min="1984" max="2027" value="${esc(m.year)}"></label><label>Division<select data-packet-field="division"><option ${m.division==='B'?'selected':''}>B</option><option ${m.division==='C'?'selected':''}>C</option></select></label><label>Event<select data-packet-field="eventId">${batchEventOptions(m.division,m.eventId)}</select></label><label class="wide">Original source link<input data-packet-field="sourceUrl" type="url" value="${esc(m.sourceUrl)}"></label></div></article>`;}).join('');
 $('#batch-groups').querySelectorAll('[data-packet]').forEach(card=>{const name=[...groups.keys()][Number(card.dataset.packet)];card.querySelectorAll('[data-packet-field]').forEach(el=>{el.disabled=batchRunning||!!batchStatuses.get(name)?.done;el.onchange=()=>{const m=batchDetails.get(name),key=el.dataset.packetField;m[key]=key==='year'?Number(el.value):el.value;if(key==='division'&&!(events[m.division]||[]).some(e=>e.id===m.eventId))m.eventId=events[m.division]?.[0]?.id||'';$('#batch-confirm').checked=false;renderBatchGroups();};});});
 $('#batch-submit').textContent=batchRunning?'Uploading…':`Upload ${ready} ready test${ready===1?'':'s'}`;$('#batch-submit').disabled=batchRunning||!ready;
}
async function uploadBatch(){
 if(!$('#batch-confirm').checked){toast('Check the file pairings and details, then tick the confirmation box.');return;}
 const packets=[...packetGroups()].filter(([name,files])=>!packetIssues(name,files).length&&!batchStatuses.get(name)?.done);
 if(!packets.length)return;batchRunning=true;batchCancel=false;let finished=0,added=0,skipped=0,failed=0;
 for(const id of ['batch-files','batch-folder','batch-clear','batch-apply','batch-confirm'])$('#'+id).disabled=true;
 $('#batch-cancel').classList.remove('hidden');$('#batch-progress').max=packets.length;$('#batch-progress').value=0;renderBatchFiles();renderBatchGroups();
 try{for(const [name,items] of packets){if(batchCancel)break;$('#batch-message').textContent=`Uploading ${finished+1} of ${packets.length}: ${name}`;
   try{const files=[];for(const item of items){const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('Could not read '+item.file.name));reader.readAsDataURL(item.file);});files.push({name:item.file.name,role:item.role,data});}
     const result=await api('upload',{metadata:batchDetails.get(name),files,skipExisting:true});batchStatuses.set(name,{done:true,message:result.message,id:result.id});if(result.alreadyExists)skipped++;else added++;
   }catch(e){failed++;batchStatuses.set(name,{done:false,message:e.message});}
   finished++;$('#batch-progress').value=finished;renderBatchGroups();await refresh();
 }}finally{batchRunning=false;for(const id of ['batch-files','batch-folder','batch-clear','batch-apply','batch-confirm'])$('#'+id).disabled=false;$('#batch-cancel').classList.add('hidden');$('#batch-message').textContent=`${batchCancel?'Stopped after the current upload.':'Batch finished.'} ${added} added, ${skipped} already queued, ${failed} failed${finished<packets.length?`, ${packets.length-finished} not uploaded yet`:''}. Corrections and remaining uploads can be retried below.`;renderBatchFiles();renderBatchGroups();}
}
$('#batch-files').onchange=e=>{addBatchFiles([...e.target.files]);e.target.value='';};$('#batch-folder').onchange=e=>{addBatchFiles([...e.target.files]);e.target.value='';};
$('#batch-division').onchange=populateBatchEvents;
$('#batch-apply').onclick=()=>{for(const name of packetGroups().keys())if(!batchStatuses.get(name)?.done)batchDetails.set(name,batchDefaults(name));$('#batch-confirm').checked=false;renderBatchGroups();};
$('#batch-clear').onclick=()=>{if(batchRunning)return;batchFiles=[];batchDetails.clear();batchStatuses.clear();$('#batch-confirm').checked=false;$('#batch-progress').value=0;$('#batch-message').textContent='Nothing uploaded yet.';renderBatchFiles();renderBatchGroups();};
$('#batch-submit').onclick=uploadBatch;$('#batch-cancel').onclick=()=>{batchCancel=true;$('#batch-message').textContent='Finishing the current upload before stopping…';};
for(const name of ['dragenter','dragover'])$('#batch-drop').addEventListener(name,e=>{e.preventDefault();$('#batch-drop').classList.add('drag-over');});
$('#batch-drop').addEventListener('dragleave',()=>$('#batch-drop').classList.remove('drag-over'));
$('#batch-drop').addEventListener('drop',e=>{e.preventDefault();$('#batch-drop').classList.remove('drag-over');addBatchFiles([...e.dataTransfer.files]);});
window.addEventListener('beforeunload',e=>{if(batchRunning){e.preventDefault();e.returnValue='';}});
document.addEventListener('converter-ready',populateBatchEvents);
if(Object.keys(events).length)populateBatchEvents();
