import json
import webbrowser
import re
import threading
import requests
import html
from urllib.parse import quote, unquote
from tkinter import *
from tkinter import messagebox

# ================= 1. 全局配置 =================
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
}

def get_real_url(url):
    short_links = ["163cn.tv", "kugou.com/share", "url.cn", "t.cn", "kuwo.cn/s", "c.migu.cn", "b23.tv"]
    if any(k in url for k in short_links):
        try:
            res = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=5)
            return res.url
        except: pass
    return url

# ================= 2. 平台 API 抓取 =================
def fetch_metadata(source, sid):
    try:
        if source == 'wy':
            res = requests.get(f"https://music.163.com/api/song/detail/?id={sid}&ids=[{sid}]", headers=HEADERS, timeout=5).json()
            s = res.get('songs', [])[0]
            return s.get('name'), s.get('artists', [{}])[0].get('name'), s.get('album', {}).get('picUrl', '')
        
        elif source == 'tx':
            is_mid = not str(sid).isdigit()
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
                a_mid = t.get('album', {}).get('mid', '')
                img = f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{a_mid}.jpg" if a_mid else ""
                return t.get('name'), t.get('singer', [{}])[0].get('name'), img
        
        elif source == 'kg':
            res = requests.get(f"http://mobilecdn.kugou.com/api/v3/song/info?hash={sid}", headers=HEADERS, timeout=5).json()
            d = res.get('data', {})
            return d.get('songname'), d.get('singername'), d.get('imgUrl', '').replace('{size}', '400')
            
        elif source == 'kw':
            try:
                html_text = requests.get(f"https://kuwo.cn/play_detail/{sid}", headers=HEADERS, timeout=5).text
                t_match = re.search(r'<title>(.*?)</title>', html_text)
                img_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_text)
                
                if t_match:
                    raw_title = html.unescape(t_match.group(1))
                    clean_title = re.sub(r'[_-](单曲在线试听|单曲|专辑|MV)?[_-]?酷我音乐.*$', '', raw_title)
                    
                    if '_' in clean_title: parts = clean_title.rsplit('_', 1)
                    else: parts = clean_title.rsplit('-', 1)
                        
                    name = parts[0].strip() if len(parts) > 0 else ""
                    singer = parts[1].strip() if len(parts) > 1 else "未知"
                    img = img_match.group(1) if img_match else ""
                    
                    if name: return name, singer, img
            except Exception as e: pass

            try:
                h_mobile = HEADERS.copy()
                h_mobile['User-Agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
                res = requests.get(f"http://m.kuwo.cn/newh5/singles/songinfoandlrc?musicId={sid}", headers=h_mobile, timeout=5).json()
                d = res.get('data', {}).get('songinfo', {})
                if d.get('songName'): return d.get('songName'), d.get('artist'), d.get('pic')
            except: pass
            
        elif source == 'mg':
            res = requests.get(f"https://c.musicapp.migu.cn/MIGUM2.0/v1.0/content/resourceinfo.do?copyrightId={sid}&resourceType=2", headers=HEADERS, timeout=5).json()
            d = res.get('resource', [{}])[0]
            if d:
                imgs = d.get('albumImgs', [{}])
                img = imgs[0].get('img') if imgs else ''
                singer = d.get('singer', '')
                if isinstance(singer, list) and len(singer) > 0: singer = singer[0].get('singerName', '')
                return d.get('songName'), singer, img
                
    except Exception as e:
        pass
    return None, None, None

# ================= 3. 核心业务处理 =================
def worker_thread(raw_input):
    url = get_real_url(unquote(raw_input))
    
    source, p_name = 'tx', '腾讯音乐'
    if '163.com' in url or '163cn.tv' in url: source, p_name = 'wy', '网易云音乐'
    elif 'kugou.com' in url or 'kugou.cn' in url: source, p_name = 'kg', '酷狗音乐'
    elif 'kuwo.cn' in url or 'kuwo.com' in url: source, p_name = 'kw', '酷我音乐'
    elif 'migu.cn' in url: source, p_name = 'mg', '咪咕音乐'

    # --- 步骤 1: 属性前置研判 (核心修复点：防止网易云歌单ID被误判为单曲) ---
    # 如果链接里出现了这些关键词，直接判定为歌单/专辑，跳过单曲解析
    is_list = any(keyword in url for keyword in ['playlist', 'album', 'special/single', 'listid', 'songlist'])

    sid = None
    lid = None

    # --- 步骤 2: 提取单曲 ID ---
    if not is_list:
        if source == 'tx':
            m = re.search(r'songid=(\d+)', url) or re.search(r'songDetail/([a-zA-Z0-9]+)', url) or \
                re.search(r'mid=([a-zA-Z0-9]+)', url) or re.search(r'song/(\d+)', url)
            if m: sid = m.group(1)
        elif source == 'kg':
            m = re.search(r'hash=([a-fA-F0-9]{32})', url, re.I) or re.search(r'song/([a-fA-F0-9]{32})', url, re.I) or re.search(r'play/info/([a-fA-F0-9]{32})', url, re.I)
            if m: sid = m.group(1).upper()
        elif source == 'kw':
            m = re.search(r'play_detail/(\d+)', url) or re.search(r'yinyue/(\d+)', url) or \
                re.search(r'rid=(\d+)', url, re.I) or re.search(r'musicId=(\d+)', url, re.I)
            if m: sid = m.group(1)
        elif source == 'mg':
            m = re.search(r'copyrightId=([a-zA-Z0-9]+)', url) or re.search(r'song/([a-zA-Z0-9]+)', url) or re.search(r'cid=([a-zA-Z0-9]+)', url)
            if m: sid = m.group(1)
        elif source == 'wy':
            m = re.search(r'id=(\d+)', url) or re.search(r'song/(\d+)', url)
            if m: sid = m.group(1)

    # --- 步骤 3: 提取歌单/专辑 ID ---
    if is_list or not sid:
        if source == 'kg':
            m_list = re.search(r'special/single/(\d+)', url) or re.search(r'listid=(\d+)', url)
            m_album = re.search(r'album_id=(\d+)', url) or re.search(r'album/(\d+)', url)
            if m_list: lid = f"special_{m_list.group(1)}"
            elif m_album: lid = f"album_{m_album.group(1)}"
        elif source == 'kw':
            m = re.search(r'playlist_detail/(\d+)', url) or re.search(r'playlist/(\d+)', url) or re.search(r'album_detail/(\d+)', url)
            if m: lid = m.group(1)
        elif source == 'mg':
            m = re.search(r'playlist/(\d+)', url) or re.search(r'id=(\d+)', url) or re.search(r'playlistId=(\d+)', url)
            if m: lid = m.group(1)
        elif source == 'wy':
            # 网易云提取逻辑优化
            m = re.search(r'id=(\d+)', url) or re.search(r'playlist/(\d+)', url) or re.search(r'album/(\d+)', url)
            if m: lid = m.group(1)
        else: # tx
            m = re.search(r'playlist/(\d+)', url) or re.search(r'album/([a-zA-Z0-9]+)', url) or re.search(r'id=([a-zA-Z0-9]+)', url)
            if m: lid = m.group(1)

    # --- 步骤 4: 协议执行与跳转 ---
    if sid:
        name, singer, img = fetch_metadata(source, sid)
        name = name or f"未知歌曲 (ID:{sid})"
        singer = singer or "未知"
        img = img or ""

        data = {"source": source, "name": name, "singer": singer, "songmid": str(sid), "img": img, "types": [{"type": "128k", "size": "0"}]}
        if source == 'tx': data["strMediaMid"] = str(sid)
        elif source == 'kg': data["hash"] = sid; data["types"][0]["hash"] = sid
        elif source == 'mg': data["copyrightId"] = sid 
        
        def go_s():
            if messagebox.askyesno("单曲识别成功", f"【{p_name}】\n歌曲：{name}\n歌手：{singer}\n\n是否立即播放？"):
                webbrowser.open(f"lxmusic://music/play?data={quote(json.dumps(data, ensure_ascii=False))}")
            reset_ui()
        root.after(0, go_s); return
        
    elif lid:
        def go_l():
            if messagebox.askyesno("歌单识别成功", f"识别到【{p_name}】歌单/专辑\nID: {lid}\n\n是否打开详情？"):
                webbrowser.open(f"lxmusic://songlist/open/{source}/{lid}")
            reset_ui()
        root.after(0, go_l); return

    root.after(0, lambda: [messagebox.showwarning("解析失败", f"无法提取有效 ID，请检查【{p_name}】链接格式是否受支持。"), reset_ui()])

# ================= 4. UI 界面逻辑 =================
def reset_ui():
    entry.delete(0, END)
    btn_run.config(state=NORMAL, text='解析并播放')

def start_process():
    content = entry.get().strip()
    if not content:
        try:
            content = root.clipboard_get().strip()
            entry.insert(0, content)
        except: return
    btn_run.config(state=DISABLED, text="识别中...")
    threading.Thread(target=worker_thread, args=(content,), daemon=True).start()

# --- 主程序窗口 ---
root = Tk()
root.title('LXMusicHelper v1.2.0 - 全平台稳定版')
root.attributes('-topmost', 1)
root.geometry('450x150')

sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
root.geometry('+%d+%d' % ((sw-450)/2, (sh-150)/2))

frame = Frame(root)
frame.pack(expand=True)

Label(frame, text='支持网易/腾讯/酷狗/酷我/咪咕，单曲及歌单快速转换', font=('Microsoft YaHei', 9), fg='#666').pack(pady=5)

entry = Entry(frame, width=50, font=('Consolas', 10), bd=2)
entry.pack(padx=20, pady=5)
entry.focus_set()
entry.bind('<Return>', lambda e: start_process())

btn_run = Button(frame, text='解析并播放', command=start_process, bg='#2196F3', fg='white', 
                relief=FLAT, width=18, font=('Microsoft YaHei', 9, 'bold'), cursor='hand2')
btn_run.pack(pady=10)

root.mainloop()