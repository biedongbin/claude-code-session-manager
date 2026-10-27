#!/usr/bin/env python3
"""Capture ccs TUI screenshots (zh/en) via pty + pyte replay -> HTML -> Chrome -> PIL.

Usage: shoot.py <main|slash|done|config> <zh|en> <output.png>
Deps: pyte, pillow (venv), Chrome. Env: CCS_HOME override for en (lang:en config).
Key fixes baked in:
- xterm REP (CSI Pn b) expansion (pyte ignores it; borders would collapse)
- wide chars (EAW F/W) pinned to inline-block width:2ch (CJK drift breaks the seam)
- letter-spacing 0 (any tracking breaks the 1ch/2ch ratio and re-introduces drift)
"""
import os, pty, sys, time, select, threading

home = None
CCS = "/Users/biedongbin/workspace/github/ccs/ccs"
COLS, ROWS = 150, 16
VT100 = {'j':'┘','k':'┐','l':'┌','m':'└','q':'─','t':'┤','u':'┴',
         'v':'└','w':'┘','x':'│','n':'┼','a':'▒','`':'◆','f':'°','g':'ﬁ','~':'·'}

HOME_MAP = {"zh": os.path.expanduser("~/.ccs"), "en": "/tmp/ccs-en-home"}

def capture(argv, keys):
    os.chdir("/Users/biedongbin/workspace/github/ccs")
    pid, fd = pty.fork()
    if pid == 0:
        env = {"TERM": "xterm-256color", "LANG": "en_US.UTF-8",
               "COLUMNS": str(COLS), "LINES": str(ROWS)}
        if home: env["CCS_HOME"] = home
        os.environ.update(env)
        os.execvp(argv[0], argv)
    buf = bytearray(); t0 = time.time()
    if keys:
        threading.Thread(target=_feed, args=(fd, keys, t0), daemon=True).start()
    end = t0 + 5.5
    while time.time() < end:
        r,_,_ = select.select([fd], [], [], 0.15)
        if r:
            try: chunk = os.read(fd, 65536)
            except OSError: break
            if not chunk: break
            buf.extend(chunk)
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done:
            try:
                while True:
                    r,_,_ = select.select([fd],[],[],0.1)
                    if not r: break
                    buf.extend(os.read(fd, 65536))
            except OSError: pass
            break
    try: os.close(fd)
    except OSError: pass
    return bytes(buf)

def _feed(fd, keys, t0):
    for at, data in keys:
        wait = at - (time.time() - t0)
        if wait > 0: time.sleep(wait)
        os.write(fd, data)

def acs_translate(data):
    out = bytearray(); i = 0; in_scs = False
    while i < len(data):
        b = data[i]
        if b == 0x1b and data[i+1:i+3] == b"(0":
            in_scs = True; out.extend(b"\x1b(B"); i += 3; continue
        if b == 0x1b and data[i+1:i+3] == b"(B":
            in_scs = False; out.extend(data[i:i+3]); i += 3; continue
        if in_scs and 0x60 <= b <= 0x7e:
            out.extend(VT100.get(chr(b), chr(b)).encode()); i += 1; continue
        out.append(b); i += 1
    return bytes(out)

def expand_rep(data):
    out = bytearray(); i = 0; last = b""
    while i < len(data):
        b = data[i]
        if b == 0x1b and data[i+1:i+2] == b"[":
            j = i + 2
            while j < len(data) and not (0x40 <= data[j] <= 0x7e):
                j += 1
            if j < len(data):
                if data[j:j+1] == b"b":
                    try: n = int(data[i+2:j] or b"1")
                    except ValueError: n = 1
                    if last: out.extend(last * n)
                    i = j + 1
                    continue
                out.extend(data[i:j+1]); i = j + 1; continue
        if 0x20 <= b < 0x7f or b >= 0x80:
            if b < 0x80:
                last = data[i:i+1]
            else:
                n = 2 if 0xc0 <= b < 0xe0 else 3 if 0xe0 <= b < 0xf0 else 4
                last = data[i:i+n]; out.extend(last); i += n; continue
        out.append(b); i += 1
    return bytes(out)

def replay(data):
    import pyte
    screen = pyte.Screen(COLS, ROWS)
    pyte.ByteStream(screen).feed(expand_rep(acs_translate(data)))
    return screen

FG = {"default": "#d4d4d4", "black": "#10141a", "red": "#ff6b6b",
      "green": "#34d399", "yellow": "#febc2e", "blue": "#6ea8fe",
      "magenta": "#d68cff", "cyan": "#5fd7d7", "white": "#e5e7eb"}

def _fmt(run):
    import unicodedata
    out = []
    for ch in run:
        e = ch.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        if unicodedata.east_asian_width(ch) in ("F","W"):
            out.append(f'<span style="display:inline-block;width:2ch;text-align:center">{e}</span>')
        else:
            out.append(e)
    return "".join(out)

def to_html(sc):
    BG = "#10141a"
    rows = []
    for y in range(sc.lines):
        spans, cur, run = [], None, []
        for x in range(sc.columns):
            c = sc.buffer[y][x]
            fg = FG.get(c.fg, "#d4d4d4") if not c.reverse else "#10141a"
            bg = BG if c.bg == "default" else (FG.get(c.fg, "#d4d4d4") if c.reverse else FG.get(c.bg, "#d4d4d4"))
            if c.reverse and c.fg == "default":
                bg = "#2a3342"
            key = (fg, bg, bool(c.bold))
            if cur != key:
                if run: spans.append((cur, "".join(run)))
                cur, run = key, []
            run.append(c.data)
        if run: spans.append((cur, "".join(run)))
        inner = "".join(
            f'<span style="color:{k[0]};background:{k[1]};{"" if not k[2] else "font-weight:700;"}">{_fmt(s)}</span>'
            for k, s in spans if s.strip(" ") or s == " ")
        rows.append(f"<div>{inner if inner else '&nbsp;'}</div>")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      * {{ margin:0; padding:0; }}
      body {{ background:{BG}; }}
      div {{ font: 15px/1.25 Menlo, "PingFang SC", monospace; white-space: pre;
            letter-spacing: 0; color:#d4d4d4; }}
    </style></head><body>{''.join(rows)}</body></html>"""

def ready(scene, sc):
    r0 = sc.display[0]
    if scene == "main":  return "0/0" not in r0
    if scene == "slash": return any("search" in sc.display[y] or "搜索" in sc.display[y] for y in range(10, sc.lines))
    if scene == "done":  return ("[q:" in r0) and ("1/1" in r0)
    return True

def shoot(scene, lang):
    global home
    home = HOME_MAP[lang]
    sc = None
    for _ in range(4):
        if scene == "main":   sc = replay(capture([CCS], None))
        elif scene == "slash": sc = replay(capture([CCS], [(2.4, b"/")]))
        elif scene == "done":  sc = replay(capture([CCS], [(2.4, b"/"), (2.8, "视频".encode())]))
        elif scene == "config": sc = replay(capture([CCS, "--config"], None))
        if ready(scene, sc): break
    out = sys.argv[3]
    html_path = out + ".html"
    open(html_path, "w").write(to_html(sc))
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    win_w = 1600 if scene == "config" else 1400
    os.system(f'"{chrome}" --headless --disable-gpu --force-device-scale-factor=2 '
              f'--window-size={win_w},700 --screenshot={out} "file://{html_path}" '
              f'--virtual-time-budget=3000 --hide-scrollbars 2>/dev/null')
    from PIL import Image
    im = Image.open(out).convert("RGB")
    px, w, h = im.load(), *im.size
    bg = px[0, 0]
    bottom = h
    while bottom > 0:
        if any(px[x, bottom-1] != bg for x in range(0, w, 40)): break
        bottom -= 2
    right = w
    while right > 0:
        if any(px[right-1, y] != bg for y in range(0, h, 20)): break
        right -= 2
    im.crop((0, 0, min(w, right + 24), min(h, bottom + 24))).save(out)
    os.remove(html_path)
    print(out)

if __name__ == "__main__":
    shoot(sys.argv[1], sys.argv[2])
