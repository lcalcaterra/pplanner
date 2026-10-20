// Projects and timeline share the same persisted task records.
const workspace = {projectId:null, taskId:null, tasks:[], projects:[], projectLoad:0, detailLoad:0, ganttLoad:0, expanded:new Set(), project:null};
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function formPayload(form) { return Object.fromEntries(new FormData(form)); }
async function workspacePost(url,payload) {
  return request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
}
async function formAction(form,callback) {
  const fields = [...form.elements], states=fields.map(field=>field.disabled);
  fields.forEach(field=>field.disabled=true);
  $('#project-status').textContent='Saving...';
  try { await callback(); $('#project-status').textContent='Saved.'; }
  catch(err) { $('#project-status').textContent=err.message; if($('#task-editor-dialog').open)$('#task-editor-status').textContent=err.message; }
  finally { fields.forEach((field,i)=>field.disabled=states[i]); }
}
const projectStatuses=['active','suspended','completed','rejected','closed'];
function populateProjects(select,all) {
  const previous=select.value;
  select.replaceChildren(new Option(all ? 'All projects' : 'Choose a project',''));
  workspace.projects.forEach(project=>select.add(new Option(project.name,String(project.id))));
  select.value=previous;
}
async function refreshProjectList() {
  const data=await request('/api/projects');
  workspace.projects=data.projects;
  populateProjects($('#project-select'),false);
  populateProjects($('#gantt-project-select'),true);
  if (workspace.projectId) $('#project-select').value=String(workspace.projectId);
}

const taskDialog=$('#task-editor-dialog');
let taskEditorTask=null, taskSavedSignature='', taskSaveTimer=null, taskSavePromise=null, taskLoading=false, taskClosing=false, taskComposing=false, taskDeleting=false;
function taskDraft() {
  const form=$('#task-edit-form');
  if(!form) return null;
  const values=formPayload(form);
  values.tags=tagInputValue(values.tags||'');
  return values;
}
function taskDirty() {return taskEditorTask && JSON.stringify(taskDraft())!==taskSavedSignature;}
function scheduleTaskSave() {
  clearTimeout(taskSaveTimer);
  if(!taskEditorTask||taskDeleting)return;
  $('#task-editor-status').textContent=taskDirty()?'Unsaved changes':'Saved';
  taskSaveTimer=setTimeout(()=>flushTaskSave(),600);
}
async function flushTaskSave() {
  if(taskDeleting)return false;
  clearTimeout(taskSaveTimer);
  if(taskSavePromise) {
    const active=taskSavePromise,saved=await active;
    if(!saved)return false;
    if(taskSavePromise===active)taskSavePromise=null;
    return flushTaskSave();
  }
  if(taskComposing)return false;
  if(!taskEditorTask || !taskDirty())return true;
  const form=$('#task-edit-form');
  if(!form.checkValidity() || !form.elements.title.value.trim()) {
    $('#task-editor-status').textContent='Not saved. A title and valid information are required.';
    return false;
  }
  const snapshot=taskDraft(),id=taskEditorTask.id;
  $('#task-editor-status').textContent='Saving...';
  taskSavePromise=(async()=>{
    try {
      const data=await workspacePost('/api/tasks/'+id+'/edit',snapshot);
      taskEditorTask=data.task;
      taskSavedSignature=JSON.stringify(snapshot);
      const index=workspace.tasks.findIndex(task=>task.id===id);
      if(index>=0)workspace.tasks[index]={...workspace.tasks[index],...data.task};
      paintTasks();
      if($('#task-edit-heading'))$('#task-edit-heading').textContent=data.task.title;
      $('#project-comment-context').textContent=(data.task.parent_id?'Subtask: ':'Task: ')+data.task.title;
      $('#task-editor-status').textContent=taskDirty()?'Unsaved changes':'Saved';
      return true;
    } catch(err) {
      $('#task-editor-status').replaceChildren(document.createTextNode('Not saved. '+err.message+' '));
      const retry=element('button','Retry','cancel');retry.type='button';retry.onclick=()=>flushTaskSave();
      $('#task-editor-status').append(retry); return false;
    }
  })();
  const active=taskSavePromise,saved=await active;
  if(taskSavePromise===active)taskSavePromise=null;
  return saved&&taskDirty()?flushTaskSave():saved;
}
function buildTaskEditForm(task) {
  const form=element('form',undefined,'workspace-form stacked');
  form.id='task-edit-form';
  form.innerHTML='<label>Title<input name="title" maxlength="200" required></label><label>Description <span class="optional-label">optional</span><textarea name="description" maxlength="10000"></textarea></label><label>Tags <span class="optional-label">one name:value per line</span><textarea name="tags" maxlength="9000"></textarea></label><label>Phase <span class="optional-label">optional</span><input name="phase" maxlength="120"></label><div class="date-pair"><label>Start<input name="start_date" type="date"></label><label>End<input name="end_date" type="date"></label></div>';
  form.elements.title.value=task.title;
  form.elements.description.value=task.description;
  form.elements.tags.value=(task.tags||[]).join('\n');
  form.elements.phase.value=task.phase_name||'';
  form.elements.start_date.value=task.start_date||'';
  form.elements.end_date.value=task.end_date||'';
  form.addEventListener('input',event=>{if(!event.isComposing)scheduleTaskSave();});
  form.addEventListener('change',scheduleTaskSave);
  form.addEventListener('compositionstart',()=>{taskComposing=true;clearTimeout(taskSaveTimer);});
  form.addEventListener('compositionend',()=>{taskComposing=false;scheduleTaskSave();});
  form.addEventListener('focusout',()=>{if(!taskComposing)flushTaskSave();});
  form.onsubmit=event=>{event.preventDefault();flushTaskSave();};
  return form;
}
async function closeTaskEditor() {
  if(taskLoading||taskClosing||discussionBusy||taskDeleting)return;
  taskClosing=true;
  try {
    const saved=await flushTaskSave();
    if(!saved&&taskDirty()&&!confirm('Discard unsaved task changes?'))return;
    clearTimeout(taskSaveTimer);
    taskDialog.close();
  } finally {taskClosing=false;}
}
$('#task-editor-close').onclick=closeTaskEditor;
taskDialog.addEventListener('cancel',event=>{event.preventDefault();closeTaskEditor();});
taskDialog.addEventListener('close',()=>{
  ++workspace.detailLoad;
  clearTimeout(taskSaveTimer);
  taskEditorTask=null;
  $('#project-discussion-home').append($('.project-discussion'));
  workspace.taskId=null;markTaskSelection();
  setDiscussion(workspace.projectId,null);
});
window.addEventListener('beforeunload',event=>{
  if(taskDialog.open&&(taskDirty()||taskSavePromise)){event.preventDefault();event.returnValue='';}
});


async function deleteTaskRecord(task,button) {
  if(taskDeleting||discussionBusy||taskLoading)return;
  const kind=task.parent_id?'subtask':'task';
  if(!confirm('Delete '+kind+' "'+task.title+'"? Its subtasks, comments and checkpoints will also be deleted. Linked calendar notes are kept. This cannot be undone.'))return;
  taskDeleting=true;workspace.deleting=true;
  clearTimeout(taskSaveTimer);button.disabled=true;
  const fields=[...document.querySelectorAll('#task-edit-form input,#task-edit-form textarea')];
  const readonly=fields.map(field=>field.readOnly);
  fields.forEach(field=>field.readOnly=true);
  $('#task-editor-status').textContent='Deleting...';
  try {
    // Finish any in-flight save before deletion; discard only the confirmed draft.
    if(taskSavePromise)await taskSavePromise;
    clearTimeout(taskSaveTimer);
    await workspacePost('/api/tasks/'+task.id+'/delete',{});
    taskEditorTask=null;
    workspace.expanded.delete(task.id);
    const closed=new Promise(resolve=>taskDialog.addEventListener('close',resolve,{once:true}));
    taskDialog.close();
    await closed;
    await loadProject();
    $('#project-status').textContent=(task.parent_id?'Subtask':'Task')+' deleted. Linked calendar notes were kept.';
  } catch(err) {
    $('#task-editor-status').textContent='Could not delete. '+err.message;
  } finally {
    taskDeleting=false;workspace.deleting=false;button.disabled=false;
    fields.forEach((field,index)=>field.readOnly=readonly[index]);
  }
}
async function deleteProjectRecord(project,button,statusSelect) {
  if(workspace.deleting)return;
  if(discussionBusy||statusSelect.disabled){$('#project-status').textContent='Wait for the current save to finish before deleting.';return;}
  if(!confirm('Delete project "'+project.name+'"? All its tasks, subtasks, phases, comments and checkpoints will be deleted. Linked calendar notes are kept. This cannot be undone.'))return;
  workspace.deleting=true;button.disabled=true;
  const picker=$('#project-select');picker.disabled=true;
  $('#project-status').textContent='Deleting project...';
  try {
    await workspacePost('/api/projects/'+project.id+'/delete',{});
    ++workspace.detailLoad;++workspace.projectLoad;++workspace.ganttLoad;
    if(workspace.projectId===project.id){
      workspace.projectId=null;workspace.taskId=null;workspace.expanded.clear();
    }
    // Drop only deleted discussion drafts, preserving other projects' drafts.
    for(const key of discussionDrafts.keys())if(key.startsWith(project.id+':'))discussionDrafts.delete(key);
    const previousContext=discussionContext;
    if(previousContext?.projectId===project.id){discussionContext=null;$('#project-comment-body').value='';}
    await refreshProjectList();
    if($('#gantt-project-select').value===String(project.id))$('#gantt-project-select').value='';
    await loadProject();
    $('#project-status').textContent='Project deleted. Linked calendar notes were kept.';
  } catch(err) {$('#project-status').textContent='Could not delete project. '+err.message;}
  finally {workspace.deleting=false;button.disabled=false;picker.disabled=false;}
}

function sectionHeading(text) { return element('h3',text); }
async function openTask(id) {
  if(workspace.deleting||taskDeleting)return;
  if(taskDialog.open && !await flushTaskSave())return;
  const ticket=++workspace.detailLoad;
  workspace.taskId=id;
  let ancestor=workspace.tasks.find(task=>task.id===id)?.parent_id;
  while(ancestor) {
    workspace.expanded.add(ancestor);
    const tree=document.querySelector('.task-tree[data-task-id="'+ancestor+'"]');
    if(tree) tree.open=true;
    ancestor=workspace.tasks.find(task=>task.id===ancestor)?.parent_id;
  }
  markTaskSelection();
  $('#task-editor-comments').append($('.project-discussion'));
  if(!taskDialog.open) taskDialog.showModal();
  taskLoading=true;taskEditorTask=null;
  $('#task-editor-status').textContent='Loading...';
  setDiscussion(workspace.projectId,id);
  const detail=$('#task-detail');
  detail.hidden=false;
  detail.replaceChildren(element('p','Loading task...','workspace-empty'));
  try {
    const data=await request('/api/tasks/'+id);
    if(ticket!==workspace.detailLoad) return;
    const task=data.task;
    taskEditorTask=task;taskComposing=false;
    const heading=element('div',undefined,'task-detail-heading');
    const title=element('h2',task.title);
    title.id='task-edit-heading';
    const toggle=element('button',task.completed ? 'Reopen task' : 'Complete task','today-button');
    toggle.type='button';
    toggle.onclick=async()=>{
      toggle.disabled=true;
      try {
        if(!await flushTaskSave()){toggle.disabled=false;return;}
        await workspacePost('/api/tasks/'+id+'/update',{completed:!task.completed});
        await loadProject(); await openTask(id);
      } catch(err) { $('#project-status').textContent=err.message; toggle.disabled=false; }
    };
    const remove=element('button',task.parent_id?'Delete subtask':'Delete task','danger-button');
    remove.id='task-delete';remove.type='button';
    remove.onclick=()=>deleteTaskRecord(task,remove);
    const actions=element('div',undefined,'record-actions');
    actions.append(toggle,remove);
    heading.append(title,actions);
    detail.replaceChildren(heading);
    detail.append(element('p','Changes save automatically as you type.','task-autosave-hint'));
    detail.append(element('p',(task.parent_id?'Subtask':'Task')+' in '+(task.project_name||workspace.project?.name||'this project'),'task-schedule'));
    if(task.parent_id) detail.append(element('p','Related task: '+(workspace.tasks.find(item=>item.id===task.parent_id)?.title||'#'+task.parent_id),'task-schedule'));
    detail.append(tagChips([],task.inherited_tags||[]),buildTaskEditForm(task));
    taskSavedSignature=JSON.stringify(taskDraft());
    $('#task-editor-status').textContent='Saved';
    if(!task.parent_id) {
      const sub=element('section',undefined,'task-section');sub.append(sectionHeading('Subtasks'));
      data.subtasks.forEach(child=>sub.append(taskButton(child)));
      const create=element('details',undefined,'creation-panel');create.append(element('summary','Add subtask'));
      const subForm=element('form',undefined,'workspace-form stacked');
      subForm.innerHTML='<label>Title<input name="title" required maxlength="200"></label><label>Description <span class="optional-label">optional</span><textarea name="description" maxlength="10000"></textarea></label><button class="insert">Create subtask</button>';
      subForm.onsubmit=async event=>{
        event.preventDefault();const payload={...formPayload(subForm),project_id:task.project_id,parent_id:id};
        if(!await flushTaskSave())return;
        const button=$('button',subForm);button.disabled=true;
        try {
          await workspacePost('/api/tasks',payload);
          await loadProject();await openTask(id);
        } catch(err) {$('#task-editor-status').textContent=err.message;button.disabled=false;}
      };
      create.append(subForm);sub.append(create);detail.append(sub);
    }
    const check=element('section',undefined,'task-section');
    check.append(sectionHeading('Checkpoints'));
    data.checkpoints.forEach(item=>{
      const label=element('label',undefined,'checkpoint-row');
      const box=element('input'); box.type='checkbox'; box.checked=Boolean(item.completed);
      box.onchange=async()=>{
        box.disabled=true;
        try { await workspacePost('/api/tasks/'+id+'/checkpoint-update',{checkpoint_id:item.id,completed:box.checked}); }
        catch(err) { box.checked=!box.checked; $('#project-status').textContent=err.message; }
        finally { box.disabled=false; }
      };
      label.append(box,element('span',item.title));
      check.append(label);
    });
    const checkForm=element('form',undefined,'workspace-form');
    checkForm.innerHTML='<label>New checkpoint<input name="title" required maxlength="500" placeholder="A small milestone"></label><button class="insert">Add</button>';
    checkForm.onsubmit=event=>{
      event.preventDefault(); const payload=formPayload(checkForm);
      formAction(checkForm,async()=>{await workspacePost('/api/tasks/'+id+'/checkpoints',payload); await openTask(id);});
    };
    check.append(checkForm);
    const related=element('section',undefined,'task-section');
    related.append(sectionHeading('Related notes'));
    data.notes.forEach(note=>{
      const button=element('button',undefined,'linked-note');
      button.type='button';
      button.append(element('small',note.date),element('span',note.body));
      button.onclick=()=>openEditor(note);
      related.append(button);
    });
    if(!data.notes.length) related.append(element('p','Link a calendar note to keep the context close.','workspace-empty'));
    const link=element('details',undefined,'creation-panel');
    link.append(element('summary','Link a calendar note'));
    const linkForm=element('form',undefined,'workspace-form stacked');
    linkForm.innerHTML='<label>Note date<input name="date" type="date" required></label><button type="button" class="today-button">Find notes</button><label>Note<select name="note_id" required><option value="">Find notes for a date first</option></select></label><button type="submit" class="insert">Link note</button>';
    linkForm.elements.date.value=key(today);
    const choices=linkForm.elements.note_id;
    $('button[type="button"]',linkForm).onclick=async()=>{
      const date=linkForm.elements.date.value;
      if(!date) return;
      try {
        const found=await request('/api/notes?start='+date+'&end='+date);
        if(!linkForm.isConnected) return;
        choices.replaceChildren(new Option(found.notes.length ? 'Choose a note' : 'No notes on this date',''));
        found.notes.forEach(note=>choices.add(new Option(note.body.slice(0,100),String(note.id))));
      } catch(err) { $('#project-status').textContent=err.message; }
    };
    linkForm.elements.date.onchange=()=>choices.replaceChildren(new Option('Find notes for this date',''));
    linkForm.onsubmit=event=>{
      event.preventDefault(); const noteId=Number(choices.value);
      if(!noteId) return;
      formAction(linkForm,async()=>{await workspacePost('/api/tasks/'+id+'/notes',{note_id:noteId}); await openTask(id);});
    };
    link.append(linkForm); related.append(link);
    detail.append(check,related);
  } catch(err) {
    if(ticket===workspace.detailLoad) {detail.replaceChildren(element('p',err.message,'workspace-status'));$('#task-editor-status').textContent=err.message;}
  } finally {if(ticket===workspace.detailLoad)taskLoading=false;}
}
function taskButton(task) {
  const button=element('button',task.title,'task-row');
  button.type='button'; button.onclick=()=>openTask(task.id); return button;
}
function tagChips(tags,inherited=[]) {
  const container=element('div',undefined,'tag-list');
  [...inherited,...tags].forEach(tag=>container.append(element('span',tag,'tag-chip'+(inherited.includes(tag)?' inherited-tag':''))));
  return container;
}
function markTaskSelection() {
  document.querySelectorAll('.task-tree').forEach(tree=>tree.classList.toggle('selected',Number(tree.dataset.taskId)===workspace.taskId));
}
function paintTasks() {
  const list=$('#task-list'), showDone=$('#show-completed-tasks').checked;
  function visible(task,seen=new Set()) {
    if(seen.has(task.id)) return false;
    seen.add(task.id);
    return showDone || !task.completed || workspace.tasks.some(child=>child.parent_id===task.id && visible(child,seen));
  }
  function branch(task) {
    const tree=element('details',undefined,'task-tree'+(task.completed?' task-done':''));
    tree.dataset.taskId=task.id;
    tree.open=workspace.expanded.has(task.id);
    const summary=element('summary');
    const content=element('div',undefined,'task-row-content');
    const titleButton=element('button',task.title,'task-tree-title task-open-button');
    titleButton.type='button';
    titleButton.onclick=event=>{event.preventDefault();event.stopPropagation();openTask(task.id);};
    content.append(titleButton);
    content.append(tagChips(task.tags||[],task.parent_id?[]:task.inherited_tags||[]));
    const expander=element('button','\u203a','task-disclosure');
    expander.type='button';expander.setAttribute('aria-label','Expand or collapse subtasks');
    expander.setAttribute('aria-expanded',String(tree.open));
    expander.onclick=event=>{event.preventDefault();event.stopPropagation();tree.open=!tree.open;};
    summary.append(expander,element('span',task.completed?'\u2713':'\u25cb','task-marker'),content);
    const children=workspace.tasks.filter(child=>child.parent_id===task.id);
    summary.append(element('small',children.length ? children.length+' subtasks' : task.phase_name||'','task-tree-meta'));
    summary.onclick=event=>{
      if(event.target.closest('.task-disclosure,.task-open-button'))return;
      event.preventDefault();openTask(task.id);
    };
    tree.append(summary);
    const body=element('div',undefined,'task-tree-children');
    if(task.description) body.append(element('p',task.description,'task-tree-description'));
    const filtered=children.filter(child=>visible(child));
    filtered.forEach(child=>body.append(branch(child)));
    if(!filtered.length) body.append(element('p','No open subtasks. Use + to add a step.','workspace-empty'));
    tree.append(body);
    tree.addEventListener('toggle',()=>{expander.setAttribute('aria-expanded',String(tree.open));if(tree.open) workspace.expanded.add(task.id);else workspace.expanded.delete(task.id);});
    return tree;
  }
  const roots=workspace.tasks.filter(task=>!task.parent_id && visible(task));
  list.replaceChildren(...roots.map(branch));
  if(!roots.length) list.append(element('p',workspace.projectId?'No open tasks. Use + to add your first task.':'Choose a project to see its tasks.','workspace-empty'));
  markTaskSelection();
}
async function loadProject() {
  const ticket=++workspace.projectLoad;
  ++workspace.detailLoad;
  if(!workspace.projectId) {
    workspace.tasks=[]; workspace.project=null;
    $('#project-overview').replaceChildren(element('p','Choose a project, or use + to create your first one.','workspace-empty'));
    $('#task-detail').hidden=true; paintTasks(); setDiscussion(null,null); return;
  }
  $('#project-status').textContent='Loading project...';
  try {
    const data=await request('/api/projects/'+workspace.projectId);
    if(ticket!==workspace.projectLoad) return;
    workspace.project=data.project; workspace.tasks=data.tasks;
    const overview=$('#project-overview');
    const button=element('button',data.project.name,'project-overview-name'); button.type='button';
    button.onclick=()=>{workspace.taskId=null; $('#task-detail').hidden=true; markTaskSelection(); setDiscussion(workspace.projectId,null);};
    const projectHeader=element('div',undefined,'project-overview-header');
    const statusLabel=element('label','Status','project-status-control');
    const statusSelect=element('select');
    statusSelect.setAttribute('aria-label','Project status');
    projectStatuses.forEach(value=>statusSelect.add(new Option(value[0].toUpperCase()+value.slice(1),value)));
    statusSelect.value=data.project.status||'active';
    statusSelect.className='status-'+statusSelect.value;
    statusLabel.append(statusSelect);
    const projectId=data.project.id;
    statusSelect.onchange=async()=>{
      const previous=workspace.projects.find(project=>project.id===projectId)?.status||data.project.status||'active';
      const value=statusSelect.value;
      statusSelect.disabled=true;
      $('#project-status').textContent='Saving project status...';
      try {
        const saved=await workspacePost('/api/projects/'+projectId+'/status',{status:value});
        const project=workspace.projects.find(item=>item.id===projectId);
        if(project)Object.assign(project,saved.project);
        if(workspace.projectId===projectId) {
          workspace.project=saved.project;
          statusSelect.className='status-'+saved.project.status;
          $('#project-status').textContent='Project status saved.';
        }
      } catch(err) {
        statusSelect.value=previous;
        if(workspace.projectId===projectId)$('#project-status').textContent='Could not save project status. '+err.message;
      } finally {statusSelect.disabled=false;}
    };
    const remove=element('button','Delete project','danger-button');
    remove.id='project-delete';remove.type='button';
    remove.onclick=()=>deleteProjectRecord(data.project,remove,statusSelect);
    const actions=element('div',undefined,'record-actions');
    actions.append(statusLabel,remove);
    projectHeader.append(button,actions);
    overview.replaceChildren(projectHeader);
    if(data.project.description) overview.append(element('p',data.project.description,'task-description'));
    overview.append(tagChips(data.project.tags||[]));
    paintTasks(); $('#project-status').textContent='';
    if(!workspace.taskId) setDiscussion(workspace.projectId,null);
  } catch(err) { if(ticket===workspace.projectLoad) $('#project-status').textContent=err.message; }
}

let creatorKind='project', creatorBusy=false, creatorLoad=0;
const creator=$('#workspace-create-dialog');
function tagInputValue(value) { return value.split('\n').map(tag=>tag.trim()).filter(Boolean); }
function createFields(kind) {
  let markup='';
  if(kind!=='project') markup+='<label>Project<select name="project_id" required></select></label>';
  if(kind==='subtask') markup+='<label>Related task<select name="parent_id" required><option value="">Choose a task</option></select></label>';
  markup+='<label>'+ (kind==='project'?'Project name':kind==='subtask'?'Subtask title':'Task title')+'<input name="'+(kind==='project'?'name':'title')+'" required maxlength="'+(kind==='project'?'120':'200')+'"></label><label>Description <span class="optional-label">optional</span><textarea name="description" maxlength="10000"></textarea></label>';
  if(kind!=='subtask') markup+='<label>Tags <span class="optional-label">optional, one name:value per line</span><textarea name="tags" maxlength="9000" placeholder="priority:high&#10;team:engineering"></textarea></label>';
  if(kind==='project') markup+='<label>Status<select name="status">'+projectStatuses.map(status=>'<option value="'+status+'">'+status[0].toUpperCase()+status.slice(1)+'</option>').join('')+'</select></label>';
  if(kind==='project') markup+='<label>Project color<input name="color" type="color" value="#65518c"></label>';
  if(kind==='task') markup+='<div id="inherited-tag-preview" class="tag-list"></div><label>Phase <span class="optional-label">optional</span><input name="phase" maxlength="120"></label>';
  if(kind!=='project') markup+='<div class="date-pair"><label>Start <span class="optional-label">optional</span><input name="start_date" type="date"></label><label>End <span class="optional-label">optional</span><input name="end_date" type="date"></label></div>';
  return markup;
}
async function fillCreatorContext() {
  const form=$('#workspace-create-form'), projectId=Number(form.elements.project_id?.value);
  const project=workspace.projects.find(p=>p.id===projectId);
  if(creatorKind==='task') {
    const preview=$('#inherited-tag-preview');
    preview.replaceChildren(...(project?[element('span','project:'+project.name,'tag-chip inherited-tag')]:[]));
  }
  if(creatorKind!=='subtask') return;
  const select=form.elements.parent_id, ticket=++creatorLoad;
  select.replaceChildren(new Option('Loading tasks...','')); select.disabled=true;
  if(!projectId) {select.replaceChildren(new Option('Choose a project first',''));return;}
  try {
    const data=await request('/api/projects/'+projectId);
    if(ticket!==creatorLoad || !creator.open) return;
    select.replaceChildren(new Option('Choose a related task',''));
    data.tasks.filter(t=>!t.parent_id).forEach(task=>select.add(new Option(task.title,String(task.id))));
    if(workspace.taskId && data.tasks.some(t=>t.id===workspace.taskId && !t.parent_id)) select.value=String(workspace.taskId);
    if(!select.options.length || select.options.length===1) select.options[0].textContent='Create a task in this project first';
  } catch(err) {$('#workspace-create-status').textContent=err.message;}
  finally { if(ticket===creatorLoad) select.disabled=false; }
}
async function launchCreator(kind) {
  $('#project-add-menu').open=false;
  creatorKind=kind; $('#workspace-create-status').textContent='';
  $('#workspace-create-title').textContent='New '+kind;
  $('#workspace-create-fields').innerHTML=createFields(kind);
  $('#workspace-create-submit').textContent='Create '+kind;
  if(kind!=='project') {
    const select=$('#workspace-create-form').elements.project_id;
    select.add(new Option('Choose a project',''));
    workspace.projects.forEach(project=>select.add(new Option(project.name,String(project.id))));
    select.value=workspace.projectId?String(workspace.projectId):'';
    select.onchange=fillCreatorContext;
  }
  creator.showModal();
  await fillCreatorContext();
  $('input',creator)?.focus();
}
function closeCreator() {
  if(creatorBusy) return;
  const form=$('#workspace-create-form');
  if([...form.querySelectorAll('input:not([type=color]),textarea')].some(input=>input.value.trim()) && !confirm('Discard this creation draft?')) return;
  ++creatorLoad; creator.close();
}
$('#workspace-create-close').onclick=closeCreator;
creator.addEventListener('cancel',event=>{event.preventDefault();closeCreator();});
document.querySelectorAll('[data-create]').forEach(button=>button.onclick=()=>launchCreator(button.dataset.create));
$('#workspace-create-form').onsubmit=async event=>{
  event.preventDefault(); if(creatorBusy) return;
  const form=event.currentTarget,payload=formPayload(form);
  if(payload.tags!==undefined) payload.tags=tagInputValue(payload.tags);
  if(creatorKind!=='project') payload.project_id=Number(payload.project_id);
  if(creatorKind==='subtask') payload.parent_id=Number(payload.parent_id);
  creatorBusy=true; $('#workspace-create-status').textContent='Creating...';
  [...form.elements].forEach(field=>field.disabled=true);
  try {
    const result=await workspacePost(creatorKind==='project'?'/api/projects':'/api/tasks',payload);
    workspace.projectId=result.project?result.project.id:result.task.project_id;
    workspace.taskId=result.task?result.task.id:null;
    if(result.task?.parent_id) workspace.expanded.add(result.task.parent_id);
    creator.close(); ++creatorLoad;
    await refreshProjectList(); await loadProject();
    if(workspace.taskId) await openTask(workspace.taskId);
    $('#project-status').textContent='Created.';
  } catch(err) {$('#workspace-create-status').textContent=err.message;}
  finally {creatorBusy=false; [...form.elements].forEach(field=>field.disabled=false);}
};
$('#project-select').onchange=()=>{
  workspace.projectId=Number($('#project-select').value)||null; workspace.taskId=null;
  workspace.expanded.clear(); $('#task-detail').hidden=true;
  setDiscussion(null,null); loadProject();
};
$('#show-completed-tasks').onchange=paintTasks;

let discussionContext=null, discussionTicket=0, discussionBusy=false;
const discussionDrafts=new Map(), discussionEdits=new Map();
function discussionKey(context) {return context ? context.projectId+':'+(context.taskId||'project') : '';}
function updateDiscussionSend() {
  $('#project-comment-send').disabled=!discussionContext || discussionBusy || !$('#project-comment-body').value.trim();
}
async function setDiscussion(projectId,taskId) {
  if(discussionContext) discussionDrafts.set(discussionKey(discussionContext),$('#project-comment-body').value);
  const ticket=++discussionTicket;
  discussionContext=projectId?{projectId,taskId:taskId||null}:null;
  $('#project-comment-history').replaceChildren();
  $('#project-comment-body').value=discussionDrafts.get(discussionKey(discussionContext))||'';
  $('#project-comment-body').disabled=!projectId;
  $('#project-discussion-root').hidden=!taskId;
  const name=taskId?workspace.tasks.find(task=>task.id===taskId)?.title:workspace.projects.find(project=>project.id===projectId)?.name;
  const kind=taskId?(workspace.tasks.find(task=>task.id===taskId)?.parent_id?'Subtask: ':'Task: '):'Project: ';
  $('#project-comment-context').textContent=projectId?kind+(name||'Loading...'):'Choose a project';
  updateDiscussionSend();
  if(!projectId) {$('#project-comment-status').textContent='';return;}
  $('#project-comment-status').textContent='Loading comments...';
  try {
    const data=await request('/api/projects/'+projectId+'/comments'+(taskId?'?task_id='+taskId:''));
    if(ticket!==discussionTicket) return;
    paintDiscussion(data.comments); $('#project-comment-status').textContent='';
  } catch(err) {if(ticket===discussionTicket) $('#project-comment-status').textContent=err.message;}
}
function paintDiscussion(comments) {
  const history=$('#project-comment-history');
  history.replaceChildren(...comments.map(projectCommentCard));
  if(!comments.length) history.append(element('p','No comments yet. Capture a thought or a decision here.','no-comments'));
  history.scrollTop=history.scrollHeight;
}
function projectCommentCard(comment) {
  const card=element('article',undefined,'comment');
  card.dataset.commentId=comment.id;
  const header=element('header',undefined,'comment-header');
  const time=element('time',new Intl.DateTimeFormat('en',{dateStyle:'medium',timeStyle:'short'}).format(new Date(comment.created_at)));
  time.dateTime=comment.created_at;
  const menu=element('details',undefined,'comment-menu'),summary=element('summary','\u22ef');
  summary.setAttribute('aria-label','Comment actions');
  const actions=element('div',undefined,'comment-menu-actions'),edit=element('button','Edit comment'),remove=element('button','Remove comment','remove-comment');
  edit.type=remove.type='button'; actions.append(edit,remove); menu.append(summary,actions);
  menu.onkeydown=event=>{if(event.key==='Escape'&&menu.open){event.preventDefault();event.stopPropagation();menu.open=false;summary.focus();}};
  const body=element('p',comment.body); header.append(time,menu);card.append(header,body);
  const context={projectId:comment.project_id,taskId:comment.task_id};
  edit.onclick=()=>{
    if(discussionBusy || $('.discussion-edit',card)) return;
    menu.open=false;
    const form=element('form',undefined,'discussion-edit workspace-form stacked'),label=element('label','Edit comment'),input=element('textarea');
    input.value=discussionEdits.get(comment.id)??comment.body;input.required=true;input.maxLength=10000;
    input.oninput=()=>discussionEdits.set(comment.id,input.value);
    label.append(input);
    const buttons=element('div',undefined,'comment-edit-actions'),cancel=element('button','Cancel','cancel'),save=element('button','Save','insert');
    cancel.type='button'; save.type='submit'; buttons.append(cancel,save);form.append(label,buttons);
    body.hidden=menu.hidden=true;card.append(form);input.focus();
    cancel.onclick=()=>{discussionEdits.delete(comment.id);form.remove();body.hidden=menu.hidden=false;summary.focus();};
    form.onsubmit=async event=>{
      event.preventDefault(); if(!input.value.trim() || discussionBusy)return;
      const result=await discussionWrite(context,'comment-edit',{comment_id:comment.id,body:input.value});
      if(result)discussionEdits.delete(comment.id);
      if(result&&card.isConnected){const next=projectCommentCard(result.comment);card.replaceWith(next);$('summary',next).focus();}
    };
  };
  remove.onclick=async()=>{
    menu.open=false;
    if(discussionBusy || !confirm('Remove this comment?'))return;
    const result=await discussionWrite(context,'comment-delete',{comment_id:comment.id});
    if(result)discussionEdits.delete(comment.id);
    if(result&&card.isConnected){card.remove();if(!$('#project-comment-history .comment'))paintDiscussion([]);}
  };
  if(discussionEdits.has(comment.id)) edit.click();
  return card;
}
async function discussionWrite(context,action,payload) {
  if(discussionBusy)return;
  discussionBusy=true;updateDiscussionSend();
  $('#project-comment-status').textContent='Saving...';
  try {
    const result=await workspacePost('/api/projects/'+context.projectId+'/'+action,{...payload,task_id:context.taskId});
    if(discussionKey(context)===discussionKey(discussionContext)) $('#project-comment-status').textContent='Saved.';
    return result;
  } catch(err) {if(discussionKey(context)===discussionKey(discussionContext))$('#project-comment-status').textContent=err.message;}
  finally {discussionBusy=false;updateDiscussionSend();}
}
$('#project-comment-form').onsubmit=async event=>{
  event.preventDefault();
  const body=$('#project-comment-body').value;
  if(!body.trim()||!discussionContext||discussionBusy)return;
  const context={...discussionContext};
  const result=await discussionWrite(context,'comments',{body});
  if(!result)return;
  // Keep drafts typed after submission, including when switching between contexts.
  const same=discussionKey(context)===discussionKey(discussionContext);
  if(same) {
    if($('#project-comment-body').value===body)$('#project-comment-body').value='';
    $('#project-comment-history .no-comments')?.remove();
    if(!document.querySelector('#project-comment-history [data-comment-id="'+result.comment.id+'"]')) $('#project-comment-history').append(projectCommentCard(result.comment));
    $('#project-comment-history').scrollTop=$('#project-comment-history').scrollHeight;
  }
  const draft=discussionDrafts.get(discussionKey(context));
  if(draft===body)discussionDrafts.delete(discussionKey(context));
  updateDiscussionSend();
};
$('#project-comment-body').oninput=updateDiscussionSend;
$('#project-comment-body').onkeydown=event=>{
  if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing&&event.keyCode!==229){
    event.preventDefault(); if(!$('#project-comment-send').disabled)$('#project-comment-form').requestSubmit();
  }
};
$('#project-discussion-root').onclick=async()=>{if(taskDialog.open){await closeTaskEditor();return;}workspace.taskId=null;$('#task-detail').hidden=true;markTaskSelection();setDiscussion(workspace.projectId,null);};

function svgElement(tag,attrs,text) {
  const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
  Object.entries(attrs||{}).forEach(([name,value])=>node.setAttribute(name,String(value)));
  if(text!==undefined) node.textContent=text;
  return node;
}
function ordinal(value) { return Math.floor(Date.parse(value+'T00:00:00Z')/86400000); }
function dayLabel(value) { return new Date(value*86400000).toLocaleDateString('en',{month:'short',day:'numeric',timeZone:'UTC'}); }
async function loadGantt() {
  const ticket=++workspace.ganttLoad;
  $('#gantt-status').textContent='Loading timeline...';
  try {
    const selected=$('#gantt-project-select').value;
    const data=await request('/api/timeline'+(selected ? '?project_id='+encodeURIComponent(selected) : ''));
    if(ticket!==workspace.ganttLoad) return;
    const scheduled=data.tasks.filter(t=>t.start_date && t.end_date).sort((a,b)=>a.project_id-b.project_id || (a.phase_id||0)-(b.phase_id||0) || a.start_date.localeCompare(b.start_date)||a.id-b.id);
    const chart=$('#gantt-chart'),legend=$('#gantt-legend');
    chart.replaceChildren(); legend.replaceChildren();
    data.projects.filter(p=>!selected || p.id===Number(selected)).forEach(project=>{
      const chip=element('span',undefined,'legend-chip'),swatch=element('span',undefined,'legend-swatch');
      swatch.style.backgroundColor=project.color;
      chip.append(swatch,element('span',project.name)); legend.append(chip);
    });
    const phasePalette=['#9665ae','#398879','#b27739','#5c80b3','#ad5d79','#7b8041'];
    const phaseColor=task=>phasePalette[(task.phase_id||0)%phasePalette.length];
    const phases=new Map(scheduled.filter(task=>task.phase_id).map(task=>[task.phase_id,task]));
    phases.forEach(task=>{
      const chip=element('span',undefined,'legend-chip'),swatch=element('span',undefined,'legend-swatch');
      swatch.style.backgroundColor=phaseColor(task);
      chip.append(swatch,element('span',task.project_name+' / '+task.phase_name)); legend.append(chip);
    });
    const missing=data.tasks.length-scheduled.length;
    $('#gantt-footnote').textContent=(missing ? missing+' task(s) without a full date range. Start-only and end-only dates save normally; add both to show a timeline bar. ' : '')+'Hover or focus a bar for details. Select it to open the task.';
    if(!scheduled.length) {
      chart.append(element('div','A timeline starts with a plan. Create a project and a task with start and end dates in Projects.','timeline-empty'));
      $('#gantt-status').textContent=''; return;
    }
    const min=Math.min(...scheduled.map(t=>ordinal(t.start_date))),max=Math.max(...scheduled.map(t=>ordinal(t.end_date)));
    const days=max-min+1,left=260,plot=850,width=left+plot+24,height=70+scheduled.length*48;
    const svg=svgElement('svg',{width, height,role:'group','aria-label':'Task timeline'});
    const tick=Math.max(1,Math.ceil(days/10));
    for(let day=0;day<days;day+=tick) {
      const x=left+day/days*plot;
      svg.append(svgElement('line',{x1:x,y1:42,x2:x,y2:height,stroke:'#e6deec'}));
      svg.append(svgElement('text',{x:x+4,y:25,class:'gantt-axis'},dayLabel(min+day)));
    }
    svg.append(svgElement('text',{x:18,y:25,class:'gantt-axis'},'PROJECT / TASK'));
    scheduled.forEach((task,index)=>{
      const y=55+index*48,start=ordinal(task.start_date),end=ordinal(task.end_date);
      svg.append(svgElement('line',{x1:0,y1:y+39,x2:width,y2:y+39,stroke:'#eee8f1'}));
      svg.append(svgElement('text',{x:18,y:y+6,class:'gantt-task-label'},(task.parent_id ? '\u21b3 ' : '')+task.title.slice(0,32)));
      svg.append(svgElement('text',{x:18,y:y+22,class:'gantt-project-label'},(task.project_name+' / '+(task.phase_name||'No phase')).slice(0,42)));
      const group=svgElement('g',{tabindex:0,role:'button',class:'gantt-bar','aria-label':task.title+', '+task.project_name+', '+(task.phase_name||'No phase')+', '+task.start_date+' to '+task.end_date+(task.completed ? ', completed' : '')});
      group.append(svgElement('title',{},task.project_name+' / '+(task.phase_name||'No phase')+'\n'+task.title+'\n'+task.start_date+' - '+task.end_date+(task.completed ? '\nCompleted' : '\nOpen')));
      group.append(svgElement('rect',{x:left+(start-min)/days*plot,y:y-7,width:Math.max(5,(end-start+1)/days*plot),height:27,rx:7,fill:task.project_color,opacity:task.completed ? .4 : .85,stroke:'#ffffff','stroke-width':1}));
      if(task.phase_id) group.append(svgElement('rect',{x:left+(start-min)/days*plot,y:y+16,width:Math.max(5,(end-start+1)/days*plot),height:4,rx:2,fill:phaseColor(task)}));
      const phase=task.phase_name||'Task';
      if((end-start+1)/days*plot>70) group.append(svgElement('text',{x:left+(start-min)/days*plot+9,y:y+10,class:'gantt-bar-label'},phase.slice(0,Math.max(1,Math.floor((end-start+1)/days*plot/6)-2))));
      const navigate=()=>{
        workspace.projectId=task.project_id; workspace.taskId=task.id;
        if(location.hash==='#projects') showPage(); else location.hash='projects';
      };
      group.onclick=navigate;
      group.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();navigate();}};
      svg.append(group);
    });
    chart.append(svg); $('#gantt-status').textContent='';
  } catch(err) { if(ticket===workspace.ganttLoad) $('#gantt-status').textContent=err.message; }
}
$('#gantt-project-select').onchange=loadGantt;
async function showPage() {
  const name=['calendar','projects','gantt'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'calendar';
  document.querySelectorAll('[data-page]').forEach(link=>{
    if(link.dataset.page===name) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current');
  });
  for(const page of ['calendar','projects','gantt']) $('#'+page+'-page').hidden=page!==name;
  document.title='Pplanner - '+name[0].toUpperCase()+name.slice(1);
  if(name==='calendar') return;
  try {
    await refreshProjectList();
    if(name==='projects') {
      await loadProject();
      if(workspace.taskId) await openTask(workspace.taskId);
    } else await loadGantt();
  } catch(err) { $('#'+(name==='projects' ? 'project' : 'gantt')+'-status').textContent=err.message; }
}
const creationMenu=$('#project-add-menu');
document.addEventListener('pointerdown',event=>{if(!creationMenu.contains(event.target))creationMenu.open=false;});
creationMenu.addEventListener('keydown',event=>{if(event.key==='Escape'&&creationMenu.open){event.preventDefault();creationMenu.open=false;$('summary',creationMenu).focus();}});
window.addEventListener('hashchange',showPage);
showPage();
