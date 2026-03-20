"""Training Data Extractor — GUI application (Windows/tkinter).

Workflow:
  1. User selects one or more scanned PDF files.
  2. User selects (or creates) the target Excel workbook.
  3. Choose OCR mode: ☁️ Claude API  or  💻 Local OCR (PaddleOCR + OpenCV).
  4. Click [시작] to process: PDF → image → OCR → Excel.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import config
from excel_writer import write_records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_api_key(key: str) -> bool:
    return bool(key and key.startswith("sk-ant-"))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Training Data Extractor")
        self.resizable(False, False)
        self._pdf_paths: list[str] = []
        self._excel_path = tk.StringVar(value=config.SHARED_FOLDER_PATH)
        self._sheet_name = tk.StringVar(value="Training")
        self._api_key = tk.StringVar(value=config.ANTHROPIC_API_KEY)
        self._ocr_mode = tk.StringVar(value=config.OCR_MODE)   # "claude" | "local"
        self._status = tk.StringVar(value="대기 중")
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # --- OCR mode ---
        frm_mode = ttk.LabelFrame(self, text="OCR 모드")
        frm_mode.grid(row=0, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Radiobutton(
            frm_mode, text="☁️  Claude API  (고정밀, 인터넷 필요)",
            variable=self._ocr_mode, value="claude",
            command=self._on_mode_change,
        ).pack(side="left", padx=10, pady=4)
        ttk.Radiobutton(
            frm_mode, text="💻  Local OCR  (PaddleOCR + OpenCV, 오프라인)",
            variable=self._ocr_mode, value="local",
            command=self._on_mode_change,
        ).pack(side="left", padx=10, pady=4)

        # --- API Key (hidden in local mode) ---
        self._frm_api = ttk.LabelFrame(self, text="Claude API Key")
        self._frm_api.grid(row=1, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Entry(self._frm_api, textvariable=self._api_key, width=60, show="*").pack(
            fill="x", padx=6, pady=4
        )

        # --- PDF files ---
        frm_pdf = ttk.LabelFrame(self, text="PDF 파일 선택")
        frm_pdf.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)
        self._pdf_listbox = tk.Listbox(frm_pdf, height=5, width=70)
        self._pdf_listbox.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        sb = ttk.Scrollbar(frm_pdf, orient="vertical", command=self._pdf_listbox.yview)
        sb.pack(side="left", fill="y", pady=4)
        self._pdf_listbox.configure(yscrollcommand=sb.set)
        btn_frame = ttk.Frame(frm_pdf)
        btn_frame.pack(side="left", padx=6)
        ttk.Button(btn_frame, text="추가",     command=self._add_pdfs).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="제거",     command=self._remove_selected_pdf).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="전체 제거", command=self._clear_pdfs).pack(fill="x", pady=2)

        # --- Excel target ---
        frm_xl = ttk.LabelFrame(self, text="대상 Excel 파일")
        frm_xl.grid(row=3, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Entry(frm_xl, textvariable=self._excel_path, width=55).pack(
            side="left", padx=6, pady=4
        )
        ttk.Button(frm_xl, text="찾아보기…", command=self._browse_excel).pack(
            side="left", padx=(0, 6), pady=4
        )

        # --- Sheet name ---
        frm_sheet = ttk.Frame(self)
        frm_sheet.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(frm_sheet, text="시트 이름:").pack(side="left")
        ttk.Entry(frm_sheet, textvariable=self._sheet_name, width=20).pack(side="left", padx=6)

        # --- Log ---
        frm_log = ttk.LabelFrame(self, text="진행 로그")
        frm_log.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)
        self._log = scrolledtext.ScrolledText(frm_log, height=10, width=72, state="disabled")
        self._log.pack(fill="both", expand=True, padx=6, pady=4)

        # --- Progress bar ---
        self._progress = ttk.Progressbar(self, mode="indeterminate")
        self._progress.grid(row=6, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 4))

        # --- Buttons ---
        btn_row = ttk.Frame(self)
        btn_row.grid(row=7, column=0, columnspan=3, pady=(0, 10))
        self._start_btn = ttk.Button(btn_row, text="▶ 시작", command=self._start, width=15)
        self._start_btn.pack(side="left", padx=6)
        ttk.Button(btn_row, text="닫기", command=self.destroy, width=10).pack(side="left", padx=6)

        # --- Status bar ---
        ttk.Label(self, textvariable=self._status, relief="sunken", anchor="w").grid(
            row=8, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 6)
        )

        # Sync UI state on startup
        self._on_mode_change()

    # ------------------------------------------------------------------
    # OCR mode toggle
    # ------------------------------------------------------------------

    def _on_mode_change(self):
        """Show/hide API key field depending on selected OCR mode."""
        if self._ocr_mode.get() == "local":
            self._frm_api.grid_remove()
        else:
            self._frm_api.grid()

    # ------------------------------------------------------------------
    # File pickers
    # ------------------------------------------------------------------

    def _add_pdfs(self):
        paths = filedialog.askopenfilenames(
            title="PDF 파일 선택",
            filetypes=[("PDF 파일", "*.pdf"), ("모든 파일", "*.*")],
        )
        for p in paths:
            if p not in self._pdf_paths:
                self._pdf_paths.append(p)
                self._pdf_listbox.insert("end", Path(p).name)

    def _remove_selected_pdf(self):
        for i in reversed(self._pdf_listbox.curselection()):
            self._pdf_listbox.delete(i)
            self._pdf_paths.pop(i)

    def _clear_pdfs(self):
        self._pdf_listbox.delete(0, "end")
        self._pdf_paths.clear()

    def _browse_excel(self):
        path = filedialog.asksaveasfilename(
            title="Excel 파일 선택 또는 생성",
            defaultextension=".xlsx",
            filetypes=[("Excel 파일", "*.xlsx"), ("모든 파일", "*.*")],
        )
        if path:
            self._excel_path.set(path)

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log_write(self, msg: str):
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_status(self, msg: str):
        self._status.set(msg)
        self.update_idletasks()

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def _start(self):
        if not self._pdf_paths:
            messagebox.showwarning("경고", "PDF 파일을 먼저 추가하세요.")
            return
        if not self._excel_path.get():
            messagebox.showwarning("경고", "대상 Excel 파일을 선택하세요.")
            return

        mode = self._ocr_mode.get()

        if mode == "claude":
            api_key = self._api_key.get().strip()
            if not _validate_api_key(api_key):
                messagebox.showerror("오류", "유효한 Claude API Key를 입력하세요 (sk-ant- 로 시작).")
                return
            self._start_btn.configure(state="disabled")
            self._progress.start(10)
            threading.Thread(
                target=self._run_claude, args=(api_key,), daemon=True
            ).start()
        else:
            self._start_btn.configure(state="disabled")
            self._progress.start(10)
            threading.Thread(target=self._run_local, daemon=True).start()

    def _run_claude(self, api_key: str):
        import anthropic
        from ocr_extractor import extract_data_from_pdf

        client = anthropic.Anthropic(api_key=api_key)
        total_written = 0
        try:
            for pdf_path in self._pdf_paths:
                self._log_write(f"\n[Claude] {Path(pdf_path).name}")
                self._set_status(f"처리 중: {Path(pdf_path).name}")
                records = extract_data_from_pdf(
                    pdf_path, client=client,
                    status_callback=lambda m: (self._log_write(f"  {m}"), self._set_status(m)),
                )
                self._log_write(f"  → {len(records)}명 추출")
                written = write_records(records, self._excel_path.get(),
                                        sheet_name=self._sheet_name.get() or None)
                total_written += written
                self._log_write(f"  → Excel {written}행 기록")
            self._finish(total_written)
        except Exception as exc:
            self._error(exc)

    def _run_local(self):
        from local_ocr_extractor import extract_data_from_pdf_local

        total_written = 0
        try:
            self._log_write("\n[Local OCR] PaddleOCR 모델 로딩 중...")
            for pdf_path in self._pdf_paths:
                self._log_write(f"\n[Local OCR] {Path(pdf_path).name}")
                self._set_status(f"처리 중: {Path(pdf_path).name}")
                records = extract_data_from_pdf_local(
                    pdf_path,
                    status_callback=lambda m: (self._log_write(f"  {m}"), self._set_status(m)),
                )
                self._log_write(f"  → {len(records)}명 추출")
                written = write_records(records, self._excel_path.get(),
                                        sheet_name=self._sheet_name.get() or None)
                total_written += written
                self._log_write(f"  → Excel {written}행 기록")
            self._finish(total_written)
        except Exception as exc:
            self._error(exc)

    def _finish(self, total_written: int):
        self._log_write(f"\n[완료] 총 {total_written}행 저장됨")
        self._set_status(f"완료 — {total_written}행 저장됨")
        messagebox.showinfo("완료", f"처리 완료\n총 {total_written}행이 저장되었습니다.")
        self._progress.stop()
        self._start_btn.configure(state="normal")

    def _error(self, exc: Exception):
        self._log_write(f"\n[오류] {exc}")
        self._set_status("오류 발생")
        messagebox.showerror("오류", str(exc))
        self._progress.stop()
        self._start_btn.configure(state="normal")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
