import re

def registration_errors(username,password,confirm=None):
    errors=[]
    if not username:
        errors.append('用户名：请输入用户名。')
    elif not 3 <= len(username) <= 40:
        errors.append(f'用户名：需要 3–40 个字符，当前为 {len(username)} 个。')
    elif not re.fullmatch(r'[A-Za-z0-9_\-\u4e00-\u9fff]+',username):
        errors.append('用户名：仅支持中文、英文字母、数字、下划线 _ 和连字符 -，不能包含空格或其他符号。')
    if not password:
        errors.append('密码：请输入密码。')
    elif not 8 <= len(password) <= 128:
        errors.append(f'密码：需要 8–128 个字符，当前为 {len(password)} 个。')
    if confirm is not None:
        if not confirm: errors.append('确认密码：请再次输入密码。')
        elif confirm!=password: errors.append('确认密码：两次输入不一致，请重新确认。')
    return errors
