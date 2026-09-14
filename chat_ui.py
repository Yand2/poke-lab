import json
import streamlit as st

def render_chat(api):
    st.markdown('<div class="eyebrow">FIVE MINDS · ONE CONVERSATION</div>',unsafe_allow_html=True)
    st.title('一个灵感，五种回应。')
    st.caption('想说多少就说多少。我们先整理你的想法，再从五种视角一起聊。')
    left,right=st.columns([3,1])
    with right:
        if st.button('＋ 新对话',use_container_width=True):
            st.session_state.pop('chat_id',None)
            st.rerun()
    with left:
        history=api('GET','/conversations') or []
        with st.popover('最近的对话'):
            if not history: st.caption('还没有对话，发出第一个点子吧。')
            for h in history:
                if st.button(h['title'],key='chat-'+h['id'],use_container_width=True):
                    st.session_state.chat_id=h['id']; st.rerun()
    cid=st.session_state.get('chat_id')
    conversation=api('GET','/conversations/'+cid) if cid else None
    mode='live'
    if conversation and conversation['mode']!='live':
        st.session_state.pop('chat_id',None)
        st.rerun()
    st.caption('AI 整理你的想法，五个角色独立给出建议。')

    @st.fragment(run_every='2s')
    def watch(cid,known):
        latest=api('GET','/conversations/'+cid)
        if latest and latest['turns']:
            last=latest['turns'][-1]
            if last['status']!='running' or len(last['replies'])!=known: st.rerun()
        st.caption('回复会自动出现，可以先阅读已完成的角色。')

    if not conversation:
        st.markdown('<div class="chat-welcome"><h3>不必准备商业计划书。</h3><p>一句“我想做个……”就可以开始。<br>你也可以补充场景、反驳建议，或直接问“价格敏感者，你怎么看？”</p></div>',unsafe_allow_html=True)
        for col,name,focus in zip(st.columns(5),['尝鲜者','保守用户','价格敏感者','信任怀疑者','专业用户'],['有新意吗','值得改变吗','值得付费吗','可以信任吗','足够好用吗']):
            with col: st.markdown(f'**{name}**\n\n{focus}')
    busy=False
    if conversation:
        for index,t in enumerate(conversation['turns']):
            with st.chat_message('user'): st.write(t['message'])
            for reply in t['replies']:
                with st.chat_message('assistant',avatar={'R1':'✨','R2':'🧭','R3':'🪙','R4':'🛡️','R5':'🔬'}[reply['persona_id']]):
                    st.markdown('**'+reply['name']+'**')
                    st.write(reply['response'])
                    st.markdown('**建议**'); st.write(reply['suggestion'])
                    if reply['question']: st.caption(reply['question'])
            if t['status']=='failed':
                st.error(t['error'])
                if index==len(conversation['turns'])-1 and st.button('重试本轮',key='retry-'+t['id']):
                    if api('POST','/conversations/'+cid+'/retry'): st.rerun()
            if t['status']=='running':
                busy=True
                st.info('正在整理你的想法…' if not t['structured'] else f'五位角色正在思考 · {len(t["replies"])} / 5 已回复')
                watch(cid,len(t['replies']))
    message=st.chat_input('说说你的点子，或继续追问…',disabled=busy,max_chars=30000)
    if message:
        response=api('POST','/conversations/'+cid+'/messages' if cid else '/conversations',json={'message':message,'mode':mode})
        if response:
            st.session_state.chat_id=response['id']; st.rerun()
