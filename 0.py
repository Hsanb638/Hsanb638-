"""
CapForge OneFile — محرّر فيديو مبسّط بملف واحد (GUI)
=====================================================

ميزات سريعة:
- إضافة مقاطع فيديو متعددة + إعادة ترتيب (أعلى/أسفل)
- قص لكل مقطع (Start/End بالثواني)
- انتقال Crossfade اختياري بين المقاطع
- نص فوق الفيديو لكل مقطع (PIL — بدون ImageMagick)
- موسيقى خلفية مع تحكم شدة الصوت
- تصدير MP4 (H.264/AAC) مع اختيار FPS ودقّة تحجيم

التشغيل:
1) ثبّت بايثون 3.10+
2) ثبّت التبعيات:
   pip install moviepy Pillow numpy
   (تأكد أن FFmpeg مثبّت على جهازك أو سيحمّله imageio تلقائياً)
3) شغّل الملف:
   python capforge_onefile.py

ملاحظات:
- لتسريع التصدير استخدم SSD واغلق البرامج الثقيلة.
- إذا ظهر تحذير ImageMagick فهذا الكود لا يعتمد عليه (نستخدم PIL للتكسيت).
"""
from __future__ import annotations
import os, sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip,
    concatenate_videoclips, ImageClip, vfx
)
from PIL import Image, ImageDraw, ImageFont
import numpy as np

@dataclass
class ClipCfg:
    path: str
    start: float = 0.0
    end: Optional[float] = None  # None => till end
    text: str = ""
    text_pos: str = "bottom"  # top/center/bottom or TL/TR/BL/BR
    text_scale: float = 0.06    # نسبة من ارتفاع الفيديو

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CapForge OneFile")
        self.geometry("1100x620")
        self.resizable(True, True)

        # الحالة
        self.clips: List[ClipCfg] = []
        self.bg_music_path: Optional[str] = None
        self.bg_gain: float = 0.35
        self.crossfade_s: float = 0.5
        self.target_h: int = 1080
        self.target_fps: int = 30

        self._build_ui()

    # ---------------- UI -----------------
    def _build_ui(self):
        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left = ttk.Frame(root)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = ttk.Frame(root)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        # قائمة التايملاين
        ttk.Label(left, text="الـ Timeline (اسحب/رتّب بأزرار)").pack(anchor=tk.W)
        self.listbox = tk.Listbox(left, height=20)
        self.listbox.pack(fill=tk.BOTH, expand=True)

        btns = ttk.Frame(left); btns.pack(fill=tk.X, pady=6)
        ttk.Button(btns, text="+ إضافة مقاطع", command=self.add_clips).pack(side=tk.LEFT)
        ttk.Button(btns, text="حذف", command=self.del_clip).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="▲", width=3, command=lambda: self.move_sel(-1)).pack(side=tk.LEFT)
        ttk.Button(btns, text="▼", width=3, command=lambda: self.move_sel(1)).pack(side=tk.LEFT)

        # إعدادات المقطع
        pane = ttk.LabelFrame(left, text="إعدادات المقطع")
        pane.pack(fill=tk.X, pady=8)
        self.var_start = tk.DoubleVar(value=0)
        self.var_end = tk.DoubleVar(value=0)
        self.var_text = tk.StringVar(value="")
        self.var_pos = tk.StringVar(value="bottom")
        self.var_tscale = tk.DoubleVar(value=0.06)
        row = ttk.Frame(pane); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="Start (s)").pack(side=tk.LEFT); ttk.Entry(row, width=8, textvariable=self.var_start).pack(side=tk.LEFT, padx=4)
        ttk.Label(row, text="End (s, 0=إلى النهاية)").pack(side=tk.LEFT); ttk.Entry(row, width=8, textvariable=self.var_end).pack(side=tk.LEFT, padx=4)
        row2 = ttk.Frame(pane); row2.pack(fill=tk.X, pady=4)
        ttk.Label(row2, text="نص المقطع").pack(side=tk.LEFT); ttk.Entry(row2, textvariable=self.var_text, width=50).pack(side=tk.LEFT, padx=4)
        ttk.Label(row2, text="موضع النص").pack(side=tk.LEFT)
        ttk.Combobox(row2, values=["top","center","bottom","TL","TR","BL","BR"], textvariable=self.var_pos, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Label(row2, text="حجم النص").pack(side=tk.LEFT)
        ttk.Entry(row2, width=6, textvariable=self.var_tscale).pack(side=tk.LEFT)
        ttk.Button(pane, text="تطبيق على المقطع المحدد", command=self.apply_to_selected).pack(pady=4)

        # إعدادات عامة / تصدير
        box = ttk.LabelFrame(right, text="تصدير")
        box.pack(fill=tk.X)
        self.var_fps = tk.IntVar(value=self.target_fps)
        self.var_height = tk.IntVar(value=self.target_h)
        ttk.Label(box, text="FPS").pack(anchor=tk.W); ttk.Entry(box, textvariable=self.var_fps, width=6).pack(anchor=tk.W)
        ttk.Label(box, text="الارتفاع (720/1080/2160)").pack(anchor=tk.W); ttk.Entry(box, textvariable=self.var_height, width=8).pack(anchor=tk.W)
        ttk.Label(box, text="Crossfade (ثانية)").pack(anchor=tk.W); self.var_xfade = tk.DoubleVar(value=self.crossfade_s); ttk.Entry(box, textvariable=self.var_xfade, width=6).pack(anchor=tk.W)

        mbox = ttk.LabelFrame(right, text="موسيقى الخلفية")
        mbox.pack(fill=tk.X, pady=8)
        self.var_gain = tk.DoubleVar(value=self.bg_gain)
        ttk.Button(mbox, text="اختيار ملف موسيقى…", command=self.pick_music).pack(fill=tk.X)
        ttk.Label(mbox, text="Gain 0-1").pack(anchor=tk.W)
        ttk.Entry(mbox, textvariable=self.var_gain, width=6).pack(anchor=tk.W)

        ttk.Button(right, text="تصدير MP4…", command=self.export_video).pack(fill=tk.X, pady=10)

        self.listbox.bind("<<ListboxSelect>>", lambda e: self.on_select())

    # ------------- Helpers --------------
    def add_clips(self):
        paths = filedialog.askopenfilenames(title="اختر ملفات فيديو", filetypes=[["Video","*.mp4 *.mov *.mkv *.avi *.m4v"]])
        for p in paths:
            self.clips.append(ClipCfg(path=p))
            self.listbox.insert(tk.END, os.path.basename(p))

    def del_clip(self):
        i = self._sel_index();
        if i is None: return
        self.clips.pop(i)
        self.listbox.delete(i)

    def move_sel(self, delta:int):
        i = self._sel_index();
        if i is None: return
        j = max(0, min(len(self.clips)-1, i+delta))
        if i==j: return
        self.clips[i], self.clips[j] = self.clips[j], self.clips[i]
        name = self.listbox.get(i)
        self.listbox.delete(i)
        self.listbox.insert(j, name)
        self.listbox.select_set(j)

    def on_select(self):
        i = self._sel_index();
        if i is None: return
        c = self.clips[i]
        self.var_start.set(c.start)
        self.var_end.set(0 if c.end is None else c.end)
        self.var_text.set(c.text)
        self.var_pos.set(c.text_pos)
        self.var_tscale.set(c.text_scale)

    def apply_to_selected(self):
        i = self._sel_index();
        if i is None: return
        endv = self.var_end.get()
        self.clips[i] = ClipCfg(
            path=self.clips[i].path,
            start=float(self.var_start.get()),
            end=None if endv==0 else float(endv),
            text=self.var_text.get(),
            text_pos=self.var_pos.get(),
            text_scale=float(self.var_tscale.get()),
        )
        messagebox.showinfo("تم", "تطبيق الإعدادات على المقطع")

    def pick_music(self):
        p = filedialog.askopenfilename(title="اختر موسيقى", filetypes=[["Audio","*.mp3 *.wav *.m4a *.aac"]])
        if p:
            self.bg_music_path = p

    def _sel_index(self) -> Optional[int]:
        sel = self.listbox.curselection()
        return int(sel[0]) if sel else None

    # ---------- Render helpers ----------
    def _pil_text_image(self, w:int, h:int, text:str, scale:float, pos:str) -> np.ndarray:
        if not text:
            return None
        img = Image.new("RGBA", (w, h), (0,0,0,0))
        draw = ImageDraw.Draw(img)
        # حاول اختيار خط متوفر
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(16, int(h*scale)))
        except:
            font = ImageFont.load_default()
        tw, th = draw.textsize(text, font=font)
        pad = int(h*0.02)
        # خلفية شبه شفافة للنص
        rect_w, rect_h = tw+pad*2, th+pad*2
        if pos.lower() == "top":
            x, y = (w-rect_w)//2, pad
        elif pos.lower() == "center":
            x, y = (w-rect_w)//2, (h-rect_h)//2
        elif pos.lower() == "tl":
            x, y = pad, pad
        elif pos.lower() == "tr":
            x, y = w-rect_w-pad, pad
        elif pos.lower() == "bl":
            x, y = pad, h-rect_h-pad
        elif pos.lower() == "br":
            x, y = w-rect_w-pad, h-rect_h-pad
        else:  # bottom
            x, y = (w-rect_w)//2, h-rect_h-pad
        draw.rounded_rectangle([x, y, x+rect_w, y+rect_h], radius=pad, fill=(0,0,0,140))
        draw.text((x+pad, y+pad), text, font=font, fill=(255,255,255,230))
        return np.array(img)

    def _build_clip(self, cfg:ClipCfg, target_h:int, fps:int):
        v = VideoFileClip(cfg.path)
        # تحجيم حسب الارتفاع المطلوب
        if target_h and v.h != target_h:
            v = v.resize(height=target_h)
        # قص
        start = max(0, float(cfg.start))
        end = cfg.end if cfg.end is not None else v.duration
        end = min(end, v.duration)
        if end > start:
            v = v.subclip(start, end)
        # نص
        if cfg.text:
            frame = self._pil_text_image(v.w, v.h, cfg.text, cfg.text_scale, cfg.text_pos)
            if frame is not None:
                txt = ImageClip(frame, ismask=False).set_duration(v.duration)
                v = CompositeVideoClip([v, txt])
        return v.set_fps(fps)

    def export_video(self):
        if not self.clips:
            messagebox.showwarning("تنبيه", "أضف مقاطع أولاً")
            return
        out = filedialog.asksaveasfilename(title="حفظ باسم", defaultextension=".mp4",
                                           filetypes=[["MP4","*.mp4"]], initialfile="output.mp4")
        if not out:
            return
        try:
            self.target_h = int(self.var_height.get())
            self.target_fps = int(self.var_fps.get())
            self.crossfade_s = float(self.var_xfade.get())
            # بناء المقاطع
            clips: List[VideoFileClip] = []
            for cfg in self.clips:
                clips.append(self._build_clip(cfg, self.target_h, self.target_fps))
            # تطبيق crossfade
            if self.crossfade_s > 0 and len(clips) > 1:
                for i in range(1, len(clips)):
                    clips[i] = clips[i].crossfadein(self.crossfade_s)
                final_v = concatenate_videoclips(clips, method="compose")
            else:
                final_v = concatenate_videoclips(clips, method="compose")

            # موسيقى خلفية
            if self.bg_music_path:
                bg = AudioFileClip(self.bg_music_path).volumex(float(self.var_gain.get()))
                if final_v.audio is not None:
                    mixed = CompositeAudioClip([final_v.audio, bg.set_duration(final_v.duration)])
                else:
                    mixed = bg.set_duration(final_v.duration)
                final_v = final_v.set_audio(mixed)

            # كتابة الملف
            final_v.write_videofile(out, codec="libx264", audio_codec="aac", fps=self.target_fps, preset="medium")
            messagebox.showinfo("تم", f"تم التصدير:\n{out}")
        except Exception as e:
            messagebox.showerror("خطأ", str(e))

if __name__ == "__main__":
    App().mainloop()
