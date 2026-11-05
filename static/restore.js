// Restoration changes only project status, preserving all related records.
let restoreProjectId=null,restoreProjectBusy=false,restoreLoad=0;
$('#restore-projects').onclick=()=>{if(commentImageUploads){$('#backup-status').textContent='Wait for the image upload to finish.';return;}settingsMenu.open=false;location.hash='restore-projects';};
async function loadRestoreProjects() {
  const ticket=++restoreLoad;
  restoreProjectId=null;$('#restore-project-submit').disabled=true;
  $('#restore-status').textContent='Loading completed projects...';
  try {
    const data=await request('/api/projects');
    if(ticket!==restoreLoad)return;
    const completed=data.projects.filter(project=>project.status==='completed');
    const list=$('#restore-project-list');list.replaceChildren();
    for(const project of completed) {
      const row=element('label',undefined,'restore-project-row');
      const radio=element('input');radio.type='radio';radio.name='restore_project';radio.value=String(project.id);
      radio.onchange=()=>{restoreProjectId=project.id;$('#restore-project-submit').disabled=restoreProjectBusy;};
      const swatch=element('span',undefined,'restore-project-color');swatch.style.backgroundColor=project.color;
      const content=element('span',undefined,'restore-project-content');
      content.append(element('strong',project.name));
      if(project.description)content.append(element('span',project.description,'restore-project-description'));
      if(project.tags?.length)content.append(tagChips(project.tags));
      row.append(radio,swatch,content,element('span','Completed','restore-project-badge'));
      list.append(row);
    }
    if(!completed.length)list.append(element('p','No completed projects to restore.','workspace-empty'));
    $('#restore-status').textContent=completed.length?completed.length+' completed project'+(completed.length===1?'':'s')+'. Select one to restore.':'';
  } catch(error) {if(ticket===restoreLoad)$('#restore-status').textContent='Could not load completed projects. '+error.message;}
}
$('#restore-project-form').onsubmit=async event=>{
  event.preventDefault();
  if(restoreProjectBusy||!restoreProjectId)return;
  const id=restoreProjectId;
  const row=document.querySelector('#restore-project-list input[value="'+id+'"]')?.closest('label');
  const name=row?.querySelector('strong')?.textContent||'this project';
  if(!confirm('Restore "'+name+'" as Active?'))return;
  restoreProjectBusy=true;$('#restore-project-submit').disabled=true;
  $('#restore-project-list').querySelectorAll('input').forEach(input=>input.disabled=true);
  $('#restore-status').textContent='Restoring project...';
  try {
    await workspacePost('/api/projects/'+id+'/status',{status:'active'});
    workspace.projectId=id;workspace.taskId=null;workspace.expanded.clear();rememberProject(id);
    $('#restore-status').textContent='Project restored.';
    location.hash='projects';
  } catch(error) {$('#restore-status').textContent='Could not restore project. '+error.message;}
  finally {
    restoreProjectBusy=false;$('#restore-project-submit').disabled=!restoreProjectId;
    $('#restore-project-list').querySelectorAll('input').forEach(input=>input.disabled=false);
  }
};
