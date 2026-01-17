import json
import webbrowser
import re
import threading
import requests
from urllib.parse import quote, unquote
from tkinter import *
from tkinter import messagebox

# ================= 1. 全局配置 =================
# 使用 Chrome 用户代理，防止被部分平台简单的反爬逻辑拦截
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
}

def get_real_url(url):
    """
    追踪原始链接：针对移动端分享的短链（如 163cn.tv, kugou.com/share）
    通过发送 HEAD 请求获取其重定向后的真实 Web 地址。
    """
    if any(k in url for k in ["163cn.tv", "kugou.com/share", "url.cn", "t.cn"]):
        try:
            res = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=5)
            return res.url
        except: pass
    return url

# ================= 2. 平台 API 抓取 =================
def fetch_metadata(source, sid):
    """
    元数据补全：根据 ID 向平台请求歌名、歌手和封面。
    LX Music 播放单曲协议必须包含这些字段，否则界面会显示空白或调用失败。
    """
    try:
        if source == 'wy':  # 网易云音乐 API
            res = requests.get(f"https://music.163.com/api/song/detail/?id={sid}&ids=[{sid}]", timeout=5).json()
            s = res.get('songs', [])[0]
            return s.get('name'), s.get('artists', [{}])[0].get('name'), s.get('album', {}).get('picUrl', '')
        
        elif source == 'tx':  # 腾讯 (QQ音乐) 官方 Web 接口
            is_mid = not str(sid).isdigit()
            # 构造腾讯通用的 musicu 接口 payload
            payload = {
                "comm": {"ct": 24, "cv": 0},
                "songinfo": {
                    "method": "get_song_detail_yqq",
                    "module": "music.pf_song_detail_svr",
                    "param": {"song_mid" if is_mid else "song_id": sid if is_mid else int(sid)}
                }
            }
            res = requests.get(f"https://u.y.qq.com/cgi-bin/musicu.fcg?data={quote(json.dumps(payload))}", headers={'Referer': 'https://i.y.qq.com/'}, timeout=5).json()
            t = res.get('songinfo', {}).get('data', {}).get('track_info', {})
            if t:
                # 合成官方 CDN 封面地址
                a_mid = t.get('album', {}).get('mid', '')
                img = f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{a_mid}.jpg" if a_mid else ""
                return t.get('name'), t.get('singer', [{}])[0].get('name'), img
        
        elif source == 'kg':  # 酷狗音乐移动端接口
            res = requests.get(f"http://mobilecdn.kugou.com/api/v3/song/info?hash={sid}", timeout=5).json()
            d = res.get('data', {})
            return d.get('songname'), d.get('singername'), d.get('imgUrl', '').replace('{size}', '400')
    except: pass
    return None, None, None

# ================= 3. 核心业务处理 =================
def worker_thread(raw_input):
    """
    后台线程：处理链接解析与协议跳转，避免 GUI 界面在请求网络时卡死。
    """
    url = get_real_url(unquote(raw_input))
    source, p_name = 'tx', '腾讯音乐'
    if '163.com' in url: source, p_name = 'wy', '网易云音乐'
    elif 'kugou.com' in url: source, p_name = 'kg', '酷狗音乐'

    # --- 步骤 1: 提取单曲 ID (优先级最高) ---
    sid = None
    if source == 'tx':
        # 依次匹配：移动端 songid、新版 songDetail 路径、旧版 mid 参数、旧版数字 song/id 路径
        m = re.search(r'songid=(\d+)', url) or re.search(r'songDetail/([a-zA-Z0-9]+)', url) or \
            re.search(r'mid=([a-zA-Z0-9]+)', url) or re.search(r'song/(\d+)', url)
        if m: sid = m.group(1)
    elif source == 'kg':
        # 提取 32 位 Hash 值
        m = re.search(r'hash=([a-fA-F0-9]{32})', url, re.I) or re.search(r'song/([a-fA-F0-9]{32})', url, re.I)
        if m: sid = m.group(1).upper()
    else: # WY
        m = re.search(r'id=(\d+)', url)
        if m: sid = m.group(1)

    # --- 步骤 2: 单曲解析与跳转 ---
    if sid:
        name, singer, img = fetch_metadata(source, sid)
        if name:
            # 构造符合 LX Music 规范的单曲播放 JSON 数据体
            data = {
                "source": source,
                "name": name,
                "singer": singer,
                "songmid": str(sid),
                "img": img,
                "types": [{"type": "128k", "size": "0"}]
            }
            # 针对不同平台的特殊必填字段
            if source == 'tx': data["strMediaMid"] = str(sid)
            elif source == 'kg': data["hash"] = sid; data["types"][0]["hash"] = sid
            
            def go_s():
                if messagebox.askyesno("歌曲识别成功", f"【{p_name}】\n歌曲：{name}\n歌手：{singer}\n\n是否立即播放？"):
                    webbrowser.open(f"lxmusic://music/play?data={quote(json.dumps(data, ensure_ascii=False))}")
                reset_ui()
            root.after(0, go_s); return  # 解析成功则终止，不再判断歌单

    # --- 步骤 3: 歌单/专辑 识别 (单曲未匹配时的兜底) ---
    lid = None
    if source == 'kg':
        m = re.search(r'special/single/(\d+)', url) or re.search(r'id=(\d+)', url)
    else:
        # 匹配网易或腾讯的歌单 ID 路径
        m = re.search(r'playlist/(\d+)', url) or re.search(r'album/([a-zA-Z0-9]+)', url) or re.search(r'id=([a-zA-Z0-9]+)', url)
    
    if m: lid = m.group(1)
    if lid:
        def go_l():
            if messagebox.askyesno("识别成功", f"识别到{p_name}歌单/专辑\nID: {lid}\n\n是否打开详情？"):
                webbrowser.open(f"lxmusic://songlist/open/{source}/{lid}")
            reset_ui()
        root.after(0, go_l); return

    root.after(0, lambda: [messagebox.showwarning("解析失败", "无法提取有效 ID，请检查链接格式。"), reset_ui()])

# ================= 4. UI 界面逻辑 =================
def reset_ui():
    """清空输入框并恢复按钮状态"""
    entry.delete(0, END)
    btn_run.config(state=NORMAL, text='解析并播放')

def start_process():
    """启动入口：获取输入 -> 锁定 UI -> 开启线程"""
    content = entry.get().strip()
    if not content:
        try: # 如果输入框为空，尝试从剪贴板读取
            content = root.clipboard_get().strip()
            entry.insert(0, content)
        except: return
    btn_run.config(state=DISABLED, text="识别中...")
    threading.Thread(target=worker_thread, args=(content,), daemon=True).start()

# --- 主程序窗口 ---
root = Tk()
root.title('LXMusicHelper v1.0')
root.attributes('-topmost', 1)  # 保持置顶，方便从浏览器切过来使用
root.geometry('420x150')

# 窗口居中逻辑
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
root.geometry('+%d+%d' % ((sw-420)/2, (sh-150)/2))

frame = Frame(root)
frame.pack(expand=True)

Label(frame, text='支持网易/腾讯/酷狗，单曲及歌单快速转换（输入框留空将自动读取剪贴板）', font=('Microsoft YaHei', 9), fg='#666').pack(pady=5)

entry = Entry(frame, width=45, font=('Consolas', 10), bd=2)
entry.pack(padx=20, pady=5)
entry.focus_set()
entry.bind('<Return>', lambda e: start_process()) # 绑定回车键

btn_run = Button(frame, text='解析并播放', command=start_process, bg='#2196F3', fg='white', 
                relief=FLAT, width=18, font=('Microsoft YaHei', 9, 'bold'), cursor='hand2')
btn_run.pack(pady=10)

root.mainloop()