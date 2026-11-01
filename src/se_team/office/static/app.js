'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const icon = (name, cls = '') => `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roles = [
  {key:'orchestrator', name:'Keen', label:'หัวหน้าทีม', discipline:'Product & planning', letter:'K', color:'lead', skin:'#e7b291', hair:'#5f4c47', shirt:'#aca0c4', home:[406,183], desk:[400,108]},
  {key:'frontend_specialist', name:'Milo', label:'Frontend', discipline:'Design & interface', letter:'M', color:'frontend', skin:'#e8b68f', hair:'#755239', shirt:'#91a481', home:[238,255], desk:[182,265]},
  {key:'backend_specialist', name:'Atlas', label:'Backend', discipline:'Data & systems', letter:'A', color:'backend', skin:'#bc8869', hair:'#41484e', shirt:'#91aab9', home:[568,256], desk:[619,265]},
  {key:'qa_verifier', name:'Sage', label:'QA', discipline:'Testing & quality', letter:'S', color:'qa', skin:'#e5ad89', hair:'#af7c47', shirt:'#d2b27e', home:[401,322], desk:[401,410]},
];
const titles = {supervisor_edit_task:'แบ่งงานแก้เฉพาะจุด',supervisor_turn_task:'วางแผนจากคำสั่งของคุณ',frontend_build_task:'สร้างและปรับหน้าเว็บ',backend_build_task:'สร้างและปรับระบบข้อมูล',qa_verification_task:'ออกแบบชุดทดสอบ',qa_report_task:'ตรวจผลและข้อกำหนด',orchestrator_reprompt_task:'แบ่งงานแก้ข้อผิดพลาด',orchestrator_signoff_task:'ตรวจรับเวอร์ชันเว็บ',pytest:'รันชุดทดสอบจริง'};
const statusLabel = {queued:'รอรับงาน',running:'กำลังทำงาน',completed:'เสร็จแล้ว',approved:'ผ่านการตรวจรับ',needs_attention:'มีจุดที่ต้องตรวจ',discussed:'บทสนทนา',failed:'ติดปัญหา',cancelled:'หยุดแล้ว',interrupted:'งานถูกขัดจังหวะ'};
const S = {token:'',projects:[],projectId:null,data:null,source:null,view:'office',selectedRevision:null,selectedFile:null,files:[],chatSignature:'',previewURL:'',providerReady:null,providerName:'Google Antigravity',backend:'antigravity',connected:true};
let refreshTimer, toastTimer, refreshing=false, refreshAgain=false;
const time = value => value ? new Date(value).toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit'}) : '';
const date = value => value ? new Date(value).toLocaleString('th-TH',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : '';
function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,6500);}
async function api(path, options={}){
  const response=await fetch('/office-api'+path,{...options,headers:{'Content-Type':'application/json','X-Office-Token':S.token,...options.headers}});
  if(!response.ok){let body;try{body=await response.json();}catch{body={detail:'เชื่อมต่อ Office ไม่สำเร็จ'};}throw new Error(typeof body.detail==='string'?body.detail:'ตรวจข้อมูลที่กรอกอีกครั้งครับ');}
  return response.json();
}
function updateConnection(){const node=$('#connection');const good=S.providerReady&&S.connected&&!S.paused;const checking=S.providerReady===null;const name=S.providerName||'Antigravity';const label=!S.connected?'Office ขาดการเชื่อมต่อ':S.paused?`พักการเรียก ${name}`:checking?`กำลังตรวจ ${name}`:S.providerReady?`${name} พร้อมรับงาน`:`${name} ยังไม่พร้อม`;node.innerHTML=`<span class="tiny-dot ${good?'green':checking?'':'failed'}"></span>${esc(label)}`;}

function duration(seconds){const n=Math.max(0,Math.round(seconds));return n>=60?`${Math.floor(n/60)} นาที ${n%60} วินาที`:`${n} วินาที`;}
function renderPerformance(){
 const revision=S.data?.revisions?.[0];const panel=$('#performance-panel');
 if(!S.projectId){panel.innerHTML='';return;}
 const tasks=(S.data?.tasks||[]).filter(t=>t.revision_id===revision?.id);
 panel.innerHTML=`<div class="performance-heading"><h2>เวลาทำงานจริง${revision?` · งาน #${revision.number}`:''}</h2><span class="performance-mode">แก้เฉพาะจุด · ตรวจผลจริง</span></div><p class="performance-note">หัวหน้าใช้แผนสั้นสำหรับงานแก้เดิม ส่งเฉพาะไฟล์ที่เกี่ยวข้อง และใช้ชุดทดสอบเดิมก่อนสำหรับงานปรับสีหรือข้อความ คำสั่งถัดไปใช้ระบบที่ปรับแล้ว</p>${tasks.length?`<div class="performance-jobs">${tasks.map(t=>{const m=t.metrics||{};const elapsed=(new Date(t.finished_at||Date.now())-new Date(t.started_at))/1000;return `<div class="performance-job"><div><b>${esc(titles[t.task_key]||t.title)}</b><small>${m.prompt_chars?`ข้อมูลที่ส่ง ${(m.prompt_chars/1000).toFixed(1)} พันตัวอักษร`:'งานที่บันทึกไว้ก่อนการปรับระบบ'}${m.effort?' · '+(m.effort==='low'?'คิดแบบกระชับ':'ตรวจละเอียด'):''}</small></div><span ${t.status==='running'?`data-elapsed-start="${esc(t.started_at)}"`:''}>${duration(m.duration_seconds??elapsed)}</span></div>`;}).join('')}</div>`:'<p class="performance-note">เวลาของแต่ละขั้นตอนจะแสดงที่นี่เมื่อเริ่มงาน</p>'}`;
}
setInterval(()=>{$$('[data-elapsed-start]').forEach(n=>{n.textContent=duration((Date.now()-new Date(n.dataset.elapsedStart))/1000);});},1000);
function renderProjects(){
  const signature=JSON.stringify([S.projects.map(p=>[p.id,p.name]),S.projectId]);
  if(signature===S.projectSignature)return;S.projectSignature=signature;
  $('#project-count').textContent=S.projects.length;
  $('#project-switcher').innerHTML=(S.projects.length?'':'<option value="">เลือกโปรเจกต์</option>')+S.projects.map(p=>`<option value="${p.id}" ${p.id===S.projectId?'selected':''}>${esc(p.name)}</option>`).join('')+'<option value="new">＋ สร้างโปรเจกต์ใหม่</option>';
  $('#project-list').innerHTML=S.projects.length?S.projects.map(p=>`<button class="project-link ${p.id===S.projectId?'active':''}" data-project="${p.id}" title="${esc(p.name)}"><span class="project-symbol">${esc(p.name[0].toUpperCase())}</span><span class="project-name">${esc(p.name)}</span>${p.id===S.projectId?'<span class="tiny-dot green"></span>':''}</button>`).join(''):'<div class="project-empty">พื้นที่สำหรับสิ่งที่คุณ<br>กำลังจะสร้าง</div>';
}
function desk(x,y,tint,label){return `<g transform="translate(${x} ${y})"><ellipse cx="0" cy="46" rx="72" ry="10" fill="#b5b49c" opacity=".09"/><rect x="-62" y="-12" width="124" height="52" rx="8" fill="#bcb3a0"/><rect x="-66" y="-17" width="132" height="51" rx="8" fill="#e0d3b8" stroke="#cfc3aa"/><path d="M-59-10H58" stroke="#ede4cd"/><rect x="-27" y="-42" width="54" height="36" rx="4" fill="#9b9c91"/><rect class="office-monitor-light" x="-23" y="-38" width="46" height="27" rx="2" fill="${tint}"/><path d="M-16-30h20m-20 5h31m-31 5h15" stroke="#ffffff" stroke-width="2" opacity=".7"/><path class="monitor-cursor" d="M9-20h4" stroke="#fafcf6" stroke-width="2"/><path d="M-3-6v6m-10 0h26" stroke="#a3a293" stroke-width="3"/><rect x="-22" y="10" width="43" height="12" rx="3" fill="#f2eee1" stroke="#d9d4c3"/><path d="M-16 14h29m-29 4h24" stroke="#d0cebf"/><rect x="31" y="12" width="9" height="12" rx="4" fill="#f0eee2"/><circle cx="-48" cy="13" r="6" fill="#faf6e9"/><circle cx="-48" cy="13" r="3.5" fill="#b4a38b"/><path d="M-54 13h-3" stroke="#e9e1ce" stroke-width="3"/><rect x="42" y="-5" width="13" height="13" rx="3" fill="#f7ebc5"/><path d="M44-2h8m-8 3h5" stroke="#d4bd86" stroke-width="1"/><rect x="-26" y="50" width="52" height="35" rx="16" fill="#a9aea0"/><rect x="-23" y="52" width="46" height="28" rx="13" fill="#bcc2b1"/><rect x="-20" y="78" width="40" height="8" rx="4" fill="#989f90"/></g>`;}
function plant(x,y,scale=1){return `<g transform="translate(${x} ${y}) scale(${scale})"><ellipse cy="15" rx="18" ry="7" fill="#b6baa4" opacity=".18"/><path d="M-13-1h26l-4 21H-9Z" fill="#d1c5b0"/><ellipse cy="-1" rx="13" ry="5" fill="#e0d4be"/><path d="M0 0v-34" stroke="#879775" stroke-width="3"/><ellipse cx="-9" cy="-22" rx="8" ry="17" transform="rotate(-35 -9 -22)" fill="#a0b38a"/><ellipse cx="10" cy="-30" rx="8" ry="17" transform="rotate(30 10 -30)" fill="#8fa77b"/><ellipse cx="-3" cy="-39" rx="7" ry="16" fill="#b0bd96"/><ellipse cx="13" cy="-13" rx="6" ry="13" transform="rotate(48 13 -13)" fill="#9eaf84"/></g>`;}
function avatar(r){return `<g id="avatar-${r.key}" class="office-avatar" style="transform:translate(${r.home[0]}px,${r.home[1]}px)"><ellipse class="active-ring" cy="13" rx="24" ry="10" fill="none" stroke="${r.shirt}" stroke-width="2" opacity=".7"/><ellipse cy="15" rx="17" ry="6" fill="#5b6858" opacity=".12"/><path d="M-8 6v10m16-10v10" stroke="#6b726a" stroke-width="6" stroke-linecap="round"/><path d="M-12-13Q0-21 12-13l3 19q-15 10-30 0Z" fill="${r.shirt}"/><g class="avatar-hands"><path d="M-12-9-17 2m29-11 5 11" stroke="${r.skin}" stroke-width="5" stroke-linecap="round"/></g><circle cy="-25" r="13" fill="${r.skin}"/><path d="M-13-26q-1-19 13-17t13 17l-5-8q-6 4-13-1l-5 9Z" fill="${r.hair}"/><path d="M-4-24v1m8-1v1" stroke="#6f5d4e" stroke-width="1.4" stroke-linecap="round"/><path d="M-2-18q2 2 4 0" fill="none" stroke="#b77762" stroke-linecap="round"/><g class="state-bubble" transform="translate(14 -52)"><rect width="25" height="16" rx="7" fill="#fffdf4" stroke="#dedecb"/><path d="m3 15-2 5 8-5" fill="#fffdf4"/><circle cx="7" cy="8" r="1.5" fill="${r.shirt}"/><circle cx="12.5" cy="8" r="1.5" fill="${r.shirt}"/><circle cx="18" cy="8" r="1.5" fill="${r.shirt}"/></g></g>`;}
function setupOffice(){
 $('#office-scene').innerHTML=`<svg viewBox="0 0 800 520" role="img" aria-label="ออฟฟิศทีม Agent: หัวหน้า Frontend Backend และ QA"><defs><pattern id="floor" width="48" height="48" patternUnits="userSpaceOnUse"><path d="M48 0H0V48" fill="none" stroke="#e7e8db" stroke-width=".8"/></pattern><filter id="softShadow" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="4" stdDeviation="5" flood-color="#a9ad96" flood-opacity=".12"/></filter></defs>
 <ellipse cx="401" cy="469" rx="320" ry="18" fill="#bdc2a8" opacity=".09"/><path d="M77 72 116 37H684l39 35v355l-39 37H116l-39-37Z" fill="#f1f1e6" stroke="#dfE1D0"/><rect x="97" y="58" width="606" height="383" rx="3" fill="#f5f4e9"/><rect x="97" y="58" width="606" height="383" fill="url(#floor)"/><path d="M77 72h20v369l-20-14Zm626 0h20v355l-20 14Z" fill="#e6e8d8"/><path d="M97 58v16h606V58Z" fill="#e4e8d7"/><path d="M97 441h606" stroke="#dadfca" stroke-width="4"/><path d="M264 441h79m113 0h78" stroke="#f8f9f1" stroke-width="5"/>
 <rect x="136" y="57" width="133" height="18" rx="3" fill="#d0d9c1"/><path d="M143 62h117" stroke="#eff3e7" stroke-width="2"/><path d="M179 58v15m46-15v15" stroke="#e9eedf" stroke-width="3"/><rect x="532" y="57" width="133" height="18" rx="3" fill="#d0d9c1"/><path d="M539 62h117" stroke="#eff3e7" stroke-width="2"/><path d="M575 58v15m46-15v15" stroke="#e9eedf" stroke-width="3"/>
 <g transform="translate(108 108)"><rect width="58" height="67" rx="4" fill="#c2b79e"/><rect x="4" y="3" width="50" height="60" fill="#d8ccb3"/><path d="M5 24h49M5 44h49" stroke="#b7ad96" stroke-width="3"/><path d="M12 7v14m7-14v14m7-14v14m7-14v14m7-14v14" stroke="#a8b996" stroke-width="5"/><path d="M13 29v12m8-12v12m8-12v12m9-12v12" stroke="#bd9d83" stroke-width="5"/><rect x="12" y="49" width="25" height="9" rx="2" fill="#efe4cb"/></g>
 <g transform="translate(649 105)"><rect x="-9" y="-13" width="45" height="48" rx="4" fill="#d7dcc7"/><rect x="-5" y="-9" width="37" height="39" rx="2" fill="#f9faf2"/><path d="m1 20 9-11 7 4 10-15" stroke="#acb69b" stroke-width="2" fill="none"/><circle cx="6" cy="1" r="4" fill="#e9cd9b"/></g>
 <rect x="297" y="200" width="211" height="102" rx="35" fill="#e3dccb" opacity=".65"/><rect x="308" y="209" width="189" height="83" rx="30" fill="#ede7d8"/><ellipse cx="401" cy="251" rx="71" ry="34" fill="#b8b09e" opacity=".18"/><rect x="340" y="220" width="122" height="54" rx="23" fill="#d4b9a0"/><rect x="338" y="214" width="126" height="53" rx="24" fill="#e6cbb0" stroke="#d6bba0"/><path d="M365 215v49m71-49v49" stroke="#d8bfa5" opacity=".8"/><rect x="377" y="223" width="24" height="17" rx="2" fill="#fcf6e9" transform="rotate(-7 377 223)"/><path d="m382 228 13-1m-12 4 10-1" stroke="#d1c6ae"/><circle cx="422" cy="245" r="7" fill="#f9f3e6"/><circle cx="422" cy="245" r="4" fill="#b4a38b"/><text x="400" y="312" text-anchor="middle" font-family="sans-serif" font-size="7" letter-spacing="1.8" fill="#b3b69f">THE THINKING SPOT</text>
 <g transform="translate(109 364)"><rect x="-6" y="-8" width="110" height="54" rx="11" fill="#b8c2a9"/><rect x="1" y="-2" width="42" height="38" rx="7" fill="#d0d8c0"/><rect x="48" y="-2" width="49" height="38" rx="7" fill="#d0d8c0"/><rect x="-10" y="-7" width="12" height="50" rx="5" fill="#c0cab0"/><rect x="97" y="-7" width="12" height="50" rx="5" fill="#c0cab0"/><rect x="9" y="2" width="22" height="20" rx="4" transform="rotate(-12 9 2)" fill="#e2ddc5"/></g>
 <g transform="translate(611 365)"><rect x="-6" y="-8" width="79" height="52" rx="10" fill="#c5b8a3"/><rect x="0" y="-3" width="67" height="37" rx="7" fill="#e0d4bf"/><rect x="-9" y="-7" width="10" height="48" rx="5" fill="#d3c6af"/><rect x="66" y="-7" width="10" height="48" rx="5" fill="#d3c6af"/><rect x="12" y="2" width="21" height="19" rx="4" transform="rotate(10 12 2)" fill="#c7cbae"/></g>
 ${plant(116,203,.78)}${plant(680,203,.85)}${plant(281,415,.65)}${plant(525,415,.65)}
 <g class="office-desk" id="desk-orchestrator" filter="url(#softShadow)">${desk(400,75,'#dcd5e7')}</g>
 <g class="office-desk" id="desk-frontend_specialist" filter="url(#softShadow)">${desk(182,232,'#dbe4cf')}</g>
 <g class="office-desk" id="desk-backend_specialist" filter="url(#softShadow)">${desk(619,232,'#d7e1e5')}</g>
 <g class="office-desk" id="desk-qa_verifier" filter="url(#softShadow)">${desk(401,377,'#eee2c5')}</g>
 <text x="400" y="166" text-anchor="middle" class="office-label-text">Keen · Lead</text><text x="400" y="177" text-anchor="middle" class="office-label-role">PLAN & DELEGATE</text>
 <text x="182" y="323" text-anchor="middle" class="office-label-text">Milo · Frontend</text><text x="182" y="334" text-anchor="middle" class="office-label-role">CRAFT THE EXPERIENCE</text>
 <text x="619" y="323" text-anchor="middle" class="office-label-text">Atlas · Backend</text><text x="619" y="334" text-anchor="middle" class="office-label-role">MAKE IT WORK</text>
 <text x="401" y="470" text-anchor="middle" class="office-label-text">Sage · QA</text><text x="401" y="481" text-anchor="middle" class="office-label-role">CHECK EVERY DETAIL</text>
 ${roles.map(avatar).join('')}</svg>`;
 $('#agent-cards').innerHTML=roles.map(r=>`<div class="agent-card" id="card-${r.key}"><div class="agent-card-top"><span class="mini-avatar role-${r.color}">${r.letter}</span><div><div class="agent-name">${r.name} <span style="font-weight:400;color:#a9ae9e">/ ${r.label}</span></div><div class="agent-role">${r.discipline}</div></div></div><div class="agent-status"><span class="tiny-dot"></span><span>พร้อมรับงาน</span></div><div class="agent-task">รอคำสั่งจากหัวหน้า</div></div>`).join('');
}
function renderAgents(){
 const tasks=S.data?.tasks||[];
 let working=0;
 $('#team-list').innerHTML=roles.map(r=>{const active=tasks.findLast(t=>t.role===r.key&&t.status==='running');const last=tasks.findLast(t=>t.role===r.key);const busy=Boolean(active);if(busy)working++;const failed=!busy&&last&&['failed','interrupted'].includes(last.status);const state=busy?'working':failed?'failed':'';const label=busy?'กำลังทำงาน':failed?'ติดปัญหา':'พร้อมรับงาน';const card=$(`#card-${r.key}`);card.classList.toggle('working',busy);$('.agent-status',card).innerHTML=`<span class="tiny-dot ${state}"></span><span>${label}</span>`;$('.agent-task',card).innerHTML=active?`${esc(active.title)} · <span data-elapsed-start="${esc(active.started_at)}">${duration((Date.now()-new Date(active.started_at))/1000)}</span>`:(last?.status==='completed'?'ส่งงานล่าสุดแล้ว':'รอคำสั่งจากหัวหน้า');const actor=$(`#avatar-${r.key}`);const pos=busy?r.desk:r.home;actor.style.transform=`translate(${pos[0]}px, ${pos[1]}px)`;actor.classList.toggle('working',busy);actor.setAttribute('aria-label',`${r.name} ${label}`);$(`#desk-${r.key}`).classList.toggle('working',busy);return `<div class="team-member" title="${r.name} · ${r.label}: ${label}"><span class="mini-avatar role-${r.color}">${r.letter}</span><div class="team-name">${r.name}<small>${r.label}</small></div><span class="tiny-dot ${state}"></span></div>`;}).join('');
 $('#working-count').textContent=working;
 const running=(S.data?.commands||[]).some(c=>c.status==='running');
 $('#office-status').textContent=S.paused?'พักการเรียก Agent · เก็บคิวและไฟล์ไว้แล้ว':working?'กำลังรับช่วงงานตามแผนหัวหน้า':running?'กำลังเตรียมงานและบันทึกผล':'พร้อมเริ่มสิ่งใหม่ ๆ';
 $('#stop-work').hidden=!running;
}
function eventDescription(e){const d=e.data||{};const r=roles.find(r=>r.key===(e.role||d.role));const name=r?.name||'ทีม';switch(e.type){
 case'engine.updated':return['อัปเดตระบบการทำงานแล้ว',d.message,'spark','success'];
 case'qa.reused':return['QA ใช้ชุดทดสอบเดิม',d.message,'check'];
 case'context.expanded':return['ส่งไฟล์ที่ Agent ขอเพิ่ม',(d.paths||[]).join(', '),'file'];
 case'plan.expanded':return['หัวหน้าปรับสัญญาระบบ','งานนี้ต้องปรับ API หรือข้อมูล จึงตรวจแผนเพิ่มเติม','grid'];
 case'review.pending':return['รอตรวจเพิ่มเติม',d.message,'help'];
 case'provider.paused':return['พักการเรียก Codex',d.message,'help','failed'];
 case'host.verified':return['ตรวจเว็บด้วยโปรแกรมแล้ว',`${d.tests_passed}/${d.tests_executed} ทดสอบผ่าน · รอตรวจรับเพิ่มเติม`,'check','success'];
 case'project.created':return['พื้นที่ใหม่สำหรับ '+d.name,'สร้างโปรเจกต์แล้ว','grid'];
 case'command.queued':return['รับคำสั่งใหม่จากคุณ',d.instruction,'chat'];
 case'revision.started':return[`เริ่มงาน #${d.number}`,'ทำต่อจากไฟล์และบริบทของโปรเจกต์','spark'];
 case'agent.started':return[`${name} รับงาน`,titles[d.task]||d.task,'code'];
 case'agent.completed':return[`${name} ส่งงานแล้ว`,(d.summary||'').slice(0,150),'check','success'];
 case'agent.failed':return[`${name} ติดปัญหา`,(d.error||'').slice(0,200),'help','failed'];
 case'files.changed':return[`บันทึกไฟล์ของ ${d.owner==='tests'?'QA':d.owner}`,`${(d.paths||[]).length} ไฟล์ที่สร้างหรือแก้${d.deleted?.length?' · ลบ '+d.deleted.length+' ไฟล์':''}`,'file'];
 case'plan.created':return['หัวหน้าแบ่งงานแล้ว',(d.target_agents||[]).join(' + '),'grid'];
 case'tests.started':return['QA เริ่มทดสอบจริง',`รอบที่ ${d.round_number}`,'code'];
 case'tests.completed':return[d.passed?'ผลทดสอบผ่าน':'มีผลทดสอบที่ต้องตรวจ',`${d.tests_passed} ผ่าน · ${d.tests_failed} ไม่ผ่าน · ${d.tests_executed} ทดสอบ`,'check',d.passed?'success':'failed'];
 case'fix.assigned':return['หัวหน้าสั่งแก้เฉพาะจุด',(d.targets||[]).join(' + '),'history'];
 case'revision.finished':return[`งาน #${d.number} · ${statusLabel[d.status]||d.status}`,'บันทึกผลและประวัติเรียบร้อย','check',d.status==='approved'?'success':d.status==='failed'?'failed':''];
 case'preview.ready':return['เว็บพร้อมเปิดดูแล้ว','สลับไปแท็บเว็บของคุณเพื่อดูผลลัพธ์','globe','success'];
 case'preview.failed':return['ยังเปิดเว็บไม่ได้',(d.error||'').slice(0,180),'globe','failed'];
 case'command.stop_requested':return['ส่งคำขอหยุดงานแล้ว','เก็บบันทึกงานและไฟล์เว็บปัจจุบันไว้','stop'];
 case'command.interrupted':return['Office หยุดระหว่างงาน','ส่งคำสั่งอีกครั้งเพื่อให้ทีมทำต่อ','help','failed'];
 default:return null;
 }}
function activityHTML(events,empty='ยังไม่มีงานในโปรเจกต์นี้ ส่งไอเดียให้หัวหน้าได้เลยครับ'){
 const visible=events.map(e=>({e,d:eventDescription(e)})).filter(x=>x.d);
 return visible.length?visible.map(({e,d})=>`<div class="activity-item"><span class="activity-marker ${d[3]||''}">${icon(d[2])}</span><div class="activity-content">${esc(d[0])}<small>${esc(d[1])}</small></div><time class="activity-time" datetime="${e.created_at}">${time(e.created_at)}</time></div>`).join(''):`<div class="activity-empty">${esc(empty)}</div>`;
}
function renderActivity(){const events=(S.data?.events||[]);$('#activity-list').innerHTML=activityHTML(events.filter(e=>eventDescription(e)).slice(-5).reverse());$('#event-history').innerHTML=activityHTML([...events].reverse());}
function renderChat(){
 const messages=S.data?.messages||[];const commands=S.data?.commands||[];
 const signature=JSON.stringify([S.projectId,messages.map(m=>m.id),commands.map(c=>[c.id,c.status])]);
 const running=commands.some(c=>c.status==='running');const queued=commands.filter(c=>c.status==='queued').length;
 $('#queue-notice').hidden=!running&&!queued;
 $('#queue-notice').textContent=S.paused?`พักการเรียก Codex${queued?' · เก็บคำสั่งรอไว้ '+queued+' งาน':''}`:running?`ทีมกำลังทำงานอยู่ ส่งคำสั่งถัดไปเข้าคิวได้${queued?' · รออยู่ '+queued+' งาน':''}`:queued?`รอหัวหน้ารับงาน ${queued} งาน`:'';
 $('#message-input').placeholder=S.projectId?'อยากให้ทีมสร้างหรือปรับอะไร…':'สร้างโปรเจกต์ก่อน แล้วคุยกับหัวหน้าได้เลย…';
 if(signature===S.chatSignature)return;S.chatSignature=signature;
 const box=$('#chat-messages');const nearBottom=box.scrollHeight-box.scrollTop-box.clientHeight<90;
 if(!messages.length){box.innerHTML=`<div class="chat-welcome"><span class="welcome-icon">${icon('spark')}</span><h3>มีไอเดียอยู่ในใจ?<br>มาเริ่มด้วยกันครับ</h3><p>คุยกับหัวหน้าเพียงคนเดียว<br>ทีมจะช่วยวางแผน สร้าง และตรวจให้</p><div class="suggestions"><button class="suggestion" data-suggestion="new">${icon('plus')}<span>สร้างโปรเจกต์แรกของคุณ</span><span>↗</span></button><button class="suggestion" data-suggestion="burning">${icon('spark')}<span>เริ่มจากไอเดีย BurningUpp</span><span>↗</span></button><button class="suggestion" data-suggestion="guide">${icon('help')}<span>Office นี้ทำงานอย่างไร?</span><span>↗</span></button></div></div>`;return;}
 box.innerHTML=messages.map(m=>{const user=m.role==='user';const system=m.role==='system';const command=commands.find(c=>c.id===m.command_id);return `<article class="chat-message ${user?'user':system?'system':'assistant'}"><div class="message-label">${user?'คุณ':system?`<span class="mini-avatar role-backend">O</span>Office · บันทึกระบบ`:`<span class="mini-avatar role-lead">K</span>Keen · หัวหน้าทีม`}<time datetime="${m.created_at}">${time(m.created_at)}</time></div><div class="message-text">${esc(m.content)}</div>${user&&command?`<div class="message-command">${esc(statusLabel[command.status]||command.status)}</div>`:''}</article>`;}).join('');
 if(messages.length===1){const brief=S.data.project.brief;box.insertAdjacentHTML('beforeend',`<div class="suggestions"><button class="suggestion" data-suggestion="start">${icon('spark')}<span>${brief?'เริ่มสร้างตามโจทย์โปรเจกต์นี้':'ช่วยวางแผนเว็บให้หน่อย'}</span><span>↗</span></button></div>`);}
 if(nearBottom||messages.length<4)box.scrollTop=box.scrollHeight;
}
function renderPreview(){
 const p=S.data?.preview;const latest=S.data?.project.latest_revision_id;
 $('#website-ready').hidden=!latest;
 if(p?.running){if(S.previewURL!==p.url||S.previewRevision!==p.revision_id){S.previewURL=p.url;S.previewRevision=p.revision_id;$('#website-frame').src=p.url+'?office_version='+encodeURIComponent(p.revision_id);}$('#website-frame').hidden=false;$('#preview-empty').hidden=true;$('#preview-address').textContent=p.url;$('#preview-external').href=p.url;$('#preview-external').classList.remove('disabled');const revision=S.data.revisions.find(r=>r.id===p.revision_id);$('#preview-note').hidden=revision?.status==='approved';$('#preview-note').textContent=`เว็บหลัก · ${statusLabel[revision?.status]||'กำลังตรวจ'} — ใช้ดูต้นแบบและส่งสิ่งที่อยากปรับต่อได้`;}
 else{$('#website-frame').hidden=true;$('#preview-empty').hidden=false;$('#preview-external').classList.add('disabled');$('#preview-note').hidden=true;$('#start-building').innerHTML=latest?'เปิดเว็บหลัก '+icon('out'):'คุยกับหัวหน้า '+icon('arrow');}
}
function renderRevisions(){
 const revisions=S.data?.revisions||[];
 renderCurrentFolder();
 const signature=JSON.stringify([S.projectId,S.selectedRevision,revisions.map(r=>[r.id,r.status,r.round_number,r.changes?.length,r.qa?.tests_executed,r.qa?.tests_passed])]);
 if(signature===S.revisionSignature)return;S.revisionSignature=signature;
 $('#export-history').classList.toggle('disabled',!S.projectId);
 if(S.projectId)$('#export-history').href=`/office-api/projects/${S.projectId}/export`;
 if(S.selectedRevision)renderWorkLog();
 $('#revision-list').innerHTML=revisions.length?revisions.map(r=>`<button class="revision-card ${S.selectedRevision===r.id?'selected':''}" data-revision="${r.id}" style="text-align:left;width:100%"><span class="revision-number">#${r.number}</span><span class="revision-content"><span class="revision-title">${esc(r.instruction)}</span><span class="revision-meta">${date(r.created_at)}<span>·</span>${r.changes?`${r.changes.length} ไฟล์ที่เปลี่ยน`:r.status==='discussed'?'ตอบคำถาม':'ยังไม่สรุปไฟล์'}${r.qa?`<span>·</span>${r.qa.tests_passed}/${r.qa.tests_executed} ทดสอบผ่าน`:''}</span></span><span class="status-pill status-${esc(r.status)}">${esc(statusLabel[r.status]||r.status)}</span></button>`).join(''):'<div class="activity-list activity-empty">เมื่อเริ่มงานครั้งแรก บันทึกงานจะอยู่ตรงนี้<br>ดูคำสั่ง สรุปไฟล์ที่เปลี่ยน และผลทดสอบได้</div>';
}
function render(){S.paused=Boolean(S.data?.provider_issue);$('#provider-notice').hidden=!S.paused;const p=S.data?.project;$('#breadcrumb-name').textContent=p?.name||'เริ่มต้นโปรเจกต์';$('#project-title').innerHTML=p?`${esc(p.name)}<span>.</span>`:'ไอเดียของคุณ ทีมของคุณ<span>.</span>';$('#project-subtitle').textContent=p?'พื้นที่ที่ทีมของคุณช่วยสร้าง ทดสอบ และปรับเว็บให้ดีขึ้น':'คุยกับหัวหน้า แล้วปล่อยให้ทีมช่วยสร้างสิ่งที่คุณคิด';renderProjects();renderAgents();renderPerformance();renderActivity();renderChat();renderPreview();renderRevisions();}
async function refresh(){if(!S.projectId)return;if(refreshing){refreshAgain=true;return;}refreshing=true;const pid=S.projectId;try{const data=await api(`/projects/${pid}`);if(pid!==S.projectId)return;S.data=data;S.connected=true;render();updateConnection();}catch(error){S.connected=false;updateConnection();}finally{refreshing=false;if(refreshAgain){refreshAgain=false;refresh();}}}
function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,120);}
async function selectProject(id){S.source?.close();S.projectId=id;S.data=null;S.selectedRevision=null;S.selectedFile=null;S.folderSignature=null;$('#current-files').hidden=true;S.chatSignature='';S.previewURL='';S.previewRevision=null;$('#website-frame').removeAttribute('src');$('#revision-detail').hidden=true;localStorage.setItem('burnt-studio-project',id);render();await refresh();if(S.projectId!==id)return;S.source=new EventSource(`/office-api/projects/${id}/events?after=${S.data?.cursor||0}`);S.source.addEventListener('update',scheduleRefresh);S.source.onopen=()=>{S.connected=true;updateConnection();};S.source.onerror=()=>{S.connected=false;updateConnection();};}
function switchView(view){S.view=view;$$('.view-tab').forEach(n=>{n.classList.toggle('active',n.dataset.view===view);n.setAttribute('aria-selected',n.dataset.view===view);});$$('.view').forEach(n=>n.classList.toggle('active',n.id===`view-${view}`));}
async function openPreview(revisionId=null){if(!S.projectId)return;try{toast('กำลังเปิดเว็บของโปรเจกต์…');await api(`/projects/${S.projectId}/preview`,{method:'POST',body:JSON.stringify({revision_id:revisionId})});await refresh();switchView('website');}catch(error){toast(error.message);}}
function renderCurrentFolder(){
 const project=S.data?.project;const box=$('#website-folder');
 if(!project){box.innerHTML='<p>เลือกโปรเจกต์เพื่อดูโฟลเดอร์เว็บ</p>';return;}
 const signature=JSON.stringify([project.id,project.website_path]);
 if(S.folderSignature===signature)return;S.folderSignature=signature;
 box.innerHTML=`<div><span class="eyebrow">โฟลเดอร์เว็บหลัก · ใช้อันเดิมทุกคำสั่ง</span><h3>${esc(project.website_folder)}</h3><p class="folder-path">${esc(project.website_path)}</p><p>เก็บเฉพาะเว็บปัจจุบันกับสรุปงาน ไม่มีสำเนาเว็บย้อนหลัง</p></div><div class="folder-actions"><button class="button button-outline" id="open-website-folder">${icon('out')}เปิดโฟลเดอร์</button><button class="button button-outline" id="browse-current-files">${icon('file')}ดูไฟล์ปัจจุบัน</button></div>`;
}
function selectRevision(id){
 S.selectedRevision=id;renderRevisions();renderWorkLog();
}
function renderWorkLog(){
 const revision=S.data?.revisions.find(r=>r.id===S.selectedRevision);if(!revision)return;
 $('#revision-detail').hidden=false;
 $('#revision-detail').innerHTML=`<div class="detail-header"><h3>บันทึกงาน #${revision.number}</h3><span class="status-pill status-${esc(revision.status)}">${esc(statusLabel[revision.status]||revision.status)}</span></div><div class="work-log"><p>${esc(revision.instruction)}</p><p class="log-note">สรุปงานเท่านั้น · ไฟล์เว็บอยู่ในโฟลเดอร์หลัก</p><ul>${(revision.changes||[]).map(c=>`<li><code>${esc(c.path)}</code> · ${esc(({added:'เพิ่มไฟล์',modified:'แก้ไข',deleted:'ลบไฟล์'})[c.kind]||c.kind)} · +${Number(c.added)||0} / −${Number(c.removed)||0} บรรทัด</li>`).join('')||'<li>ไม่มีรายการไฟล์ที่เปลี่ยน</li>'}</ul>${revision.error?`<p>${esc(revision.error)}</p>`:''}${revision.qa?`<p><b>ทดสอบ:</b> ${revision.qa.tests_passed}/${revision.qa.tests_executed} ผ่าน</p><p>${esc(revision.qa.summary)}</p>`:''}${revision.signoff?`<p><b>หัวหน้า:</b> ${esc(revision.signoff.summary)}</p>`:''}</div>`;
}
async function browseCurrentFiles(){
 const pid=S.projectId;if(!pid)return;
 try{const result=await api(`/projects/${pid}/files`);if(pid!==S.projectId)return;S.files=result.files;$('#current-files').hidden=false;$('#current-files').innerHTML=`<div class="detail-header"><h3>ไฟล์เว็บปัจจุบัน</h3><span>แก้ต่อในโฟลเดอร์นี้</span></div><div class="detail-body"><nav class="file-list" aria-label="ไฟล์เว็บปัจจุบัน">${S.files.map(f=>`<button class="file-button" data-file="${esc(f.path)}">${icon('file')}<span>${esc(f.path)}</span></button>`).join('')||'<p class="code-empty">ยังไม่มีไฟล์เว็บ</p>'}</nav><div class="file-viewer"><pre class="code-view" id="file-content">เลือกไฟล์เพื่อดูเนื้อหาปัจจุบัน</pre></div></div>`;if(S.files.length)await showFile(S.files[0].path);}catch(error){toast(error.message);}
}
async function showFile(path){
 S.selectedFile=path;$$('.file-button').forEach(b=>b.classList.toggle('active',b.dataset.file===path));const pid=S.projectId;
 try{const file=await api(`/projects/${pid}/file?path=${encodeURIComponent(path)}`);if(pid===S.projectId&&S.selectedFile===path)$('#file-content').textContent=file.content;}catch(error){toast(error.message);}
}
function newProject(prefill=false){$('#project-dialog').showModal();if(prefill){$('#project-name').value='BurningUpp';$('#project-brief').value='แพลตฟอร์มดูแลสุขภาวะทีม รองรับหลายองค์กรและหลายทีม มีการเช็กอินอารมณ์ ประวัติรายวัน แดชบอร์ดแนวโน้ม และการติดตามผลโดยหัวหน้าทีม';}$('#project-name').focus();}
$('#recheck-codex').addEventListener('click',async()=>{const button=$('#recheck-codex');button.disabled=true;try{let status;try{status=await api('/provider/recheck',{method:'POST',body:'{}'});}catch{status=await api('/codex/recheck',{method:'POST',body:'{}'});}S.providerReady=Boolean(status.ready);if(status.provider)S.providerName=status.provider;toast(status.message);await refresh();updateConnection();}catch(error){toast(error.message);}finally{button.disabled=false;}});
$('#new-project').addEventListener('click',()=>newProject());$('#close-project-dialog').addEventListener('click',()=>$('#project-dialog').close());$('#close-info').addEventListener('click',()=>$('#info-dialog').close());['guide','office-info'].forEach(id=>$('#'+id).addEventListener('click',()=>$('#info-dialog').showModal()));
$('#project-form').addEventListener('submit',async e=>{e.preventDefault();const submit=$('button[type=submit]',e.target);submit.disabled=true;try{const project=await api('/projects',{method:'POST',body:JSON.stringify({name:$('#project-name').value,brief:$('#project-brief').value})});S.projects.unshift(project);$('#project-dialog').close();e.target.reset();await selectProject(project.id);$('#message-input').focus();}catch(error){toast(error.message);}finally{submit.disabled=false;}});
$('#project-list').addEventListener('click',e=>{const button=e.target.closest('[data-project]');if(button)selectProject(button.dataset.project);});
$('#project-switcher').addEventListener('change',e=>{if(e.target.value==='new'){newProject();e.target.value=S.projectId||'';}else if(e.target.value)selectProject(e.target.value);});
$('#jump-chat').addEventListener('click',()=>{$('.chat-panel').scrollIntoView({behavior:'smooth'});$('#message-input').focus({preventScroll:true});});
$('#jump-office').addEventListener('click',()=>{$('.main-panel').scrollIntoView({behavior:'smooth'});});
$$('[data-view]').forEach(b=>b.addEventListener('click',()=>switchView(b.dataset.view)));$('#all-activity').addEventListener('click',()=>switchView('history'));
$('#chat-form').addEventListener('submit',async e=>{e.preventDefault();if(!S.projectId){newProject();return;}const input=$('#message-input');const text=input.value.trim();if(!text)return;$('#send-message').disabled=true;try{await api(`/projects/${S.projectId}/messages`,{method:'POST',body:JSON.stringify({content:text})});input.value='';await refresh();$('#chat-messages').scrollTop=$('#chat-messages').scrollHeight;}catch(error){toast(error.message);}finally{$('#send-message').disabled=false;input.focus();}});
$('#message-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#chat-form').requestSubmit();}});
$('#chat-messages').addEventListener('click',e=>{const suggestion=e.target.closest('[data-suggestion]')?.dataset.suggestion;if(suggestion==='new')newProject();if(suggestion==='burning')newProject(true);if(suggestion==='guide')$('#info-dialog').showModal();if(suggestion==='start'){$('#message-input').value=S.data.project.brief?'เริ่มสร้างเว็บตามโจทย์โปรเจกต์นี้ ให้ใช้งานได้เป็นต้นแบบ แล้วสรุปสิ่งที่ทำและข้อจำกัดให้ด้วย':'ช่วยเสนอแนวทางและวางแผนเว็บให้หน่อย';$('#message-input').focus();}});
$('#stop-work').addEventListener('click',async()=>{try{await api(`/projects/${S.projectId}/stop`,{method:'POST',body:'{}'});toast('ขอหยุดงานแล้ว กำลังเก็บผลที่ทำไว้');await refresh();}catch(error){toast(error.message);}});
$('#start-building').addEventListener('click',()=>{if(S.data?.project.latest_revision_id)openPreview();else if(!S.projectId)newProject();else $('#message-input').focus();});
$('#preview-refresh').addEventListener('click',()=>{if(S.previewURL)$('#website-frame').src=S.previewURL;else if(S.data?.project.latest_revision_id)openPreview();else toast('รอให้ทีมสร้างเว็บก่อนครับ');});$('#preview-mobile').addEventListener('click',()=>{$('#website-frame').classList.toggle('mobile');$('#preview-mobile').classList.toggle('selected');});
$('#revision-list').addEventListener('click',e=>{const revision=e.target.closest('[data-revision]')?.dataset.revision;if(revision)selectRevision(revision);});
$('#current-files').addEventListener('click',e=>{const path=e.target.closest('[data-file]')?.dataset.file;if(path)showFile(path);});
$('#website-folder').addEventListener('click',async e=>{if(e.target.closest('#browse-current-files'))browseCurrentFiles();if(e.target.closest('#open-website-folder')){try{await api(`/projects/${S.projectId}/open-folder`,{method:'POST',body:'{}'});toast('เปิดโฟลเดอร์เว็บแล้ว');}catch(error){toast(error.message);}}});
async function boot(){setupOffice();render();try{const boot=await api('/bootstrap');S.token=boot.token;S.projects=boot.projects;S.backend=boot.backend||'antigravity';S.providerName=boot.provider_name||(S.backend==='codex'?'Codex':'Google Antigravity');renderProjects();const saved=localStorage.getItem('burnt-studio-project');const project=S.projects.find(p=>p.id===saved)||S.projects[0];if(project)await selectProject(project.id);let prov;try{prov=await api('/provider');}catch{prov=await api('/codex');}S.providerReady=Boolean(prov.ready);if(prov.provider)S.providerName=prov.provider;$('#connection').title=prov.message||'';updateConnection();}catch(error){S.connected=false;updateConnection();toast(error.message);}}
setInterval(()=>{if(S.projectId&&document.visibilityState==='visible')refresh();},12000);
boot();
