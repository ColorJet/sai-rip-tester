#!/usr/bin/env python3
"""
SAI RIP/CMS Tester  --  no-CLI quick-test front-end for the test team.

Two tabs:
  * "RIP / CMS Engine"  (Test Engineer 2): runs sai_process_image.exe with every
    CLI switch exposed as a control. Drives + verifies RIP/CMS quality & integrity.
  * "GUI (SAI Studio)"  (Test Engineer 1): launches the SAI Studio V3 app for
    GUI-feature testing.

Zero build, zero dependencies beyond the Python standard library (tkinter).
Run:  python rip_tester.py        (or double-click RIP_Tester.bat)

Verified engine invocation (2026-06-30):
  sai_process_image.exe --input <img> --xml <profile.xml> --w-mm 100 --output <out.prt>
  (run with cwd = the profile's folder so relative ICC/LUT filenames resolve)
"""
import os
import sys
import json
import time
import queue
import tempfile
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---- install-relative path resolution (portable across machines) ------------
# Installed layout:  <install>/{bin, profiles, testdata, tester, SAI_Studio}
# This file lives in tester/ (or is frozen as tester\rip_tester.exe), so the
# install root is the PARENT of our folder. We resolve everything relative to it
# and only fall back to the original dev D:\ paths when running from the source tree.
import glob

def _install_base():
    here = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)          # parent of tester/

_BASE = _install_base()

def _pick(*cands):
    for c in cands:
        if c and os.path.exists(c):
            return c
    return cands[0]

# Installed layout puts the engine in <install>/bin. In a dev tree the freshly built
# one may be under bin/Release; check that before a bare bin/ so a fresh build wins
# over a stale copy.
# Install-relative first (how a real install is laid out); the dev tree happens to
# match that layout, so it resolves there too. SAI_* env vars let a developer point
# at a build elsewhere without editing this file -- no machine-specific paths are
# baked into the source. (A Release/ subdir is checked before a bare bin/ so a fresh
# build wins over a stale one.)
DEFAULT_ENGINE = _pick(os.path.join(_BASE, "bin", "Release", "sai_process_image.exe"),
                       os.path.join(_BASE, "bin", "sai_process_image.exe"),
                       os.environ.get("SAI_ENGINE", ""))
DEFAULT_STUDIO = _pick(os.path.join(_BASE, "SAI_Studio", "SAI_Studio.exe"),
                       os.environ.get("SAI_STUDIO", ""))
DEFAULT_PROFILE_DIR = _pick(os.path.join(_BASE, "profiles"),
                            os.environ.get("SAI_PROFILE_DIR", ""))
DEFAULT_INPUT = _pick(os.path.join(_BASE, "testdata", "test_image.jpg"),
                      os.environ.get("SAI_INPUT", ""))

def _first_profile_xml():
    hits = glob.glob(os.path.join(DEFAULT_PROFILE_DIR, "**", "*.xml"), recursive=True)
    return hits[0] if hits else ""

DEFAULT_PROFILE = _first_profile_xml()

# ---- persistent settings (last-used paths/values survive restarts) ----------
SETTINGS_PATH = os.path.join(os.environ.get("APPDATA", _BASE), "SAI_Tester", "settings.json")

def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_settings(d: dict):
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass

# ---- self-update ------------------------------------------------------------
# Bumped at each release (matches the installer's AppVersion). Compared against
# `version` in the update manifest.
APP_VERSION = "1.3.1"

# No update host is baked into this source -- it ships in updateconfig.json beside the
# install (or the SAI_UPDATE_URL env var), so this script carries no infrastructure and
# can be published openly. With neither set, self-update is simply disabled.
DEFAULT_UPDATE_URL = ""

def _read_config():
    cfg = os.path.join(_BASE, "updateconfig.json")
    if os.path.exists(cfg):
        try:
            with open(cfg) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _update_url():
    return (os.environ.get("SAI_UPDATE_URL")
            or _read_config().get("update_url")
            or DEFAULT_UPDATE_URL)

def _ver_tuple(v):
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)

def fetch_latest():
    """Return the parsed latest.json  {version, url, notes, sha256}."""
    import json, urllib.request
    with urllib.request.urlopen(_update_url(), timeout=8) as r:
        return json.loads(r.read().decode())

def _resolve_installer_url(latest):
    """Prefer a bare `file` field over a full `url`, so latest.json can carry no
    host at all -- the update base is already known here (DEFAULT_UPDATE_URL). A
    domain-free latest.json means the JSON itself discloses no infrastructure."""
    if latest.get("file"):
        base = _update_url().rsplit("/", 1)[0]      # strip "latest.json"
        return base + "/" + latest["file"].lstrip("/")
    return latest.get("url", "")


def download_installer(url, sha256_hex, progress_cb=None):
    """Download the installer to temp, verify checksum, return its path."""
    import urllib.request, hashlib, tempfile
    dst = os.path.join(tempfile.gettempdir(), "SAI-Update-Setup.exe")
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length", 0)); done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk); h.update(chunk); done += len(chunk)
            if progress_cb and total:
                progress_cb(min(100, done * 100 // total))
    if sha256_hex and h.hexdigest().lower() != sha256_hex.lower():
        raise RuntimeError("checksum mismatch — download rejected")
    return dst

# ---- telemetry (customer-ready, opt-out) ------------------------------------
# Same as the update URL: not baked into the source. From SAI_TELEMETRY_URL or
# updateconfig.json's "telemetry_url"; empty disables telemetry entirely.
TELEMETRY_URL = os.environ.get("SAI_TELEMETRY_URL", "") or _read_config().get("telemetry_url", "")

def _telemetry_opted_out():
    if os.environ.get("SAI_TELEMETRY", "").lower() in ("0", "no", "off", "false"):
        return True
    for d in (_BASE, os.path.dirname(DEFAULT_ENGINE)):
        if d and os.path.exists(os.path.join(d, "telemetry.off")):
            return True
    return False

def _machine_id():
    for cand in (os.path.join(_BASE, "tester", "sai_machineid.exe"),
                 os.path.join(_BASE, "bin", "sai_machineid.exe"),
                 os.path.join(os.path.dirname(DEFAULT_ENGINE), "sai_machineid.exe")):
        try:
            if os.path.exists(cand):
                out = subprocess.run([cand], capture_output=True, text=True, timeout=3).stdout.strip()
                if len(out) >= 8:
                    return out
        except Exception:
            pass
    return "unknown"

def send_telemetry(event, reason="", sync=False):
    """Fire-and-forget diagnostic/heartbeat. Honors opt-out; only coarse fields.
    sync=True runs inline (used by the scheduled --heartbeat task)."""
    if not TELEMETRY_URL or _telemetry_opted_out():
        return
    import json, time, urllib.request
    body = json.dumps({"machine_id": _machine_id(), "app": "sai_tester", "event": event,
                       "reason": reason, "app_version": APP_VERSION,
                       "ts": int(time.time())}).encode()
    def work():
        try:
            req = urllib.request.Request(TELEMETRY_URL, data=body,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=6)
        except Exception:
            pass
    if sync:
        work()
    else:
        threading.Thread(target=work, daemon=True).start()

WIDTH_UNITS = {"mm": "--w-mm", "cm": "--w-cm", "inch": "--w-inc", "meter": "--w-mt"}
DPI_FLAGS = {
    "From XML (default)": None,
    "720 x 1440 (4-pass)": "--dpi720x1440",
    "720 x 1080 (3-pass)": "--dpi720x1080",
    "720 x 720 (2-pass)":  "--dpi720x720",
    "540 x 1440 (4-pass)": "--dpi540x1440",
    "540 x 1080 (3-pass)": "--dpi540x1080",
    "540 x 720 (2-pass)":  "--dpi540x720",
}


def first_existing(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return paths[0] if paths else ""


# ---- GPU / driver report ------------------------------------------------------
# The engine ships its own CUDA runtime (bin\cudart64_<N>.dll) but the DRIVER comes
# from the PC. A driver older than that runtime fails on the very first CUDA call,
# which the engine reports as a GPU allocation error -- the single most common
# field report so far (2026-11: driver 560 / CUDA 12.6 against a CUDA 13 engine).
# Say so at startup, before anyone blames the licence or the profile.

def engine_cuda_major(engine_exe):
    """Major CUDA version of the runtime shipped beside the engine (0 = unknown)."""
    import glob, re
    d = os.path.dirname(engine_exe or "")
    for p in glob.glob(os.path.join(d, "cudart64_*.dll")) if d else []:
        m = re.search(r"cudart64_(\d+)", os.path.basename(p))
        if m:
            return int(m.group(1))
    return 0


def gpu_report(engine_exe):
    """Run nvidia-smi; return (log_lines, warning_or_None)."""
    import re
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    need = engine_cuda_major(engine_exe)
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used",
                            "--format=csv,noheader"], capture_output=True, text=True,
                           timeout=15, creationflags=flags).stdout
        head = subprocess.run(["nvidia-smi"], capture_output=True, text=True,
                              timeout=15, creationflags=flags).stdout
    except Exception as e:
        warn = ("nvidia-smi is not available (%s).\n\nNo NVIDIA driver was found. The RIP engine needs an "
                "NVIDIA GPU with a current driver (CUDA %s or newer)." % (e.__class__.__name__, need or "13"))
        return ["[gpu] nvidia-smi not found - no NVIDIA driver? The engine cannot run without one.\n"], warn
    lines = []
    for l in q.splitlines():
        if l.strip():
            lines.append("[gpu] %s\n" % l.strip())
    m = re.search(r"CUDA Version:\s*([0-9]+(?:\.[0-9]+)?)", head)
    have = m.group(1) if m else "unknown"
    lines.append("[gpu] driver supports CUDA %s; engine runtime is CUDA %s\n" % (have, need or "unknown"))
    warn = None
    try:
        if need and m and int(float(have)) < need:
            warn = ("The NVIDIA driver on this PC supports CUDA %s, but the RIP engine was built for "
                    "CUDA %d.\n\nEvery RIP will fail with a GPU allocation / 'CUDA driver version is "
                    "insufficient' error until the driver is updated.\n\nInstall the latest NVIDIA driver "
                    "(580 series or newer), reboot, and relaunch this tester." % (have, need))
            lines.append("[gpu] WARNING: driver too old for the engine runtime - update the NVIDIA driver "
                         "to 580+ before testing. RIPs will fail until then.\n")
    except ValueError:
        pass
    return lines, warn


class Tester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SAI RIP / CMS Tester")
        self.geometry("960x760")
        self.minsize(820, 640)
        self.proc = None
        self.log_q = queue.Queue()
        self.cfg = load_settings()
        self._out_autofilled = ""

        # engine/studio paths live on the Settings tab; vars created up-front
        # because the other tabs reference them.
        self.v_engine = tk.StringVar(value=self.cfg.get("engine_path") or first_existing(DEFAULT_ENGINE))
        self.v_studio = tk.StringVar(value=self.cfg.get("studio_path") or first_existing(DEFAULT_STUDIO))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.engine_tab = ttk.Frame(nb)
        self.gui_tab = ttk.Frame(nb)
        self.settings_tab = ttk.Frame(nb)
        nb.add(self.engine_tab, text="  RIP / CMS Engine  (Test Eng 2)  ")
        nb.add(self.gui_tab, text="  GUI - SAI Studio  (Test Eng 1)  ")
        nb.add(self.settings_tab, text="  Settings  ")

        self._build_engine_tab(self.engine_tab)
        self._build_gui_tab(self.gui_tab)
        self._build_settings_tab(self.settings_tab)
        self._build_menu()
        self._restore_values()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._drain_log)
        self.after(300, self._gpu_report)                              # driver vs engine CUDA check
        self.after(1500, lambda: self._check_updates(silent=True))   # quiet check on launch
        self.after(2200, lambda: send_telemetry("heartbeat"))        # support heartbeat (opt-out honored)

    def _gpu_report(self):
        """Log GPU, driver and CUDA versions; warn once if the driver predates the engine."""
        def work():
            lines, warn = gpu_report(self.v_engine.get().strip())
            self.log_q.put("[tester] v%s\n" % APP_VERSION)
            for l in lines:
                self.log_q.put(l)
            if warn:
                self.after(0, lambda: messagebox.showwarning("NVIDIA driver too old", warn))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ helpers
    def _row(self, parent, r, label):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=6, pady=3)

    def _browse_into(self, var, kind="open", types=None, initial=None, mem=None):
        # mem = key under which the last-used folder is remembered across runs
        if mem:
            saved = self.cfg.get("dirs", {}).get(mem)
            if saved and os.path.isdir(saved):
                initial = saved
        if kind == "open":
            p = filedialog.askopenfilename(filetypes=types or [("All", "*.*")],
                                           initialdir=initial or os.getcwd())
        elif kind == "save":
            p = filedialog.asksaveasfilename(defaultextension=".prt",
                                             filetypes=[("PRT", "*.prt"), ("All", "*.*")],
                                             initialdir=initial or os.getcwd())
        else:
            p = filedialog.askdirectory(initialdir=initial or os.getcwd())
        if p:
            var.set(os.path.normpath(p))
            if mem:
                self.cfg.setdefault("dirs", {})[mem] = os.path.dirname(os.path.normpath(p))
                save_settings(self.cfg)

    def _browse_profile(self):
        self._browse_into(self.v_profile, "open",
                          [("Profiles", "*.xml *.icc *.icm"), ("All", "*.*")],
                          DEFAULT_PROFILE_DIR, mem="profile")
        # auto-switch the XML/ICC radio to match the picked file type
        p = self.v_profile.get().lower()
        if p.endswith((".icc", ".icm")):
            self.v_profmode.set("icc")
        elif p.endswith(".xml"):
            self.v_profmode.set("xml")

    # ------------------------------------------------------- settings persistence
    _SAVED_FIELDS = ("v_input", "v_profile", "v_profmode", "v_width", "v_length",
                     "v_unit", "v_dpi", "v_channels", "v_output", "v_ip", "v_port",
                     "v_contrast", "v_saturation", "v_upscale", "v_inprof", "v_inprof_file",
                     "v_dither", "v_dstrength", "v_dtaper", "v_dthreshold")

    def _restore_values(self):
        vals = self.cfg.get("values", {})
        for name in self._SAVED_FIELDS:
            v = vals.get(name)
            if v:
                getattr(self, name).set(v)

    def _on_close(self):
        self.cfg["engine_path"] = self.v_engine.get().strip()
        self.cfg["studio_path"] = self.v_studio.get().strip()
        self.cfg["values"] = {n: getattr(self, n).get() for n in self._SAVED_FIELDS}
        save_settings(self.cfg)
        self.destroy()

    # --------------------------------------------------------------- engine tab
    def _build_engine_tab(self, t):
        for c in range(4):
            t.columnconfigure(c, weight=(1 if c == 1 else 0))
        r = 0
        # input image (engine exe moved to the Settings tab)
        self.v_input = tk.StringVar(value=DEFAULT_INPUT)
        self._row(t, r, "Input image *")
        ttk.Entry(t, textvariable=self.v_input).grid(row=r, column=1, columnspan=2, sticky="ew", padx=4)
        ttk.Button(t, text="Browse",
                   command=lambda: self._browse_into(self.v_input, "open",
                                                     [("Images", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.pdf"),
                                                      ("All", "*.*")], mem="input")
                   ).grid(row=r, column=3, padx=4)
        r += 1
        # profile mode
        self.v_profmode = tk.StringVar(value="xml")
        self._row(t, r, "Profile via *")
        pf = ttk.Frame(t); pf.grid(row=r, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(pf, text="XML (extracts ICC+LUT)", variable=self.v_profmode, value="xml").pack(side="left")
        ttk.Radiobutton(pf, text="ICC (bypass XML)", variable=self.v_profmode, value="icc").pack(side="left", padx=10)
        r += 1
        # profile path (shared field; meaning follows the radio)
        self.v_profile = tk.StringVar(value=DEFAULT_PROFILE)
        self._row(t, r, "Profile file *")
        ttk.Entry(t, textvariable=self.v_profile).grid(row=r, column=1, columnspan=2, sticky="ew", padx=4)
        ttk.Button(t, text="Browse",
                   command=self._browse_profile).grid(row=r, column=3, padx=4)
        r += 1
        # width + unit + optional length override
        self._row(t, r, "Print width *")
        wf = ttk.Frame(t); wf.grid(row=r, column=1, columnspan=2, sticky="w")
        self.v_width = tk.StringVar(value="100")
        ttk.Entry(wf, textvariable=self.v_width, width=10).pack(side="left")
        self.v_unit = tk.StringVar(value="mm")
        ttk.Combobox(wf, textvariable=self.v_unit, values=list(WIDTH_UNITS), width=7,
                     state="readonly").pack(side="left", padx=6)
        ttk.Label(wf, text="Length").pack(side="left", padx=(14, 2))
        self.v_length = tk.StringVar()
        ttk.Entry(wf, textvariable=self.v_length, width=10).pack(side="left")
        ttk.Label(wf, text="(same unit; blank = proportional, value stretches design)",
                  foreground="#666").pack(side="left", padx=6)
        r += 1
        # dpi + channels
        self._row(t, r, "DPI / Channels")
        df = ttk.Frame(t); df.grid(row=r, column=1, columnspan=2, sticky="w")
        self.v_dpi = tk.StringVar(value="From XML (default)")
        ttk.Combobox(df, textvariable=self.v_dpi, values=list(DPI_FLAGS), width=22,
                     state="readonly").pack(side="left")
        self.v_upscale = tk.StringVar(value="lanczos (default, sharpest)")
        self.v_inprof = tk.StringVar(value="Auto (from profile)")
        self.v_inprof_file = tk.StringVar()
        self.v_channels = tk.StringVar(value="8 (AICN)")
        ttk.Combobox(df, textvariable=self.v_channels,
                     values=["8 (AICN)", "6 (AICY)", "4 (CMYK profile)"], width=18,
                     state="readonly").pack(side="left", padx=8)
        ttk.Label(df, text="Input space").pack(side="left", padx=(10, 2))
        ip = ttk.Combobox(df, textvariable=self.v_inprof, width=20, state="readonly",
                          values=["Auto (from profile)", "sRGB", "Adobe RGB (1998)",
                                  "Browse for .icc..."])
        ip.pack(side="left")
        ip.bind("<<ComboboxSelected>>", self._on_input_space)
        ttk.Label(df, text="Upscale").pack(side="left", padx=(10, 2))
        ttk.Combobox(df, textvariable=self.v_upscale, width=22, state="readonly",
                     values=["lanczos (default, sharpest)", "bicubic", "bilinear (old default)",
                             "lab", "nearest"]).pack(side="left")
        r += 1
        # optional overrides (collapsible-ish group)
        adv = ttk.LabelFrame(t, text="Optional overrides")
        adv.grid(row=r, column=0, columnspan=4, sticky="ew", padx=6, pady=6)
        for c in range(4):
            adv.columnconfigure(c, weight=(1 if c == 1 else 0))
        self.v_cs = tk.StringVar()
        self.v_pllut = tk.StringVar(); self.v_plsize = tk.StringVar(value="256")
        self.v_lut = tk.StringVar(); self.v_lutdim = tk.StringVar(value="33"); self.v_luthdr = tk.StringVar(value="22")
        ttk.Label(adv, text="Channel swap --cs").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(adv, textvariable=self.v_cs).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(adv, text='(e.g. "56742103")').grid(row=0, column=2, columnspan=2, sticky="w")
        ttk.Label(adv, text="PL-LUT file").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(adv, textvariable=self.v_pllut).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(adv, text="Browse",
                   command=lambda: self._browse_into(self.v_pllut, "open", [("LUT", "*.lut"), ("All", "*.*")],
                                                     DEFAULT_PROFILE_DIR, mem="lut")).grid(row=1, column=2, padx=2)
        ttk.Label(adv, text="pl-size").grid(row=1, column=3, sticky="w")
        ttk.Entry(adv, textvariable=self.v_plsize, width=8).grid(row=1, column=3, sticky="e", padx=4)
        ttk.Label(adv, text="3D LUT file").grid(row=2, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(adv, textvariable=self.v_lut).grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Button(adv, text="Browse",
                   command=lambda: self._browse_into(self.v_lut, "open", [("LUT", "*.lut"), ("All", "*.*")],
                                                     DEFAULT_PROFILE_DIR, mem="lut")).grid(row=2, column=2, padx=2)
        df2 = ttk.Frame(adv); df2.grid(row=2, column=3, sticky="e")
        ttk.Label(df2, text="dim").pack(side="left"); ttk.Entry(df2, textvariable=self.v_lutdim, width=5).pack(side="left", padx=2)
        ttk.Label(df2, text="hdr").pack(side="left"); ttk.Entry(df2, textvariable=self.v_luthdr, width=5).pack(side="left", padx=2)
        r += 1
        # input preprocessing — applied to the pixels before the engine sees them.
        # One set of values for every source format so a tif and a png of the same
        # artwork rip through an identical adjustment (see _build_cmd).
        pp = ttk.LabelFrame(t, text="Input preprocessing (same settings for every format)")
        pp.grid(row=r, column=0, columnspan=4, sticky="ew", padx=6, pady=(0, 6))
        self.v_contrast = tk.StringVar(value="1.00")
        self.v_saturation = tk.StringVar(value="1.00")
        ttk.Label(pp, text="Contrast").pack(side="left", padx=(6, 2))
        ttk.Entry(pp, textvariable=self.v_contrast, width=7).pack(side="left")
        ttk.Label(pp, text="Saturation").pack(side="left", padx=(14, 2))
        ttk.Entry(pp, textvariable=self.v_saturation, width=7).pack(side="left")
        ttk.Button(pp, text="Reset",
                   command=lambda: (self.v_contrast.set("1.00"), self.v_saturation.set("1.00"))
                   ).pack(side="left", padx=10)
        ttk.Label(pp, text="1.00 = unchanged, range 0–4. Applies to jpg/png as well as converted tif.",
                  foreground="#666").pack(side="left", padx=6)
        r += 1
        # Halftone. Each control here has a measured number behind it (see
        # docs/BUILD_INVENTORY.md); the point of exposing them is that the press,
        # not the numbers, settles which setting ships.
        hf = ttk.LabelFrame(t, text="Halftone")
        hf.grid(row=r, column=0, columnspan=4, sticky="ew", padx=6, pady=(0, 6))
        self.v_dither = tk.StringVar(value="blue (dispersed, default)")
        self.v_dstrength = tk.StringVar(value="85")
        self.v_dtaper = tk.StringVar(value="8")
        self.v_dadaptive = tk.BooleanVar()
        self.v_dthreshold = tk.StringVar(value="12")
        self.v_dropsizes = tk.BooleanVar()

        h1 = ttk.Frame(hf); h1.pack(fill="x", padx=4, pady=2)
        ttk.Label(h1, text="Mask").pack(side="left", padx=(2, 2))
        ttk.Combobox(h1, textvariable=self.v_dither, width=26, state="readonly",
                     values=["blue (dispersed, default)",
                             "green (clustered, better on fabric)"]).pack(side="left")
        ttk.Label(h1, text="Strength").pack(side="left", padx=(14, 2))
        ttk.Entry(h1, textvariable=self.v_dstrength, width=6).pack(side="left")
        ttk.Label(h1, text="Taper").pack(side="left", padx=(10, 2))
        ttk.Entry(h1, textvariable=self.v_dtaper, width=6).pack(side="left")
        ttk.Label(h1, text="(85 = one full level step; 32 was the old value and bands)",
                  foreground="#666").pack(side="left", padx=8)

        h2 = ttk.Frame(hf); h2.pack(fill="x", padx=4, pady=2)
        ttk.Checkbutton(h2, text="--drop-sizes (use the profile's real level coverages)",
                        variable=self.v_dropsizes).pack(side="left")
        # The profile states nominal volumes (7/17/27). A real head may deliver
        # 6-8 / 16-18 / 25-30, and the largest matters most because coverage is a ratio
        # to it. Blank = use the profile's numbers.
        ttk.Label(h2, text="volumes pl:").pack(side="left", padx=(10, 2))
        self.v_dropvols = tk.StringVar()
        ttk.Entry(h2, textvariable=self.v_dropvols, width=10).pack(side="left")
        ttk.Checkbutton(h2, text="--dither-adaptive", variable=self.v_dadaptive).pack(side="left", padx=(16, 2))
        ttk.Label(h2, text="detail threshold").pack(side="left", padx=(6, 2))
        ttk.Entry(h2, textvariable=self.v_dthreshold, width=5).pack(side="left")
        r += 1

        # Edge-aware upscale. Protects vibrancy where unrelated colours meet; leaves
        # smooth gradients inside a motif untouched.
        ef = ttk.LabelFrame(t, text="Edge-aware upscale (keeps vibrant colours from blending to mud)")
        ef.grid(row=r, column=0, columnspan=4, sticky="ew", padx=6, pady=(0, 6))
        self.v_edge = tk.BooleanVar()
        self.v_edge_thr = tk.StringVar(value="24")
        self.v_edge_soft = tk.StringVar(value="24")
        self.v_edge_rad = tk.StringVar(value="6")
        ttk.Checkbutton(ef, text="enable", variable=self.v_edge).pack(side="left", padx=(6, 8))
        for lbl, var in (("threshold", self.v_edge_thr), ("softness", self.v_edge_soft),
                         ("radius", self.v_edge_rad)):
            ttk.Label(ef, text=lbl).pack(side="left", padx=(8, 2))
            ttk.Entry(ef, textvariable=var, width=6).pack(side="left")
        ttk.Label(ef, text="partial: recovers ~1/3 of the boundary ink dip",
                  foreground="#666").pack(side="left", padx=10)
        r += 1
        # flags
        self.v_debug = tk.BooleanVar(); self.v_preview = tk.BooleanVar(); self.v_cmyk = tk.BooleanVar()
        ff = ttk.Frame(t); ff.grid(row=r, column=0, columnspan=4, sticky="w", padx=6)
        ttk.Checkbutton(ff, text="--debug-save (intermediate stages)", variable=self.v_debug).pack(side="left")
        ttk.Checkbutton(ff, text="--preview (soft proof)", variable=self.v_preview).pack(side="left", padx=10)
        ttk.Checkbutton(ff, text="--cmyk-test (4ch math, ignores profile)", variable=self.v_cmyk).pack(side="left")
        self.v_inkctl = tk.BooleanVar(); self.v_rasterok = tk.BooleanVar()
        self.v_inklimit = tk.BooleanVar()
        ff2 = ttk.Frame(t); ff2.grid(row=r + 1, column=0, columnspan=4, sticky="w", padx=6)
        ttk.Checkbutton(ff2, text="--ink-control (apply the profile's density curve)",
                        variable=self.v_inkctl).pack(side="left")
        # The profile states a total ink limit; without this it is only printed. On a
        # correctly built device link it should barely fire -- the log says how often.
        ttk.Checkbutton(ff2, text="--enforce-ink-limit (clamp to the profile's TAC)",
                        variable=self.v_inklimit).pack(side="left", padx=10)
        # Blank = use the profile's own limit. A number overrides it and implies
        # enforcement -- handy for trialling a tighter limit for cost or bleeding.
        ttk.Label(ff2, text="override %:").pack(side="left", padx=(12, 2))
        self.v_inklimit_pct = tk.StringVar()
        ttk.Entry(ff2, textvariable=self.v_inklimit_pct, width=6).pack(side="left")

        ff3 = ttk.Frame(t); ff3.grid(row=r + 2, column=0, columnspan=4, sticky="w", padx=6)
        # Post-linearisation runs by default because the profile was built assuming it
        # does; this is the escape hatch for comparing against the old behaviour.
        self.v_nopl = tk.BooleanVar()
        ttk.Checkbutton(ff3, text="--no-pl-lut (skip the profile's post-linearisation)",
                        variable=self.v_nopl).pack(side="left")
        ttk.Checkbutton(ff3, text="--allow-raster-mismatch (force a 1-bit profile - output WILL be wrong)",
                        variable=self.v_rasterok).pack(side="left", padx=10)
        r += 1
        # output / printer
        self._row(t, r, "Output PRT")
        of = ttk.Frame(t); of.grid(row=r, column=1, columnspan=2, sticky="ew")
        of.columnconfigure(0, weight=1)
        self.v_output = tk.StringVar()
        ttk.Entry(of, textvariable=self.v_output).grid(row=0, column=0, sticky="ew", padx=4)
        ttk.Button(of, text="Save as",
                   command=lambda: self._browse_into(self.v_output, "save", mem="output")).grid(row=0, column=1, padx=2)
        ttk.Button(of, text="Clear", command=self._clear_output).grid(row=0, column=2, padx=2)
        ttk.Label(of, text="(blank = auto: <name>_<ext>.prt beside the input, timestamped if it already exists)",
                  foreground="#666").grid(row=1, column=0, columnspan=3, sticky="w", padx=4)
        r += 1
        self._row(t, r, "Send to printer")
        sf = ttk.Frame(t); sf.grid(row=r, column=1, columnspan=2, sticky="w")
        self.v_send = tk.BooleanVar()
        ttk.Checkbutton(sf, text="enable (no file output)", variable=self.v_send).pack(side="left")
        self.v_ip = tk.StringVar(); self.v_port = tk.StringVar(value="9100")
        ttk.Label(sf, text="IP").pack(side="left", padx=(10, 2)); ttk.Entry(sf, textvariable=self.v_ip, width=16).pack(side="left")
        ttk.Label(sf, text="port").pack(side="left", padx=(8, 2)); ttk.Entry(sf, textvariable=self.v_port, width=7).pack(side="left")
        r += 1
        # action buttons
        bf = ttk.Frame(t); bf.grid(row=r, column=0, columnspan=4, sticky="ew", padx=6, pady=6)
        ttk.Button(bf, text="Preview command", command=self._preview_cmd).pack(side="left")
        self.run_btn = ttk.Button(bf, text="▶  Run", command=self._run_engine)
        self.run_btn.pack(side="left", padx=6)
        ttk.Button(bf, text="Stop", command=self._stop).pack(side="left")
        ttk.Button(bf, text="Open output folder", command=self._open_out).pack(side="left", padx=6)
        ttk.Button(bf, text="Clear log", command=lambda: self.log.delete("1.0", "end")).pack(side="right")
        r += 1
        # log
        t.rowconfigure(r, weight=1)
        self.log = tk.Text(t, height=12, bg="#0d1117", fg="#c9d1d9", insertbackground="#c9d1d9",
                           font=("Consolas", 9), wrap="word")
        self.log.grid(row=r, column=0, columnspan=4, sticky="nsew", padx=6, pady=(0, 6))
        sb = ttk.Scrollbar(t, command=self.log.yview); sb.grid(row=r, column=4, sticky="ns")
        self.log["yscrollcommand"] = sb.set

    # ------------------------------------------------------------------ gui tab
    def _build_gui_tab(self, t):
        t.columnconfigure(1, weight=1)
        ttk.Label(t, text="Launch the SAI Studio V3 desktop app for GUI-feature testing.",
                  font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=12)
        ttk.Button(t, text="▶  Launch SAI Studio", command=self._launch_studio
                   ).grid(row=1, column=0, columnspan=3, pady=18)
        ttk.Label(t, foreground="#666",
                  text="Eng 1 checks GUI features here; Eng 2 uses the other tab for RIP/CMS quality.\n"
                       "The SAI Studio exe location is set on the Settings tab."
                  ).grid(row=2, column=0, columnspan=3, padx=10)

    # -------------------------------------------------------------- settings tab
    def _build_settings_tab(self, t):
        t.columnconfigure(1, weight=1)
        ttk.Label(t, text="Paths (normally auto-detected — change only if testing a different build).",
                  font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=12)
        ttk.Label(t, text="Engine exe").grid(row=1, column=0, sticky="w", padx=10)
        ttk.Entry(t, textvariable=self.v_engine).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(t, text="Browse",
                   command=lambda: self._browse_into(self.v_engine, "open", [("exe", "*.exe")], mem="engine")
                   ).grid(row=1, column=2, padx=6)
        ttk.Label(t, text="SAI Studio exe").grid(row=2, column=0, sticky="w", padx=10)
        ttk.Entry(t, textvariable=self.v_studio).grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Button(t, text="Browse",
                   command=lambda: self._browse_into(self.v_studio, "open", [("exe", "*.exe")], mem="studio")
                   ).grid(row=2, column=2, padx=6)
        ttk.Label(t, foreground="#666",
                  text=f"Preferences file: {SETTINGS_PATH}\nLast-used folders and field values are saved automatically."
                  ).grid(row=3, column=0, columnspan=3, sticky="w", padx=10, pady=14)

    def _launch_studio(self):
        exe = self.v_studio.get().strip()
        if not os.path.exists(exe):
            messagebox.showerror("Not found", f"SAI Studio exe not found:\n{exe}")
            return
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe))
        except Exception as e:
            messagebox.showerror("Launch failed", str(e))

    # -------------------------------------------------------------- self-update
    def _build_menu(self):
        menubar = tk.Menu(self)
        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="Check for Updates…", command=lambda: self._check_updates(silent=False))
        helpm.add_separator()
        helpm.add_command(label=f"Version {APP_VERSION}", state="disabled")
        menubar.add_cascade(label="Help", menu=helpm)
        self.config(menu=menubar)

    def _check_updates(self, silent):
        if not _update_url():
            if not silent:
                messagebox.showinfo("Updates",
                    "No update source is configured.\n\n"
                    "Updates come from updateconfig.json beside the app, or the\n"
                    "SAI_UPDATE_URL environment variable.")
            return
        def work():
            try:
                latest = fetch_latest()
            except Exception as e:
                latest = {"__error__": str(e)}
            self.after(0, lambda: self._on_latest(latest, silent))
        threading.Thread(target=work, daemon=True).start()

    def _on_latest(self, latest, silent):
        if "__error__" in latest:
            if not silent:
                messagebox.showwarning("Updates", "Could not check for updates:\n" + latest["__error__"])
            return
        if _ver_tuple(latest.get("version")) <= _ver_tuple(APP_VERSION):
            if not silent:
                messagebox.showinfo("Updates", f"You're up to date (v{APP_VERSION}).")
            return
        notes = latest.get("notes", "")
        if not messagebox.askyesno("Update available",
                f"Version {latest.get('version')} is available (you have {APP_VERSION}).\n\n"
                f"{notes}\n\nDownload and install now?"):
            return
        self._do_update(latest)

    def _do_update(self, latest):
        win = tk.Toplevel(self); win.title("Updating"); win.geometry("440x130"); win.resizable(False, False)
        ttk.Label(win, text=f"Downloading v{latest.get('version')}…").pack(pady=(14, 6))
        pb = ttk.Progressbar(win, length=400, mode="determinate", maximum=100); pb.pack()
        lbl = ttk.Label(win, text="0%"); lbl.pack(pady=4)
        def prog(p): self.after(0, lambda: (pb.config(value=p), lbl.config(text=f"{p}%")))
        def work():
            try:
                exe = download_installer(_resolve_installer_url(latest), latest.get("sha256", ""), prog)
                # The install is silent, so leave a trail: an Inno Setup log in %TEMP%.
                # "Nothing happened" reports are otherwise impossible to diagnose.
                logf = os.path.join(tempfile.gettempdir(), "sai_rip_tester_update.log")
                subprocess.Popen([exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=" + logf])
                self.after(0, lambda: (messagebox.showinfo("Updating",
                    "The installer is running silently in the background (about a minute).\n"
                    "This app will now close; relaunch it afterwards and check Help > Version.\n\n"
                    "If the version did not change, a UAC prompt may have been dismissed. "
                    "The install log is at:\n" + logf),
                    self.destroy(), os._exit(0)))
            except Exception as e:
                self.after(0, lambda: (win.destroy(), messagebox.showerror("Update failed", str(e))))
        threading.Thread(target=work, daemon=True).start()

    # -------------------------------------------------------------- build / run
    def _build_cmd(self):
        """Return (argv list, cwd, pre) or raise ValueError with a clear message.
        pre = None, or a dict describing input preprocessing (tif convert /
        length stretch) that the worker performs just before launching."""
        engine = self.v_engine.get().strip()
        if not os.path.exists(engine):
            raise ValueError(f"Engine exe not found (see Settings tab):\n{engine}")
        inp = self.v_input.get().strip()
        if not inp:
            raise ValueError("Input image is required.")
        prof = self.v_profile.get().strip()
        if not prof:
            raise ValueError("Profile file (XML or ICC) is required.")
        width = self.v_width.get().strip()
        if not width:
            raise ValueError("Print width is required.")

        # channels 4 and --cmyk-test imply each other in the engine — pair them
        channels = self.v_channels.get().split()[0]
        # 4 channels is now a real profile-driven mode (a CMYK device link or printer
        # ICC), NOT the --cmyk-test maths. Only the explicit checkbox selects the maths
        # path; picking 4 channels alone must keep using the profile.
        cmyk = self.v_cmyk.get()
        if cmyk:
            channels = "4"

        # optional length override: engine output is proportional to the image
        # aspect, so we pre-stretch the image to width:length before the run.
        length = self.v_length.get().strip()
        pre = None
        if length:
            try:
                ratio = float(length) / float(width)
                if ratio <= 0:
                    raise ValueError
            except ValueError:
                raise ValueError("Print length must be a positive number (same unit as width).")
            pre = {"stretch_ratio": ratio}
        ext = os.path.splitext(inp)[1].lower()
        if ext == ".pdf":
            # PDF goes through sai_loader (MuPDF). A forced length is FREE here:
            # we just scale the render dpi_y, no resample pass needed.
            pre = pre or {}
            pre["loader"] = True
            pre["pdf"] = True
        elif ext in (".tif", ".tiff"):
            pre = pre or {}
            if pre.get("stretch_ratio"):
                pre["convert"] = True          # stretch needs the GDI+ raster path
            else:
                pre["loader"] = True           # fast raw path via sai_loader (libtiff)
                pre["convert"] = True          # GDI+ fallback if loader missing
        elif ext == ".bmp":
            pre = pre or {}
            pre["convert"] = True

        # Contrast / saturation. Both paths (converted tif, direct jpg/png) take the
        # same numbers, so two formats of one artwork stay comparable. Only the GDI+
        # raster stage can touch pixels — the loader emits a raw .sair the engine
        # reads directly — so any active adjustment forces conversion.
        adj = self._adjustments()
        if adj:
            pre = pre or {}
            pre.update(adj)
            if ext in (".tif", ".tiff", ".pdf") and self._loader_exe():
                # sai_loader applies the curve while it streams rows, so a 2 GB TIFF
                # never lands in Python and no intermediate PNG is written. Only the
                # GDI+ fallback needs the whole image in memory.
                pre["loader"] = True
                pre.setdefault("convert", True)      # still the fallback if the loader dies
            else:
                # jpg/png/bmp: no loader for these formats, use the raster path
                pre["convert"] = True
                pre.pop("loader", None)
        if pre:
            pre["src"] = inp

        argv = [engine, "--input", inp]
        if self.v_profmode.get() == "xml":
            argv += ["--xml", prof]
        else:
            argv += ["--icc", prof]
        argv += [WIDTH_UNITS[self.v_unit.get()], width]

        dpi = DPI_FLAGS.get(self.v_dpi.get())
        if dpi:
            argv.append(dpi)
        argv += ["--channels", channels]

        if self.v_cs.get().strip():
            argv += ["--cs", self.v_cs.get().strip()]
        if self.v_pllut.get().strip():
            argv += ["--pl-lut", self.v_pllut.get().strip(), "--pl-size", self.v_plsize.get().strip() or "256"]
        if self.v_lut.get().strip():
            argv += ["--lut", self.v_lut.get().strip(),
                     "--lut-dim", self.v_lutdim.get().strip() or "33",
                     "--lut-header", self.v_luthdr.get().strip() or "22"]
        # the engine now defaults to lanczos; only pass the flag when overriding it
        # Exact matches, not prefixes: a browsed file called "AdobeRGB1998.icc" shows up
        # as the label and would otherwise be mistaken for the built-in Adobe RGB.
        sel = self.v_inprof.get()
        if sel == "Auto (from profile)":
            argv += ["--input-profile", "auto"]
        elif sel == "sRGB":
            argv += ["--input-profile", "srgb"]
        elif sel == "Adobe RGB (1998)":
            argv += ["--input-profile", "adobergb"]
        elif self.v_inprof_file.get().strip():
            argv += ["--input-profile", self.v_inprof_file.get().strip()]
        up = self.v_upscale.get().split()[0]
        if up and up != "lanczos":
            argv += ["--upscale", up]
        if self.v_dither.get().startswith("green"):
            argv += ["--dither", "green"]
        for flag, var, default in (("--dither-strength", self.v_dstrength, "85"),
                                   ("--dither-taper", self.v_dtaper, "8")):
            v = var.get().strip()
            if v and v != default:
                argv += [flag, v]
        if self.v_dadaptive.get():
            argv.append("--dither-adaptive")
            thr = self.v_dthreshold.get().strip()
            if thr and thr != "12":
                argv += ["--dither-threshold", thr]
        if self.v_dropsizes.get():
            argv.append("--drop-sizes")
            vols = self.v_dropvols.get().strip()
            if vols:
                argv.append(vols)      # measured volumes override the profile nominals
        if self.v_edge.get():
            argv.append("--edge-aware")
            for flag, var, default in (("--edge-threshold", self.v_edge_thr, "24"),
                                       ("--edge-softness", self.v_edge_soft, "24"),
                                       ("--edge-radius", self.v_edge_rad, "6")):
                v = var.get().strip()
                if v and v != default:
                    argv += [flag, v]
        if self.v_inkctl.get():
            argv.append("--ink-control")
        pct = self.v_inklimit_pct.get().strip()
        if pct:
            argv += ["--ink-limit", pct]      # implies enforcement engine-side
        elif self.v_inklimit.get():
            argv.append("--enforce-ink-limit")
        if self.v_nopl.get():
            argv.append("--no-pl-lut")
        if self.v_rasterok.get():
            argv.append("--allow-raster-mismatch")
        if self.v_debug.get():
            argv.append("--debug-save")
        if self.v_preview.get():
            argv.append("--preview")
        if cmyk:
            argv.append("--cmyk-test")

        if self.v_send.get():
            ip = self.v_ip.get().strip()
            if not ip:
                raise ValueError("Printer IP is required when 'Send to printer' is enabled.")
            argv += ["--printer", ip, "--port", self.v_port.get().strip() or "9100"]
        else:
            out = self.v_output.get().strip()
            if not out or out == self._out_autofilled:
                # auto-name after the ORIGINAL input; timestamp instead of overwrite.
                # The source extension goes into the name so the same artwork ripped
                # from .tif and from .png lands on two files, not one.
                # No separators anywhere:  Wine & Cheesepng.prt
                #                          Wine & Cheesepng280726210415.prt
                base = os.path.splitext(os.path.basename(inp))[0]
                src_ext = os.path.splitext(inp)[1].lstrip(".").lower()
                folder = os.path.dirname(inp) or os.getcwd()
                stem = base + src_ext
                out = os.path.join(folder, stem + ".prt")
                if os.path.exists(out):
                    out = os.path.join(folder, stem + time.strftime("%y%d%m%H%M%S") + ".prt")
                self.v_output.set(out)
                self._out_autofilled = out
            argv += ["--output", out]

        # cwd = profile folder so relative ICC/LUT filenames inside the XML resolve
        cwd = os.path.dirname(prof) or os.path.dirname(engine)
        return argv, cwd, pre

    def _on_input_space(self, _evt=None):
        """'Browse' turns the dropdown into a file picker; the chosen file's name
        becomes the visible label so the operator can see what is selected."""
        if not self.v_inprof.get().startswith("Browse"):
            return
        p = filedialog.askopenfilename(title="Select an input colour profile",
                                       filetypes=[("ICC profiles", "*.icc *.icm"), ("All", "*.*")],
                                       initialdir=self.cfg.get("last_inprof_dir", DEFAULT_PROFILE_DIR))
        if p:
            self.v_inprof_file.set(p)
            self.v_inprof.set(os.path.basename(p))
            self.cfg["last_inprof_dir"] = os.path.dirname(p)
        else:
            self.v_inprof.set("Auto (from profile)")

    def _clear_output(self):
        """Empty the output field so the next run re-derives the auto name."""
        self.v_output.set("")
        self._out_autofilled = ""

    def _adjustments(self):
        """Contrast/saturation as {name: value}, omitting neutral (1.00) entries."""
        out = {}
        for name, var in (("contrast", self.v_contrast), ("saturation", self.v_saturation)):
            raw = var.get().strip() or "1"
            try:
                val = float(raw)
            except ValueError:
                raise ValueError(f"{name.capitalize()} must be a number (1.00 = unchanged).")
            if not 0.0 <= val <= 4.0:
                raise ValueError(f"{name.capitalize()} must be between 0 and 4 (1.00 = unchanged).")
            if abs(val - 1.0) > 1e-6:
                out[name] = val
        return out

    @staticmethod
    def _color_matrix(contrast, saturation):
        """5x5 GDI+ ColorMatrix applying saturation then contrast, or None when both
        are neutral. Row-vector convention: out = [r g b a 1] * M."""
        c = 1.0 if contrast is None else float(contrast)
        s = 1.0 if saturation is None else float(saturation)
        if abs(c - 1.0) < 1e-6 and abs(s - 1.0) < 1e-6:
            return None
        lr, lg, lb = 0.3086, 0.6094, 0.0820          # luminance weights
        sr, sg, sb = (1.0 - s) * lr, (1.0 - s) * lg, (1.0 - s) * lb
        m = [[sr + s, sr, sr], [sg, sg + s, sg], [sb, sb, sb + s]]
        m = [[v * c for v in row] for row in m]      # contrast scales the 3x3...
        t = (1.0 - c) / 2.0                          # ...and pivots about mid-grey
        return [m[0] + [0.0, 0.0],
                m[1] + [0.0, 0.0],
                m[2] + [0.0, 0.0],
                [0.0, 0.0, 0.0, 1.0, 0.0],
                [t, t, t, 0.0, 1.0]]

    # ----------------------------------------------- input preprocessing (loader)
    def _loader_exe(self):
        """Locate sai_loader.exe (TIFF/PDF decoder, separate from the engine)."""
        cands = [os.path.join(_BASE, "bin", "sai_loader.exe"),
                 os.path.join(_BASE, "loader", "sai_loader.exe"),
                 os.path.join(os.path.dirname(self.v_engine.get().strip() or DEFAULT_ENGINE),
                              "sai_loader.exe")]
        for c in cands:
            if os.path.exists(c):
                return c
        return None

    def _dpi_pair(self):
        """DPI implied by the dropdown, for PDF rendering (default 540x720)."""
        import re as _re
        m = _re.match(r"(\d+)\s*x\s*(\d+)", self.v_dpi.get())
        return (int(m.group(1)), int(m.group(2))) if m else (540, 720)

    def _preprocess_loader(self, pre):
        """Decode TIFF/PDF via sai_loader.exe to a raw .sair frame (no PNG
        round-trip). Returns the .sair path, or None to use the GDI+ fallback."""
        exe = self._loader_exe()
        if not exe:
            return None
        src = pre["src"]
        dst = os.path.join(tempfile.gettempdir(),
                           "sai_pre_" + os.path.splitext(os.path.basename(src))[0] + ".sair")
        argv = [exe, "--input", src, "--out", dst]
        if pre.get("pdf"):
            dx, dy = self._dpi_pair()
            if pre.get("stretch_ratio"):
                # forced length: scale the render's vertical dpi instead of resampling
                dy = max(1, int(round(dy * pre["stretch_ratio"])))
            argv += ["--dpi", str(dx), str(dy), "--page", "1"]
        if pre.get("contrast"):
            argv += ["--contrast", "%.4f" % pre["contrast"]]
        if pre.get("saturation"):
            argv += ["--saturation", "%.4f" % pre["saturation"]]
        if pre.get("stretch_ratio") and not pre.get("pdf"):
            return None      # a forced length on a TIFF still needs the resampling path
        r = subprocess.run(argv, capture_output=True, text=True, timeout=600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0 or not os.path.exists(dst):
            self.log_q.put("[loader] failed (%s) - falling back\n" % (r.stderr or "?").strip()[:200])
            return None
        return dst

    # ------------------------------------------------- input preprocessing (GDI+)
    @staticmethod
    def _preprocess_input(pre):
        """Convert tif/bmp to png and/or stretch to the forced length, using
        Windows GDI+ via PowerShell — no Python imaging library needed, and the
        engine exe is untouched. Returns the path of the temp png."""
        src = pre["src"]
        dst = os.path.join(tempfile.gettempdir(),
                           "sai_pre_" + os.path.splitext(os.path.basename(src))[0] + ".png")
        real_dst = dst
        # single quotes would break the quoted PowerShell literals below
        src, dst = src.replace("'", "''"), dst.replace("'", "''")
        ratio = pre.get("stretch_ratio")
        stretch = (f"$h=[int][math]::Round($img.Width*{ratio})"
                   if ratio else "$h=$img.Height")
        # contrast/saturation ride along as a ColorMatrix on the same DrawImage,
        # so there is no extra resample pass and no second temp file
        cm = Tester._color_matrix(pre.get("contrast"), pre.get("saturation"))
        if cm:
            rows = ",".join("[float[]]@(" + ",".join("%.6f" % v for v in row) + ")" for row in cm)
            draw = (
                f'$rows=@({rows}); '
                '$cmx=New-Object System.Drawing.Imaging.ColorMatrix(,[float[][]]$rows); '
                '$ia=New-Object System.Drawing.Imaging.ImageAttributes; '
                '$ia.SetColorMatrix($cmx); '
                '$rect=New-Object System.Drawing.Rectangle(0,0,$img.Width,$h); '
                '$g.DrawImage($img,$rect,0,0,$img.Width,$img.Height,'
                '[System.Drawing.GraphicsUnit]::Pixel,$ia); $ia.Dispose(); '
            )
        else:
            draw = '$g.DrawImage($img,0,0,$img.Width,$h); '
        ps = (
            'Add-Type -AssemblyName System.Drawing; '
            f'$img=[System.Drawing.Image]::FromFile(\'{src}\'); '
            f'{stretch}; '
            '$bmp=New-Object System.Drawing.Bitmap($img.Width,$h); '
            '$g=[System.Drawing.Graphics]::FromImage($bmp); '
            '$g.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic; '
            + draw +
            f'$bmp.Save(\'{dst}\',[System.Drawing.Imaging.ImageFormat]::Png); '
            '$g.Dispose(); $bmp.Dispose(); $img.Dispose()'
        )
        if os.path.exists(real_dst):
            os.remove(real_dst)
        shells = (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                               "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
                  "powershell", "pwsh")
        err = "no PowerShell found"
        for exe in shells:
            try:
                r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", ps],
                                   capture_output=True, text=True, timeout=300,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception as e:
                err = str(e)
                continue
            if r.returncode == 0 and os.path.exists(real_dst):
                return real_dst
            err = (r.stderr or r.stdout or "unknown error").strip()
        raise RuntimeError("Input preprocessing failed:\n" + err)

    @staticmethod
    def _quote(argv):
        return " ".join((f'"{a}"' if " " in a else a) for a in argv)

    def _preview_cmd(self):
        try:
            argv, cwd, pre = self._build_cmd()
        except ValueError as e:
            messagebox.showwarning("Incomplete", str(e)); return
        if pre:
            what = []
            if pre.get("convert"):
                what.append("convert to png")
            if pre.get("stretch_ratio"):
                what.append(f"stretch to aspect 1:{pre['stretch_ratio']:.3f} for the forced length")
            if pre.get("contrast"):
                what.append(f"contrast x{pre['contrast']:.2f}")
            if pre.get("saturation"):
                what.append(f"saturation x{pre['saturation']:.2f}")
            self._append(f"[preprocess] input will be {' + '.join(what)} before the run\n")
        self._append(f"[cwd] {cwd}\n{self._quote(argv)}\n\n")

    def _run_engine(self):
        if self.proc is not None:
            messagebox.showinfo("Busy", "A run is already in progress."); return
        try:
            argv, cwd, pre = self._build_cmd()
        except ValueError as e:
            messagebox.showwarning("Incomplete", str(e)); return
        if self.v_send.get():
            if not messagebox.askyesno("Send to printer?",
                                       f"This will stream directly to {self.v_ip.get()}:{self.v_port.get()}.\nProceed?"):
                return
        self._append("=" * 70 + f"\n[cwd] {cwd}\n{self._quote(argv)}\n" + "=" * 70 + "\n")
        self.run_btn.config(state="disabled")
        threading.Thread(target=self._worker, args=(argv, cwd, pre), daemon=True).start()

    def _worker(self, argv, cwd, pre=None):
        try:
            if pre:
                self.log_q.put("[preprocess] preparing input image…\n")
                tmp = None
                if pre.get("loader"):
                    tmp = self._preprocess_loader(pre)   # raw .sair via libtiff/MuPDF
                if tmp is None:
                    if pre.get("pdf"):
                        raise RuntimeError("PDF input needs sai_loader.exe (not found)")
                    tmp = self._preprocess_input(pre)    # GDI+ fallback (png)
                argv[argv.index(pre["src"], 1)] = tmp   # swap --input value only
                self.log_q.put(f"[preprocess] using {tmp}\n")
            self.proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, bufsize=1,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in self.proc.stdout:
                self.log_q.put(line)
            self.proc.wait()
            rc = self.proc.returncode
            out = self.v_output.get().strip()
            msg = f"\n[exit code {rc}] "
            if rc == 0 and not self.v_send.get() and out and os.path.exists(out):
                mb = os.path.getsize(out) / (1024 * 1024)
                msg += f"OK  ->  {out}  ({mb:,.2f} MB)\n"
            elif rc == 0:
                msg += "OK\n"
            else:
                msg += "FAILED (see log above)\n"
                send_telemetry("error", f"engine exit {rc}")
            self.log_q.put(msg)
        except Exception as e:
            self.log_q.put(f"\n[error] {e}\n")
        finally:
            self.proc = None
            self.log_q.put(("__done__", None))

    def _stop(self):
        if self.proc:
            try:
                self.proc.terminate()
                self._append("\n[stopped by user]\n")
            except Exception:
                pass

    def _open_out(self):
        out = self.v_output.get().strip()
        folder = os.path.dirname(out) if out else ""
        if folder and os.path.isdir(folder):
            os.startfile(folder)  # noqa: WPS (Windows-only, intended)
        else:
            messagebox.showinfo("No folder", "Set/produce an output file first.")

    # ----------------------------------------------------------------- logging
    def _append(self, text):
        self.log.insert("end", text); self.log.see("end")

    def _drain_log(self):
        try:
            while True:
                item = self.log_q.get_nowait()
                if isinstance(item, tuple) and item[0] == "__done__":
                    self.run_btn.config(state="normal")
                else:
                    self._append(item)
        except queue.Empty:
            pass
        self.after(80, self._drain_log)


if __name__ == "__main__":
    if "--heartbeat" in sys.argv:      # headless: used by the scheduled diagnostics task
        send_telemetry("heartbeat", sync=True)
        sys.exit(0)
    if "--paths" in sys.argv:          # diagnostic: show resolved install-relative paths
        print("install base:", _BASE)
        print("engine  :", DEFAULT_ENGINE, os.path.exists(DEFAULT_ENGINE))
        print("profile :", DEFAULT_PROFILE, os.path.exists(DEFAULT_PROFILE))
        print("input   :", DEFAULT_INPUT, os.path.exists(DEFAULT_INPUT))
        print("studio  :", DEFAULT_STUDIO, os.path.exists(DEFAULT_STUDIO))
        sys.exit(0)
    Tester().mainloop()
