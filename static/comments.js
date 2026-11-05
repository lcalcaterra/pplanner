// Small, safe comment-format renderer. Uploaded/stored HTML is never executed.
function commentLinkAllowed(url) {
  return /^(https?:\/\/|mailto:)/i.test(url.trim());
}
function commentInline(target,text,depth=0) {
  if(depth>8){target.append(document.createTextNode(text));return;}
  const tokens=/!\[[^\]\n]*\]\(\/api\/comment-images\/[0-9]+\)|https?:\/\/[^\s<>]+|\*\*|~~|\+\+|==|\x60|\*|_|\[/g;
  let start=0,match;
  while((match=tokens.exec(text))) {
    const at=match.index,token=match[0];
    if(at>start)target.append(document.createTextNode(text.slice(start,at)));
    if(token.startsWith('![')) {
      const imageMatch=token.match(/^!\[([^\]]*)\]\((\/api\/comment-images\/[0-9]+)\)$/);
      const link=document.createElement('a');link.href=imageMatch[2];link.target='_blank';link.rel='noopener noreferrer';link.className='comment-image-link';
      const image=document.createElement('img');image.src=imageMatch[2];image.alt=imageMatch[1]||'Comment image';image.className='comment-inline-image';image.loading='lazy';image.decoding='async';
      link.append(image);target.append(link);start=tokens.lastIndex;continue;
    }
    if(/^https?:\/\//i.test(token)) {
      const url=token.replace(/[.,;!?]+$/,'');
      const a=document.createElement('a');a.href=url;a.textContent=url;a.target='_blank';a.rel='noopener noreferrer';
      target.append(a,document.createTextNode(token.slice(url.length)));
      start=tokens.lastIndex;continue;
    }
    if(token==='[') {
      const middle=text.indexOf('](',at+1),end=middle<0?-1:text.indexOf(')',middle+2);
      if(end>=0) {
        const url=text.slice(middle+2,end).trim();
        if(commentLinkAllowed(url)) {
          const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';
          commentInline(a,text.slice(at+1,middle),depth+1);
          target.append(a);start=end+1;tokens.lastIndex=start;continue;
        }
      }
    } else {
      const end=text.indexOf(token,at+token.length);
      const intraword=(token==='_'||token==='*')&&at>0&&/\w/.test(text[at-1]);
      if(end>at+token.length&&!intraword) {
        const tags={'**':'strong','*':'em','_':'em','++':'u','~~':'s','==':'mark','\x60':'code'};
        const node=document.createElement(tags[token]);
        const content=text.slice(at+token.length,end);
        if(token==='\x60')node.textContent=content;else commentInline(node,content,depth+1);
        target.append(node);start=end+token.length;tokens.lastIndex=start;continue;
      }
    }
    target.append(document.createTextNode(token));start=tokens.lastIndex;
  }
  if(start<text.length)target.append(document.createTextNode(text.slice(start)));
}
function renderFormattedComment(target,text) {
  target.replaceChildren();target.classList.add('comment-rich');
  const lines=String(text).replace(/\r\n?/g,'\n').split('\n');
  let paragraph=[],list=null;
  const flush=()=>{if(paragraph.length){const p=document.createElement('p');commentInline(p,paragraph.join('\n'));target.append(p);paragraph=[];}};
  for(let i=0;i<lines.length;i++) {
    const line=lines[i];
    if(line.trim()==='\x60\x60\x60') {
      flush();list=null;const code=[];
      while(++i<lines.length&&lines[i].trim()!=='\x60\x60\x60')code.push(lines[i]);
      const pre=document.createElement('pre'),node=document.createElement('code');node.textContent=code.join('\n');pre.append(node);target.append(pre);continue;
    }
    const item=line.match(/^\s*(?:([-*])\s+|(\d+)\.\s+)(.*)$/);
    if(item) {
      flush();const kind=item[2]?'ol':'ul';
      if(!list||list.tagName.toLowerCase()!==kind){list=document.createElement(kind);target.append(list);}
      const li=document.createElement('li');commentInline(li,item[3]);list.append(li);continue;
    }
    list=null;
    if(/^>\s?/.test(line)) {
      flush();const quote=document.createElement('blockquote');commentInline(quote,line.replace(/^>\s?/,''));target.append(quote);continue;
    }
    if(!line.trim()){flush();continue;}
    paragraph.push(line);
  }
  flush();
}
function clearCommentFormatting(text) {
  return text.replace(/(!?)\[([^\]]+)\]\(([^)]+)\)/g,(all,image,label)=>image?all:label)
    .replace(/\*\*|~~|\+\+|==|\x60\x60\x60|\x60/g,'')
    .replace(/([*_])([^\n]+?)\1/g,'$2')
    .replace(/^\s*(?:>\s?|[-*]\s+|\d+\.\s+)/gm,'');
}
let commentImageUploads=0;
const commentEditors=new WeakMap();
function refreshCommentEditor(input) {
  const state=commentEditors.get(input);if(!state)return;
  state.toolbar.querySelectorAll('button').forEach(button=>button.disabled=input.disabled||Boolean(state.uploading));
  if(!input.value.trim()&&!state.uploading&&state.uploadStatus?.textContent==='Image added. Send the comment to save it.')state.uploadStatus.textContent='';
  if(!state.preview.hidden)renderFormattedComment(state.preview,input.value);
}
function enhanceCommentInput(input,contextProvider) {
  if(!input||commentEditors.has(input))return;
  const toolbar=document.createElement('div');toolbar.className='comment-format-toolbar';toolbar.setAttribute('role','group');toolbar.setAttribute('aria-label','Comment formatting');
  const preview=document.createElement('div');preview.className='comment-format-preview';preview.hidden=true;preview.setAttribute('aria-label','Comment preview');
  const more=document.createElement('details');more.className='comment-format-more';
  const summary=document.createElement('summary');summary.textContent='\u22ef';summary.setAttribute('aria-label','More formatting');
  const menu=document.createElement('div');menu.className='comment-format-options';more.append(summary,menu);
  const state={toolbar,preview,uploading:0};commentEditors.set(input,state);
  function showSource(){input.hidden=false;preview.hidden=true;previewButton.setAttribute('aria-pressed','false');}
  function change(action) {
    if(input.disabled||input.readOnly)return;
    showSource();more.open=false;
    let a=input.selectionStart,b=input.selectionEnd,text=input.value.slice(a,b),replacement='',selectStart=a,selectEnd=b;
    const markers={bold:'**',italic:'*',underline:'++',strike:'~~',highlight:'==',code:'\x60'};
    if(markers[action]) {
      const marker=action==='code'&&text.includes('\n')?'\x60\x60\x60\n':markers[action],endMarker=marker.includes('\n')?'\n\x60\x60\x60':marker;
      text=text||'text';replacement=marker+text+endMarker;selectStart=a+marker.length;selectEnd=selectStart+text.length;
    } else if(['bullet','number','quote'].includes(action)) {
      a=input.value.lastIndexOf('\n',a-1)+1;const end=input.value.indexOf('\n',b);b=end<0?input.value.length:end;
      text=input.value.slice(a,b)||'text';
      replacement=text.split('\n').map((line,index)=>(action==='bullet'?'- ':action==='number'?(index+1)+'. ':'> ')+line).join('\n');
      selectStart=a;selectEnd=a+replacement.length;
    } else if(action==='link') {
      const url=prompt('Link URL (https://, http:// or mailto:)','https://');
      if(url===null)return;
      if(!commentLinkAllowed(url)){alert('Use an https://, http:// or mailto: link.');return;}
      text=text||'link text';replacement='['+text+']('+url.trim().replace(/\)/g,'%29')+')';selectStart=a+1;selectEnd=selectStart+text.length;
    } else {
      if(a===b){a=0;b=input.value.length;}replacement=clearCommentFormatting(input.value.slice(a,b));selectStart=a;selectEnd=a+replacement.length;
    }
    if(input.value.length-(b-a)+replacement.length>input.maxLength&&input.maxLength>0)return;
    input.setRangeText(replacement,a,b,'select');input.focus();input.setSelectionRange(selectStart,selectEnd);
    input.dispatchEvent(new Event('input',{bubbles:true}));
  }
  const tools=[['bold','B','Bold (Ctrl+B)'],['italic','I','Italic (Ctrl+I)'],['underline','U','Underline (Ctrl+U)'],['strike','S','Strikethrough'],['highlight','H','Highlight'],['bullet','\u2022','Bulleted list'],['number','1.','Numbered list'],['quote','Quote','Quote'],['code','Code','Code'],['link','Link','Insert link'],['clear','Clear formatting','Clear formatting']];
  tools.forEach(([action,label,title],index)=>{
    const button=document.createElement('button');button.type='button';button.textContent=label;button.title=title;button.setAttribute('aria-label',title);button.dataset.format=action;
    button.onpointerdown=event=>event.preventDefault();button.onclick=()=>change(action);
    (index<7?toolbar:menu).append(button);
  });
  const imagePicker=document.createElement('input');imagePicker.type='file';imagePicker.accept='image/png,image/jpeg,image/gif,image/webp';imagePicker.multiple=true;imagePicker.hidden=true;
  const imageButton=document.createElement('button');imageButton.type='button';imageButton.textContent='Image';imageButton.title='Insert image (or paste with Ctrl+V)';imageButton.setAttribute('aria-label','Insert image');
  imageButton.onclick=()=>imagePicker.click();
  const uploadStatus=document.createElement('span');uploadStatus.className='comment-image-status';uploadStatus.setAttribute('role','status');uploadStatus.setAttribute('aria-live','polite');state.uploadStatus=uploadStatus;
  async function insertImages(files) {
    if(input.disabled||input.readOnly||state.uploading||!files.length)return;
    const context=contextProvider?.();
    if(!context){uploadStatus.textContent='Open a note or choose a discussion first.';return;}
    showSource();
    state.uploading++;commentImageUploads++;refreshCommentEditor(input);
    const notify=()=>{if(typeof updateCommentSend==='function')updateCommentSend();if(typeof updateDiscussionSend==='function')updateDiscussionSend();};
    notify();
    try {
      for(const file of files) {
        if(file.size>5*1024*1024){uploadStatus.textContent='Each image must be 5 MB or smaller.';continue;}
        const placeholder='[Uploading image '+Math.random().toString(36).slice(2)+']';
        const at=input.selectionStart,end=input.selectionEnd;
        if(input.value.length+placeholder.length+150>input.maxLength){uploadStatus.textContent='There is not enough space in this comment for an image.';continue;}
        input.setRangeText('\n'+placeholder+'\n',at,end,'end');input.dispatchEvent(new Event('input',{bubbles:true}));
        uploadStatus.textContent='Uploading image...';
        try {
          const content=await new Promise((resolve,reject)=>{
            const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]||'');reader.onerror=()=>reject(Error('Could not read image.'));reader.readAsDataURL(file);
          });
          const response=await fetch('/api/comment-images',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...context,content})});
          const result=await response.json();if(!response.ok)throw Error(result.error||'Image upload failed.');
          const index=input.value.indexOf(placeholder);
          if(index>=0) {
            const alt=(file.name||'Image').replace(/[\[\]\r\n]/g,' ').slice(0,100);
            input.setRangeText('!['+alt+']('+result.image.url+')',index,index+placeholder.length,'end');
            input.dispatchEvent(new Event('input',{bubbles:true}));
          }
          uploadStatus.textContent='Image added. Send the comment to save it.';
        } catch(error) {
          const index=input.value.indexOf(placeholder);
          if(index>=0){input.setRangeText('',index,index+placeholder.length,'end');input.dispatchEvent(new Event('input',{bubbles:true}));}
          uploadStatus.textContent='Could not add image. '+error.message;
        }
      }
    } finally {state.uploading--;commentImageUploads--;imagePicker.value='';refreshCommentEditor(input);notify();input.focus();}
  }
  imagePicker.onchange=()=>insertImages([...imagePicker.files]);
  input.addEventListener('paste',event=>{
    const files=[...(event.clipboardData?.items||[])].filter(item=>item.kind==='file'&&item.type.startsWith('image/')).map(item=>item.getAsFile()).filter(Boolean);
    if(files.length){event.preventDefault();insertImages(files);}
  });
  toolbar.append(imageButton,imagePicker);
  toolbar.append(more);
  const previewButton=document.createElement('button');previewButton.type='button';previewButton.textContent='Preview';previewButton.className='comment-preview-toggle';previewButton.setAttribute('aria-pressed','false');
  previewButton.onclick=()=>{
    if(preview.hidden){renderFormattedComment(preview,input.value);preview.style.height=Math.max(90,input.offsetHeight)+'px';preview.hidden=false;input.hidden=true;previewButton.setAttribute('aria-pressed','true');}
    else {showSource();input.focus();}
  };
  toolbar.append(previewButton);
  input.before(toolbar);input.after(preview);
  const composer=input.closest('.comment-composer');if(composer)composer.after(uploadStatus);else input.after(uploadStatus);input.classList.add('comment-formatted-input');
  input.addEventListener('input',()=>refreshCommentEditor(input));
  input.form?.addEventListener('reset',()=>setTimeout(()=>{showSource();refreshCommentEditor(input);},0));
  input.addEventListener('keydown',event=>{
    if((event.ctrlKey||event.metaKey)&&!event.altKey&&['b','i','u'].includes(event.key.toLowerCase())) {
      event.preventDefault();change({b:'bold',i:'italic',u:'underline'}[event.key.toLowerCase()]);
    }
  });
  refreshCommentEditor(input);
}
enhanceCommentInput(document.querySelector('#comment-body'),()=>editorNote?{note_id:editorNote.id}:null);
enhanceCommentInput(document.querySelector('#project-comment-body'),()=>discussionContext?{project_id:discussionContext.projectId,task_id:discussionContext.taskId}:null);

document.addEventListener('click',event=>{
  if(commentImageUploads&&event.target.closest('.page-nav a')){event.preventDefault();event.stopPropagation();}
},true);
window.addEventListener('beforeunload',event=>{if(commentImageUploads){event.preventDefault();event.returnValue='';}});
