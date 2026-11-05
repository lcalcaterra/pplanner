// Complete saved-data backup and restore. No external service or dependency.
const settingsMenu=$('#settings-menu'),importDialog=$('#import-dialog');
let importBackup=null,importBusy=false,importDone=false,fileReadTicket=0;
function backupPending() {
  return mutationBusy||pendingCreates||taskSavePromise||discussionBusy||taskDeleting||taskAttachmentBusy||commentImageUploads;
}
function updateImportButton() {
  $('#import-submit').disabled=importBusy||!importBackup||!$('#import-confirm').checked;
}
function closeImportDialog() {
  if(importBusy)return;
  if(importDone){location.reload();return;}
  ++fileReadTicket;importDialog.close();
}
$('#import-close').onclick=closeImportDialog;
$('#import-cancel').onclick=closeImportDialog;
importDialog.addEventListener('cancel',event=>{event.preventDefault();closeImportDialog();});
$('#import-confirm').onchange=updateImportButton;
$('#import-data').onclick=()=>{
  if(backupPending()){$('#backup-status').textContent='Wait for the current save to finish.';return;}
  settingsMenu.open=false;importBackup=null;importDone=false;++fileReadTicket;
  $('#import-form').reset();$('#import-file-info').textContent='';$('#import-status').textContent='';
  $('#import-submit').hidden=false;$('#import-submit').textContent='Replace data';$('#import-cancel').textContent='Cancel';
  updateImportButton();importDialog.showModal();
};
async function readImportFile(file) {
  if(importBusy||importDone)return;
  const ticket=++fileReadTicket;
  importBackup=null;$('#import-confirm').checked=false;updateImportButton();
  $('#import-status').textContent='';$('#import-file-info').textContent='';
  if(!file)return;
  try {
    if(!file.size||file.size>256*1024*1024)throw Error('Choose a nonempty backup file up to 256 MB.');
    const backup=JSON.parse(await file.text());
    if(ticket!==fileReadTicket)return;
    if(backup?.format!=='pplanner-backup'||backup.version!==1||!backup.tables)throw Error('Choose a supported Pplanner export file.');
    const tables=backup.tables;
    if(!['notes','projects','project_tasks','comments','project_comments'].every(name=>Array.isArray(tables[name])))throw Error('The backup is incomplete.');
    importBackup=backup;
    $('#import-file-info').textContent=file.name+' ? '+tables.projects.length+' projects, '+tables.project_tasks.length+' tasks/subtasks, '+tables.notes.length+' notes. The server will validate all records before replacement.';
  } catch(error) {
    if(ticket===fileReadTicket)$('#import-status').textContent=error instanceof SyntaxError?'This file is not a valid Pplanner backup.':error.message;
  }
  if(ticket===fileReadTicket)updateImportButton();
}
$('#import-file').onchange=()=>readImportFile($('#import-file').files[0]);
const dropzone=$('#import-dropzone');
dropzone.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();$('#import-file').click();}};
for(const name of ['dragenter','dragover'])dropzone.addEventListener(name,event=>{
  event.preventDefault();if(!importBusy)dropzone.classList.add('drag-over');
});
dropzone.addEventListener('dragleave',()=>dropzone.classList.remove('drag-over'));
dropzone.addEventListener('drop',event=>{
  event.preventDefault();dropzone.classList.remove('drag-over');
  if(event.dataTransfer.files.length!==1){importBackup=null;$('#import-confirm').checked=false;updateImportButton();$('#import-status').textContent='Drop one backup file at a time.';return;}
  readImportFile(event.dataTransfer.files[0]);
});
$('#import-form').onsubmit=async event=>{
  event.preventDefault();
  if(importBusy||!importBackup||!$('#import-confirm').checked)return;
  if(backupPending()){$('#import-status').textContent='Wait for the current save to finish, then retry.';return;}
  importBusy=true;updateImportButton();
  $('#import-status').textContent='Validating and importing?';
  $('#import-file').disabled=true;$('#import-confirm').disabled=true;$('#import-close').disabled=true;$('#import-cancel').disabled=true;
  try {
    const result=await request('/api/data/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm_replace:true,backup:importBackup})});
    importDone=true;
    $('#import-status').textContent='Import complete. Recovery backup: '+result.recovery_backup+' (in the backups folder beside your database). Reload to open your restored planner.';
    $('#import-submit').hidden=true;$('#import-cancel').textContent='Open restored planner';
  } catch(error) {$('#import-status').textContent='Could not complete the import request. '+error.message+' If the connection was interrupted, reload to check the result before retrying.';}
  finally {
    importBusy=false;$('#import-file').disabled=importDone;$('#import-confirm').disabled=importDone;
    $('#import-close').disabled=false;$('#import-cancel').disabled=false;updateImportButton();
  }
};
$('#export-data').onclick=async()=>{
  if(backupPending()){$('#backup-status').textContent='Wait for the current save to finish.';return;}
  const button=$('#export-data');button.disabled=true;
  $('#backup-status').textContent='Preparing export?';
  try {
    const response=await fetch('/api/data/export',{cache:'no-store'});
    if(!response.ok){const error=await response.json();throw Error(error.error||'Export failed.');}
    const blob=await response.blob(),url=URL.createObjectURL(blob);
    const link=document.createElement('a');link.href=url;
    link.download='pplanner-'+new Date().toISOString().replace(/[:.]/g,'-')+'.pplanner';
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
    $('#backup-status').textContent='';settingsMenu.open=false;
  } catch(error) {$('#backup-status').textContent='Could not export. '+error.message;}
  finally {button.disabled=false;}
};
document.addEventListener('pointerdown',event=>{if(!settingsMenu.contains(event.target))settingsMenu.open=false;});
settingsMenu.addEventListener('keydown',event=>{if(event.key==='Escape'){settingsMenu.open=false;$('summary',settingsMenu).focus();}});
