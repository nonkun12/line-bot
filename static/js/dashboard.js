document.addEventListener('DOMContentLoaded', () => {
  const userId = document.querySelector('meta[name="user-id"]')?.getAttribute('content') || '';
  const qs = new URLSearchParams(location.search);
  const authQuery = () => { const p = new URLSearchParams(); if (userId) p.set('user_id', userId); if (qs.get('ts')) p.set('ts', qs.get('ts')); if (qs.get('token')) p.set('token', qs.get('token')); return p.toString() ? '?' + p.toString() : ''; };
  const api = path => path + authQuery();
  const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
  const cls = s => s === 'online' || s === 'ok' ? 'online' : s === 'stale' ? 'stale' : s === 'offline' || s === 'error' ? 'offline' : 'unknown';
  const label = s => ({online:'🟢 正常',ok:'🟢 正常',stale:'🟡 遅延',offline:'🔴 オフライン',error:'🔴 エラー',unknown:'⚪ 未確認'})[s] || '⚪ 未確認';
  const setStatus = (id, s) => { const el=document.getElementById(id); if(el) el.innerHTML=`<span class="status-dot ${cls(s)}"></span>${label(s)}`; };

  async function fetchSystem() {
    const err=document.getElementById('systemError'); err.classList.add('hidden');
    try {
      const r=await fetch(api('/api/dashboard/system')); const d=await r.json(); if(!r.ok || !d.ok) throw new Error(d.error || `HTTP ${r.status}`);
      setStatus('renderStatus', d.render?.status || 'unknown');
      document.getElementById('renderDetails').textContent='Dashboard / Flask: online';
      const o=d.oracle || {}; setStatus('oracleStatus', o.status);
      if(o.data){ const m=o.data.memory||{}, disk=o.data.disk||{}; const gb=x=>(Number(x||0)/1073741824).toFixed(1); document.getElementById('oracleDetails').textContent=`Memory ${gb(m.used_bytes)} / ${gb(m.total_bytes)} GB ・ Disk ${disk.used_percent ?? '--'}%`; document.getElementById('oracleN8n').textContent=`Uptime ${o.data.uptime_sec != null ? Math.floor(o.data.uptime_sec/3600)+'h' : '--'} ・ Load ${(o.data.load||[]).join(' / ') || '--'}`; const n=o.data.docker?.n8n; document.getElementById('n8nContainer').textContent=n ? `${n.name} ・ ${n.status}` : 'n8nコンテナ未確認'; setStatus('n8nStatus', d.services?.n8n || (n ? 'online' : 'unknown')); } else { document.getElementById('oracleDetails').textContent='Oracleエージェント未接続'; document.getElementById('oracleN8n').textContent='初回データ待ち'; document.getElementById('n8nContainer').textContent='Oracleエージェント未接続のため確認不可'; setStatus('n8nStatus', d.services?.n8n || 'unknown'); }
      setStatus('dbStatus', d.notes?.status === 'ok' ? 'online' : 'error'); document.getElementById('dbStatus').textContent=`Database: ${d.notes?.status === 'ok' ? 'online' : 'error'}`;
      setStatus('aiStatus', d.services?.ai_mcp || 'unknown'); document.getElementById('aiDetails').textContent='LangGraph / MCP';
      const steps=d.e2e?.steps||[]; const flow=document.getElementById('e2eFlow'); flow.innerHTML=steps.map(s=>`<div class="system-card"><div class="system-card-title">${esc(s.label)}</div><div class="system-status">${label(s.state)}</div><div class="system-details">${s.last_http_status ? 'HTTP '+esc(s.last_http_status) : ''}</div></div>`).join('');
      const e2eOk=steps.filter(s=>s.state==='ok').length;
      document.getElementById('e2eSummary').textContent=steps.length && steps.some(s=>s.state!=='unknown' && s.state!=='not_reached') ? `E2E: ${e2eOk}/${steps.length} OK` : 'E2E: 待機中';
      const notes=d.notes||{}; document.getElementById('reminderSummary').textContent=`${d.reminders?.count ?? 0} 件 ・ メモ ${notes.count ?? 0} 件`;
      document.getElementById('reminderList').innerHTML=(d.reminders?.latest||[]).slice(0,5).map(x=>`<div class="system-card"><div class="system-card-title">⏰ ${esc(x.title||x.name||'リマインダー')}</div><div class="system-details">${esc(x.datetime||x.remind_at||x.time||x.body||JSON.stringify(x))}</div></div>`).join('') || '<div class="system-details">リマインダーはありません</div>';
      document.getElementById('systemUpdated').textContent='最終更新 '+new Date().toLocaleTimeString('ja-JP');
    } catch(e) { const el=document.getElementById('systemError'); document.getElementById('systemErrorMessage').textContent=`システム情報の取得に失敗: ${e.message}`; el.classList.remove('hidden'); }
  }

  let allNotes=[];
  const tbody=document.getElementById('notesTableBody'), loading=document.getElementById('loadingState'), empty=document.getElementById('emptyState'), error=document.getElementById('errorAlert');
  function cat(c){ const x=String(c||'').toLowerCase(); return x.includes('予定')?'cat-schedule':x.includes('技術')?'cat-tech':x.includes('学習')?'cat-study':x.includes('生活')?'cat-life':'cat-general'; }
  function renderNotes(notes){ tbody.innerHTML=''; empty.classList.toggle('hidden', notes.length>0); notes.forEach(n=>{const id=n.id??'-',tr=document.createElement('tr');tr.innerHTML=`<td class="col-id">${esc(id)}</td><td><span class="cat-badge ${cat(n.category)}">${esc(n.category||'一般')}</span></td><td>${esc(n.title||'LINEメモ')}</td><td>${esc(n.body||'').replace(/\n/g,'<br>')}</td><td><button class="btn btn-danger delete-btn" data-id="${esc(id)}">削除</button></td>`;tbody.appendChild(tr);});tbody.querySelectorAll('.delete-btn').forEach(b=>b.onclick=()=>deleteNote(b.dataset.id));}
  async function fetchNotes(){ loading.classList.remove('hidden'); error.classList.add('hidden'); try{const r=await fetch(api('/api/dashboard/notes'));const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||`HTTP ${r.status}`);allNotes=d.notes||[];filterNotes();}catch(e){document.getElementById('errorMessage').textContent=`メモの取得に失敗しました: ${e.message}`;error.classList.remove('hidden');}finally{loading.classList.add('hidden');}}
  function filterNotes(){const q=document.getElementById('searchInput').value.toLowerCase().trim();renderNotes(q?allNotes.filter(n=>[n.id,n.title,n.body,n.category].some(v=>String(v||'').toLowerCase().includes(q))):allNotes);}
  async function deleteNote(id){if(!id||id==='-'||!confirm('このメモを削除してよろしいですか？'))return;try{const r=await fetch(api('/api/dashboard/notes/'+encodeURIComponent(id)),{method:'DELETE'});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||`HTTP ${r.status}`);fetchNotes();}catch(e){document.getElementById('errorMessage').textContent=`削除に失敗しました: ${e.message}`;error.classList.remove('hidden');}}
  async function addNote(title,body,category){try{const r=await fetch(api('/api/dashboard/notes'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,body,category})});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||`HTTP ${r.status}`);closeModal();fetchNotes();}catch(e){document.getElementById('modalErrorMessage').textContent=e.message;document.getElementById('modalErrorAlert').classList.remove('hidden');}}
  const modal=document.getElementById('newNoteModal'); const closeModal=()=>modal.classList.add('hidden');
  document.getElementById('refreshBtn').onclick=fetchNotes; document.getElementById('searchInput').oninput=filterNotes; document.getElementById('systemRefreshBtn').onclick=fetchSystem; document.getElementById('newNoteBtn').onclick=()=>{document.getElementById('newNoteForm').reset();modal.classList.remove('hidden');document.getElementById('noteTitle').focus();}; document.getElementById('closeModalBtn').onclick=closeModal; document.getElementById('cancelModalBtn').onclick=closeModal; modal.onclick=e=>{if(e.target===modal)closeModal();};
  document.getElementById('newNoteForm').onsubmit=e=>{e.preventDefault();const t=document.getElementById('noteTitle').value.trim(),b=document.getElementById('noteBody').value.trim(),c=document.getElementById('noteCategory').value;if(t&&b)addNote(t,b,c);};
  fetchSystem(); fetchNotes(); setInterval(fetchSystem,30000);
});
