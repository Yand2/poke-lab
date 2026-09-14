export const steps=[
 ['roles','五角色判断','先读不同顾虑','AI 会自动扮演五种假设用户。你只需阅读他们愿不愿意尝试，以及为什么。无需自己扮演角色。','会议助手示例：保守用户可能觉得原来的笔记已经够用，不愿迁移。'],
 ['questions','重点质询','找到值得问真人的问题','这里是系统根据采用阻力推荐的访谈问题，不是要求你答题。把它带给目标用户，追问最近一次真实经历。','示例：上次会议后遗漏了什么任务？你当时用什么办法找回？'],
 ['challenge','单变量挑战','可选：只改一个条件','先读完原始结果。选择价格、上手、信任等一个变量，填入新条件再运行；系统会生成独立实验，对比前后判断。其他条件保持不变。','示例：只把收费改为“前14天免费，之后每月19元”，不要同时改变目标用户或功能。运行挑战另计1次额度。'],
 ['report','验证报告','带走结论，验证假设','阅读核心阻力、意外价值和是否调整方向的建议。下载 Word 或 Markdown，与团队讨论，再找真实用户访谈。无需先完成单变量挑战也能看报告。','示例：先用会议纪要原型访谈5名团队成员，记录遗漏是否减少，而非把AI评价当作市场结论。']
];
export function walkthrough(e){return `<details class="panel getting-started"><summary><span>第一次使用？看一个从想法到报告的例子</span><span class="tiny muted">展开步骤 · 不消耗额度</span></summary><div class="walkthrough-intro"><b>先写一句话</b><p>“开会后总忘记谁负责什么，我想做个会议助手。”</p><p>可以直接分析，也可以先点“AI 帮我完善”，检查并修改概念、痛点和现有做法。AI补充的内容只是待验证假设，不必填满所有字段。</p></div><div class="walkthrough-steps">${steps.map((s,i)=>`<article><span class="process-num">0${i+1}</span><div><h3>${e(s[1])} · ${e(s[2])}</h3><p>${e(s[3])}</p><p class="walkthrough-example">${e(s[4])}</p></div></article>`).join('')}</div><p class="tiny muted">上面仅为操作示例，不是实际生成的分析结果。灵感聊天室适合反复讨论，新建实验适合得到一份完整报告。</p></details>`}
export function stepHint(active,e){const s=steps.find(x=>x[0]===active);return s?`<div class="result-help"><b>${e(s[2])}</b><p>${e(s[3])}</p><details><summary>看一个例子</summary><p>${e(s[4])}</p></details></div>`:''}
export function mountIdeaHelper({api,e,icon,refreshMe,toast}){
 const input=document.querySelector('#idea'),form=document.querySelector('#idea-form');
 const tools=document.createElement('div');tools.className='idea-assist-tools';tools.innerHTML=`<div><b>只有一句话？也可以开始。</b><p>让 AI 先给一份可修改的草稿，再由你决定分析什么。</p></div><button class="btn" type="button" id="prepare-idea">${icon('spark')}AI 帮我完善</button><span class="tiny muted">完善草稿计1次；生成实验另计1次</span>`;
 input.before(tools);const target=document.createElement('section');target.id='idea-preparation';target.setAttribute('aria-live','polite');form.after(target);
 const button=tools.querySelector('button');let busy=false,recover=null;
 async function waitDraft(job){
  for(let i=0;i<180;i++){
   if(!target.isConnected)throw Error('返回新建实验可恢复草稿。');
   if(job.status==='completed')return job.result;
   if(job.status==='failed')throw Error(job.error||'草稿生成失败，原文已保留。');
   target.innerHTML='<p class="notice">AI 正在后台完善草稿，可能需要几分钟。离开本页后可恢复结果，请勿重复提交。</p>';
   await new Promise(r=>setTimeout(r,2500));
   job=await api('/idea-drafts/'+job.id);
  }
  throw Error('草稿仍在后台处理，稍后返回新建实验可恢复。');
 }
 api('/idea-drafts/latest').then(job=>{
  if(!job||busy||!target.isConnected)return;
  const resume=document.createElement('button');resume.className='btn';resume.type='button';resume.textContent='恢复上次完善草稿';
  resume.onclick=()=>{recover=job;button.click()};target.append(resume);
 }).catch(()=>{});
 button.onclick=async()=>{
  if(busy)return;const original=recover?recover.text:input.value.trim();if(!original){document.querySelector('#idea-error').textContent='先写一句你的困扰或想做的事情，例如：开会后总忘记谁负责什么。';input.focus();return}
  document.querySelector('#idea-error').textContent='';busy=true;button.disabled=true;button.innerHTML='<span class="spinner"></span> 正在完善…';target.innerHTML='<p class="notice">正在整理可能的方向。你可以继续思考，生成后请检查 AI 的建议。</p>';
  try{const job=recover||await api('/idea-drafts',{method:'POST',data:{text:original}}).catch(err=>{throw Error('未确认草稿提交结果。请刷新本页，点击“恢复上次完善草稿”查看；不要连续提交。'+(err.message.includes('额度')?err.message:''))});recover=null;const d=await waitDraft(job);if(!target.isConnected)return;
   const fields=[['concept','商业概念','你准备做什么'],['pain_point','核心痛点','想解决什么麻烦'],['alternative','现有替代方案','大家现在怎么办'],['target_user','目标用户','先帮助哪类人'],['business_model','收费方式','不知道可留空']];
   target.innerHTML=`<div class="draft-heading"><h3>你的实验草稿</h3><p>以下内容可编辑或留空。尤其要检查“AI建议”，它们不是已确认事实。</p></div><div class="draft-fields">${fields.map(([key,label,hint])=>`<div class="field"><label for="draft-${key}">${label}<span class="badge">${e(d[key].source)}</span></label><textarea class="input" id="draft-${key}" rows="2" maxlength="1000" placeholder="${hint}">${e(d[key].value)}</textarea>${d[key].evidence?`<small class="muted">原文依据：${e(d[key].evidence)}</small>`:''}</div>`).join('')}</div>${d.questions?.length?`<div class="notice"><b>还可以想一想（不必全部回答）</b><ul>${d.questions.map(q=>`<li>${e(q)}</li>`).join('')}</ul></div>`:''}<div class="draft-actions"><button type="button" class="btn primary" id="apply-draft">使用这份草稿</button><button type="button" class="btn" id="dismiss-draft">保留原文</button><span class="tiny muted">应用后仍可修改，不会自动开始分析。</span></div>`;
   target.querySelector('#dismiss-draft').onclick=()=>{target.innerHTML='';input.focus()};
   target.querySelector('#apply-draft').onclick=()=>{
    if(input.value.trim()&&input.value.trim()!==original){toast('原文已修改，请保留当前内容，重新点击“AI 帮我完善”生成匹配的草稿。');return}
    const values=fields.map(([key,label])=>{const value=target.querySelector('#draft-'+key).value.trim();return value?label+'（'+(d[key].source==='原文提取'?'用户检查后的描述':'补充方向，待验证假设')+'）：'+value:''}).filter(Boolean);
    const combined=original+'\n\n【已检查的实验草稿；补充方向仍需真实用户验证】\n'+values.join('\n');
    if(combined.length>30000){toast('合并后超过30,000字，请先精简原文。');return}
    input.value=combined;input.dispatchEvent(new Event('input'));target.innerHTML='';input.focus();toast('草稿已填入输入框。确认后点击“生成实验结果”。');
   };
  }catch(err){if(target.isConnected)target.innerHTML=`<div class="error" role="alert">${e(err.message)}</div>`}
  finally{busy=false;button.disabled=false;button.innerHTML=icon('spark')+'AI 帮我完善';refreshMe().catch(()=>{})}
 };
}
