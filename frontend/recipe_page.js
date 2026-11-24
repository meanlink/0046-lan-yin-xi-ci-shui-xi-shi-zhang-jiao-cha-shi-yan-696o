import {h,empty,badge,notice} from './base.js';
import {intro,table} from './readout.js';
import {cyan} from './cyan_api.js';
import {printTime} from './wash_stamp.js';

const issueState={current:['当前有效','paired'],replaced:['已换签留存','excluded']};

function readingsTable(issue){
  const rows=issue.readings||issue.strips||[];
  if(!rows.length) return '<p class="empty-state">没有留存读数。</p>';
  return table('签发时采用的试条与读数',
    ['试条','短洗水温','长洗水温','短洗密度','长洗密度','掉色','复核状态'],
    rows.map(x=>[x.code,x.short_temp+' °C',x.long_temp+' °C',x.short_density,x.long_density,x.long_fade,({paired:'纳入',excluded:'隔离',pending:'待复核'})[x.state]||x.state]));
}

function currentCard(r,canCorrect){
  const rev=r.revision?('第 '+r.revision+' 签'):'工签';
  let action='';
  if(r.active_correction){
    action='<div class="correction-banner" role="status">更正单 #'+r.active_correction.id
      +' 进行中：本工签继续有效，换签签发时才一次性切换。'
      +' <a href="#pairs">去更正读数 →</a>　<a href="#assay">去重算换签 →</a></div>';
  }else if(canCorrect){
    action='<button type="button" data-start-correction data-plate="'+h(r.plate)+'">发起更正</button>'
      +'<p class="empty-state">发起后可改正抄错的试条读数，原工签在换签前继续有效。</p>';
  }
  return '<article class="contact" data-current-recipe="'+h(r.plate)+'">'
    +'<h2>'+h(r.plate)+' · 水洗 '+h(r.wash_sec)+' 秒 '+badge(rev,'paired')+'</h2>'
    +'<p>当前检验证据号 '+h(r.assay)+(r.issue_id?' · 签发存根 #'+h(r.issue_id):'')+'</p>'
    +'<p>'+h(r.signer)+' · '+h(printTime(r.signed_at))+'</p>'
    +'<p>签发时采用 '+(r.readings||[]).length+' 对试条读数；历次工签见下方签发记录。</p>'
    +action+'</article>';
}

function historySection(issues){
  if(!issues||!issues.length) return '';
  return '<section class="issue-history"><h2>签发记录与旧工签</h2>'
    +'<p class="empty-state">每次签发都封存当时采用的试条和读数；换签后旧工签仍可在此查询。</p>'
    +issues.map(it=>{
      const [label,cls]=issueState[it.state]||[it.state,''];
      return '<details class="contact issue" data-issue="'+it.id+'" data-revision="'+it.revision+'" open>'
        +'<summary><b>第 '+it.revision+' 签 · '+h(it.plate)+' · 水洗 '+h(it.wash_sec)+' 秒</b> '
        +badge(label,cls)+' <span>证据号 '+h(it.assay)+' · '+h(it.signer)+' · '+h(printTime(it.issued_at||it.signed_at))+'</span></summary>'
        +readingsTable(it)+'</details>';
    }).join('')+'</section>';
}

export async function render(outlet,user,message=''){
  const [rows,issues]=await Promise.all([
    cyan('/recipes'),
    cyan('/recipes?history=true').catch(()=>[]),
  ]);
  const canCorrect=user&&(user.role==='reviewer'||user.role==='operator');
  outlet.innerHTML=intro('定版纸样工签','印刷师按原版纸号执行。工签发出后发现读数抄错，可在此发起更正；更正期间原工签有效，达标重签后一次性换签。')
    +'<p role="status" aria-live="polite"></p>'
    +(rows.length?rows.map(r=>currentCard(r,canCorrect)).join(''):empty('待复核员从置换比对签入工单。'))
    +historySection(issues);
  const status=outlet.querySelector('[role=status]');
  if(message) notice(status,message);
  for(const btn of outlet.querySelectorAll('[data-start-correction]')){
    btn.onclick=async()=>{
      btn.disabled=true;
      try{
        const ticket=await cyan('/plates/'+encodeURIComponent(btn.dataset.plate)+'/corrections','POST',{});
        await render(outlet,user,'更正单 #'+ticket.id+' 已发起，原工签继续有效。请到「配对试条」改正读数。');
      }catch(err){
        notice(status,err.message,true);
        btn.disabled=false;
      }
    };
  }
}
