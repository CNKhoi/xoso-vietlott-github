const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let DATA = null;

function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}
function fmtDate(s){if(!s)return '—'; const [y,m,d]=s.slice(0,10).split('-'); return `${d}/${m}/${y}`}
function pct(v){return `${(Number(v||0)*100).toFixed(1)}%`}
function toast(msg){const t=$('#toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3200)}

$$('.tab').forEach(b=>b.onclick=()=>{
  $$('.tab').forEach(x=>x.classList.remove('active')); b.classList.add('active');
  $$('.tab-panel').forEach(x=>x.classList.remove('active')); $(`#tab-${b.dataset.tab}`).classList.add('active');
  if(b.dataset.tab==='viet') renderViet();
});

function renderStatus(){
  $('#latestXsmn').textContent=fmtDate(DATA.latest?.xsmn);
  $('#latestMega').textContent=fmtDate(DATA.latest?.mega645);
  $('#latestPower').textContent=fmtDate(DATA.latest?.power655);
  const g=DATA.generated_at ? new Date(DATA.generated_at) : null;
  $('#lastUpdate').textContent='Cập nhật: '+(g?g.toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh'}):'—');
  const p=$('#statusPill');
  const notRun=!g || DATA.fetch?.mode==='not-run';
  const stale=!notRun && (Date.now()-g.getTime())>36*3600*1000;
  p.className='status-pill '+(!notRun && !stale?'ok':'');
  p.querySelector('span:last-child').textContent=notRun?'CHƯA CHẠY AUTO UPDATE':(stale?'Dữ liệu có thể đang cũ':'Tự động đã cập nhật');
  if(DATA.fetch?.errors_count) p.title=`Có ${DATA.fetch.errors_count} request nguồn bị lỗi; dữ liệu cũ vẫn được giữ.`;
}

function renderAudit(){
  const a=DATA.audit_247346||{};
  $('#auditPrev').textContent=`${fmtDate(a.previous_date)} · ${a.previous_special||'—'}`;
  $('#auditCalc').textContent=a.calculation||'24 + 7346 = 247346';
  $('#auditActual').textContent=`${fmtDate(a.actual_date)} · ${a.actual_special||'—'}`;
  $('#auditBadge').textContent=a.exact_match?'KHỚP EXACT':'KHÔNG KHỚP';
  $('#auditWarning').textContent=a.warning||'';
}

function renderProvinceList(){
  const preds=DATA.xsmn?.predictions||{};
  const names=Object.keys(preds).sort((a,b)=>a.localeCompare(b,'vi'));
  $('#province').innerHTML=names.map(p=>`<option value="${esc(p)}" ${p==='Bình Thuận'?'selected':''}>${esc(p)}</option>`).join('');
  if(!names.includes('Bình Thuận') && names[0]) $('#province').value=names[0];
}

function chips(arr){return (arr||[]).map(x=>`<span class="chip">${esc(x.value)}<small>${Number(x.score||0).toFixed(0)}</small></span>`).join('')}

function renderXsmn(){
  if(!DATA) return;
  const province=$('#province').value;
  const r=DATA.xsmn?.predictions?.[province];
  if(!r || r.error){
    $('#xsmnEmpty').classList.remove('hidden'); $('#xsmnContent').classList.add('hidden');
    $('#xsmnEmpty').textContent=r?.error || 'Chưa có đủ dữ liệu cho đài này. Workflow tự động sẽ bổ sung lịch sử.';
    $('#targetDate').value=r?.next_draw_date?fmtDate(r.next_draw_date):'—'; return;
  }
  $('#xsmnEmpty').classList.add('hidden'); $('#xsmnContent').classList.remove('hidden');
  $('#targetDate').value=fmtDate(r.next_draw_date||r.target_date);
  $('#xHistory').textContent=`${r.draw_count} kỳ · ${fmtDate(r.history_from)} → ${fmtDate(r.history_to)}`;
  $('#lastSpecial').textContent=`Kỳ gần nhất ${fmtDate(r.last_date)}: ${r.last_special}`;
  $('#exactCandidates').innerHTML=(r.candidates||[]).map((x,i)=>`<div class="number-card ${i<3?'featured':''}"><strong>${esc(x.value)}</strong><small>Điểm xếp hạng ${Number(x.score||0).toFixed(1)}/100</small><small>LR vị trí ×${Number(x.relative_likelihood_vs_uniform||0).toFixed(2)} · P mô hình ${(Number(x.model_probability||0)*100).toFixed(5)}%</small>${x.reasons?.length?`<small class="reason">${esc(x.reasons[0])}</small>`:''}<div class="bar" style="width:${Math.min(100,Number(x.score||0))}%"></div></div>`).join('');
  $('#suffix2').innerHTML=(r.top_suffix2||[]).map(x=>`<span class="chip">${esc(x.value)}<small>${Number(x.score||0).toFixed(2)}%</small></span>`).join('');
  $('#suffix3').innerHTML=chips(r.top_suffix3);

  const eng=r.adaptive_engine||{}; const bt=eng.holdout||{};
  $('#engineStatus').textContent=eng.status||'—';
  $('#engineStatus').className='engine-status '+((bt.digit_log_skill_vs_uniform||0)>0 && (bt.suffix2_log_skill_vs_uniform||0)>0?'good':'warn');
  $('#engineBasis').textContent=`Kỳ làm cơ sở: ${fmtDate(r.previous_draw_basis?.draw_date)} · ĐB ${r.previous_draw_basis?.special||'—'}. ${eng.principle||''}`;
  $('#engineTests').textContent=bt.tests??'—';
  $('#engineDigit').textContent=bt.tests!=null?`${(Number(bt.digit_top1_rate||0)*100).toFixed(1)}%`:'—';
  $('#engineSuffix10').textContent=bt.tests!=null?`${(Number(bt.suffix2_top10_rate||0)*100).toFixed(1)}%`:'—';
  $('#engineExact20').textContent=bt.tests!=null?`${bt.exact_top20_hits||0}/${bt.tests||0}`:'—';
  const modelRow=m=>`<div class="model-row"><div><b>${esc(m.name)}</b><small>${m.tests} kỳ test · skill ${Number(m.log_skill_vs_uniform||0)>=0?'+':''}${(Number(m.log_skill_vs_uniform||0)*100).toFixed(1)}%</small></div><span>${(Number(m.weight||0)*100).toFixed(1)}%</span></div>`;
  $('#engineModels').innerHTML=(eng.position_models||[]).map(modelRow).join('');
  $('#suffixModels').innerHTML=(eng.suffix_models||[]).map(m=>`<div class="model-row"><div><b>${esc(m.name)}</b><small>${m.tests} kỳ test · Top10 ${(Number(m.top10_rate||0)*100).toFixed(1)}%</small></div><span>${(Number(m.weight||0)*100).toFixed(1)}%</span></div>`).join('');
  $('#formulaToday').innerHTML=(r.formula_today||[]).map(x=>`<div class="formula"><b>${esc(x.value)}</b><small>${esc(x.name)}</small><small>Backtest score: ${Number(x.backtest_score||0).toFixed(3)}</small></div>`).join('');
  $('#formulaTable').innerHTML=(r.formulas||[]).map(x=>`<tr><td>${esc(x.name)}</td><td>${x.tests}</td><td>${x.exact} (${pct(x.exact_rate)})</td><td>${x.suffix4} (${pct(x.suffix4_rate)})</td><td>${x.suffix3} (${pct(x.suffix3_rate)})</td><td>${x.suffix2} (${pct(x.suffix2_rate)})</td><td>${Number(x.avg_digit_matches||0).toFixed(2)}/6</td></tr>`).join('');
  $('#xRecent').innerHTML=(r.recent_results||[]).map(x=>`<div class="history-item"><small>${fmtDate(x.draw_date)}</small><strong>${esc(x.special||'—')}</strong>${x.source?`<a class="source-link" target="_blank" rel="noopener" href="${esc(x.source)}">Nguồn ↗</a>`:''}</div>`).join('');
}

function balls(items,overdue=false){return (items||[]).map(x=>`<div class="ball">${String(x.number).padStart(2,'0')}<em>${overdue?`${x.gap_draws} kỳ`:`${Number(x.score||0).toFixed(0)}`}</em></div>`).join('')}

function renderViet(){
  if(!DATA) return;
  const product=$('#vietProduct').value;
  const r=DATA.vietlott?.[product];
  $('#vietNextDate').value=fmtDate(r?.next_draw_date);
  if(!r || r.error){
    $('#vietEmpty').classList.remove('hidden'); $('#vietContent').classList.add('hidden');
    $('#vietEmpty').textContent=r?.error || 'Chưa có đủ dữ liệu Vietlott.'; return;
  }
  $('#vietEmpty').classList.add('hidden'); $('#vietContent').classList.remove('hidden');
  $('#hotBalls').innerHTML=balls(r.hot); $('#overdueBalls').innerHTML=balls(r.overdue,true);
  $('#jackpotOdds').textContent=`1 / ${Number(r.jackpot_combinations).toLocaleString('vi-VN')}`;
  $('#jackpotComb').textContent=`≈ ${(Number(r.theoretical_jackpot_probability)*100).toFixed(8)}% cho một bộ 6 số cụ thể`;
  $('#vietHistory').textContent=`${r.draw_count} kỳ · ${fmtDate(r.history_from)} → ${fmtDate(r.history_to)}`;
  $('#vietSets').innerHTML=(r.sets||[]).map(s=>`<div class="set-card"><div class="balls">${s.numbers.map(n=>`<span class="mini-ball">${String(n).padStart(2,'0')}</span>`).join('')}</div><div class="set-meta"><span>Điểm ${Number(s.score||0).toFixed(1)}</span><span>Tổng ${s.sum}</span></div></div>`).join('');
  $('#modelMatches').textContent=Number(r.backtest?.top12_pool_avg_matches||0).toFixed(3);
  $('#randomMatches').textContent=Number(r.backtest?.random_top12_expected_matches||0).toFixed(3);
  const edge=Number(r.backtest?.edge_vs_random||0); $('#edgeMatches').textContent=(edge>=0?'+':'')+edge.toFixed(3);
  $('#vietNote').textContent=r.note||'';
  $('#vietRecent').innerHTML=(r.recent_results||[]).map(x=>`<div class="history-item"><small>#${x.draw_id} · ${fmtDate(x.draw_date)}</small><strong>${(x.numbers||[]).map(n=>String(n).padStart(2,'0')).join(' ')}</strong>${x.special?`<small>ĐB: ${String(x.special).padStart(2,'0')}</small>`:''}${x.source?`<a class="source-link" target="_blank" rel="noopener" href="${esc(x.source)}">Nguồn ↗</a>`:''}</div>`).join('');
}

$('#province').onchange=renderXsmn;
$('#vietProduct').onchange=renderViet;
$('#todayStations').onclick=()=>{
  const names=DATA.today_stations||[]; const opts=[...$('#province').options].map(o=>o.value);
  const pick=names.find(n=>opts.includes(n));
  if(pick){$('#province').value=pick;renderXsmn();}
  toast(names.length?`Đài hôm nay: ${names.join(', ')}`:'Không xác định được lịch hôm nay');
};

(async function init(){
  try{
    const r=await fetch('./data/dashboard.json',{cache:'no-store'});
    if(!r.ok) throw new Error(`HTTP ${r.status}`);
    DATA=await r.json();
    renderStatus(); renderAudit(); renderProvinceList(); renderXsmn(); renderViet();
  }catch(e){
    $('#statusPill').querySelector('span:last-child').textContent='Chưa có dữ liệu';
    $('#xsmnEmpty').textContent='Chưa có dữ liệu phân tích. Hãy chạy workflow Auto Update trên GitHub lần đầu để tạo dashboard.';
    $('#vietEmpty').textContent='Chưa có dữ liệu. Bạn có thể chạy Actions → Auto Update Lottery Data → Run workflow.';
    console.error(e);
  }
})();
