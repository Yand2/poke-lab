import html
import json
from diagnosis import report_sections
import os
from pathlib import Path
import httpx
import streamlit as st

st.set_page_config(page_title='Poke · 创业点子审判庭', page_icon='◈',layout='wide')
API = os.getenv('POKE_API_URL','http://127.0.0.1:8765')
ROOT = Path(__file__).resolve().parent
st.markdown('<style>'+ (ROOT/'style.css').read_text(encoding='utf-8')+'</style>',unsafe_allow_html=True)

def api(method,path,**kwargs):
    try:
        health=httpx.get(API+'/health',timeout=3)
        if health.status_code!=200 or health.json().get('service')!='poke-demo-local':
            st.error('连接的服务不是本项目后端，请检查端口配置并重新启动。')
            return None
        token=st.session_state.get('token')
        response = httpx.request(method,API+path,timeout=12,headers={'Authorization':'Bearer '+token} if token else {},**kwargs)
        if response.is_error:
            if response.status_code==401 and not path.startswith('/auth/'):
                st.session_state.clear()
                st.rerun()
            detail = response.json().get('detail','请求未完成')
            if path=='/auth/register' and not isinstance(detail,str):
                from registration_rules import registration_errors
                payload=kwargs.get('json',{})
                detail='\n\n'.join(registration_errors(payload.get('username',''),payload.get('password',''))) or '注册信息格式不正确，请检查用户名和密码。'
            st.error(detail if isinstance(detail,str) else '请检查输入长度和内容后重试。')
            if path=='/auth/register': st.toast(detail if isinstance(detail,str) else '注册信息不符合要求。',icon='⚠️')
            return None
        if path.endswith('/report.docx'): return response.content
        return response.text if path.endswith('/report') else response.json()
    except (httpx.HTTPError,ValueError):
        st.error('暂时无法连接分析服务。请确认已运行启动脚本，再点击重试。')
        return None

def safe(value):
    return html.escape(str(value))

@st.fragment(run_every='2s')
def watch_run(run_id):
    current=api('GET','/runs/'+run_id)
    if current and current['status']!='running':
        st.rerun()
    st.caption('每 2 秒自动更新分析进度。')

def card(pid,name,focus,question):
    st.markdown(f'<div class="persona"><div class="avatar {pid}">{pid}</div><h4>{name}</h4><span>{focus}</span><p>{question}</p></div>',unsafe_allow_html=True)

PERSONAS = [
    ('R1','尝鲜者','创新体验','新鲜感之后，价值还在吗？'),
    ('R2','保守用户','习惯与迁移','为什么要改变我的习惯？'),
    ('R3','价格敏感者','成本与收益','这笔钱，真的值得花吗？'),
    ('R4','信任怀疑者','风险与信任','我凭什么相信你？'),
    ('R5','专业用户','质量与可控性','它能胜任关键任务吗？')]

from auth_ui import gate
gate(api)

with st.sidebar:
    st.markdown('<div class="brand">◈ <b>poke</b><span>THE HYPOTHETICAL</span></div>',unsafe_allow_html=True)
    st.caption('创业点子审判庭')
    st.markdown('---')
    if 'page' not in st.session_state: st.session_state.page='新建实验'
    for item in ['新建实验','灵感聊天室','历史实验','使用指南']:
        if st.button(item,key='nav-'+item,use_container_width=True,type='primary' if st.session_state.page==item else 'secondary'):
            st.session_state.page=item
            st.rerun()
    page=st.session_state.page
    st.caption('已登录：'+st.session_state.get('username',''))
    if st.button('退出登录',use_container_width=True):
        api('POST','/auth/logout')
        st.session_state.clear()
        st.rerun()
    st.markdown('---')
    st.caption('五种视角，一起打磨你的想法。')
    st.markdown('<div class="sidebar-note">先发现阻力<br>再投入开发。<small>AI 模拟 ≠ 真人验证</small></div>',unsafe_allow_html=True)

st.markdown('<div class="topline">WORKSPACE / 实验室 <span>POKE LAB · MVP</span></div>',unsafe_allow_html=True)

def results(run_id):
    r = api('GET','/runs/'+run_id)
    if not r: return
    st.markdown('---')
    st.subheader('实验结果')
    st.caption(f'{r["id"][:8]} · AI 分析 · {r["created_at"][:19]} UTC')
    if r['status']=='running':
        st.info('五角色分析已完成，正在生成综合诊断报告。' if len(r['results'])==5 else f'正在整理想法与分析角色：已完成 {len(r["results"])} / 5。可稍后从历史实验查看。')
        if st.button('刷新进度'): st.rerun()
        watch_run(run_id)
        return
    if r['status']=='failed':
        st.error(r['error'])
        if st.button('重新分析'):
            new = api('POST',f'/runs/{run_id}/retry')
            if new:
                st.session_state.active_run=new['id']
                st.rerun()
        return
    counts=[sum(x['choice']==c for x in r['results']) for c in ['暂不采用','需要验证','愿意尝试']]
    for col,label,n in zip(st.columns(3),['暂不采用','需要验证','愿意尝试'],counts): col.metric(label,f'{n} / 5')
    st.caption('选择下方页签，查看判断、质询、挑战或报告。')
    tabs=st.tabs(['五角色判断','重点质询','单变量挑战','验证报告'])
    with tabs[0]:
        if r.get('profiles_json'):
            with st.expander('查看本次假设用户画像'):
                st.caption('这些画像用于模拟，不是真实用户样本；推断不能当成已核实事实。')
                for p in json.loads(r['profiles_json']):
                    st.markdown('**'+p['persona_id']+' · '+p['scenario']+'**')
                    st.write('现有习惯：'+p['current_habit']+'；预算约束：'+p['budget_constraint'])
                    st.write('采用条件：'+p['adoption_condition'])
                    st.caption('假设：'+'；'.join(p['assumptions']))
        for x in r['results']:
            name=next(p[1] for p in PERSONAS if p[0]==x['persona_id'])
            with st.expander(f'{x["persona_id"]} · {name}　|　{x["choice"]}',expanded=True):
                st.write(x['recognition'])
                st.markdown('**采用阻力**')
                st.write(x['barrier'])
                st.markdown('**判断依据**')
                st.write(x['reason'])
                st.caption('输入证据（用户陈述，未独立核验）')
                st.code(x['evidence'],language=None,wrap_lines=True)
    with tabs[1]:
        x=next(x for x in r['results'] if x['persona_id']==r['focus'])
        st.markdown(f'### 优先访谈：{x["persona_id"]}')
        st.caption('选择规则：暂不采用优先，其次需要验证；同级按角色编号。')
        st.warning(x['barrier'])
        st.markdown('**把问题带给真人**')
        st.write(x['question'])
        st.code(x['evidence'],language=None,wrap_lines=True)
        st.write('请受访者回忆最近一次具体经历，并展示实际使用的替代方案。记录原话与行为，不把推测当作证据。')
    with tabs[2]:
        if r['parent_id']:
            st.caption(f'基线 {r["parent_id"][:8]} · 变更 {r["variable"]}：{r["change_value"]}')
            base=api('GET','/runs/'+r['parent_id'])
            if base:
                st.table([{'角色':a['persona_id'],'基线':a['choice'],'挑战后':b['choice'],'变化':'已变化' if a['choice']!=b['choice'] else '不变'} for a,b in zip(base['results'],r['results'])])
            st.caption('需测试其他变量时，请从历史实验打开原始基线。')
        else:
            st.markdown('#### 只改一个条件，观察判断变化')
            st.write('概念、痛点与替代方案保持原样。补充条件仅覆盖你选择的变量。')
            with st.form('challenge-'+run_id):
                labels={'price':'价格与收费','onboarding':'上手与迁移','trust':'信任与保障','quality':'质量与控制','novelty':'创新体验'}
                variable=st.selectbox('选择变量',list(labels),format_func=lambda v:labels[v])
                value=st.text_area('新的条件',placeholder='例如：提供 14 天免费试用，之后每月 19 元。',max_chars=1000)
                challenge=st.form_submit_button('运行单变量挑战',type='primary')
            if challenge:
                if len(value.strip())<2: st.error('请至少输入 2 个字符的新条件。')
                else:
                    new=api('POST',f'/runs/{run_id}/challenge',json={'variable':variable,'value':value})
                    if new:
                        st.session_state.active_run=new['id']
                        st.rerun()
    with tabs[3]:
        if r.get('diagnosis_json'):
            st.markdown(report_sections(json.loads(r['diagnosis_json'])))
        else:
            st.warning(r.get('diagnosis_error') or '这份历史实验尚无综合诊断，可基于已有角色结果生成。')
            if st.button('生成 / 重试综合诊断',type='primary',key='diagnosis-'+run_id):
                if api('POST',f'/runs/{run_id}/diagnosis'): st.rerun()
        st.markdown('#### 下一步，去找真实用户')
        st.write('招募 5 位符合场景的受访者进行探索性访谈，记录最近一次痛点、现有做法、任务结果及拒绝原因。这个样本用于发现问题，不用于推算市场规模。')
        report=api('GET',f'/runs/{run_id}/report')
        st.caption('Word 适合阅读、编辑和打印；Markdown 适合复制与归档。')
        word=api('GET',f'/runs/{run_id}/report.docx')
        left,right=st.columns(2)
        with left:
            if word: st.download_button('下载美化报告 · Word',word,file_name=f'poke-{run_id[:8]}.docx',mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',type='primary',use_container_width=True)
        with right:
            if report: st.download_button('下载完整报告 · Markdown',report,file_name=f'poke-{run_id[:8]}.md',mime='text/markdown',use_container_width=True)

if page=='灵感聊天室':
    from chat_ui import render_chat
    render_chat(api)
elif page=='新建实验':
    st.markdown('<div class="eyebrow">CONCEPT STRESS TEST</div><h1>好点子，经得起追问。</h1><p class="lead">让五种不同的用户视角，帮你看见商业概念背后的采用阻力。</p>',unsafe_allow_html=True)
    st.markdown('<div class="steps"><b>01　描述概念</b><span>02　发现阻力</span><span>03　挑战假设</span><span>04　真人验证</span></div>',unsafe_allow_html=True)
    st.subheader('描述你的想法')
    st.caption('用自己的话说清想做什么。一句话或一大段都可以，AI会自动整理并分析。')
    with st.form('experiment-text'):
        text=st.text_area('你的创新点',placeholder='例如：我想做一个面向小团队的AI会议助手，自动整理行动项。目前大家靠人工记笔记，容易遗漏任务。',height=200,max_chars=30000)
        submitted=st.form_submit_button('生成实验结果',type='primary',use_container_width=True)
    if submitted:
        if not text.strip(): st.error('请先写下你的想法。')
        else:
            new=api('POST','/experiments',json={'text':text})
            if new: st.session_state.active_run=new['id']
    st.markdown('### 五种视角，同一个概念')
    for col,p in zip(st.columns(5),PERSONAS):
        with col: card(*p)
    if st.session_state.get('active_run'): results(st.session_state.active_run)
elif page=='历史实验':
    st.title('历史实验')
    st.write('回看原始概念、角色判断，以及每一次单变量挑战。')
    if st.button('刷新历史'): st.rerun()
    history=api('GET','/runs')
    if history:
        query=st.text_input('搜索概念',placeholder='输入关键词筛选')
        rows=[r for r in history if query.casefold() in r['concept'].casefold()]
        if not rows: st.info('没有匹配的实验。')
        for r in rows:
            with st.container(border=True):
                a,b=st.columns([5,1])
                with a:
                    st.write(r['concept'])
                    st.caption(f'{r["id"][:8]} · {r["created_at"][:19]} UTC · {r["mode"]} · {r["status"]} · {"挑战" if r["parent_id"] else "基线"}')
                with b:
                    if st.button('打开',key=r['id']): st.session_state.active_run=r['id']
        if st.session_state.get('active_run'): results(st.session_state.active_run)
    elif history==[]: st.info('还没有实验。前往“新建实验”，可以使用示例快速体验。')
else:
    st.title('使用指南')
    st.write('想分析一个点子并获得实验报告，选择“新建实验”；想听取不同角度的建议，选择“灵感聊天室”。')
    st.subheader('新建实验 · 分析想法，获得实验报告')
    st.caption('报告包含执行摘要、核心阻力、潜在意外价值、方向与转型建议和验证步骤。信息不足时会明确说明；所有结论仍需真人验证。')
    st.markdown("""
    1. 在左侧点击 **新建实验**，用一段文字描述你的想法。
    2. 点击 **生成实验结果**，等待 AI 完成分析。
    3. 在 **五角色判断** 查看不同角色的判断与采用阻力，在 **重点质询** 查看优先需要验证的问题。
    4. 打开 **验证报告**，选择 **下载美化报告 · Word** 或 **下载完整报告 · Markdown**，保存想法的实验报告。
    """)
    st.caption('如果想比较修改前后的判断，可以在“单变量挑战”中只改变一个条件。已有实验可在“历史实验”中重新打开。')
    st.subheader('灵感聊天室 · 交流想法，获得不同角度的建议')
    st.markdown("""
    1. 在左侧点击 **灵感聊天室**，在底部输入你的点子或问题并发送。
    2. 阅读 **尝鲜者、保守用户、价格敏感者、信任怀疑者、专业用户** 的回复，了解不同角度的建议。
    3. 继续发送消息，可以补充背景、讨论建议、纠正理解或点名角色追问。
    4. 点击 **新对话** 开启另一个主题，或通过 **最近的对话** 继续之前的交流。
    """)
    st.subheader('保存与重试')
    st.write('实验和对话会自动保存到当前账号。实验分析失败时点击“重新分析”；聊天回复失败时点击“重试本轮”。')
    st.caption('AI 判断与建议需要结合真实用户反馈进行验证。')