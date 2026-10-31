document.addEventListener('DOMContentLoaded', () => {
  const userId = document.querySelector('meta[name="user-id"]')?.getAttribute('content') || '';
  const qs = new URLSearchParams(location.search);
  const authQuery = () => { const p = new URLSearchParams(); if (userId) p.set('user_id', userId); if (qs.get('ts')) p.set('ts', qs.get('ts')); if (qs.get('token')) p.set('token', qs.get('token')); return p.toString() ? '?' + p.toString() : ''; };
  const api = path => path + authQuery();
  const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;').replace(/'/g,'&#039;');
  const cls = s => s === 'online' || s === 'ok' ? 'online' : s === 'stale' ? 'stale' : s === 'offline' || s === 'error' ? 'offline' : 'unknown';
  const label = s => ({online:'🟢 正常',ok:'🟢 正常',stale:'🟡 遅延',offline:'🔴 オフライン',error:'🔴 エラー',planned:'🔵 開発予定',unknown:'⚪ 未確認'})[s] || '⚪ 未確認';
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
      const features=d.features||{};
      const featureOrder=[
        ['management_ai','統合AI / Management','タスク分解・配分・結果回収'],
        ['general','General AI','汎用・フォールバック'],
        ['english_learning','英語学習AI','学習・進捗・復習'],
        ['stocks','株価AI','株価・テクニカル分析・監視'],
        ['global_market','世界市場AI','NYダウ・主要為替'],
        ['ai_news','AI NEWS','取得・要約・配信'],
        ['voice','AIスピーカー / Voice','音声入力・音声出力'],
        ['jobs','求職AI','求人検索・応募支援'],
        ['music','音楽AI','選曲・作曲/作詞補助・プレイリスト'],
        ['video','映像AI','企画・台本・絵コンテ・編集'],
      ];
      const icons={management_ai:'🧠',general:'🧩',english_learning:'🇬🇧',stocks:'📈',global_market:'🌎',ai_news:'📰',voice:'🎙️',jobs:'💼',music:'🎵',video:'🎬'};
      const featureGrid=document.getElementById('featureGrid');
      featureGrid.innerHTML=featureOrder.map(([key,title,baseDetail])=>{
        const f=features[key]||{}, status=f.status||'unknown';
        return `<div class="system-card"><div class="system-card-title">${icons[key]||'🤖'} ${esc(title)}</div><div class="system-status">${label(status)}</div><div class="system-details">${esc(f.detail||baseDetail)}</div></div>`;
      }).join('');
      let loopLastRun = {};
      try {
        const lr=await fetch(api('/api/dashboard/loop')); const ld=await lr.json();
        const l=ld.loop||{}, s=ld.safety||{}, h=ld.hand_sign||{};
        loopLastRun = l.last_run || {};
        const cards=[
          ['🔄 Loop','🟢 自動運転設定済み',`1日 ${l.frequency_per_day||4}回 ・ ${(l.schedule_jst||[]).join(' / ')} JST`],
          ['🛡️ Safety Gate',s.fail_closed||l.fail_closed?'🟢 FAIL_CLOSED 有効':'⚪ 未確認',`Auto Merge: ${s.auto_merge?'有':'無'} ・ Auto Deploy: ${s.auto_deploy?'有':'無'}`],
          ['📋 Sheets監査',l.sheets_audit?'🟢 有効':'⚪ 未確認',`Runtime telemetry: ${esc(l.runtime_telemetry||'unknown')}`],
          ['🧭 Hermes Adviser',s.hermes_role==='adviser'?'🟢 Adviser':'⚪ 未確認',s.hermes_is_auxiliary?'補助系統・Loop本体とは分離':'状態確認要'],
          ['✋ Hand Sign',h.camera_smoke_test==='implemented'?'🟢 Camera準備済み':'🔵 開発中',`Upload: ${h.camera_upload?'有':'無'} ・ Storage: ${h.camera_storage?'有':'無'}`],
          ['📡 実行実績',
            l.last_run&&l.last_run.status==='ok'&&l.last_run.runs&&l.last_run.runs.length?'🟢 Run取得済み':'⚪ 未取得',
            l.last_run&&l.last_run.runs&&l.last_run.runs.length
              ? '最新: Run #'+(l.last_run.runs[0].run_number||'-')+' / '+(l.last_run.runs[0].status||'-')+' / '+(l.last_run.runs[0].conclusion||'実行中')
              : '未取得のRunを成功扱いしません'],
        ];
        document.getElementById('loopGrid').innerHTML=cards.map(x=>'<div class="system-card"><div class="system-card-title">'+x[0]+'</div><div class="system-status">'+x[1]+'</div><div class="system-details">'+esc(x[2])+'</div></div>').join('');
        document.getElementById('loopSummary').textContent=`自動Loop ${l.frequency_per_day||4}回/日 ・ 安全設定確認済み`;
      } catch(e) {
        document.getElementById('loopSummary').textContent='状態取得失敗';
        document.getElementById('loopGrid').innerHTML='<div class="system-details">Loop状態を取得できません。未確認の稼働を断定しません。</div>';
      }
      const historyBody=document.getElementById('loopHistoryBody');
      const historyUpdated=document.getElementById('loopHistoryUpdated');
      const historyError=document.getElementById('loopHistoryError');
      const runData=loopLastRun;
      if(historyError) historyError.classList.add('hidden');
      if(historyUpdated) historyUpdated.textContent='更新 '+new Date().toLocaleTimeString('ja-JP')+' ・ 直近5件';
      const historyMetrics=document.getElementById('loopHistoryMetrics');
      const historyRuns=runData.status==='ok' && Array.isArray(runData.runs)?runData.runs:[];
      const completedRuns=historyRuns.filter(run=>String(run.status||'').toLowerCase()==='completed');
      const successfulRuns=completedRuns.filter(run=>String(run.conclusion||'').toLowerCase()==='success');
      const failedRuns=completedRuns.filter(run=>Boolean(run.conclusion)&&String(run.conclusion).toLowerCase()!=='success');
      const runningRuns=historyRuns.filter(run=>String(run.status||'').toLowerCase()==='in_progress');
      const queuedRuns=historyRuns.filter(run=>['queued','waiting','pending','requested'].includes(String(run.status||'').toLowerCase()));
      if(historyMetrics){
        const metrics=runData.status==='ok'?[
          ['取得件数',historyRuns.length+'件','直近5件のWorkflow'],
          ['Workflow成功',successfulRuns.length+'件','個別タスクPASSとは別判定'],
          ['失敗・取消等',failedRuns.length+'件','success以外の完了'],
          ['実行中',runningRuns.length+'件','in_progress'],
          ['待機中',queuedRuns.length+'件','queued / waiting']
        ]:[['履歴','未取得',runData.reason||'GitHub API未接続']];
        historyMetrics.innerHTML=metrics.map(item=>'<div class="system-card"><div class="system-card-title">'+esc(item[0])+'</div><div class="history-metric-value">'+esc(item[1])+'</div><div class="system-details">'+esc(item[2])+'</div></div>').join('');
      }
      if(historyBody){
        if(runData.status!=='ok'){
          historyBody.innerHTML='<tr><td colspan="6">GitHub Actions 履歴を取得できません。'+esc(runData.reason||'状態未取得')+'</td></tr>';
        } else {
          historyBody.innerHTML=historyRuns.length?historyRuns.map(run=>{
            const status=String(run.status||'unknown').toLowerCase();
            const conclusion=String(run.conclusion||'').toLowerCase();
            const workflowLabel=['queued','waiting','pending','requested'].includes(status)?'待機中':status==='in_progress'?'実行中':status!=='completed'?'状態: '+esc(status):conclusion==='success'?'成功':conclusion?({failure:'失敗',cancelled:'取消',timed_out:'タイムアウト',action_required:'要対応'}[conclusion]||'完了: '+esc(conclusion)):'完了状態不明';
            const tone=status!=='completed'?'running':conclusion==='success'?'ok':conclusion?'failed':'unknown';
            const started=run.created_at?new Date(run.created_at).toLocaleString('ja-JP'):'未取得';
            const sha=String(run.head_sha||'').slice(0,10)||'未取得';
            const href=String(run.html_url||'');
            const safeHref=/^https:\/\/github\.com\/nonkun12\/line-bot\/actions\/runs\/[0-9]+$/.test(href)?href:'';
            const title=esc(run.display_title||run.name||'Distributed Loop');
            return '<tr><td>#'+esc(run.run_number??'—')+'<div class="run-title">'+title+'</div></td><td><span class="run-state '+tone+'">'+workflowLabel+'</span></td><td>'+esc(run.event||'未取得')+'</td><td>'+esc(started)+'</td><td><code>'+esc(sha)+'</code></td><td>'+(safeHref?'<a href="'+safeHref+'" target="_blank" rel="noopener noreferrer">Runを開く ↗</a>':'リンク未取得')+'</td></tr>';
          }).join(''):'<tr><td colspan="6">取得できる実行履歴はありません</td></tr>';
        }
      }
      const distributed=d.distributed_ai||{};
      const specialists=distributed.specialists||[];
      const onlineCount=specialists.filter(x=>x.status==='online').length;
      const plannedCount=specialists.filter(x=>x.status==='planned').length;
      const summary=document.getElementById('distributedAiSummary');
      if(summary) summary.textContent=`分散AI ${onlineCount}稼働 ・ ${plannedCount}開発中`;
      const messageSummary=document.getElementById('agentMessageSummary');
      if(messageSummary) messageSummary.textContent=distributed.message_bus
        ? `メッセージバス: 有効 ・ ${esc(distributed.architecture||'統合AI → 分散AI → 結果回収 → 再指示')}`
        : 'メッセージバス: 未接続';
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
  fetchSystem(); fetchNotes();
});
