import {h,badge} from './base.js';
import {table} from './readout.js';
export const states={pending:'待复核',paired:'纳入',excluded:'隔离'};
export function stripRows(rows){
  return table('试条密度配对',['试条','短洗温度','长洗温度','短洗密度','长洗密度','掉色','证据状态'],
    rows.map(x=>[x.code,x.short_temp+' °C',x.long_temp+' °C',x.short_density,x.long_density,x.long_fade,states[x.state]]));
}
export function controls(rows){
  return rows.filter(x=>x.state==='pending').map(x=>'<div><b>'+h(x.code)+'</b> '+badge(states[x.state])+' <button data-code="'+h(x.code)+'" data-include="true">纳入</button> <button class="quiet" data-code="'+h(x.code)+'" data-include="false">隔离</button></div>').join('');
}
const readingFields=[['short_temp','短洗水温'],['long_temp','长洗水温'],['short_density','短洗密度'],['long_density','长洗密度'],['long_fade','长洗掉色']];
export function readingEditor(rows){
  return '<section class="reading-editor"><h2>更正抄错的读数</h2>'
    +'<p class="empty-state">按送检试条上的原始读数改正。保存后，依据旧读数的检验会立即失效，需要重新运行检验，达标后才能换签；换签前原工签继续有效。</p>'
    +rows.map(x=>'<form class="reading-row" data-reading-form="'+h(x.code)+'">'
      +'<b class="reading-code">'+h(x.code)+'</b>'
      +readingFields.map(([key,label])=>'<label for="reading-'+h(x.code)+'-'+key+'">'+label+'</label>'
        +' <input id="reading-'+h(x.code)+'-'+key+'" name="'+key+'" data-field="'+key+'"'
        +' aria-label="'+h(x.code)+' '+label+'" type="number" step=".001" min="0" value="'+h(x[key])+'" required>').join('')
      +'<button type="submit" data-save-reading="'+h(x.code)+'">保存读数</button>'
      +'</form>').join('')+'</section>';
}
