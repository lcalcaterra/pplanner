const $ = (selector, root = document) => root.querySelector(selector);
let today = new Date(), displayedClock = null;
function key(date) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
}
function shift(date, days) { const result = new Date(date); result.setDate(result.getDate() + days); return result; }
function monday(date) { return shift(date, -((date.getDay() + 6) % 7)); }
let week = monday(today), generation = 0;
const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
const month = new Intl.DateTimeFormat('en', {month:'long'});
async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Something went wrong. Please retry.');
  return data;
}
let mutationBusy = false, pendingCreates = 0, dragged = null, suppressClickUntil = 0;
const noteModels = new Map();
function card(note) {
  noteModels.set(note.id, note);
  const article = document.createElement('article');
  article.className = 'note' + (note.completed ? ' completed' : '');
  article.dataset.id = note.id;
  article.draggable = true;
  article.tabIndex = 0;
  article.title = 'Click to edit. Drag to move.';
  article.setAttribute('aria-label', 'Note: ' + note.body.slice(0, 100) + '. Press Enter to edit.');
  article.onclick = event => {
    if (!event.target.closest('button,select,input,textarea') && !dragged && Date.now() >= suppressClickUntil && !window.getSelection()?.toString()) openEditor(note);
  };
  article.onkeydown = event => {
    if (event.target === article && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      openEditor(note);
    }
  };
  const toolbar = document.createElement('div');
  toolbar.className = 'note-toolbar';
  const complete = document.createElement('button');
  complete.className = 'complete-note';
  complete.type = 'button';
  complete.setAttribute('aria-label', note.completed ? 'Mark note unfinished' : 'Mark note completed');
  complete.setAttribute('aria-pressed', String(Boolean(note.completed)));
  complete.textContent = note.completed ? '\u2713' : '';
  complete.onclick = () => mutate(note, 'complete', {completed: !note.completed}, 'Completion saved.');
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'delete-note';
  remove.setAttribute('aria-label', 'Delete note');
  remove.title = 'Delete note';
  const bin = document.createElement('img');
  bin.src = '/imgs/bin.png';
  bin.alt = '';
  bin.width = 18;
  bin.height = 18;
  bin.draggable = false;
  remove.append(bin);
  remove.onclick = async () => {
    if (mutationBusy || pendingCreates) return;
    if (window.confirm('Delete this note and all its comments? This cannot be undone.')) {
      await mutate(note, 'delete', {}, 'Note deleted.');
      const column = document.querySelector('[data-date="' + note.date + '"]');
      if (column) $('.add-note', column).focus({preventScroll:true});
    }
  };
  toolbar.append(complete,remove);
  const body = document.createElement('p');
  body.className = 'note-body';
  body.textContent = note.body;
  const time = document.createElement('time');
  time.className = 'note-time';
  time.dateTime = note.created_at;
  time.textContent = 'Added ' + new Intl.DateTimeFormat('en', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(note.created_at));
  const controls = document.createElement('div');
  controls.className = 'note-controls';
  for (const [direction, symbol] of [['up','\u2191'], ['down','\u2193']]) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = symbol;
    button.setAttribute('aria-label', 'Move note ' + direction);
    button.onclick = () => {
      const siblings = groupCards(article.closest('.day'), note);
      const index = siblings.indexOf(article);
      const next = direction === 'up' ? siblings[index - 1] : siblings[index + 1];
      if (!next) return;
      const before = direction === 'up' ? next : siblings[index + 2];
      mutate(note, 'move', {date:note.date, before_id:before ? Number(before.dataset.id) : null}, 'Note reordered.');
    };
    controls.append(button);
  }
  const select = document.createElement('select');
  select.setAttribute('aria-label', 'Move note to weekday');
  for (let i = 0; i < 5; i++) {
    const option = document.createElement('option');
    option.value = key(shift(week,i));
    option.textContent = days[i];
    option.selected = option.value === note.date;
    select.append(option);
  }
  select.onchange = () => {
    const target = select.value;
    select.value = note.date;
    mutate(note,'move',{date:target},'Note moved.');
  };
  controls.append(select);
  article.append(toolbar,body,time,controls);
  article.ondragstart = event => {
    if (mutationBusy || event.target.closest('button,select,input,textarea')) { event.preventDefault(); return; }
    dragged = note;
    suppressClickUntil = Date.now() + 500;
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain',String(note.id));
    article.classList.add('dragging');
  };
  article.ondragend = () => { suppressClickUntil = Date.now() + 250; setTimeout(() => { dragged = null; }, 0); clearDropHints(); article.classList.remove('dragging'); };
  return article;
}
function groupCards(column, note) {
  return [...column.querySelectorAll('.note')].filter(el => Boolean(noteModels.get(Number(el.dataset.id)).completed) === Boolean(note.completed));
}
function refreshControls(column) {
  for (const completed of [false,true]) {
    const cards = groupCards(column,{completed});
    cards.forEach((el,index) => {
      const buttons = el.querySelectorAll('.note-controls button');
      buttons[0].disabled = mutationBusy || index === 0;
      buttons[1].disabled = mutationBusy || index === cards.length - 1;
    });
  }
}
function clearDropHints() {
  document.querySelectorAll('.drop-target,.drop-before').forEach(el => el.classList.remove('drop-target','drop-before'));
}
function dropPosition(column, y) {
  return groupCards(column,dragged).find(el => {
    if (Number(el.dataset.id) === dragged.id) return false;
    const rect = el.getBoundingClientRect();
    return y < rect.top + rect.height / 2;
  });
}
function enableDrop(column) {
  column.ondragover = event => {
    if (!dragged || mutationBusy) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    clearDropHints();
    column.classList.add('drop-target');
    const before = dropPosition(column,event.clientY);
    if (before) before.classList.add('drop-before');
    const content = $('.day-content',column), rect = content.getBoundingClientRect();
    if (event.clientY < rect.top + 45) content.scrollTop -= 14;
    if (event.clientY > rect.bottom - 45) content.scrollTop += 14;
  };
  column.ondrop = event => {
    if (!dragged || mutationBusy) return;
    event.preventDefault();
    const before = dropPosition(column,event.clientY);
    const note = dragged;
    dragged = null;
    clearDropHints();
    mutate(note,'move',{date:column.dataset.date,before_id:before ? Number(before.dataset.id) : null},'Note moved.');
  };
}
async function mutate(note, action, payload, message) {
  if (mutationBusy || pendingCreates) { $('#status').textContent = 'Please wait for the current save to finish.'; return; }
  mutationBusy = true;
  const current = generation;
  $('#status').textContent = 'Saving change...';
  document.querySelectorAll('.note button,.note select').forEach(el => el.disabled = true);
  try {
    const data = await request('/api/notes/' + note.id + '/' + action, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if (current !== generation) return;
    const affected = data.notes ? (data.dates || [note.date]) : [];
    for (const date of affected) {
      const column = document.querySelector('[data-date="' + date + '"]');
      if (!column) continue;
      const notes = $('.notes',column);
      notes.replaceChildren(...data.notes.filter(n => n.date === date).map(card));
      updateCount(column);
    }
    $('#status').textContent = message;
    const updated = document.querySelector('.note[data-id="' + note.id + '"]');
    if (updated && !$('#note-editor').open) $('.complete-note',updated).focus({preventScroll:true});
    return data;
  } catch (err) {
    const message = 'Could not save the change. ' + err.message;
    if (current === generation) $('#status').textContent = message;
    if ($('#note-editor').open) $('#editor-status').textContent = message;
  } finally {
    mutationBusy = false;
    document.querySelectorAll('.note button,.note select').forEach(el => el.disabled = false);
    document.querySelectorAll('.day').forEach(refreshControls);
  }
}
function updateCount(column) {
  refreshControls(column);
  const count = $('.notes', column).children.length;
  $('.day-count', column).textContent = count ? count + (count === 1 ? ' NOTE' : ' NOTES') : 'A FRESH START';
  $('.empty', column).hidden = count > 0 || Boolean($('form', column));
}
function openForm(column, selected) {
  if ($('form', column)) { $('textarea', column).focus(); return; }
  const form = document.createElement('form');
  form.innerHTML = '<label>Date<input type="date" name="date" required></label><label>Your note<textarea name="body" placeholder="What?s on your mind?" maxlength="10000" required></textarea></label><p class="form-error" role="alert"></p><div class="form-actions"><button type="button" class="cancel">Cancel</button><button type="submit" class="insert">Insert note</button></div>';
  form.elements.date.value = selected;
  $('.composer', column).append(form);
  updateCount(column);
  $('.day-content', column).scrollTop = 0;
  form.elements.body.focus();
  $('.cancel', form).onclick = () => { form.remove(); updateCount(column); $('.add-note', column).focus(); };
  form.onsubmit = async event => {
    event.preventDefault();
    if (mutationBusy) { $('.form-error', form).textContent = 'Wait for the current change to finish, then insert your note.'; return; }
    const button = $('.insert', form);
    const selectedDate = form.elements.date.value;
    const body = form.elements.body.value;
    const error = $('.form-error', form);
    if (!body.trim()) { error.textContent = 'Write a note before inserting it.'; return; }
    if ([0,6].includes(new Date(selectedDate + 'T12:00:00').getDay())) { error.textContent = 'Choose Monday to Friday.'; return; }
    pendingCreates++;
    button.disabled = true;
    button.textContent = 'Saving?';
    error.textContent = '';
    try {
      const {note} = await request('/api/notes', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:selectedDate,body})});
      form.remove();
      updateCount(column);
      const destination = document.querySelector('[data-date="' + note.date + '"]');
      if (destination) {
        $('.notes', destination).prepend(card(note));
        updateCount(destination);
        $('.day-content', destination).scrollTop = 0;
      }
      $('#status').textContent = destination ? '' : 'Note saved for ' + note.date + '. Navigate to that week to see it.';
      if (column.isConnected) $('.add-note', column).focus();
    } catch (err) { error.textContent = 'Could not save. ' + err.message; }
    finally { pendingCreates--; button.disabled = false; button.textContent = 'Insert note'; }
  };
};
async function render(preserveDrafts = false) {
  const current = ++generation;
  try {
    const clock = await request('/api/clock');
    if (current !== generation) return;
    if (preserveDrafts === true && (mutationBusy || pendingCreates || editor.open || document.querySelector('.composer form') || dragged)) return;
    const oldMonday = key(monday(today));
    today = new Date(clock.today + 'T12:00:00');
    if (!displayedClock || key(week) === oldMonday) week = monday(today);
    displayedClock = clock.today;
  } catch (err) {
    if (current !== generation) return;
    $('#status').replaceChildren(document.createTextNode('Could not check the current week. ' + err.message + ' '));
    const retry = document.createElement('button');
    retry.className = 'today-button';
    retry.textContent = 'Retry';
    retry.onclick = render;
    $('#status').append(retry);
    return;
  }
  const friday = shift(week,4);
  const range = month.format(week) === month.format(friday) ? month.format(week) + ' ' + week.getDate() + ' - ' + friday.getDate() : month.format(week) + ' ' + week.getDate() + ' - ' + month.format(friday) + ' ' + friday.getDate();
  $('#week-title').textContent = range;
  $('#week-year').textContent = week.getFullYear() === friday.getFullYear() ? week.getFullYear() : week.getFullYear() + ' / ' + friday.getFullYear();
  $('#status').textContent = 'Loading notes?';
  const calendar = $('#calendar');
  calendar.replaceChildren();
  noteModels.clear();
  dragged = null;
  for (let i = 0; i < 5; i++) {
    const date = shift(week,i), selected = key(date);
    const column = $('#day-template').content.firstElementChild.cloneNode(true);
    column.dataset.date = selected;
    column.setAttribute('aria-label', days[i] + ' ' + selected);
    $('.day-name',column).textContent = days[i];
    $('.day-number',column).textContent = String(date.getDate()).padStart(2,'0');
    if (selected === key(today)) { column.classList.add('current'); $('.today-label',column).hidden = false; }
    const add = $('.add-note',column);
    add.setAttribute('aria-label','Add note for ' + days[i] + ' ' + selected);
    add.disabled = true;
    add.onclick = () => openForm(column,selected);
    enableDrop(column);
    calendar.append(column);
    updateCount(column);
  }
  try {
    const {notes} = await request('/api/notes?start=' + key(week) + '&end=' + key(friday));
    if (current !== generation) return;
    for (const note of notes) {
      const column = calendar.querySelector('[data-date="' + note.date + '"]');
      if (column) $('.notes', column).append(card(note));
    }
    calendar.querySelectorAll('.day').forEach(column => { updateCount(column); $('.add-note',column).disabled = false; });
    $('#status').textContent = '';
  } catch (err) {
    if (current !== generation) return;
    $('#status').replaceChildren(document.createTextNode('Could not load notes. ' + err.message + ' '));
    const retry = document.createElement('button');
    retry.textContent = 'Retry';
    retry.className = 'today-button';
    retry.onclick = render;
    $('#status').append(retry);
  }
}
$('#previous').onclick = () => { week = shift(week,-7); render(); };
$('#next').onclick = () => { week = shift(week,7); render(); };
$('#today').onclick = () => { week = monday(today); render(); };
render();

const editor = $('#note-editor');
let editorNote = null, editorToken = 0, editorLoading = false;
function editorDirty() {
  return editorNote && ($('#edit-body').value !== editorNote.body || $('#edit-date').value !== editorNote.date || $('#comment-body').value.trim() || [...document.querySelectorAll('.comment-edit textarea')].some(input => input.value !== input.dataset.original));
}
function closeEditor() {
  if (mutationBusy || editorLoading) { $('#editor-status').textContent = 'Please wait for the current request to finish.'; return; }
  if (editorDirty() && !window.confirm('Discard unsaved changes and the comment draft?')) return;
  editor.close();
}
$('#editor-close').onclick = closeEditor;
editor.addEventListener('cancel', event => { event.preventDefault(); closeEditor(); });
editor.addEventListener('close', () => {
  editorToken++;
  const card = editorNote && document.querySelector('.note[data-id="' + editorNote.id + '"]');
  if (card) card.focus({preventScroll:true});
  editorNote = null;
});
function commentCard(comment) {
  const article = document.createElement('article');
  article.className = 'comment';
  const header = document.createElement('header');
  header.className = 'comment-header';
  const time = document.createElement('time');
  time.dateTime = comment.created_at;
  time.textContent = new Intl.DateTimeFormat('en', {dateStyle:'medium',timeStyle:'short'}).format(new Date(comment.created_at));
  const menu = document.createElement('details');
  menu.className = 'comment-menu';
  const toggle = document.createElement('summary');
  toggle.textContent = '\u22ef';
  toggle.setAttribute('aria-label','Comment actions');
  const actions = document.createElement('div');
  actions.className = 'comment-menu-actions';
  const edit = document.createElement('button');
  edit.type = 'button';
  edit.textContent = 'Edit comment';
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'remove-comment';
  remove.textContent = 'Remove comment';
  actions.append(edit,remove);
  menu.append(toggle,actions);
  menu.addEventListener('toggle', () => {
    if (menu.open) document.querySelectorAll('.comment-menu[open]').forEach(other => { if (other !== menu) other.open = false; });
  });
  menu.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.open) { event.preventDefault(); event.stopPropagation(); menu.open = false; toggle.focus(); }
  });
  const body = document.createElement('p');
  body.textContent = comment.body;
  edit.onclick = () => {
    if (mutationBusy || $('.comment-edit',article)) return;
    menu.open = false;
    const form = document.createElement('form');
    form.className = 'comment-edit';
    const label = document.createElement('label');
    label.textContent = 'Edit comment';
    const input = document.createElement('textarea');
    input.value = comment.body;
    input.dataset.original = comment.body;
    input.required = true;
    input.maxLength = 10000;
    label.append(input);
    const buttons = document.createElement('div');
    buttons.className = 'comment-edit-actions';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'cancel';
    cancel.textContent = 'Cancel';
    const save = document.createElement('button');
    save.type = 'submit';
    save.className = 'insert';
    save.textContent = 'Save';
    buttons.append(cancel,save);
    form.append(label,buttons);
    body.hidden = true;
    menu.hidden = true;
    article.append(form);
    input.focus();
    cancel.onclick = () => { form.remove(); body.hidden = false; menu.hidden = false; toggle.focus(); };
    form.onsubmit = async event => {
      event.preventDefault();
      if (!input.value.trim()) { $('#editor-status').textContent = 'Write a comment before saving.'; input.focus(); return; }
      const result = await editorMutation('comment-edit',{comment_id:comment.id,body:input.value},'Comment updated.');
      if (!result) return;
      const replacement = commentCard(result.comment);
      article.replaceWith(replacement);
      $('#editor-status').textContent = 'Comment updated.';
      $('.comment-menu summary',replacement).focus();
    };
  };
  remove.onclick = async () => {
    if (mutationBusy) return;
    menu.open = false;
    if (!window.confirm('Remove this comment? This cannot be undone.')) { toggle.focus(); return; }
    const result = await editorMutation('comment-delete',{comment_id:comment.id},'Comment removed.');
    if (!result) return;
    article.remove();
    if (!$('#comment-history .comment')) showComments([]);
    $('#editor-status').textContent = 'Comment removed.';
    $('#comment-body').focus();
  };
  header.append(time,menu);
  article.append(header,body);
  return article;
}
async function openEditor(note) {
  if (mutationBusy || pendingCreates || editor.open) return;
  const token = ++editorToken;
  editorNote = null;
  editorLoading = true;
  $('#edit-note-form').reset();
  $('#comment-form').reset();
  $('#comment-history').replaceChildren();
  $('#edit-state').textContent = '';
  $('#editor-status').textContent = 'Loading note...';
  editor.querySelectorAll('input,textarea,button[type="submit"]').forEach(el => el.disabled = true);
  editor.showModal();
  try {
    const data = await request('/api/notes/' + note.id);
    if (token !== editorToken) return;
    editorNote = data.note;
    $('#edit-date').value = data.note.date;
    $('#edit-body').value = data.note.body;
    showComments(data.comments);
    $('#editor-status').textContent = '';
  } catch (err) { $('#editor-status').textContent = 'Could not load note. ' + err.message + ' Close and try again.'; }
  finally {
    editorLoading = false;
    editor.querySelectorAll('input,textarea,button[type="submit"]').forEach(el => el.disabled = !editorNote);
    if (editorNote) $('#edit-body').focus();
  }
}
function showComments(comments) {
  const history = $('#comment-history');
  history.replaceChildren(...comments.map(commentCard));
  if (!comments.length) {
    const empty = document.createElement('p');
    empty.className = 'no-comments';
    empty.textContent = 'No comments yet. Start the conversation with yourself.';
    history.append(empty);
  }
  history.scrollTop = history.scrollHeight;
}
async function editorMutation(action, payload, message) {
  if (!editorNote || mutationBusy || pendingCreates) return;
  $('#editor-status').textContent = 'Saving...';
  editor.querySelectorAll('button,input,textarea').forEach(el => el.disabled = true);
  const result = await mutate(editorNote,action,payload,message);
  editor.querySelectorAll('button,input,textarea').forEach(el => el.disabled = false);
  return result;
}
$('#edit-note-form').onsubmit = async event => {
  event.preventDefault();
  if (!editorNote) return;
  const body = $('#edit-body').value;
  let date = $('#edit-date').value;
  if (!body.trim()) { $('#editor-status').textContent = 'Write a note before saving.'; return; }
  if ([0,6].includes(new Date(date + 'T12:00:00').getDay())) { $('#editor-status').textContent = 'Choose Monday to Friday.'; return; }
  if (date === editorNote.date) {
    try {
      const latest = await request('/api/notes/' + editorNote.id);
      if (latest.note.date !== editorNote.date) {
        date = latest.note.date;
        $('#edit-date').value = date;
      }
    } catch (err) { $('#editor-status').textContent = 'Could not check the note date. ' + err.message; return; }
  }
  const data = await editorMutation('edit',{date,body},'Note updated.');
  if (!data) return;
  editorNote = data.note;
  $('#edit-body').value = editorNote.body;
  $('#edit-state').textContent = 'Saved';
  $('#editor-status').textContent = document.querySelector('[data-date="' + date + '"]') ? 'Changes saved.' : 'Changes saved. Navigate to ' + date + ' to see this note.';
};
$('#comment-form').onsubmit = async event => {
  event.preventDefault();
  const body = $('#comment-body').value;
  if (!body.trim()) { $('#editor-status').textContent = 'Write a comment before adding it.'; return; }
  const data = await editorMutation('comments',{body},'Comment added.');
  if (!data) return;
  $('#comment-history .no-comments')?.remove();
  $('#comment-history').append(commentCard(data.comment));
  $('#comment-history').scrollTop = $('#comment-history').scrollHeight;
  $('#comment-body').value = '';
  $('#editor-status').textContent = 'Comment added.';
  $('#comment-body').focus();
};

// Refresh on day/week changes without discarding open forms or editor drafts.
let checkingClock = false;
async function checkCalendarClock() {
  if (checkingClock || document.hidden || mutationBusy || pendingCreates || editor.open || document.querySelector('.composer form') || dragged) return;
  checkingClock = true;
  try {
    const clock = await request('/api/clock');
    if (clock.today !== displayedClock && !mutationBusy && !pendingCreates && !editor.open && !document.querySelector('.composer form') && !dragged) await render(true);
  } catch (err) {
    $('#status').textContent = 'Could not check for a new week. Will retry automatically.';
  } finally { checkingClock = false; }
}
setInterval(checkCalendarClock, 60000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) checkCalendarClock(); });
window.addEventListener('focus', checkCalendarClock);
