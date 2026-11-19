"""Private documentation library: SQLite originals and safe DOCX reading models."""
import base64
import binascii
import io
import re
import zipfile
import hashlib
import threading
from collections import OrderedDict
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

MAX_FILE = 20 * 1024 * 1024
MAX_REQUEST = 28 * 1024 * 1024
SCHEMA = """
CREATE TABLE IF NOT EXISTS documentation (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 parent_id INTEGER REFERENCES documentation(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('folder','document')),
 name TEXT NOT NULL,
 content TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS documentation_parent ON documentation(parent_id,kind,name);
"""
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
MEDIA = {'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         '.md':'text/markdown','.markdown':'text/markdown','.txt':'text/plain'}

def name_value(value):
    if not isinstance(value,str) or not value.strip() or len(value)>200 or any(ord(c)<32 or c in '/\\' for c in value) or value.strip() in ('.','..'):
        raise ValueError("Use a name of 1-200 characters without slashes or control characters.")
    return value.strip()

def extension(name):
    return PurePosixPath(name.lower()).suffix

def decode(name, content):
    if extension(name) not in MEDIA:
        raise ValueError("Supported documents: .pdf, .docx, .md, .markdown and .txt.")
    if not isinstance(content,str) or len(content)>MAX_REQUEST:
        raise ValueError("Document exceeds 20 MB.")
    try:
        raw=base64.b64decode(content,validate=True)
    except (ValueError,binascii.Error) as exc:
        raise ValueError("Invalid document content.") from exc
    if len(raw)>MAX_FILE:
        raise ValueError("Document exceeds 20 MB.")
    ext=extension(name)
    if ext=='.pdf' and not raw.startswith(b'%PDF-'):
        raise ValueError("This file is not a PDF.")
    if ext in ('.md','.markdown','.txt'):
        try:
            text=raw.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError("Text documents must use UTF-8 encoding.") from exc
        if '\x00' in text:
            raise ValueError("Invalid text document.")
    if ext=='.docx':
        docx_model(raw)
    return raw

def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError("Document contains unsupported XML declarations.")
    root=ET.fromstring(data)
    stack=[(root,0)]
    count=0
    while stack:
        node,level=stack.pop()
        count+=1
        if level>80 or count>100000:
            raise ValueError("DOCX XML exceeds the supported complexity.")
        stack.extend((child,level+1) for child in node)
    return root

def docx_model(raw):
    """Return content as data, never uploaded HTML. Never extract ZIPs to disk."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist()
            if len(entries)>2000 or sum(i.file_size for i in entries)>60*1024*1024:
                raise ValueError("DOCX expands beyond the supported size.")
            if len({i.filename for i in entries})!=len(entries):
                raise ValueError("DOCX contains duplicate archive entries.")
            document=xml(archive.read('word/document.xml'))
            rels={}
            if 'word/_rels/document.xml.rels' in archive.namelist():
                rels={r.get('Id'):r for r in xml(archive.read('word/_rels/document.xml.rels'))}
            styles={}
            if 'word/styles.xml' in archive.namelist():
                for style in xml(archive.read('word/styles.xml')).findall(W+'style'):
                    outline=style.find('.//'+W+'outlineLvl')
                    if outline is not None:
                        styles[style.get(W+'styleId')]=min(6,int(outline.get(W+'val','0'))+1)
            images=[]
            blocks=[]
            def paragraph(p):
                parts=[]
                def walk(node,link=None):
                    if node.tag==W+'hyperlink':
                        rel=rels.get(node.get(R+'id'))
                        link=rel.get('Target') if rel is not None else None
                    if node.tag==W+'r':
                        props=node.find(W+'rPr')
                        def enabled(tag):
                            item=None if props is None else props.find(W+tag)
                            return item is not None and item.get(W+'val','1') not in ('0','false','off')
                        text=''.join(n.text or '' if n.tag==W+'t' else '\t' if n.tag==W+'tab' else '\n' if n.tag in (W+'br',W+'cr') else '' for n in node.iter() if n.tag in (W+'t',W+'tab',W+'br',W+'cr'))
                        if text:
                            parts.append({'text':text,'bold':enabled('b'),'italic':enabled('i'),'underline':enabled('u'),'link':link})
                        for blip in node.iter(A+'blip'):
                            rel=rels.get(blip.get(R+'embed'))
                            if rel is None or rel.get('TargetMode')=='External':
                                continue
                            target=rel.get('Target','')
                            # Only embedded raster media below word/media is readable.
                            target='word/'+target.removeprefix('./')
                            if not re.fullmatch(r'word/media/[^/\\]+',target):
                                continue
                            data=archive.read(target)
                            media=image_type(data)
                            if media:
                                idx=len(images)
                                images.append((data,media))
                                parts.append({'image':idx})
                        return
                    for child in node:
                        walk(child,link)
                walk(p)
                style=p.find('./'+W+'pPr/'+W+'pStyle')
                style_id='' if style is None else style.get(W+'val','')
                heading=re.search(r'heading\s*([1-6])',style_id,re.I)
                outline=p.find('./'+W+'pPr/'+W+'outlineLvl')
                level=int(heading[1]) if heading else styles.get(style_id,0)
                if outline is not None:
                    level=min(6,int(outline.get(W+'val','0'))+1)
                numbered=p.find('./'+W+'pPr/'+W+'numPr') is not None
                return {'type':'heading' if level else 'paragraph','level':level,'list':numbered,'runs':parts}
            body=document.find(W+'body')
            if body is None:
                raise ValueError("DOCX has no document body.")
            for node in body:
                if node.tag==W+'p':
                    blocks.append(paragraph(node))
                elif node.tag==W+'tbl':
                    blocks.append({'type':'table','rows':[[[paragraph(p) for p in cell.findall(W+'p')] for cell in row.findall(W+'tc')] for row in node.findall(W+'tr')]})
            return blocks,images
    except (zipfile.BadZipFile,KeyError,ET.ParseError,RuntimeError,NotImplementedError,OverflowError) as exc:
        raise ValueError("Could not read this DOCX. Encrypted or damaged files are not supported.") from exc

def image_type(data):
    if len(data)>5*1024*1024:
        return None
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith((b'GIF87a',b'GIF89a')): return 'image/gif'
    if data[:4]==b'RIFF' and data[8:12]==b'WEBP': return 'image/webp'
    return None

def metadata(row):
    return {key:row[key] for key in ('id','parent_id','kind','name','created_at','updated_at')}

def folder(db, value):
    if value is None: return None
    if type(value) is not int or value<1:
        raise ValueError("Choose a valid destination folder.")
    row=db.execute("SELECT kind FROM documentation WHERE id=?",(value,)).fetchone()
    if not row or row['kind']!='folder':
        raise ValueError("Destination folder does not exist.")
    return value

def depth(db, parent):
    seen=set()
    while parent is not None:
        if parent in seen or len(seen)>=32:
            raise ValueError("Folders support up to 32 nested levels.")
        seen.add(parent)
        parent=record(db,parent)["parent_id"]
    return len(seen)

def record(db, ident):
    row=db.execute("SELECT * FROM documentation WHERE id=?",(ident,)).fetchone()
    if row is None: raise LookupError("Document or folder not found.")
    return row

def check_hierarchy(db):
    rows={r['id']:r for r in db.execute("SELECT * FROM documentation")}
    for row in rows.values():
        depth(db,row['parent_id'])
        name_value(row['name'])
        if row['kind'] not in ('folder','document'): raise ValueError("Invalid documentation item.")
        if row['kind']=='folder':
            if row['content']: raise ValueError("Folders cannot contain file content.")
        else:
            decode(row['name'],row['content'])
        seen={row['id']}
        parent=row['parent_id']
        while parent is not None:
            if parent in seen or parent not in rows or rows[parent]['kind']!='folder':
                raise ValueError("Invalid documentation folder hierarchy.")
            seen.add(parent)
            parent=rows[parent]['parent_id']

def read(db,path):
    if path=='/api/documentation':
        return {'items':[metadata(r) for r in db.execute("SELECT id,parent_id,kind,name,created_at,updated_at FROM documentation ORDER BY kind DESC,name COLLATE NOCASE,id")]}
    match=re.fullmatch(r'/api/documentation/([0-9]+)',path)
    if not match: raise LookupError("Documentation route not found.")
    row=record(db,int(match[1]))
    result=metadata(row)
    if row['kind']=='document':
        raw=decode(row['name'],row['content'])
        ext=extension(row['name'])
        result['format']=ext
        if ext=='.docx':
            result['blocks']=docx_model(raw)[0]
        elif ext!='.pdf':
            result['text']=raw.decode('utf-8-sig')
    return {'item':result}

def write(db,path,payload):
    if path=='/api/documentation':
        kind=payload.get('kind')
        if kind not in ('folder','document'): raise ValueError("Choose folder or document.")
        name=name_value(payload.get('name'))
        parent=folder(db,payload.get('parent_id'))
        depth(db,parent)
        content=payload.get('content','') if kind=='document' else ''
        if kind=='document': decode(name,content)
        ident=db.execute("INSERT INTO documentation(parent_id,kind,name,content) VALUES (?,?,?,?)",(parent,kind,name,content)).lastrowid
        return 201,{'item':metadata(record(db,ident))}
    match=re.fullmatch(r'/api/documentation/([0-9]+)/(move|rename|delete|edit)',path)
    if not match: raise LookupError("Documentation route not found.")
    ident=int(match[1]); action=match[2]; row=record(db,ident)
    if action=='delete':
        db.execute("DELETE FROM documentation WHERE id=?",(ident,))
        return 200,{'deleted':True}
    if action=='move':
        parent=folder(db,payload.get('parent_id'))
        depth(db,parent)
        ancestor=parent
        while ancestor is not None:
            if ancestor==ident: raise ValueError("A folder cannot be moved into itself or its descendants.")
            ancestor=record(db,ancestor)['parent_id']
        db.execute("UPDATE documentation SET parent_id=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(parent,ident))
    elif action=='rename':
        name=name_value(payload.get('name'))
        if row['kind']=='document' and extension(name)!=extension(row['name']):
            raise ValueError("Keep the document's original file extension.")
        db.execute("UPDATE documentation SET name=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(name,ident))
    else:
        if row['kind']!='document' or extension(row['name']) not in ('.md','.markdown','.txt'):
            raise ValueError("Only Markdown and text documents can be edited here.")
        content=payload.get('content')
        decode(row['name'],content)
        db.execute("UPDATE documentation SET content=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(content,ident))
    if action=='move':
        for entry in db.execute("SELECT parent_id FROM documentation"):
            depth(db,entry['parent_id'])
    return 200,{'item':metadata(record(db,ident))}

# Search data is a bounded process-local cache; originals remain the backup source.
_SEARCH_CACHE = OrderedDict()
_SEARCH_CACHE_BYTES = 0
_SEARCH_LOCK = threading.Lock()
_SEARCH_BUDGET = 8 * 1024 * 1024

def searchable_pages(name, content):
    global _SEARCH_CACHE_BYTES
    key=(extension(name),hashlib.sha256(content.encode("ascii")).digest())
    with _SEARCH_LOCK:
        if key in _SEARCH_CACHE:
            value,size=_SEARCH_CACHE.pop(key)
            _SEARCH_CACHE[key]=(value,size)
            return value
    raw=decode(name,content)
    ext=extension(name)
    if ext=='.pdf':
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF content search needs pypdf. Install requirements.txt and restart the app.") from exc
        try:
            reader=PdfReader(io.BytesIO(raw),strict=False)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("Password-protected PDF content is not searchable.")
            pages=[(i+1,page.extract_text() or "") for i,page in enumerate(reader.pages)]
            if not any(text.strip() for _,text in pages):
                raise ValueError("This PDF has no extractable text; scanned pages need OCR.")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Could not extract this PDF's text.") from exc
    elif ext=='.docx':
        def block_text(block):
            if block["type"]=="table":
                return "\n".join(block_text(part) for row in block["rows"] for cell in row for part in cell)
            return "".join(run.get("text","") for run in block["runs"])
        pages=[(None,"\n".join(block_text(block) for block in docx_model(raw)[0]))]
    else:
        pages=[(None,raw.decode("utf-8-sig"))]
    size=sum(len(text.encode("utf-8")) for _,text in pages)
    if size<=_SEARCH_BUDGET:
        with _SEARCH_LOCK:
            # Another search may have filled the same entry while extraction ran.
            if key not in _SEARCH_CACHE:
                while _SEARCH_CACHE and (_SEARCH_CACHE_BYTES+size>_SEARCH_BUDGET or len(_SEARCH_CACHE)>=128):
                    _,(_,removed)=_SEARCH_CACHE.popitem(last=False)
                    _SEARCH_CACHE_BYTES-=removed
                _SEARCH_CACHE[key]=(pages,size)
                _SEARCH_CACHE_BYTES+=size
    return pages

def search(db,query):
    if not isinstance(query,str) or not 2<=len(query.strip())<=200:
        raise ValueError("Search with 2-200 characters.")
    query=query.strip()
    if not db.in_transaction:
        db.execute("BEGIN")  # Keep folder paths and document contents in one read snapshot.
    needle=query.casefold()
    matches=[]; skipped=[]
    parents={row["id"]:(row["parent_id"],row["name"]) for row in db.execute("SELECT id,parent_id,name FROM documentation WHERE kind='folder'")}
    for row in db.execute("SELECT * FROM documentation WHERE kind='document' ORDER BY name COLLATE NOCASE,id"):
        title_match=needle in row["name"].casefold()
        page=None;snippet="";content_match=False
        try:
            for number,text in searchable_pages(row["name"],row["content"]):
                text=" ".join(text.split())
                at=text.casefold().find(needle)
                if at>=0:
                    page=number;content_match=True
                    snippet=("..." if at>65 else "")+text[max(0,at-65):at+len(query)+125]+("..." if at+len(query)+125<len(text) else "")
                    break
        except ValueError as exc:
            skipped.append({"id":row["id"],"name":row["name"],"reason":str(exc)})
        if not title_match and not content_match:
            continue
        path=[];parent=row["parent_id"]
        while parent is not None:
            parent,label=parents[parent];path.insert(0,label)
        matches.append({**metadata(row),"path":" / ".join(["Library",*path]),"snippet":snippet or "Matched document name.","page":page,"content_match":content_match})
    matches.sort(key=lambda item:(not item["content_match"],item["name"].casefold(),item["id"]))
    return {"query":query,"matches":matches[:100],"total":len(matches),"skipped":skipped}
