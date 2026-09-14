import streamlit as st
from registration_rules import registration_errors
def gate(api):
    if st.session_state.get('token'): return
    st.markdown('''<style>
    .stApp{background-color:#edf0fc!important;background-image:radial-gradient(ellipse at 12% 18%,#c7c4ff99 0%,transparent 42%),radial-gradient(ellipse at 90% 80%,#b9e2f080 0%,transparent 42%),linear-gradient(135deg,#f6f7ff 0%,#eef1fb 55%,#eaf2f8 100%)!important;background-attachment:fixed!important}
    [data-testid="stAppViewContainer"]{background:transparent!important}
    .stMain{margin-left:0!important;width:100%!important;background-image:linear-gradient(#777fa00a 1px,transparent 1px),linear-gradient(90deg,#777fa00a 1px,transparent 1px);background-size:48px 48px}
    [data-testid="stMainBlockContainer"]{max-width:520px!important;margin:auto!important;padding:20px 28px!important;background:#fff;border:1px solid #ffffff;border-radius:24px;box-shadow:0 24px 80px #494b8d18,0 2px 8px #494b8d08}
    .stMain{padding:24px 16px!important}
    [data-testid="stMainBlockContainer"] h1{text-align:center;font-size:25px!important;letter-spacing:-.5px}
    .eyebrow{text-align:center;margin-top:0}
    [data-testid="stForm"]{border:0!important;padding:4px 0 0!important}
    [data-testid="stTextInputRootElement"]{border:1px solid #aeb7ca!important;border-radius:9px!important;background:#fff!important;min-height:40px}
    [data-testid="stTextInputRootElement"]:focus-within{border-color:#5346e5!important;box-shadow:0 0 0 3px #5346e51a!important}
    [data-testid="stTextInput"] input{background:transparent!important}
    [role="tablist"]{margin:4px 0 8px!important}
    @media(max-width:600px){.stMain{padding:16px 12px!important}[data-testid="stMainBlockContainer"]{padding:16px 20px!important} [data-testid="stMainBlockContainer"] h1{font-size:25px!important}}
    [data-testid="stVerticalBlock"]{gap:14px!important}
    [data-testid="stMainBlockContainer"] h1{padding:0!important;margin:0!important;line-height:1.3!important}
    [data-testid="stMainBlockContainer"] p{margin-bottom:0!important}
    .eyebrow{margin-bottom:0!important;font-size:10px}
    [role="tab"]{min-height:40px!important;height:40px!important;padding:6px!important}
    [data-testid="stTextInput"] label{margin-bottom:3px!important}
    [data-testid="stCaptionContainer"] p{font-size:12px!important;line-height:1.45!important}
    [data-testid="stAlert"]{padding:8px 12px!important}
    </style>''',unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">POKE · YOUR IDEA WORKSPACE</div>',unsafe_allow_html=True)
    tabs=st.tabs(['登录','注册账号'])
    for i,tab in enumerate(tabs):
        with tab:
            with st.form('auth-'+str(i)):
                username=st.text_input('用户名',key='user-'+str(i),help='3–40个字符，中文、字母、数字、下划线或连字符。')
                if i: st.caption('3–40字符：中文、字母、数字、_ 或 -；无空格。例：小林_2026')
                password=st.text_input('密码',type='password',key='pass-'+str(i),help='8–128个字符。')
                if i: st.caption('8–128字符，区分大小写；建议组合字母、数字和符号。')
                confirm=st.text_input('确认密码',type='password') if i else None
                sent=st.form_submit_button('创建账号并登录' if i else '登录',type='primary',use_container_width=True)
            if sent:
                errors=registration_errors(username,password,confirm) if i else []
                if errors:
                    st.toast('注册未完成：请修改下方标出的内容。',icon='⚠️')
                    st.error('注册未完成：'+ '\n'.join(errors))
                else:
                    r=api('POST','/auth/register' if i else '/auth/login',json={'username':username,'password':password})
                    if r:
                        st.session_state.token=r['token']; st.session_state.username=r['username']; st.rerun()
    st.stop()
