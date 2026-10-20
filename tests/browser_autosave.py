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
      const closed=new Promise(resolve=>taskDialog.addEventListener('close',resolve,{once:true}));
      await closeTaskEditor();
      await closed;
    }

    await render();
    const column=document.querySelector('#calendar .day');
    openForm(column,column.dataset.date);
    const noteForm=column.querySelector('.composer form');
    noteForm.elements.body.value='Browser tagged note';
    noteForm.elements.tags.value='area:personal\npriority:high';
    await noteForm.onsubmit(new Event('submit',{cancelable:true}));
    const noteCard=column.querySelector('.note');
    assert(noteCard.textContent.includes('area:personal'),'Note creation tag chip missing');
    await openEditor(noteModels.get(Number(noteCard.dataset.id)));
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
    const noteClosed=new Promise(resolve=>editor.addEventListener('close',resolve,{once:true}));
    await closeEditor();await noteClosed;
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
