"""Augur desktop app: the main window (tier lists, match helper, settings) plus a small
always-on-top overlay that pops up the grades when hex cards appear in your game.

    python -m augur.desktop          (or double-click Augur.exe)
"""
import socket
import sys
import threading
import time
import traceback
import webbrowser

from . import config, gamedata, server

OVERLAY_W, OVERLAY_H, MARGIN = 360, 300, 16


def free_port(preferred):
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no free port")


def prepare(cfg, log=print):
    """Game data + website files ready to serve. Works offline on first run (game data ships with the app)."""
    from . import __main__ as cli
    g = gamedata.load(cfg)
    if not g:
        g = gamedata.update(cfg, log=log)
    cli.build(cfg, g)
    return g


def refresh_in_background(cfg, log=print):
    """After each patch: new hex list, icons and names. Runs once at start-up if the data is 3+ days old."""
    def work():
        try:
            path = cfg["data_path"] / "gamedata.json"
            if path.exists() and time.time() - path.stat().st_mtime < 3 * 86400:
                return
            from . import __main__ as cli, screen
            g = gamedata.update(cfg, log=log)
            if screen.available():
                screen.load_icons(cfg, g)
            cli.build(cfg, g)
        except Exception as e:
            log(f"Game data refresh skipped: {e}")
    threading.Thread(target=work, daemon=True).start()


def overlay_xy(cfg, screen_w, screen_h):
    pos = cfg.get("overlay_position", "top-right")
    x = MARGIN if "left" in pos else screen_w - OVERLAY_W - MARGIN
    y = MARGIN + 40 if "top" in pos else screen_h - OVERLAY_H - MARGIN - 40
    return int(x), int(y)


class OverlayApi:
    """Called from the overlay page: show it when cards appear, hide it afterwards."""

    def __init__(self):
        self.window = None
        self.visible = False

    def show(self):
        if self.window and not self.visible:
            self.visible = True
            self.window.show()

    def hide(self):
        if self.window and self.visible:
            self.visible = False
            self.window.hide()


def main():
    cfg = config.load()
    cfg["_desktop"] = True
    g = prepare(cfg)
    port = free_port(cfg["server_port"])
    httpd = server.ThreadingHTTPServer(("127.0.0.1", port), server.make_handler(cfg, g))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    refresh_in_background(cfg)
    summary = config.ROOT / "data" / "opgg" / "summary.json"
    if cfg.get("use_opgg", True) and (not summary.exists() or time.time() - summary.stat().st_mtime > 86400):
        cfg["_start_job"]("opgg_all")  # OP.GG data for all champions, refreshed daily
    base = f"http://127.0.0.1:{port}/"

    try:
        import webview
    except Exception:
        # No desktop window library: use the browser instead (everything still works).
        print(f"Augur is running at {base}#/grade  (close this window to stop)")
        webbrowser.open(base + "#/grade")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    main_win = webview.create_window("Augur", base + "#/grade", width=1200, height=820, min_size=(420, 500))
    api = OverlayApi()
    overlay = None

    def make_overlay():
        nonlocal overlay
        try:
            scr = webview.screens[0]
            sw, sh = scr.width, scr.height
        except Exception:
            sw, sh = 1920, 1080
        x, y = overlay_xy(cfg, sw, sh)
        overlay = webview.create_window("Augur overlay", base + "#/overlay", js_api=api, width=OVERLAY_W, height=OVERLAY_H,
                                        x=x, y=y, on_top=True, frameless=True, easy_drag=True, focus=False,
                                        hidden=True, background_color="#10141A")
        api.window = overlay

    def on_settings(saved):
        # Overlay switched on/off or moved in Settings.
        if not saved.get("overlay", True):
            api.hide()
        elif overlay is not None:
            try:
                scr = webview.screens[0]
                overlay.move(*overlay_xy(cfg, scr.width, scr.height))
            except Exception:
                pass
    cfg["_on_settings"] = on_settings

    if cfg.get("overlay", True):
        make_overlay()

    def quit_all():
        for w in list(webview.windows):
            if w is not main_win:
                try:
                    w.destroy()
                except Exception:
                    pass
        httpd.shutdown()
    main_win.events.closed += quit_all
    webview.start(debug="--debug" in sys.argv)


def selftest():
    """Draw 3 hex cards, read them back, check the app's parts load. Writes selftest.txt; exit code 0 = pass."""
    import json
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageFont
    from . import screen
    lines, ok = [], True
    cfg = config.load()
    g = gamedata.load(cfg)
    want = ["Nightstalking", "Dawnbringer's Resolve", "Apex Inventor"]  # all gold, like a real selection
    try:
        W, H = 1920, 1080
        img = Image.new("RGB", (W, H), (8, 14, 18))
        d = ImageDraw.Draw(img)
        font = None
        for f in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                  "/Library/Fonts/Arial Unicode.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            if Path(f).exists():
                font = ImageFont.truetype(f, 34)
                break
        by_name = {a["name"]: a for a in g["augments"].values()}
        for k, name in zip((-1, 0, 1), want):
            cx = W / 2 + k * screen.CARD_DX * H
            d.rectangle((cx - 0.22 * H, 0.11 * H, cx + 0.22 * H, 0.75 * H), outline=(250, 242, 220), width=14)
            icon = Image.open(cfg["data_path"] / "icons" / f"{by_name[name]['id']}.png").convert("RGBA")
            size = int(0.19 * H)
            icon = icon.resize((size, size))
            img.paste(icon, (int(cx - size / 2), int(screen.ICON_Y * H - size / 2)), icon)
            d.text((cx, 0.46 * H), name, font=font, fill=(240, 232, 214), anchor="mm")
        res = screen.read_cards(img, cfg, g)
        got = [c["name"] for c in res["cards"]]
        lines.append(f"cards: {got}")
        ok = ok and got == want
        res2 = screen.read_cards(Image.new("RGB", (W, H), (30, 60, 40)), cfg, g)  # a screen with no cards
        lines.append(f"no-card screen: {'ok' if not res2['on_screen'] else 'WRONG'}")
        ok = ok and not res2["on_screen"]
    except Exception as e:
        ok = False
        lines.append(f"card reading failed: {e!r}")
    try:
        import webview  # noqa: F401
        lines.append("window library: ok")
    except Exception as e:
        ok = False
        lines.append(f"window library failed: {e!r}")
    lines.append("PASS" if ok else "FAIL")
    (config.ROOT / "selftest.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    sys.exit(0 if ok else 1)


def run():
    if "--selftest" in sys.argv:
        return selftest()
    try:
        main()
    except Exception:
        # Packaged apps have no console: leave a log next to the user's data.
        (config.ROOT / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    run()
