"""Isolated real-browser documentation checks; never opens the user's database."""
import base64
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

def fixtures():
    word=io.BytesIO()
    text='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Word guide</w:t></w:r></w:p><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Formatted DOCX content</w:t></w:r></w:p></w:body></w:document>'
    with zipfile.ZipFile(word,"w") as archive: archive.writestr(zipfile.ZipInfo("word/document.xml",date_time=(2026,1,1,0,0,0)),text)
    objects=[b"<< /Type /Catalog /Pages 2 0 R >>",b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 500] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",b"<< /Length 51 >>\nstream\nBT /F1 20 Tf 40 440 Td (Documentation PDF) Tj ET\nendstream"]
    pdf=b"%PDF-1.4\n";offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(pdf));pdf+=str(i).encode()+b" 0 obj\n"+obj+b"\nendobj\n"
    start=len(pdf);pdf+=b"xref\n0 6\n0000000000 65535 f \n"+b"".join(("%010d 00000 n \n"%offset).encode() for offset in offsets)+b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"+str(start).encode()+b"\n%%EOF"
    return {"word":base64.b64encode(word.getvalue()).decode(),"pdf":base64.b64encode(pdf).decode()}

TEST=r"""
document.addEventListener('DOMContentLoaded',async()=>{
 const result={checks:[],errors:[]};
 const assert=(value,message)=>{if(!value)throw Error(message);};
 const wait=async fn=>{for(let i=0;i<120;i++){if(fn())return;await new Promise(r=>setTimeout(r,50));}throw Error('Timed out waiting for UI');};
 const q=s=>document.querySelector(s);
 addEventListener('unhandledrejection',event=>result.errors.push(String(event.reason?.stack||event.reason)));
 function fill(name,value){const field=q('#docs-action-form').elements[name];field.value=value;field.dispatchEvent(new Event('input',{bubbles:true}));}
 async function submit(){q('#docs-action-form').requestSubmit();await wait(()=>!docsState.busy&&!q('#docs-action-dialog').open);}
 async function createFolder(name){q('#docs-new-folder').click();fill('value',name);await submit();return docsState.selected;}
 try{
  location.hash='documentation';await showPage();
  assert(!q('#documentation-page').hidden,'Documentation navigation failed');
  assert(q('#docs-content').textContent.includes('Open a document'),'Initial reader prompt missing');
  const folder=await createFolder('Engineering');
  q('#docs-new-document').click();fill('value','Getting started.md');
  fill('body','# Getting started\n\nPrivate documentation for your workspace.\n\n## Installation\n\nUse **Docker** or Python.\n\n## Daily workflow\n\n- Capture a note\n- Review projects\n\n### Details\n\n<script>window.docsInjected=true</script>\n\n| Feature | Available |\n| --- | --- |\n| Offline | Yes |\n\n'+Array.from({length:18},(_,i)=>'## Section '+i+'\n\nReference information for this section.').join('\n\n'));
  await submit();const documentId=docsState.selected;
  assert(q('#docs-content strong')?.textContent==='Docker','Markdown bold missing');
  assert(q('#docs-content table'),'Markdown table missing');
  assert(q('#docs-outline-links').querySelectorAll('button').length>20,'Heading outline missing');
  assert(!window.docsInjected&&!q('#docs-content script'),'Uploaded markup executed');
  q('#docs-outline-links button:last-child').click();await wait(()=>q('#docs-content').scrollTop>0);
  const left=q('.docs-library').getBoundingClientRect(),center=q('.docs-reader').getBoundingClientRect(),right=q('.docs-outline').getBoundingClientRect();
  assert(left.right<center.left&&center.right<right.left,'Desktop columns overlap');
  assert(q('.docs-reader').scrollHeight<=q('.docs-reader').clientHeight+1,'Reader outer container overflows');
  result.checks.push('Create folders and Markdown; safe formatting, tables, headings, outline navigation and independent reader scroll');
  q('#docs-edit').click();fill('value','# Updated guide\n\nEdited documentation.');await submit();
  assert(q('#docs-content h1')?.textContent==='Updated guide','Document edit did not persist');
  assert((await request('/api/documentation/'+documentId)).item.text.includes('Edited documentation'),'Saved edit not returned');
  const destination=await createFolder('Reference');
  await docsMove(documentId,destination);
  assert(docsItem(documentId).parent_id===destination,'Move did not persist');
  const row=[...document.querySelectorAll('.docs-tree-row')].find(row=>row.querySelector('.docs-tree-open')?.title==='Getting started.md');
  const transfer=new DataTransfer();transfer.setData('application/x-pplanner-doc',String(documentId));
  row.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:transfer}));
  q('#docs-root').dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:transfer}));
  await wait(()=>!docsState.busy&&docsItem(documentId).parent_id===null);
  result.checks.push('Markdown editing and folder/document moves, including drag and drop to root');
  const fixtures=await request('/documentation-fixtures');
  const bytes=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
  q('#docs-root').click();
  const uploads=new DataTransfer();uploads.items.add(new File([bytes(fixtures.word)],'Word guide.docx'));uploads.items.add(new File([bytes(fixtures.pdf)],'Schedule.pdf'));
  q('#docs-content').dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:uploads}));
  await wait(()=>!docsState.busy&&docsState.items.some(item=>item.name==='Schedule.pdf'));
  const pdf=docsState.items.findLast(item=>item.name==='Schedule.pdf'),word=docsState.items.findLast(item=>item.name==='Word guide.docx');
  await docsOpen(word.id);assert(q('#docs-content h1')?.textContent==='Word guide','DOCX heading missing');assert(q('#docs-content strong')?.textContent==='Formatted DOCX content','DOCX formatting missing');
  assert(q('#docs-outline-links button')?.textContent==='Word guide','DOCX outline missing');
  assert(q('#docs-edit').hidden,'DOCX should not show source editor');
  const original=await fetch('/api/documentation/'+word.id+'/download');assert(btoa(String.fromCharCode(...new Uint8Array(await original.arrayBuffer())))===fixtures.word,'Original DOCX download changed');
  await docsOpen(pdf.id);assert(q('#docs-content iframe')?.src.includes('/file'),'Embedded PDF viewer missing');
  const pdfResponse=await fetch('/api/documentation/'+pdf.id+'/file');assert(pdfResponse.headers.get('content-type')==='application/pdf','PDF MIME incorrect');
  result.checks.push('Drag/drop DOCX and PDF upload, DOCX reading and outline, original download, embedded PDF route');
  await docsOpen(folder);
  q('#docs-rename').click();fill('value','Product documentation');await submit();assert(docsItem(folder).name==='Product documentation','Folder rename failed');
  const backup=await request('/api/data/export');assert(backup.tables.documentation.length===docsState.items.length,'Documentation missing from backup');
  const oldConfirm=window.confirm;window.confirm=()=>true;
  q('#docs-delete').click();await wait(()=>!docsState.busy&&!docsItem(folder));window.confirm=oldConfirm;
  result.checks.push('Folder rename, confirmed recursive deletion and backup inclusion');
  q('#docs-root').click();
  const folderFile=new File(['# Imported directory'], 'overview.md');
  Object.defineProperty(folderFile,'webkitRelativePath',{value:'Imported/Nested/overview.md'});
  await docsUploadFolder([folderFile]);
  const imported=docsState.items.find(item=>item.name==='overview.md');
  assert(imported&&docsItem(imported.parent_id).name==='Nested'&&docsItem(docsItem(imported.parent_id).parent_id).name==='Imported','Folder upload lost its hierarchy');
  result.checks.push('Directory upload preserves nested folders');
  await docsOpen(documentId);
  q('#docs-add-menu summary').click();
  assert(q('#docs-add-menu').open,'Plus menu did not open');
  assert(q('#docs-add-menu').querySelectorAll('button').length===4,'Creation/upload options missing');
  q('#docs-new-folder').click();assert(q('#docs-action-dialog').open&&!q('#docs-add-menu').open,'Plus menu action did not open form and close menu');
  q('#docs-action-cancel').click();
  const readerWidth=q('.docs-reader').getBoundingClientRect().width;
  q('#docs-library-toggle').click();
  const wideLeft=q('.docs-reader').getBoundingClientRect().width;
  assert(wideLeft>readerWidth+150&&q('#docs-library-body').hidden,'Collapsing library did not widen reader');
  q('#docs-outline-toggle').click();
  assert(q('.docs-reader').getBoundingClientRect().width>wideLeft+100&&q('#docs-outline-body').hidden,'Collapsing outline did not widen reader');
  assert(localStorage.getItem('pplanner.docs.libraryCollapsed')==='true','Panel preference not saved');
  q('#docs-library-toggle').click();q('#docs-outline-toggle').click();
  assert(Math.abs(q('.docs-reader').getBoundingClientRect().width-readerWidth)<2,'Expanded panels did not restore reader width');
  result.checks.push('Plus menu actions and independently collapsing panels reclaim and restore reader width');
  async function searchDocs(query){q('#docs-search-input').value=query;await docsSearchRun();assert(!q('#docs-search-results').hidden,'Search results not shown');}
  await searchDocs('Edited documentation');
  assert(q('.docs-search-result')?.textContent.includes('Getting started.md'),'Body-only Markdown content was not found');
  q('.docs-search-result').click();await wait(()=>!!q('#docs-content .docs-search-match'));
  assert(q('#docs-content .docs-search-match').textContent==='Edited documentation','Markdown match not highlighted');
  await searchDocs('Formatted DOCX content');
  assert(q('.docs-search-result')?.textContent.includes('Word guide.docx'),'DOCX content was not found');
  q('.docs-search-result').click();await wait(()=>q('#docs-content .docs-search-match')?.textContent==='Formatted DOCX content');
  await searchDocs('Documentation PDF');
  assert(q('.docs-search-result')?.textContent.includes('Schedule.pdf'),'PDF body text was not found');
  q('.docs-search-result').click();await wait(()=>q('#docs-content iframe')?.src.includes('#page=1&search='));
  await searchDocs('zzzz-no-document-match');
  assert(!q('.docs-search-result')&&q('#docs-search-status').textContent==='No documents found.','Empty search state missing');
  q('#docs-search-clear').click();assert(q('#docs-search-results').hidden&&!q('#docs-search-input').value,'Clear search failed');
  result.checks.push('Library-wide Markdown, DOCX and PDF content search, match highlighting, PDF page jump, empty results and clearing');
  await docsOpen(documentId);
  result.passed=true;
 }catch(error){result.errors.push(String(error.stack||error));result.passed=false;}
 const report=document.createElement('pre');report.id='documentation-test-results';report.textContent=JSON.stringify(result);report.hidden=true;document.body.append(report);
});
"""
class Handler(server.Handler):
    def do_GET(self):
        if self.path.startswith('/documentation-test.js'):
            raw=TEST.encode();self.send_response(200);self.send_header('Content-Type','text/javascript');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
        if self.path=='/documentation-fixtures':
            self.respond(200,fixtures());return
        if self.path=='/documentation-test':
            raw=(server.ROOT/'static/index.html').read_text().replace('</head>','<script src="/documentation-test.js" defer></script></head>').encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'");self.end_headers();self.wfile.write(raw);return
        super().do_GET()

if __name__=='__main__':
    with tempfile.TemporaryDirectory() as temp:
        server.DB=Path(temp)/'docs-test.sqlite3';server.initialize()
        app=server.ThreadingHTTPServer(('127.0.0.1',8766),Handler)
        print('DOCUMENTATION FIXTURE http://localhost:8766/documentation-test',flush=True)
        try: app.serve_forever()
        except KeyboardInterrupt: pass
        finally: app.server_close()
