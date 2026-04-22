from __future__ import annotations
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import sf_config as cfg
from sf_connector import SalesforceConnector
from sf_excel_reader import preview_records, read_excel


class SalesforceUploaderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Salesforce Uploader")
        self.resizable(False, False)
        self.geometry("700x560")
        self._connector = SalesforceConnector()
        self._records: list[dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 4}
        tk.Label(self, text="Salesforce Uploader", font=("Segoe UI", 14, "bold")).pack(**pad, anchor="w")
        tk.Label(self, text=f"Target Object: {cfg.SF_OBJECT_API_NAME}  |  Domain: {cfg.SF_DOMAIN}", font=("Segoe UI", 9), fg="gray").pack(anchor="w", padx=10)
        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=10, pady=6)

        file_frame = tk.Frame(self)
        file_frame.pack(fill="x", **pad)
        tk.Label(file_frame, text="Excel 파일:", width=12, anchor="w").pack(side="left")
        self._file_var = tk.StringVar()
        tk.Entry(file_frame, textvariable=self._file_var, width=52, state="readonly").pack(side="left", padx=(0, 6))
        tk.Button(file_frame, text="찾아보기", command=self._browse_file).pack(side="left")

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=(0, 4))
        self._load_btn = tk.Button(btn_frame, text="엑셀 불러오기", width=20, command=self._load_excel)
        self._load_btn.pack(side="left", padx=(0, 8))
        self._row_label = tk.Label(btn_frame, text="", fg="navy", font=("Segoe UI", 9))
        self._row_label.pack(side="left")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=10, pady=6)

        cred_frame = tk.LabelFrame(self, text="Salesforce 연결 (.env)", padx=8, pady=6)
        cred_frame.pack(fill="x", padx=10, pady=(0, 6))

        def _cred_row(parent, label, var, show=""):
            tk.Label(parent, text=label, width=18, anchor="w").pack(side="left")
            tk.Entry(parent, textvariable=var, width=40, show=show).pack(side="left")

        r1 = tk.Frame(cred_frame); r1.pack(fill="x", pady=2)
        r2 = tk.Frame(cred_frame); r2.pack(fill="x", pady=2)
        r3 = tk.Frame(cred_frame); r3.pack(fill="x", pady=2)

        self._username_var = tk.StringVar(value=cfg.SF_USERNAME)
        self._password_var = tk.StringVar(value=cfg.SF_PASSWORD)
        self._token_var    = tk.StringVar(value=cfg.SF_SECURITY_TOKEN)

        _cred_row(r1, "Username:",       self._username_var)
        _cred_row(r2, "Password:",       self._password_var, show="*")
        _cred_row(r3, "Security Token:", self._token_var,    show="*")

        self._connect_btn = tk.Button(cred_frame, text="Salesforce 연결", command=self._connect)
        self._connect_btn.pack(pady=(6, 0))
        self._conn_status = tk.Label(cred_frame, text="● 미연결", fg="red", font=("Segoe UI", 9))
        self._conn_status.pack()

        up_frame = tk.Frame(self)
        up_frame.pack(fill="x", padx=10, pady=(0, 4))
        self._upload_btn = tk.Button(up_frame, text="Salesforce 업로드", width=22, state="disabled", command=self._upload)
        self._upload_btn.pack(side="left", padx=(0, 10))
        self._progress = ttk.Progressbar(up_frame, length=340, mode="determinate")
        self._progress.pack(side="left")

        tk.Label(self, text="로그", anchor="w").pack(fill="x", padx=10)
        self._log = scrolledtext.ScrolledText(self, height=9, state="disabled", font=("Consolas", 9))
        self._log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _browse_file(self):
        path = filedialog.askopenfilename(title="Excel 파일 선택", filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")])
        if path:
            self._file_var.set(path)

    def _load_excel(self):
        path = self._file_var.get().strip()
        if not path:
            messagebox.showwarning("파일 없음", "엑셀 파일을 먼저 선택하세요.")
            return
        try:
            self._records = read_excel(path)
            self._row_label.config(text=f"✔ {len(self._records)}행 로드됨")
            self._log_write(f"[엑셀 로드 완료]\n{preview_records(self._records)}\n")
            self._refresh_upload_btn()
        except Exception as exc:
            self._log_write(f"[오류] 엑셀 읽기 실패: {exc}\n")
            messagebox.showerror("엑셀 오류", str(exc))

    def _connect(self):
        cfg.SF_USERNAME       = self._username_var.get().strip()
        cfg.SF_PASSWORD       = self._password_var.get().strip()
        cfg.SF_SECURITY_TOKEN = self._token_var.get().strip()
        self._connect_btn.config(state="disabled", text="연결 중…")
        self._log_write("[Salesforce] 연결 시도 중…\n")
        threading.Thread(target=self._do_connect, daemon=True).start()

    def _do_connect(self):
        try:
            self._connector.connect()
            self.after(0, self._on_connect_success)
        except Exception as exc:
            self.after(0, self._on_connect_fail, str(exc))

    def _on_connect_success(self):
        self._conn_status.config(text="● 연결됨", fg="green")
        self._connect_btn.config(state="normal", text="Salesforce 연결")
        self._log_write("[Salesforce] 연결 성공!\n")
        self._refresh_upload_btn()

    def _on_connect_fail(self, msg):
        self._conn_status.config(text="● 연결 실패", fg="red")
        self._connect_btn.config(state="normal", text="Salesforce 연결")
        self._log_write(f"[오류] 연결 실패: {msg}\n")
        messagebox.showerror("연결 오류", msg)

    def _upload(self):
        if not self._records:
            messagebox.showwarning("데이터 없음", "먼저 엑셀 파일을 불러오세요.")
            return
        if not self._connector.is_connected:
            messagebox.showwarning("연결 필요", "Salesforce에 먼저 연결하세요.")
            return
        self._upload_btn.config(state="disabled", text="업로드 중…")
        self._progress["value"] = 0
        self._progress["maximum"] = len(self._records)
        self._log_write(f"[업로드 시작] {len(self._records)}건 업로드 중…\n")
        threading.Thread(target=self._do_upload, daemon=True).start()

    def _do_upload(self):
        def on_progress(done, total):
            self.after(0, lambda: self._progress.config(value=done))
        try:
            success, fail, errors = self._connector.insert_records(self._records, on_progress=on_progress)
            self.after(0, self._on_upload_done, success, fail, errors)
        except Exception as exc:
            self.after(0, self._on_upload_error, str(exc))

    def _on_upload_done(self, success, fail, errors):
        self._upload_btn.config(state="normal", text="Salesforce 업로드")
        self._progress["value"] = self._progress["maximum"]
        self._log_write(f"[업로드 완료] 성공: {success}건  |  실패: {fail}건\n")
        if errors:
            self._log_write("[실패 내역]\n" + "\n".join(errors) + "\n")
        if fail == 0:
            messagebox.showinfo("완료", f"{success}건 모두 업로드 성공!")
        else:
            messagebox.showwarning("일부 실패", f"성공: {success}건\n실패: {fail}건\n\n로그 창에서 실패 내역을 확인하세요.")

    def _on_upload_error(self, msg):
        self._upload_btn.config(state="normal", text="Salesforce 업로드")
        self._log_write(f"[오류] 업로드 실패: {msg}\n")
        messagebox.showerror("업로드 오류", msg)

    def _refresh_upload_btn(self):
        if self._records and self._connector.is_connected:
            self._upload_btn.config(state="normal")

    def _log_write(self, text):
        self._log.config(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.config(state="disabled")


if __name__ == "__main__":
    app = SalesforceUploaderApp()
    app.mainloop()
