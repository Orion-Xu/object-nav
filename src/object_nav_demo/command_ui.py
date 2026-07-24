from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, simpledialog, ttk
import importlib.util
from pathlib import Path
import threading
import time

from .app_factory import build_offline_demo
from .camera_protocol import PercipioRgbdSource
from .command_parser import CommandParser
from .config import default_config
from .config import PROJECT_ROOT
from .config import load_yaml
from .realtime_detection import ConsecutiveLabelConfirmer, OpenCvLatestFrameSource
from .vocabulary_manager import VocabularyManager


class CommandUI:
    """Request/validation UI only; it has no navigation or velocity interface."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.vocabulary = VocabularyManager(default_config("vocabulary.yaml"))
        self.parser = CommandParser(self.vocabulary)
        self.supported = {item.canonical_label for item in self.vocabulary.policies}
        self.prompt_to_policy = {item.prompt_en: item for item in self.vocabulary.policies}
        self.system = load_yaml(default_config("system.yaml"))
        self.active_machine = None
        self._model = None
        self._model_lock = threading.Lock()
        self._realtime_source = None
        self._realtime_stop = None
        self._realtime_thread = None
        self._realtime_confirmer = ConsecutiveLabelConfirmer(
            int(self.system["search"]["confirmation_frames"])
        )
        root.title("GM461-E1 可见目标检测与短距离局部导航 Demo")
        root.geometry("980x720")
        root.columnconfigure(0, weight=1)
        ttk.Label(root, text="输入受控指令（例如：帮我找椅子）").grid(row=0, column=0, sticky="w", padx=12, pady=8)
        self.entry = ttk.Entry(root, width=52)
        self.entry.grid(row=1, column=0, sticky="ew", padx=12)
        actions = ttk.Frame(root)
        actions.grid(row=2, column=0, sticky="w", padx=12, pady=8)
        ttk.Button(actions, text="只解析", command=self.submit).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="运行 Mock 离线闭环", command=self.run_offline).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="用 YOLO-World 检测图片", command=self.choose_real_image).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="实时摄像头", command=self.start_camera).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="GM461 RGB-D", command=self.start_percipio).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="实时视频", command=self.choose_video).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="停止/复位", command=self.stop).pack(side="left")
        model_ready = (PROJECT_ROOT / "models" / "yolov8s-worldv2-objectnav.pt").is_file()
        package_ready = importlib.util.find_spec("ultralytics") is not None
        backend_text = ("检测后端：YOLO-World GPU 已就绪（图片/实时模式按需加载）" if model_ready and package_ready
                        else "检测后端：fake-detector-v1（YOLO-World 环境或权重未就绪）")
        self.backend = tk.StringVar(value=backend_text)
        ttk.Label(root, textvariable=self.backend, foreground="#9a5b00").grid(row=3, column=0, sticky="w", padx=12)
        self.status = tk.StringVar(value="IDLE | 无全局地图；当前仅连接 Mock RGB-D 和 Mock 局部导航")
        ttk.Label(root, textvariable=self.status, wraplength=720).grid(row=4, column=0, sticky="w", padx=12, pady=(6, 0))
        supported = "；".join(f"{p.aliases_zh[0]}({p.navigation_mode.value})" for p in self.vocabulary.policies)
        ttk.Label(root, text="支持列表：" + supported, wraplength=720).grid(row=5, column=0, sticky="w", padx=12, pady=12)
        ttk.Label(root, text="安全说明：本窗口不会发布 /cmd_vel；离线闭环只移动 MockNavigationAdapter。",
                  foreground="#555555").grid(row=6, column=0, sticky="w", padx=12)
        self.preview = ttk.Label(root, text="图片检测结果将在这里显示", anchor="center")
        self.preview.grid(row=7, column=0, sticky="nsew", padx=12, pady=12)
        root.rowconfigure(7, weight=1)
        self._preview_image = None
        root.protocol("WM_DELETE_WINDOW", self.close)

    def submit(self) -> None:
        result = self.parser.parse(self.entry.get(), self.supported)
        if result.accepted and result.policy:
            self.status.set(f"PARSE OK | {result.policy.canonical_label} | {result.policy.navigation_mode.value} | 词表 {result.vocabulary_version}")
        else:
            self.status.set("FAILED | " + str(result.reason))

    def run_offline(self) -> None:
        result = self.parser.parse(self.entry.get(), self.supported)
        if not result.accepted or result.policy is None:
            self.status.set("FAILED | " + str(result.reason))
            return
        self.status.set("RUNNING | 当前视野 → 三帧确认 → 滚动局部障碍 → Mock 短距离导航")
        self.root.update_idletasks()
        self.active_machine = build_offline_demo(result.policy.canonical_label, "logs/gui_demo.jsonl")
        state = self.active_machine.run(self.entry.get())
        reason = self.active_machine.failure_reason
        self.status.set(f"{state.value} | {'离线闭环完成' if reason is None else reason} | 日志 logs/gui_demo.jsonl")

    def choose_real_image(self) -> None:
        path = filedialog.askopenfilename(
            title="选择本地测试图片",
            filetypes=(("图片", "*.jpg *.jpeg *.png *.bmp"), ("所有文件", "*.*")),
        )
        if not path:
            return
        model_path = PROJECT_ROOT / "models" / "yolov8s-worldv2-objectnav.pt"
        if not model_path.is_file():
            self.status.set("FAILED | YOLO-World 离线词表权重尚未准备")
            return
        self.status.set("RUNNING | 正在用 YOLO-World GPU 检测本地图片……")
        threading.Thread(target=self._real_image_worker, args=(Path(path), model_path), daemon=True).start()

    def _real_image_worker(self, image_path: Path, model_path: Path) -> None:
        try:
            model, device = self._load_model(model_path)
            with self._model_lock:
                results = model.predict(str(image_path), device=device, verbose=False)
            found = []
            for result in results:
                for box in result.boxes:
                    label = str(result.names[int(box.cls.item())])
                    found.append(f"{label}:{float(box.conf.item()):.2f}")
            plotted_bgr = results[0].plot() if results else None
            message = "YOLO-WORLD OK | " + ("，".join(found[:8]) if found else "未检测到配置目标")
            self.root.after(0, lambda: self._show_detection_result(message, plotted_bgr))
            self.root.after(0, lambda: self.backend.set(f"检测后端：YOLO-World {device}（真实模型）"))
        except Exception as exc:
            message = f"FAILED | YOLO-World: {exc}"
            self.root.after(0, lambda value=message: self.status.set(value))

    def _load_model(self, model_path: Path):
        with self._model_lock:
            if self._model is None:
                import torch
                from ultralytics import YOLOWorld
                self._model = YOLOWorld(str(model_path))
                self._model.set_classes([
                    policy.prompt_en for policy in self.vocabulary.policies
                ])
                self._model_device = 0 if torch.cuda.is_available() else "cpu"
            return self._model, self._model_device

    def start_camera(self) -> None:
        default_index = int(self.system.get("realtime_detection", {}).get("camera_index", 0))
        index = simpledialog.askinteger("实时摄像头", "OpenCV 摄像头编号：", initialvalue=default_index,
                                        minvalue=0, parent=self.root)
        if index is not None:
            self._start_realtime(index, f"摄像头 {index}")

    def start_percipio(self) -> None:
        settings = self.system.get("camera", {}).get("bridge", {})
        source = PercipioRgbdSource(
            str(settings.get("host", "127.0.0.1")),
            int(settings.get("port", 18765)),
        )
        self._start_realtime_source(source, "GM461 RGB-D")

    def choose_video(self) -> None:
        path = filedialog.askopenfilename(
            title="选择实时检测视频",
            filetypes=(("视频", "*.mp4 *.avi *.mov *.mkv *.mjpeg"), ("所有文件", "*.*")),
        )
        if path:
            self._start_realtime(path, Path(path).name)

    def _start_realtime(self, source: int | str, source_name: str) -> None:
        self._start_realtime_source(OpenCvLatestFrameSource(source), source_name)

    def _start_realtime_source(self, capture, source_name: str) -> None:
        model_path = PROJECT_ROOT / "models" / "yolov8s-worldv2-objectnav.pt"
        if not model_path.is_file():
            self.status.set("FAILED | YOLO-World 离线词表权重尚未准备")
            return
        self._stop_realtime(update_status=False)
        try:
            capture.start()
        except Exception as exc:
            self.status.set(f"FAILED | {exc}")
            return
        self._realtime_source = capture
        stop_event = threading.Event()
        self._realtime_stop = stop_event
        self._realtime_confirmer.reset()
        self.status.set(f"LOADING | {source_name} | 正在加载 YOLO-World……")
        self._realtime_thread = threading.Thread(
            target=self._realtime_worker,
            args=(capture, model_path, source_name, stop_event),
            daemon=True,
            name="yolo-world-realtime",
        )
        self._realtime_thread.start()

    def _realtime_worker(self, capture, model_path: Path, source_name: str,
                         stop_event: threading.Event) -> None:
        try:
            model, device = self._load_model(model_path)
            settings = self.system.get("realtime_detection", {})
            confidence = float(settings.get("confidence", 0.25))
            image_size = int(settings.get("image_size", 640))
            last_sequence = 0
            while not stop_event.is_set():
                captured = capture.latest_after(last_sequence)
                if captured is None:
                    if capture.finished:
                        message = capture.error or "数据源已结束"
                        self.root.after(0, lambda value=message: self.status.set(f"STOPPED | {value}"))
                        break
                    stop_event.wait(0.01)
                    continue
                last_sequence = captured.sequence
                started = time.perf_counter()
                with self._model_lock:
                    result = model.predict(
                        captured.bgr, device=device, imgsz=image_size,
                        conf=confidence, verbose=False,
                    )[0]
                if stop_event.is_set():
                    break
                inference_s = max(time.perf_counter() - started, 1e-6)
                labels = []
                for box in result.boxes:
                    label = str(result.names[int(box.cls.item())])
                    labels.append((label, float(box.conf.item())))
                target_message = self._target_confirmation_message(labels)
                latency_ms = max(0.0, (time.time() - captured.captured_at) * 1000.0)
                found = "，".join(f"{label}:{score:.2f}" for label, score in labels[:6]) or "无目标"
                message = (
                    f"LIVE | {source_name} | {1.0 / inference_s:.1f} FPS | 延迟 {latency_ms:.0f} ms | "
                    f"{found}{target_message}"
                )
                plotted = result.plot()
                self.root.after(0, lambda value=message, frame=plotted: self._show_detection_result(value, frame))
                self.root.after(0, lambda value=device: self.backend.set(
                    f"检测后端：YOLO-World {value} | 实时模式（仅保留最新帧）"
                ))
        except Exception as exc:
            message = f"FAILED | 实时 YOLO-World: {type(exc).__name__}: {exc}"
            self.root.after(0, lambda value=message: self.status.set(value))
        finally:
            capture.stop()

    def _target_confirmation_message(self, labels: list[tuple[str, float]]) -> str:
        parsed = self.parser.parse(self.entry.get(), self.supported)
        if not parsed.accepted or parsed.policy is None:
            self._realtime_confirmer.reset()
            return " | 未设置有效指令，仅显示检测"
        policy = parsed.policy
        present = any(label == policy.prompt_en and score >= policy.min_confidence for label, score in labels)
        confirmed = self._realtime_confirmer.observe(present)
        state = "CONFIRMED" if confirmed else f"{self._realtime_confirmer.count}/{self._realtime_confirmer.required_frames}"
        return f" | 目标 {policy.canonical_label}：{state}（仅检测，不导航）"

    def _show_detection_result(self, message: str, plotted_bgr) -> None:
        self.status.set(message)
        if plotted_bgr is None:
            return
        from PIL import Image, ImageTk
        image = Image.fromarray(plotted_bgr[:, :, ::-1])
        image.thumbnail((940, 430))
        self._preview_image = ImageTk.PhotoImage(image)
        self.preview.configure(image=self._preview_image, text="")

    def stop(self) -> None:
        self._stop_realtime(update_status=False)
        if self.active_machine is not None:
            self.active_machine.navigation.request_stop("GUI 停止/复位请求")
            self.active_machine.reset()
        self.status.set("IDLE | 已停止并复位；本界面未连接真实底盘")

    def _stop_realtime(self, update_status: bool = True) -> None:
        stop_event = self._realtime_stop
        self._realtime_stop = None
        if stop_event is not None:
            stop_event.set()
        source = self._realtime_source
        self._realtime_source = None
        if source is not None:
            source.stop()
        self._realtime_confirmer.reset()
        if update_status:
            self.status.set("IDLE | 实时检测已停止")

    def close(self) -> None:
        self._stop_realtime(update_status=False)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    CommandUI(root)
    root.mainloop()
