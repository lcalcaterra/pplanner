"""Headless-browser fixture for task autosave; never uses the real database."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from urllib.parse import urlsplit

TEST_JS = r"""
(async()=>{
  const report=document.createElement('pre'); report.id='autosave-test-results'; document.body.append(report);
  const result={checks:[],errors:[]};
  addEventListener('unhandledrejection',event=>result.errors.push(String(event.reason?.stack||event.reason)));
  function assert(value,message){if(!value)throw Error(message);}
  async function pause(ms){await new Promise(resolve=>setTimeout(resolve,ms));}
  async function waitSaved(){
    for(let i=0;i<80;i++){
      const status=document.querySelector('#task-editor-status').textContent;
      if(status==='Saved')return;
      if(status.startsWith('Not saved'))throw Error(status);
      await pause(100);
    }
    throw Error('Autosave timed out: '+document.querySelector('#task-editor-status').textContent);
  }
  try {
    document.querySelector('#calendar-page').hidden=true;document.querySelector('#projects-page').hidden=false;
    let tasks;
    if(new URL(location.href).searchParams.has('existing')){
      tasks=(await request('/api/timeline')).tasks.filter(task=>['Read documentation','Request access','Read RTP documentation'].includes(task.title));
      assert(tasks.length===3,'The three named records were not found in the isolated database copy');
    }else{
      const project=(await workspacePost('/api/projects',{name:'Browser autosave fixture'})).project;
      const parent=(await workspacePost('/api/tasks',{project_id:project.id,title:'Original task'})).task;
      const sub=(await workspacePost('/api/tasks',{project_id:project.id,parent_id:parent.id,title:'Original subtask'})).task;
      tasks=[parent,sub];
    }
    for(const task of tasks){
      workspace.projectId=task.project_id;
      await refreshProjectList();await loadProject();
      await openTask(task.id);
      assert(document.querySelector('#task-editor-status').textContent==='Saved','Initial save indicator missing');
      if(new URL(location.href).searchParams.has('layout')){
        const left=document.querySelector('#task-detail');
        const aside=document.querySelector('#task-editor-comments .project-discussion');
        const composer=document.querySelector('#project-comment-form');
        const dialog=document.querySelector('#task-editor-dialog');
        const leftRect=left.getBoundingClientRect(),rightRect=aside.getBoundingClientRect();
        assert(Math.abs(leftRect.height-rightRect.height)<2,'Comment panel does not fill the column height');
        assert(dialog.scrollHeight<=dialog.clientHeight+1,'The outer dialog still scrolls');
        assert(left.scrollHeight>left.clientHeight,'Task information is not independently scrollable');
        const rightTop=rightRect.top;
        left.scrollTop=120;
        assert(left.scrollTop>0,'Left column cannot scroll');
        assert(Math.abs(aside.getBoundingClientRect().top-rightTop)<1,'Comments move when task information scrolls');
        assert(composer.getBoundingClientRect().bottom<=rightRect.bottom+1,'Comment composer extends outside the panel');
        left.scrollTop=0;
        result.checks.push('Full-height comments and independent left scrolling: '+task.title);
      }
      const field=document.querySelector('#task-edit-form textarea[name="description"]');
      assert(field,'Editor description field was not created. Editor: '+document.querySelector('#task-detail').textContent);
      field.value='Autosaved '+task.title;
      field.dispatchEvent(new Event('input',{bubbles:true}));
      await waitSaved();
      const persisted=(await request('/api/tasks/'+task.id)).task;
      assert(persisted.description===field.value,'Description did not autosave for '+task.title+'. Status: '+document.querySelector('#task-editor-status').textContent);
      result.checks.push('Description autosaves: '+task.title);
      const form=document.querySelector('#task-edit-form');
      for(const [start,end] of [['2026-10-20',''],['','2026-10-23'],['','']]){
        form.elements.start_date.value=start;
        form.elements.end_date.value=end;
        form.elements.end_date.dispatchEvent(new Event('change',{bubbles:true}));
        await waitSaved();
        const saved=(await request('/api/tasks/'+task.id)).task;
        assert(saved.start_date===(start||null)&&saved.end_date===(end||null),'Partial dates failed: '+JSON.stringify([start,end])+' Status: '+document.querySelector('#task-editor-status').textContent);
        assert(document.querySelector('#task-editor-status').textContent==='Saved','Save status not confirmed');
      }
      result.checks.push('Start-only, end-only and blank dates autosave: '+task.title);
      form.elements.title.value='Renamed '+task.title;
      form.elements.title.dispatchEvent(new Event('input',{bubbles:true}));
      form.elements.tags.value='owner:Browser';
      form.elements.phase.value='Testing';
      form.elements.start_date.value='2026-10-20';
      form.elements.end_date.value='2026-10-23';
      form.elements.end_date.dispatchEvent(new Event('change',{bubbles:true}));
      await waitSaved();
      const edited=(await request('/api/tasks/'+task.id)).task;
      assert(edited.title==='Renamed '+task.title,'Title did not save');
      assert(edited.tags.includes('owner:Browser'),'Tags did not save');
      assert(edited.phase_name==='Testing','Phase did not save');
      assert(edited.end_date==='2026-10-23','Dates did not save');
      result.checks.push('All editable fields autosave: '+task.title);
      for (const [status,priority] of [['locked','high'],['update-required','medium'],['loading','low'],['completed','none'],['open','none']]) {
        form.elements.status.value=status;
        form.elements.priority.value=priority;
        form.elements.status.dispatchEvent(new Event('change',{bubbles:true}));
        await flushTaskSave();
        const savedActivity=(await request('/api/tasks/'+task.id)).task;
        assert(savedActivity.status===status&&savedActivity.priority===priority,'Activity menus did not autosave');
        if(status!=='completed') {
          const row=document.querySelector('.task-tree[data-task-id="'+task.id+'"] > summary');
          assert(Boolean(row.querySelector('.status-icon'))===(status!=='open'),'Status icon visibility incorrect');
          assert(Boolean(row.querySelector('.priority-icon'))===(priority!=='none'),'Priority icon visibility incorrect');
          if(status!=='open')assert(row.querySelector('.status-icon').nextElementSibling.classList.contains('task-tree-meta'),'Status icon position incorrect');
          if(priority!=='none')assert(row.querySelector('.task-title-row .priority-icon'),'Priority icon should be beside title');
        }
      }
      result.checks.push('Status/priority menu autosave and row icons: '+task.title);
      const fileSection=document.querySelector('.task-attachments');
      assert(fileSection.querySelector('img[src="/imgs/attachments.png"]'),'Attachment icon missing');
      const files=new DataTransfer();
      files.items.add(new File(['Browser attachment content'],'browser-file.txt',{type:'text/plain'}));
      fileSection.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:files}));
      for(let attempt=0;attempt<100&&taskAttachmentBusy;attempt++)await pause(50);
      let attached=(await request('/api/tasks/'+task.id)).attachments;
      assert(attached.length===1,'File upload failed: '+fileSection.textContent);
      const downloaded=await fetch('/api/attachments/'+attached[0].id);
      assert((await downloaded.text())==='Browser attachment content','Downloaded bytes differ');
      assert(fileSection.querySelector('.attachment-download').download==='browser-file.txt','Download link missing filename');
      const originalFileConfirm=window.confirm;
      try {
        window.confirm=()=>true;
        await fileSection.querySelector('.attachment-row button').onclick();
      } finally {window.confirm=originalFileConfirm;}
      assert((await request('/api/tasks/'+task.id)).attachments.length===0,'Attachment removal failed');
      // Leave one file for the existing complete export/import browser check.
      await workspacePost('/api/tasks/'+task.id+'/attachments',{filename:'backup-file.txt',content:btoa('Preserved attachment bytes')});
      result.checks.push('Attachment icon, drop upload, download and removal: '+task.title);
      const closed=new Promise(resolve=>taskDialog.addEventListener('close',resolve,{once:true}));
      await closeTaskEditor();
      await closed;
    }

    const orderProject=(await workspacePost('/api/projects',{name:'Ordering browser'})).project;
    const orderA=(await workspacePost('/api/tasks',{project_id:orderProject.id,title:'Order A'})).task;
    const orderB=(await workspacePost('/api/tasks',{project_id:orderProject.id,title:'Order B'})).task;
    const orderX=(await workspacePost('/api/tasks',{project_id:orderProject.id,parent_id:orderA.id,title:'Order X'})).task;
    const orderY=(await workspacePost('/api/tasks',{project_id:orderProject.id,parent_id:orderA.id,title:'Order Y'})).task;
    workspace.projectId=orderProject.id;workspace.expanded.add(orderA.id);
    await loadProject();
    assert(localStorage.getItem(lastProjectKey)===String(orderProject.id),'Last viewed project was not remembered');
    workspace.projectId=null;workspace.taskId=null;
    await refreshProjectList();await loadProject();
    assert(workspace.projectId===orderProject.id,'Remembered project was not restored');
    assert(document.querySelector('#project-select').value===String(orderProject.id),'Restored project picker mismatch');
    workspace.projectId=null;localStorage.setItem(lastProjectKey,'99999999');
    await refreshProjectList();await loadProject();
    assert(workspace.projectId===workspace.projects[0].id,'Missing remembered project should fall back to newest');
    result.checks.push('Last project persistence, selection restoration and deleted-project fallback');
    workspace.expanded.add(orderA.id);paintTasks();
    const row=id=>document.querySelector('.task-tree[data-task-id="'+id+'"] > summary');
    async function dragTask(source,target,after=false) {
      const transfer=new DataTransfer(),from=row(source),to=row(target);
      from.dispatchEvent(new DragEvent('dragstart',{bubbles:true,cancelable:true,dataTransfer:transfer}));
      const rect=to.getBoundingClientRect(),y=rect.top+rect.height*(after?.75:.25);
      to.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:transfer,clientY:y}));
      to.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer,clientY:y}));
      from.dispatchEvent(new DragEvent('dragend',{bubbles:true,dataTransfer:transfer}));
      for(let attempt=0;attempt<100&&taskOrderBusy;attempt++)await pause(50);
    }
    assert(!document.querySelector('.task-order'),'Arrow buttons were not removed');
    await dragTask(orderA.id,orderB.id);
    assert(workspace.tasks.filter(t=>!t.parent_id)[0].id===orderA.id,'Root drag failed');
    assert(!taskDialog.open,'Dragging opened task editor');
    await dragTask(orderY.id,orderX.id,true);
    await loadProject();
    assert(workspace.tasks.filter(t=>t.parent_id===orderA.id)[0].id===orderX.id,'Child drag order did not persist');
    const beforeInvalid=workspace.tasks.map(t=>t.id).join(',');
    await dragTask(orderX.id,orderB.id);
    assert(workspace.tasks.map(t=>t.id).join(',')===beforeInvalid,'Cross-parent drop was allowed');
    assert(workspace.expanded.has(orderA.id),'Dragging lost expanded state');
    await pause(300);
    row(orderX.id).querySelector('.task-open-button').click();
    for(let attempt=0;attempt<100&&taskLoading;attempt++)await pause(50);
    assert(taskDialog.open,'Ordinary task click no longer opens editor');
    const orderClosed=new Promise(resolve=>taskDialog.addEventListener('close',resolve,{once:true}));
    await closeTaskEditor();await orderClosed;
    result.checks.push('Task/subtask drag/drop, persistent order, parent boundaries, click-to-edit and no arrow controls');

    if(new URL(location.href).searchParams.has('layout')) {
      for(let index=0;index<20;index++) {
        await workspacePost('/api/tasks',{project_id:orderProject.id,title:'Overflow task '+index});
        await workspacePost('/api/projects/'+orderProject.id+'/comments',{body:'Project comment '+index+' with enough text to exercise scrolling.'});
      }
      await loadProject();
      for(let attempt=0;attempt<60&&document.querySelectorAll('#project-comment-history .comment').length<20;attempt++)await pause(50);
      const overview=document.querySelector('#project-overview');
      const discussion=document.querySelector('#project-discussion-home > .project-discussion');
      const taskList=document.querySelector('#task-list');
      const history=document.querySelector('#project-comment-history');
      const composer=document.querySelector('#project-comment-form');
      const rect=discussion.getBoundingClientRect();
      assert(Math.abs(rect.top-overview.getBoundingClientRect().top)<2,'Discussion must align with project overview');
      assert(overview.getBoundingClientRect().right<rect.left,'Overview should leave room for discussion');
      assert(rect.bottom<=window.innerHeight+1,'Discussion extends below viewport');
      assert(taskList.scrollHeight>taskList.clientHeight,'Task list does not overflow independently');
      assert(history.scrollHeight>history.clientHeight,'Comment history does not overflow independently');
      const height=rect.height,composerTop=composer.getBoundingClientRect().top;
      taskList.scrollTop=150;history.scrollTop=120;
      assert(taskList.scrollTop>0&&history.scrollTop>0,'Independent scrolling failed');
      assert(Math.abs(discussion.getBoundingClientRect().height-height)<1,'Discussion height changed while scrolling');
      assert(Math.abs(composer.getBoundingClientRect().top-composerTop)<1,'Composer moved while scrolling');
      assert(composer.getBoundingClientRect().bottom<=rect.bottom,'Composer is outside discussion');
      result.checks.push('Project overview alignment, fixed discussion, independent task/comment scroll and visible composer');
    }

    const coloredProject=(await workspacePost('/api/projects',{name:'Note color browser',color:'#123456'})).project;
    await render();
    const column=document.querySelector('#calendar .day');
    openForm(column,column.dataset.date);
    const noteForm=column.querySelector('.composer form');
    await fillNoteProjects(noteForm.elements.project_id,coloredProject.id);
    noteForm.elements.body.value='Browser tagged note';
    noteForm.elements.description.value='Initial description';
    noteForm.elements.tags.value='area:personal\npriority:high';
    await noteForm.onsubmit(new Event('submit',{cancelable:true}));
    const noteCard=column.querySelector('.note');
    assert(noteCard.textContent.includes('area:personal'),'Note creation tag chip missing');
    assert(noteCard.classList.contains('project-note'),'Project note color missing');
    assert(noteCard.style.getPropertyValue('--note-project-color')==='#123456','Wrong project color');
    await openEditor(noteModels.get(Number(noteCard.dataset.id)));
    assert(document.querySelector('#edit-project').value===String(coloredProject.id),'Project selection did not persist');
    assert(document.querySelector('#edit-description').value==='Initial description','Description did not persist on creation');
    document.querySelector('#edit-body').value='Updated note title';
    document.querySelector('#edit-description').value='Updated note description';
    document.querySelector('#edit-description').dispatchEvent(new Event('input',{bubbles:true}));
    await flushNoteAutosave();
    const noteFields=(await request('/api/notes/'+editorNote.id)).note;
    assert(noteFields.title==='Updated note title'&&noteFields.description==='Updated note description','Separate note fields did not autosave');
    assert(!document.querySelector('.note[data-id="'+editorNote.id+'"] .note-description'),'Description should be hidden on calendar cards');
    assert(document.querySelector('#edit-description').value==='Updated note description','Description should remain available in the editor');
    result.checks.push('Separate note title/description creation, autosave and description only in editor');
    const tagField=document.querySelector('#edit-tags');
    tagField.value=' topic : browser \ntopic:browser';
    tagField.dispatchEvent(new Event('input',{bubbles:true}));
    await flushNoteAutosave();
    let savedNote=(await request('/api/notes/'+editorNote.id)).note;
    assert(JSON.stringify(savedNote.tags)===JSON.stringify(['topic:browser']),'Note tags did not autosave');
    assert(document.querySelector('#edit-state').textContent==='Saved','Note tags remain dirty');
    tagField.value='';tagField.dispatchEvent(new Event('input',{bubbles:true}));
    await flushNoteAutosave();
    savedNote=(await request('/api/notes/'+editorNote.id)).note;
    assert(savedNote.tags.length===0,'Clearing tags did not autosave');
    const commentInput=document.querySelector('#comment-body');
    commentInput.value='Important';
    commentInput.dispatchEvent(new Event('input',{bubbles:true}));
    commentInput.setSelectionRange(0,commentInput.value.length);
    document.querySelector('#comment-form [data-format="bold"]').click();
    assert(commentInput.value==='**Important**','Bold toolbar did not format selection');
    document.querySelector('#comment-form .comment-preview-toggle').click();
    assert(document.querySelector('#comment-form .comment-format-preview strong')?.textContent==='Important','Formatted preview missing');
    document.querySelector('#comment-form .comment-preview-toggle').click();
    const richSource='**Important** *italic* ++underline++ ~~removed~~ ==highlight==\n\n- first\n- second\n\n> quoted\n\n\x60code\x60 [Docs](https://example.com) <img src=x onerror=alert(1)>';
    commentInput.value=richSource;commentInput.dispatchEvent(new Event('input',{bubbles:true}));
    await document.querySelector('#comment-form').onsubmit(new Event('submit',{cancelable:true}));
    const savedRich=(await request('/api/notes/'+editorNote.id)).comments.at(-1);
    assert(savedRich.body===richSource,'Formatting source was not persisted');
    const richCard=[...document.querySelectorAll('#comment-history .comment')].at(-1);
    assert(richCard.querySelector('strong')&&richCard.querySelector('em')&&richCard.querySelector('u')&&richCard.querySelector('s')&&richCard.querySelector('mark'),'Inline comment formatting missing');
    assert(richCard.querySelectorAll('ul li').length===2&&richCard.querySelector('blockquote')&&richCard.querySelector('code'),'Block comment formatting missing');
    assert(!richCard.querySelector('img'),'Comment HTML was executed or injected');
    richCard.querySelector('.comment-menu-actions button').click();
    assert(richCard.querySelector('.comment-edit .comment-format-toolbar'),'Comment edit formatting toolbar missing');
    const editRich=richCard.querySelector('.comment-edit textarea');editRich.value='==Edited==';editRich.dispatchEvent(new Event('input',{bubbles:true}));
    await richCard.querySelector('.comment-edit').onsubmit(new Event('submit',{cancelable:true}));
    assert(document.querySelector('#comment-history mark')?.textContent==='Edited','Edited comment formatting did not render');
    const safe=document.createElement('div');
    renderFormattedComment(safe,'[Unsafe](javascript:alert(1)) <script>alert(1)</script>\n\n\x60\x60\x60\n<script>literal</script>\n\x60\x60\x60');
    assert(!safe.querySelector('script,img,a'),'Unsafe HTML or URL was rendered');
    assert(safe.querySelector('pre code')?.textContent==='<script>literal</script>','Code block did not preserve literal source');
    result.checks.push('Note comment toolbar, preview, formatted send/edit, lists, code and safe rendering');

    const pngContent='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgaPj/HwAEggJ/59habAAAAABJRU5ErkJggg==';
    const imageBytes=Uint8Array.from(atob(pngContent),c=>c.charCodeAt(0));
    const pasted=new DataTransfer();pasted.items.add(new File([imageBytes],'pasted.png',{type:'image/png'}));
    commentInput.value='Pasted screenshot: ';commentInput.setSelectionRange(commentInput.value.length,commentInput.value.length);
    commentInput.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:pasted}));
    for(let attempt=0;attempt<100&&commentImageUploads;attempt++)await pause(50);
    assert(commentInput.value.includes('![pasted.png](/api/comment-images/'),'Clipboard image was not inserted: '+commentInput.value);
    await document.querySelector('#comment-form').onsubmit(new Event('submit',{cancelable:true}));
    const savedImage=document.querySelector('#comment-history .comment:last-child .comment-inline-image');
    assert(savedImage,'Saved comment image missing');
    savedImage.loading='eager';
    for(let attempt=0;attempt<80&&!savedImage.complete;attempt++)await pause(50);
    assert(savedImage.naturalWidth===1,'Uploaded PNG did not load correctly');
    assert((await fetch(savedImage.getAttribute('src'))).headers.get('Content-Type')==='image/png','Image MIME type incorrect');
    const noExternal=document.createElement('div');renderFormattedComment(noExternal,'![external](https://example.com/tracker.png)');
    assert(!noExternal.querySelector('img'),'External image URLs should not load');
    result.checks.push('Clipboard image paste, local upload, saved rendering and image decoding');
    const noteClosed=new Promise(resolve=>editor.addEventListener('close',resolve,{once:true}));
    await closeEditor();await noteClosed;
    const picker=document.querySelector('#week-date');
    picker.value='2027-01-03';
    picker.dispatchEvent(new Event('change',{bubbles:true}));
    await pause(500);
    assert(document.querySelector('#calendar .day').dataset.date==='2026-12-28','Weekend/year-boundary week jump failed');
    result.checks.push('Project note colors and date picker navigation');
    result.checks.push('Note creation tags, card chips, normalized autosave and tag removal');

    const project=(await workspacePost('/api/projects',{name:'Disposable deletion UI'})).project;
    const parent=(await workspacePost('/api/tasks',{project_id:project.id,title:'Delete parent'})).task;
    const child=(await workspacePost('/api/tasks',{project_id:project.id,parent_id:parent.id,title:'Delete child'})).task;
    workspace.projectId=project.id;await refreshProjectList();await loadProject();await openTask(child.id);
    const originalConfirm=window.confirm;
    try {
      window.confirm=()=>false;
      await document.querySelector('#task-delete').onclick();
      assert((await request('/api/tasks/'+child.id)).task.id===child.id,'Cancel unexpectedly deleted subtask');
      window.confirm=()=>true;
      await document.querySelector('#task-delete').onclick();
      assert(!taskDialog.open,'Task dialog remained open after deleting');
      assert(!(await request('/api/projects/'+project.id)).tasks.some(task=>task.id===child.id),'Subtask still exists');
      result.checks.push('Subtask delete confirmation and UI refresh');
      await openTask(parent.id);
      const field=document.querySelector('#task-edit-form textarea[name="description"]');
      field.value='Pending draft to discard when deleting';
      field.dispatchEvent(new Event('input',{bubbles:true}));
      await document.querySelector('#task-delete').onclick();
      assert((await request('/api/projects/'+project.id)).tasks.length===0,'Task deletion failed');
      result.checks.push('Task deletion with pending autosave draft');
      await document.querySelector('#project-delete').onclick();
      assert(!(await request('/api/projects')).projects.some(item=>item.id===project.id),'Project still exists');
      result.checks.push('Project delete and project picker refresh');
    } finally {window.confirm=originalConfirm;}
    const discussionProject=workspace.projects.find(project=>project.status!=='completed');
    const discussionTask=(await workspacePost('/api/tasks',{project_id:discussionProject.id,title:'Formatted discussion task'})).task;
    const discussionSub=(await workspacePost('/api/tasks',{project_id:discussionProject.id,parent_id:discussionTask.id,title:'Formatted discussion subtask'})).task;
    workspace.projectId=discussionProject.id;await refreshProjectList();await loadProject();
    for(const taskId of [null,discussionTask.id,discussionSub.id]) {
      await setDiscussion(discussionProject.id,taskId);
      const input=document.querySelector('#project-comment-body');input.value='**Context bold** ==Context highlight==';input.dispatchEvent(new Event('input',{bubbles:true}));
      assert(document.querySelector('#project-comment-form .comment-format-toolbar'),'Discussion toolbar missing');
      const imagePaste=new DataTransfer();imagePaste.items.add(new File([imageBytes],'context.png',{type:'image/png'}));
      input.setSelectionRange(input.value.length,input.value.length);
      input.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:imagePaste}));
      for(let attempt=0;attempt<100&&commentImageUploads;attempt++)await pause(50);
      assert(input.value.includes('/api/comment-images/'),'Project/task/subtask image paste failed');

      await document.querySelector('#project-comment-form').onsubmit(new Event('submit',{cancelable:true}));
      const card=[...document.querySelectorAll('#project-comment-history .comment')].at(-1);
      assert(card.querySelector('strong')&&card.querySelector('mark')&&card.querySelector('.comment-inline-image'),'Context formatting or image missing');
      card.querySelector('.comment-menu-actions button').click();
      assert(card.querySelector('.discussion-edit .comment-format-toolbar'),'Discussion edit toolbar missing');
      const edit=card.querySelector('.discussion-edit textarea');edit.value='*Edited context*';edit.dispatchEvent(new Event('input',{bubbles:true}));
      await card.querySelector('.discussion-edit').onsubmit(new Event('submit',{cancelable:true}));
      assert(document.querySelector('#project-comment-history .comment:last-child em'),'Discussion edit formatting failed');
    }
    await setDiscussion(discussionProject.id,null);
    result.checks.push('Formatted project, task and subtask comment submission and editing');
    const archivedProject=(await workspacePost('/api/projects',{name:'Restore browser project',description:'Keep all related data'})).project;
    const archivedTask=(await workspacePost('/api/tasks',{project_id:archivedProject.id,title:'Preserved task',priority:'high'})).task;
    await workspacePost('/api/projects/'+archivedProject.id+'/comments',{body:'Preserved project discussion'});
    workspace.projectId=archivedProject.id;await refreshProjectList();await loadProject();
    const projectStatusSelect=document.querySelector('.project-status-control select');
    projectStatusSelect.value='completed';await projectStatusSelect.onchange();
    assert(![...document.querySelector('#project-select').options].some(option=>option.value===String(archivedProject.id)),'Completed project remains in selector');
    assert(workspace.projectId!==archivedProject.id,'Completed project remains selected');
    const allProjects=(await request('/api/projects')).projects;
    for(const project of allProjects)await workspacePost('/api/projects/'+project.id+'/status',{status:'completed'});
    await refreshProjectList();await loadProject();
    assert(workspace.projectId===null,'All-completed state should not select an archived project');
    assert(document.querySelector('#project-overview').textContent.includes('Restore projects'),'All-completed state should explain restoration');
    document.querySelector('#restore-projects').click();
    for(let attempt=0;attempt<100&&!document.querySelector('#restore-project-list input[value="'+archivedProject.id+'"]');attempt++)await pause(50);
    assert(!document.querySelector('#restore-projects-page').hidden,'Settings did not open restore page');
    const restoreChoice=document.querySelector('#restore-project-list input[value="'+archivedProject.id+'"]');
    assert(restoreChoice,'Completed project missing from restore list');
    restoreChoice.checked=true;restoreChoice.dispatchEvent(new Event('change'));
    const oldConfirm=window.confirm;
    try {
      window.confirm=()=>false;
      await document.querySelector('#restore-project-form').onsubmit(new Event('submit',{cancelable:true}));
      assert((await request('/api/projects/'+archivedProject.id)).project.status==='completed','Cancel unexpectedly restored project');
      window.confirm=()=>true;
      await document.querySelector('#restore-project-form').onsubmit(new Event('submit',{cancelable:true}));
    } finally {window.confirm=oldConfirm;}
    for(let attempt=0;attempt<100&&(document.querySelector('#projects-page').hidden||document.querySelector('#project-select').value!==String(archivedProject.id));attempt++)await pause(50);
    assert(document.querySelector('#project-select').value===String(archivedProject.id),'Restored project was not selected');
    const restoredProject=await request('/api/projects/'+archivedProject.id);
    assert(restoredProject.project.status==='active','Project was not restored as active');
    assert(restoredProject.tasks.some(task=>task.id===archivedTask.id)&&restoredProject.comments.some(comment=>comment.body==='Preserved project discussion'),'Restoration lost related data');
    assert(localStorage.getItem(lastProjectKey)===String(archivedProject.id),'Restored project not remembered');
    result.checks.push('Completed project filtering, automatic fallback, all-completed state and confirmed restoration preserving data');

    for(let attempt=0;attempt<80&&backupPending();attempt++)await pause(50);
    settingsMenu.open=true;
    assert(!document.querySelector('#settings-menu summary').hasAttribute('disabled'),'Settings is disabled');
    const originalAnchorClick=HTMLAnchorElement.prototype.click;
    let downloadName='';
    HTMLAnchorElement.prototype.click=function(){downloadName=this.download;};
    try {await document.querySelector('#export-data').onclick();}
    finally {HTMLAnchorElement.prototype.click=originalAnchorClick;}
    assert(downloadName.endsWith('.pplanner'),'Export did not create a Pplanner download');
    const savedBackup=await request('/api/data/export');
    const extraNote=(await workspacePost('/api/notes',{date:document.querySelector('#calendar .day').dataset.date,title:'Discard on restore'})).note;
    document.querySelector('#import-data').click();
    assert(importDialog.open,'Import dialog did not open');
    await readImportFile(new File(['not valid JSON'],'invalid.pplanner'));
    assert(document.querySelector('#import-submit').disabled,'Invalid file enables import');
    const transfer=new DataTransfer();
    transfer.items.add(new File([JSON.stringify(savedBackup)],'browser-backup.pplanner',{type:'application/json'}));
    document.querySelector('#import-dropzone').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
    for(let attempt=0;attempt<60&&!importBackup;attempt++)await pause(50);
    assert(importBackup?.format==='pplanner-backup','Drag/drop did not load backup');
    assert(document.querySelector('#import-submit').disabled,'Import must require explicit confirmation');
    document.querySelector('#import-confirm').checked=true;
    document.querySelector('#import-confirm').dispatchEvent(new Event('change'));
    assert(!document.querySelector('#import-submit').disabled,'Confirmed valid backup did not enable import');
    await document.querySelector('#import-form').onsubmit(new Event('submit',{cancelable:true}));
    assert(importDone,'Restore UI failed: '+document.querySelector('#import-status').textContent);
    const restored=await request('/api/data/export');
    assert(JSON.stringify(restored.tables)===JSON.stringify(savedBackup.tables),'Imported data differs from exported data');
    assert(!restored.tables.notes.some(note=>note.id===extraNote.id),'Import did not overwrite later data');
    assert(document.querySelector('#import-status').textContent.includes('Recovery backup:'),'Recovery information missing');
    result.checks.push('Settings export download, invalid file rejection, drag/drop import, confirmation and complete replacement');
  }catch(error){result.errors.push(error.stack||String(error));}
  result.passed=!result.errors.length;
  report.textContent=JSON.stringify(result);
  document.title=result.passed?'AUTOSAVE PASS':'AUTOSAVE FAIL';
})();
"""

class FixtureHandler(server.Handler):
    def do_GET(self):
        path=urlsplit(self.path).path
        if path in ("/autosave-test","/autosave-test.js"):
            if path.endswith(".js"):
                data=TEST_JS.encode();mime="text/javascript"
            else:
                data=(server.ROOT/"static"/"index.html").read_text().replace('<script src="/workspace.js" defer></script>','<script src="/workspace.js" defer></script><script src="/autosave-test.js" defer></script>').encode()
                mime="text/html"
            self.send_response(200)
            self.send_header("Content-Type",mime+"; charset=utf-8")
            self.send_header("Content-Length",str(len(data)))
            self.end_headers();self.wfile.write(data)
            return
        super().do_GET()

if __name__=="__main__":
    with tempfile.TemporaryDirectory(prefix="pplanner-browser-") as directory:
        source=server.DB
        server.DB=Path(directory)/"fixture.sqlite3"
        if "--existing-copy" in sys.argv:
            import sqlite3
            with sqlite3.connect(source.resolve().as_uri()+"?mode=ro",uri=True) as existing:
                with sqlite3.connect(server.DB) as copied:
                    existing.backup(copied)
        server.initialize()
        http=server.ThreadingHTTPServer(("127.0.0.1",8765),FixtureHandler)
        print("AUTOSAVE FIXTURE http://localhost:8765/autosave-test",flush=True)
        try:http.serve_forever()
        except KeyboardInterrupt:pass
        finally:http.server_close()
