// Local documentation library. Uploaded HTML is never inserted into the page.
const docsState={items:[],selected:null,opened:new Set(),busy:false,token:0,action:null,dirty:false,searchTicket:0,searchTimer:null,searchAbort:null};
const docsNode=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const docsGet=id=>document.getElementById(id);
const docsItem=id=>docsState.items.find(item=>item.id===id);
const docsPost=(path,data)=>request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function docsMessage(text){docsGet('docs-status').textContent=text;}
function docsFolder(){const item=docsItem(docsState.selected);return item?.kind==='folder'?item.id:item?.parent_id??null;}
function docsTrail(id){
  const names=[],seen=new Set();
  while(id!=null&&!seen.has(id)){seen.add(id);const item=docsItem(id);if(!item)break;names.unshift(item.name);id=item.parent_id;}
  return ['Library',...names].join(' / ');
}
function docsDescendant(id,parent){
  const seen=new Set();
  while(parent!=null&&!seen.has(parent)){if(id===parent)return true;seen.add(parent);parent=docsItem(parent)?.parent_id??null;}
  return false;
}
async function loadDocumentation(){
  try{const data=await request('/api/documentation');docsState.items=data.items;docsTree();if(docsState.selected&&!docsItem(docsState.selected))docsClear();}
  catch(error){docsMessage('Could not load library. '+error.message);}
}
function docsTree(){
  const tree=docsGet('docs-tree');tree.replaceChildren();
  function branch(parent,container,depth){
    const items=docsState.items.filter(item=>item.parent_id===parent).sort((a,b)=>(a.kind===b.kind?0:a.kind==='folder'?-1:1)||a.name.localeCompare(b.name));
    for(const item of items){
      const group=docsNode('div',undefined,'docs-tree-group');
      const row=docsNode('div',undefined,'docs-tree-row');row.classList.toggle('selected',item.id===docsState.selected);row.draggable=true;
      row.style.setProperty('--docs-depth',Math.min(depth,10));
      if(item.kind==='folder'){
        const toggle=docsNode('button','','docs-folder-toggle');toggle.type='button';toggle.setAttribute('aria-label','Expand '+item.name);toggle.setAttribute('aria-expanded',String(docsState.opened.has(item.id)));
        toggle.onclick=()=>{if(docsState.opened.has(item.id))docsState.opened.delete(item.id);else docsState.opened.add(item.id);docsTree();};
        row.append(toggle);
      }else row.append(docsNode('span','', 'docs-tree-spacer'));
      const button=docsNode('button',undefined,'docs-tree-open');button.type='button';button.title=item.name;
      button.append(docsNode('span',item.kind==='folder'?'':item.name.split('.').pop().toUpperCase(),'docs-file-type'+(item.kind==='folder'?' docs-folder-icon':'')),docsNode('span',item.name));
      if(item.id===docsState.selected)button.setAttribute('aria-current','true');
      button.onclick=()=>docsOpen(item.id);row.append(button);
      row.ondragstart=event=>{if(docsState.busy){event.preventDefault();return;}event.dataTransfer.setData('application/x-pplanner-doc',String(item.id));event.dataTransfer.effectAllowed='move';};
      if(item.kind==='folder')docsDropTarget(row,item.id);
      group.append(row);
      if(item.kind==='folder'&&docsState.opened.has(item.id))branch(item.id,group,depth+1);
      container.append(group);
    }
  }
  branch(null,tree,0);
  if(!docsState.items.length)tree.append(docsNode('p','Your library is empty. Create a folder or upload a document.','workspace-empty'));
}
function docsClear(){
  docsState.selected=null;docsState.token++;docsGet('docs-document-header').hidden=true;
  const blank=docsNode('div',undefined,'docs-placeholder');
  blank.append(docsNode('span','DOC'),docsNode('h2','Open a document'),docsNode('p','Choose a document from your library, or upload one to get started.'));
  docsGet('docs-content').replaceChildren(blank);docsOutline([]);docsTree();
}
function docsOutline(headings,pdf=false){
  const nav=docsGet('docs-outline-links');nav.replaceChildren();
  if(!headings.length){nav.append(docsNode('p',pdf?"Use the PDF viewer\u2019s outline or page controls when available.":'No headings in this document.'));return;}
  headings.forEach(heading=>{
    const button=docsNode('button',heading.textContent);button.type='button';
    button.style.setProperty('--heading-depth',Math.max(0,Number(heading.tagName.slice(1))-1));
    button.onclick=()=>{const reader=docsGet('docs-content');reader.scrollTo({top:reader.scrollTop+heading.getBoundingClientRect().top-reader.getBoundingClientRect().top-20,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});heading.focus({preventScroll:true});};
    nav.append(button);
  });
}
function docsHeading(node,headings){node.tabIndex=-1;node.id='docs-heading-'+headings.length;headings.push(node);return node;}
function docsMarkdown(text,plain=false){
  const article=docsNode('article',undefined,'docs-article comment-rich'),headings=[];
  if(plain){article.append(docsNode('pre',text,'docs-plain'));return {article,headings};}
  const lines=text.replace(/\r\n?/g,'\n').split('\n');let i=0;
  const inline=(node,value)=>{commentInline(node,value);return node;};
  while(i<lines.length){
    const line=lines[i];let match;
    if(!line.trim()){i++;continue;}
    if((match=line.match(/^\s*(\x60{3,}|~{3,})(.*)$/))){
      const fence=match[1],code=[];i++;
      while(i<lines.length&&!lines[i].trim().startsWith(fence)){code.push(lines[i++]);}
      if(i<lines.length)i++;
      const pre=docsNode('pre');pre.append(docsNode('code',code.join('\n')));article.append(pre);continue;
    }
    if((match=line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/))){article.append(docsHeading(inline(docsNode('h'+match[1].length),match[2]),headings));i++;continue;}
    if(i+1<lines.length&&/^ {0,3}(=+|-+)\s*$/.test(lines[i+1])&&line.trim()){article.append(docsHeading(inline(docsNode(lines[i+1].trim()[0]==='='?'h1':'h2'),line.trim()),headings));i+=2;continue;}
    if(/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)){article.append(docsNode('hr'));i++;continue;}
    if((match=line.match(/^\s*>\s?(.*)$/))){
      const quote=docsNode('blockquote');while(i<lines.length&&(match=lines[i].match(/^\s*>\s?(.*)$/))){quote.append(inline(docsNode('p'),match[1]));i++;}article.append(quote);continue;
    }
    if((match=line.match(/^\s*(?:([-+*])|(\d+)[.)])\s+(.+)$/))){
      const ordered=!!match[2],list=docsNode(ordered?'ol':'ul');if(ordered)list.start=Number(match[2]);
      while(i<lines.length&&(match=lines[i].match(/^\s*(?:([-+*])|(\d+)[.)])\s+(.+)$/))&&!!match[2]===ordered){list.append(inline(docsNode('li'),match[3]));i++;}article.append(list);continue;
    }
    if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/.test(lines[i+1])){
      const table=docsNode('table'),header=docsNode('tr'),cells=value=>value.trim().replace(/^\||\|$/g,'').split('|').map(cell=>cell.trim());
      cells(line).forEach(value=>header.append(inline(docsNode('th'),value)));table.append(header);i+=2;
      while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){const row=docsNode('tr');cells(lines[i++]).forEach(value=>row.append(inline(docsNode('td'),value)));table.append(row);}article.append(table);continue;
    }
    const paragraph=[line];i++;
    while(i<lines.length&&lines[i].trim()&&!/^\s*(#{1,6}\s|>|[-+*]\s|\d+[.)]\s|\x60{3,}|~{3,})/.test(lines[i])){if(i+1<lines.length&&/^\s*(=+|-+)\s*$/.test(lines[i+1]))break;paragraph.push(lines[i++]);}
    article.append(inline(docsNode('p'),paragraph.join('\n')));
  }
  return {article,headings};
}
function docsWord(item){
  const article=docsNode('article',undefined,'docs-article comment-rich'),headings=[];
  function block(model){
    if(model.type==='table'){
      const table=docsNode('table');for(const cells of model.rows){const row=docsNode('tr');for(const parts of cells){const cell=docsNode('td');parts.forEach(part=>cell.append(block(part)));row.append(cell);}table.append(row);}return table;
    }
    const node=docsNode(model.type==='heading'?'h'+model.level:'p');if(model.list)node.classList.add('docs-word-list');
    for(const run of model.runs){
      if(run.image!==undefined){const img=docsNode('img');img.src='/api/documentation/'+item.id+'/media/'+run.image;img.alt='Document image';img.loading='lazy';node.append(img);continue;}
      let child=document.createTextNode(run.text);
      for(const [enabled,tag]of[[run.bold,'strong'],[run.italic,'em'],[run.underline,'u']])if(enabled){const wrapper=docsNode(tag);wrapper.append(child);child=wrapper;}
      if(run.link&&commentLinkAllowed(run.link)){const link=docsNode('a');link.href=run.link;link.rel='noopener noreferrer';link.target='_blank';link.append(child);child=link;}
      node.append(child);
    }
    if(model.type==='heading')docsHeading(node,headings);return node;
  }
  item.blocks.forEach(model=>article.append(block(model)));return {article,headings};
}
async function docsOpen(id,allowBusy=false){
  if(docsState.busy&&!allowBusy)return;
  const token=++docsState.token;docsState.selected=id;docsTree();
  const local=docsItem(id);if(!local)return docsClear();
  for(let parent=local.parent_id;parent!=null;parent=docsItem(parent)?.parent_id??null)docsState.opened.add(parent);
  docsTree();docsGet('docs-document-header').hidden=false;docsGet('docs-document-title').textContent=local.name;docsGet('docs-breadcrumb').textContent=docsTrail(local.parent_id);
  docsGet('docs-download').hidden=true;docsGet('docs-edit').hidden=true;
  docsGet('docs-content').replaceChildren(docsNode('p','Loading...','workspace-empty'));docsOutline([]);
  if(local.kind==='folder'){
    docsState.opened.add(id);docsTree();const blank=docsNode('div',undefined,'docs-placeholder');blank.append(docsNode('span','DOC'),docsNode('h2',local.name),docsNode('p','Create a document or upload files into this folder.'));docsGet('docs-content').replaceChildren(blank);return;
  }
  try{
    const {item}=await request('/api/documentation/'+id);if(token!==docsState.token)return;
    const link=docsGet('docs-download');link.href='/api/documentation/'+id+'/download';link.download=item.name;link.hidden=false;
    const content=docsGet('docs-content');content.replaceChildren();content.scrollTop=0;
    if(item.format==='.pdf'){
      const frame=docsNode('iframe');frame.src='/api/documentation/'+id+'/file';frame.title=item.name+' - PDF reader';frame.className='docs-pdf';
      const fallback=docsNode('p',undefined,'docs-pdf-hint'),open=docsNode('a','Open PDF in a new tab');open.href=frame.src;open.target='_blank';open.rel='noopener';fallback.append(open,document.createTextNode(' if your browser does not show the embedded viewer.'));content.append(fallback,frame);docsOutline([],true);
    }else{
      const result=item.format==='.docx'?docsWord(item):docsMarkdown(item.text,item.format==='.txt');content.append(result.article);docsOutline(result.headings);
      const edit=docsGet('docs-edit');edit.hidden=item.format==='.docx';edit.onclick=()=>docsAction('edit',item);
    }
    docsMessage('');
  }catch(error){if(token===docsState.token){docsGet('docs-content').replaceChildren(docsNode('p','Could not open document. '+error.message,'workspace-empty'));docsMessage(error.message);}}
}
function docsAction(type,item=docsItem(docsState.selected)){
  if(docsState.busy)return;
  const dialog=docsGet('docs-action-dialog'),fields=docsGet('docs-action-fields');fields.replaceChildren();docsGet('docs-action-status').textContent='';docsState.action={type,item,parent:docsFolder()};docsState.dirty=false;
  const titles={folder:'New folder',document:'New Markdown document',rename:'Rename',move:'Move to folder',edit:'Edit document'};
  docsGet('docs-action-title').textContent=titles[type];docsGet('docs-action-submit').textContent=type==='move'?'Move':'Save';
  const label=docsNode('label',type==='move'?'Destination':type==='edit'?'Document content':'Name');let input;
  if(type==='move'){
    input=docsNode('select');input.add(new Option('Library (root)',''));
    docsState.items.filter(entry=>entry.kind==='folder'&&!docsDescendant(item.id,entry.id)).sort((a,b)=>docsTrail(a.id).localeCompare(docsTrail(b.id))).forEach(entry=>input.add(new Option(docsTrail(entry.id),String(entry.id))));input.value=item.parent_id??'';
  }else if(type==='edit'){input=docsNode('textarea');input.value=item.text;input.spellcheck=false;input.className='docs-source';}
  else{input=docsNode('input');input.required=true;input.maxLength=200;input.value=type==='rename'?item.name:type==='document'?'Untitled.md':'';input.placeholder=type==='folder'?'Folder name':'Document name.md';}
  input.name='value';input.oninput=()=>docsState.dirty=true;label.append(input);fields.append(label);
  if(type==='document'){const bodyLabel=docsNode('label','Content (Markdown)'),body=docsNode('textarea');body.name='body';body.className='docs-source';body.placeholder='# Title\n\nWrite your documentation...';body.oninput=()=>docsState.dirty=true;bodyLabel.append(body);fields.append(bodyLabel);}
  dialog.classList.toggle('docs-edit-dialog',type==='edit'||type==='document');dialog.showModal();input.focus();
}
function docsCloseAction(){if(docsState.busy)return;if(docsState.dirty&&!confirm('Discard unsaved document changes?'))return;docsGet('docs-action-dialog').close();docsState.action=null;docsState.dirty=false;}
function docsBase64(text){const bytes=new TextEncoder().encode(text);let binary='';for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384));return btoa(binary);}
async function docsSubmit(event){
  event.preventDefault();if(docsState.busy)return;
  const form=event.currentTarget,{type,item,parent}=docsState.action,value=form.elements.value.value;
  docsState.busy=true;Array.from(form.elements).forEach(field=>field.disabled=true);docsGet('docs-action-status').textContent='Saving...';
  try{
    let result;
    if(type==='folder'||type==='document'){
      const name=type==='document'&&!/\.(md|markdown)$/i.test(value)?value+'.md':value;
      result=await docsPost('/api/documentation',{kind:type==='folder'?'folder':'document',name,parent_id:parent,content:type==='document'?docsBase64(form.elements.body.value):''});
    }else result=await docsPost('/api/documentation/'+item.id+'/'+type,type==='move'?{parent_id:value?Number(value):null}:type==='edit'?{content:docsBase64(value)}:{name:value});
    docsState.dirty=false;docsGet('docs-action-dialog').close();if(parent)docsState.opened.add(parent);await loadDocumentation();await docsOpen(result.item.id,true);docsMessage('Saved.');
  }catch(error){docsGet('docs-action-status').textContent=error.message;}
  finally{docsState.busy=false;Array.from(form.elements).forEach(field=>field.disabled=false);}
}
async function docsMove(id,parent){
  if(docsState.busy)return;docsState.busy=true;
  try{await docsPost('/api/documentation/'+id+'/move',{parent_id:parent});if(parent)docsState.opened.add(parent);await loadDocumentation();await docsOpen(id,true);docsMessage('Moved.');}
  catch(error){docsMessage(error.message);}finally{docsState.busy=false;}
}
async function docsUpload(files,parent=docsFolder()){
  if(docsState.busy||!files.length)return;
  docsState.busy=true;let last=null;const errors=[];
  for(const file of files){
    if(file.size>20*1024*1024){errors.push(file.name+': exceeds 20 MB.');continue;}
    docsMessage('Uploading '+file.name+'...');
    try{
      const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]||'');reader.onerror=()=>reject(Error('Could not read file.'));reader.readAsDataURL(file);});
      const result=await docsPost('/api/documentation',{kind:'document',parent_id:parent,name:file.name,content});last=result.item.id;
    }catch(error){errors.push(file.name+': '+error.message);}
  }
  try{if(parent)docsState.opened.add(parent);await loadDocumentation();if(last)await docsOpen(last,true);docsMessage(errors.join(' ')||'Upload complete.');}
  finally{docsState.busy=false;docsGet('docs-file-input').value='';}
}
async function docsUploadFolder(files){
  if(docsState.busy||!files.length)return;
  const supported=files.filter(file=>/\.(pdf|docx|md|markdown|txt)$/i.test(file.name));
  if(!supported.length){docsMessage('No supported documents in this folder. Choose PDF, DOCX, Markdown or text files.');return;}
  const root=docsFolder(),folders=new Map([['',root]]),errors=[];
  docsState.busy=true;let last=null;
  try{
    for(const file of supported){
      if(file.size>20*1024*1024){errors.push(file.name+': exceeds 20 MB.');continue;}
      const parts=(file.webkitRelativePath||file.name).split('/').slice(0,-1);
      let path='',parent=root;
      try{
        for(const part of parts){
          path=path?path+'/'+part:part;
          if(!folders.has(path)){
            const created=await docsPost('/api/documentation',{kind:'folder',name:part,parent_id:parent});
            folders.set(path,created.item.id);docsState.opened.add(created.item.id);
          }
          parent=folders.get(path);
        }
        docsMessage('Uploading '+(file.webkitRelativePath||file.name)+'...');
        const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]||'');reader.onerror=()=>reject(Error('Could not read file.'));reader.readAsDataURL(file);});
        last=(await docsPost('/api/documentation',{kind:'document',name:file.name,parent_id:parent,content})).item.id;
      }catch(error){errors.push(file.name+': '+error.message);}
    }
    await loadDocumentation();if(last)await docsOpen(last,true);
    const skipped=files.length-supported.length;
    docsMessage((last?'Folder upload complete. ':'')+(skipped?skipped+' unsupported file(s) skipped. ':'')+errors.join(' '));
  }catch(error){docsMessage(error.message);}
  finally{docsState.busy=false;docsGet('docs-folder-input').value='';}
}
function docsDropTarget(node,parent){
  node.addEventListener('dragover',event=>{if([...event.dataTransfer.types].some(type=>type==='Files'||type==='application/x-pplanner-doc')){event.preventDefault();event.stopPropagation();node.classList.add('docs-drop-target');}});
  node.addEventListener('dragleave',event=>{if(!node.contains(event.relatedTarget))node.classList.remove('docs-drop-target');});
  node.addEventListener('drop',event=>{event.preventDefault();event.stopPropagation();node.classList.remove('docs-drop-target');if(event.dataTransfer.files.length)docsUpload([...event.dataTransfer.files],parent);else{const id=Number(event.dataTransfer.getData('application/x-pplanner-doc'));if(id)docsMove(id,parent);}});
}
document.addEventListener('DOMContentLoaded',()=>{
  docsGet('docs-new-folder').onclick=()=>docsAction('folder');docsGet('docs-new-document').onclick=()=>docsAction('document');
  docsGet('docs-upload').onclick=()=>{if(!docsState.busy)docsGet('docs-file-input').click();};
  docsGet('docs-file-input').onchange=event=>docsUpload([...event.target.files]);
  docsGet('docs-upload-folder').onclick=()=>{if(!docsState.busy)docsGet('docs-folder-input').click();};
  docsGet('docs-folder-input').onchange=event=>docsUploadFolder([...event.target.files]);
  docsGet('docs-root').onclick=()=>{if(!docsState.busy)docsClear();};docsDropTarget(docsGet('docs-root'),null);docsDropTarget(docsGet('docs-tree'),null);
  docsGet('docs-content').addEventListener('dragover',event=>{if([...event.dataTransfer.types].includes('Files'))event.preventDefault();});
  docsGet('docs-content').addEventListener('drop',event=>{if(event.dataTransfer.files.length){event.preventDefault();docsUpload([...event.dataTransfer.files]);}});
  docsGet('docs-rename').onclick=()=>docsAction('rename');docsGet('docs-move').onclick=()=>docsAction('move');
  docsGet('docs-delete').onclick=async()=>{
    const item=docsItem(docsState.selected);if(!item||docsState.busy||!confirm('Delete "'+item.name+'"'+(item.kind==='folder'?' and all its folders and documents':'')+'? This cannot be undone.'))return;
    docsState.busy=true;try{await docsPost('/api/documentation/'+item.id+'/delete',{});docsClear();await loadDocumentation();docsMessage('Deleted.');}catch(error){docsMessage(error.message);}finally{docsState.busy=false;}
  };
  docsGet('docs-action-form').onsubmit=docsSubmit;docsGet('docs-action-close').onclick=docsCloseAction;docsGet('docs-action-cancel').onclick=docsCloseAction;
  docsGet('docs-action-dialog').addEventListener('cancel',event=>{event.preventDefault();docsCloseAction();});
  window.addEventListener('beforeunload',event=>{if(docsState.busy||docsState.dirty){event.preventDefault();event.returnValue='';}});
});

// Panel choices are saved only in this browser.
function docsPanel(kind,collapsed,persist=true){
  const panel=document.querySelector(kind==='library'?'.docs-library':'.docs-outline');
  const body=docsGet('docs-'+kind+'-body'),toggle=docsGet('docs-'+kind+'-toggle');
  document.querySelector('.docs-layout').classList.toggle('docs-'+kind+'-collapsed',collapsed);
  panel.classList.toggle('is-collapsed',collapsed);body.hidden=collapsed;
  toggle.setAttribute('aria-expanded',String(!collapsed));
  const label=(collapsed?'Expand ':'Collapse ')+(kind==='library'?'library':'document outline');
  toggle.setAttribute('aria-label',label);toggle.title=label;
  if(collapsed&&kind==='library')docsGet('docs-add-menu').open=false;
  if(persist)try{localStorage.setItem('pplanner.docs.'+kind+'Collapsed',String(collapsed));}catch{}
}
function docsSearchClose(){
  docsGet('docs-search-results').hidden=true;
  docsGet('docs-search-input').setAttribute('aria-expanded','false');
}
function docsSearchUnmark(){
  for(const mark of document.querySelectorAll('#docs-content mark.docs-search-match')){
    const parent=mark.parentNode;mark.replaceWith(document.createTextNode(mark.textContent));parent.normalize();
  }
}
function docsSearchMark(query){
  docsSearchUnmark();
  const article=document.querySelector('#docs-content .docs-article');
  if(!article||!query)return;
  const walker=document.createTreeWalker(article,NodeFilter.SHOW_TEXT),nodes=[];
  let text='',node;
  while((node=walker.nextNode())){nodes.push({node,start:text.length,end:text.length+node.length});text+=node.data;}
  const lower=text.toLowerCase(),needle=query.toLowerCase(),matches=[];
  for(let at=lower.indexOf(needle);at>=0&&matches.length<200;at=lower.indexOf(needle,at+Math.max(1,needle.length)))matches.push([at,at+needle.length]);
  for(const entry of nodes.reverse()){
    const overlaps=matches.filter(([start,end])=>start<entry.end&&end>entry.start);
    for(const [start,end]of overlaps.reverse()){
      const range=document.createRange();
      range.setStart(entry.node,Math.max(0,start-entry.start));range.setEnd(entry.node,Math.min(entry.end,end)-entry.start);
      range.surroundContents(docsNode('mark',undefined,'docs-search-match'));
    }
  }
  const first=article.querySelector('.docs-search-match');
  if(first){const reader=docsGet('docs-content');reader.scrollTop+=first.getBoundingClientRect().top-reader.getBoundingClientRect().top-30;}
}
function docsSearchSnippet(target,text,query){
  const lower=text.toLowerCase(),needle=query.toLowerCase();
  let start=0,at=lower.indexOf(needle);
  while(at>=0){target.append(document.createTextNode(text.slice(start,at)),docsNode('mark',text.slice(at,at+query.length)));start=at+query.length;at=lower.indexOf(needle,start);}
  target.append(document.createTextNode(text.slice(start)));
}
async function docsSearchRun(){
  clearTimeout(docsState.searchTimer);docsState.searchAbort?.abort();
  const query=docsGet('docs-search-input').value.trim(),ticket=++docsState.searchTicket;
  docsGet('docs-search-clear').hidden=!query;
  if(query.length<2){docsSearchClose();docsSearchUnmark();return;}
  const controller=new AbortController();docsState.searchAbort=controller;
  const panel=docsGet('docs-search-results'),list=docsGet('docs-search-list'),status=docsGet('docs-search-status');
  panel.hidden=false;docsGet('docs-search-input').setAttribute('aria-expanded','true');list.replaceChildren();status.textContent='Searching documents...';
  try{
    const data=await request('/api/documentation/search?q='+encodeURIComponent(query),{signal:controller.signal});
    if(ticket!==docsState.searchTicket)return;
    status.textContent=data.total?(data.total+' document'+(data.total===1?'':'s')+' found'+(data.total>100?' (showing first 100)':'')+'.'):'No documents found.';
    if(data.skipped.length){
      const warning=docsNode('details',undefined,'docs-search-skipped'),summary=docsNode('summary',data.skipped.length+' document(s) could only be searched by name');warning.append(summary);
      for(const skipped of data.skipped)warning.append(docsNode('p',skipped.name+': '+skipped.reason));
      list.append(warning);
    }
    for(const match of data.matches){
      const button=docsNode('button',undefined,'docs-search-result');button.type='button';
      const title=docsNode('strong');docsSearchSnippet(title,match.name,query);
      const path=docsNode('span',match.path+(match.page?' / Page '+match.page:''),'docs-search-path');
      const snippet=docsNode('span',undefined,'docs-search-snippet');docsSearchSnippet(snippet,match.snippet,query);
      button.append(title,path,snippet);
      button.onclick=async()=>{
        if(docsState.busy)return;
        docsSearchClose();await docsOpen(match.id);
        if(docsState.selected!==match.id)return;
        const frame=document.querySelector('#docs-content .docs-pdf');
        if(frame)frame.src='/api/documentation/'+match.id+'/file#'+(match.page?'page='+match.page+'&':'')+'search='+encodeURIComponent(query);
        else docsSearchMark(query);
      };
      list.append(button);
    }
  }catch(error){if(ticket===docsState.searchTicket&&error.name!=='AbortError')status.textContent='Could not search documents. '+error.message;}
}
document.addEventListener('DOMContentLoaded',()=>{
  const menu=docsGet('docs-add-menu');
  for(const button of menu.querySelectorAll('button'))button.addEventListener('click',()=>{menu.open=false;});
  document.addEventListener('pointerdown',event=>{if(!menu.contains(event.target))menu.open=false;if(!event.target.closest('.docs-search'))docsSearchClose();});
  menu.addEventListener('keydown',event=>{if(event.key==='Escape'){menu.open=false;menu.querySelector('summary').focus();}});
  for(const kind of ['library','outline']){
    let collapsed=false;try{collapsed=localStorage.getItem('pplanner.docs.'+kind+'Collapsed')==='true';}catch{}
    docsPanel(kind,collapsed,false);
    docsGet('docs-'+kind+'-toggle').onclick=()=>docsPanel(kind,docsGet('docs-'+kind+'-toggle').getAttribute('aria-expanded')==='true');
  }
  const input=docsGet('docs-search-input');
  input.addEventListener('input',()=>{
    clearTimeout(docsState.searchTimer);++docsState.searchTicket;docsState.searchAbort?.abort();
    docsGet('docs-search-clear').hidden=!input.value;
    if(input.value.trim().length<2){docsSearchClose();docsSearchUnmark();return;}
    docsState.searchTimer=setTimeout(docsSearchRun,350);
  });
  docsGet('docs-search-form').onsubmit=event=>{event.preventDefault();docsSearchRun();};
  docsGet('docs-search-clear').onclick=()=>{input.value='';docsSearchRun();input.focus();};
  document.querySelector('.docs-search').addEventListener('keydown',event=>{
    if(event.key==='Escape'){docsSearchClose();input.focus();}
    if(event.key==='ArrowDown'&&event.target===input){const first=document.querySelector('.docs-search-result');if(first){event.preventDefault();first.focus();}}
  });
  input.addEventListener('focus',()=>{if(input.value.trim().length>=2&&!docsGet('docs-search-list').childNodes.length)docsSearchRun();else if(input.value.trim().length>=2){docsGet('docs-search-results').hidden=false;input.setAttribute('aria-expanded','true');}});
});
