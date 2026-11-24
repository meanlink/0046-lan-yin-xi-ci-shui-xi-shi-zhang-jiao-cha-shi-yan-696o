import {notice} from './base.js';
import {intro} from './readout.js';
import {onSubmit,feedback} from './submit.js';
import {cyan,plate} from './cyan_api.js';
import {stripRows,controls,readingEditor} from './strips_view.js';
import {form,reading} from './strip_form.js';

const numericKeys=['short_temp','long_temp','short_density','long_density','long_fade'];

export async function render(outlet,user,message=''){
  const rows=await cyan(plate+'/strips');
  const [edition]=await cyan('/plates');
  const corrections=await cyan(plate+'/corrections').catch(()=>[]);
  const ticket=(corrections||[]).find(x=>x.state==='open');
  const correcting=Boolean(ticket);
  const canReview=user.role==='reviewer';
  const canRead=user.role==='reviewer'||user.role==='operator';
  const locked=edition.state!=='open'&&!correcting;
  outlet.innerHTML=intro('试条配对与隔离','温差超 2°C 的配对单独隔离，保留原始测量。')
    +(correcting
      ?'<div class="correction-banner" role="status">更正单 #'+ticket.id+' 进行中：原工签继续有效。改正抄错的读数后，请到「置换比对」重新运行检验，达标后签发换签。 <a href="#assay">去重算换签 →</a></div>'
      :(edition.state==='sealed'
        ?'<p class="empty-state">该版已定版封版，试条读数锁定。若工签采用的读数抄错，请先到「定版工签」发起更正。</p>'
        :''))
    +'<div class="stripdesk"><div>'+stripRows(rows)+'</div><aside class="entry">'
    +((edition.state==='open'||correcting)&&canReview?controls(rows):'')
    +feedback
    +(edition.state==='open'&&user.role==='operator'?form():'')
    +(locked&&!correcting?'':'')
    +'</aside></div>'
    +(correcting&&canRead?readingEditor(rows):'');
  const status=outlet.querySelector('[role=status]');
  if(message) notice(status,message);
  const addForm=outlet.querySelector('form[data-add-strip]');
  if(addForm) onSubmit(addForm,async data=>{
    await cyan(plate+'/strips','POST',reading(data));
    await render(outlet,user,'试条已登记');
  });
  for(const btn of outlet.querySelectorAll('[data-code]')) btn.onclick=async()=>{
    try {
      await cyan(plate+'/strips/'+encodeURIComponent(btn.dataset.code)+'/qualify?include='+btn.dataset.include,'POST');
      await render(outlet,user,'已登记复核结果');
    } catch(err){ notice(status,err.message,true); }
  };
  for(const formEl of outlet.querySelectorAll('[data-reading-form]')){
    formEl.addEventListener('submit',async event=>{
      event.preventDefault();
      const code=formEl.dataset.readingForm;
      const button=formEl.querySelector('button');
      if(button) button.disabled=true;
      try{
        const data=reading(Object.fromEntries(new FormData(formEl)));
        const payload={};
        for(const key of numericKeys) payload[key]=data[key];
        await cyan(plate+'/strips/'+encodeURIComponent(code),'PATCH',payload);
        await render(outlet,user,'已更正 '+code+' 的读数；原检验已失效，请重新运行检验。');
      }catch(err){
        notice(status,err.message,true);
        if(button) button.disabled=false;
      }
    });
  }
}
