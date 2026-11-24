import {h,empty,badge} from './base.js';
import {stats} from './readout.js';
export function assayResult(rows,canSign,correcting=false){
  if(!rows.length) return empty('纳入至少六对试条后发起置换。');
  const a=rows[0];
  const stale=Boolean(a.stale??a.invalidated);
  const head=stale?badge('已失效 · 须重算','excluded'):(a.eligible?badge('满足限值','paired'):badge('需要补测','pending'));
  return '<section class="band"><header><h2>同底片精确配对</h2>'+head+'</header>'
    +stats([['样本',a.n+' 对'],['中位增益',a.gain.toFixed(3)],['双侧 p',a.p.toFixed(5)],['最大掉色',a.fade.toFixed(2)]])
    +'<p>样本指纹 '+h(a.sample_key.slice(0,16))+'</p>'
    +(stale?'<p class="stale-note" role="alert">送检后试条读数又被修改，本次检验已失效；请重新运行检验，达标后才能'+(correcting?'换签':'签发')+'。</p>':'')
    +(a.readings?'<details><summary>本次检验采用的读数</summary><pre class="snapshot-json">'+h(JSON.stringify(a.readings,null,2))+'</pre></details>':'')
    +(a.eligible&&!stale&&canSign?'<button data-sign="'+a.id+'">'+(correcting?'签发换签':'签发洗次')+'</button>':'')
    +'</section>';
}
