import datetime
import os
import sys
import time
from typing import Optional

import psutil
from PySide6.QtCore import QEvent, QEasingCurve, QPropertyAnimation, QRect, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class DynamicIsland(QWidget):
    """A compact always-on-top overlay for Windows 11."""

    SMALL_W, SMALL_H = 190, 44
    BIG_W, BIG_H = 410, 260
    TOP_MARGIN = 12

    def __init__(self):
        super().__init__()
        self.expanded = False
        self.page = 0
        self.start_pos = None
        self.old_net = psutil.net_io_counters()
        self.old_time = time.monotonic()
        self._nvml = None
        self._nvml_handle = None
        self._sensor_checked_at = 0.0
        self._sensor_cache = (None, None, [])

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(self._target_geometry(self.SMALL_W, self.SMALL_H))
        self.setStyleSheet("""
            QWidget { background: transparent; color: white; font-family: Segoe UI; }
            QWidget#island { background: #050505; border: 1px solid #252525; border-radius: 25px; }
            QLabel { color: white; font-size: 13px; }
            QPushButton { background: #252525; color: white; border: none; border-radius: 12px; padding: 7px 12px; }
            QPushButton:hover { background: #444444; }
            QProgressBar { background: #252525; border: none; border-radius: 4px; height: 7px; text-align: center; }
            QProgressBar::chunk { background: #30D158; border-radius: 4px; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.island = QWidget()
        self.island.setObjectName("island")
        root.addWidget(self.island)

        self.layout = QVBoxLayout(self.island)
        self.layout.setContentsMargins(18, 8, 18, 10)
        self.layout.setSpacing(7)

        header = QHBoxLayout()
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color: #30D158;")
        self.header_title = QLabel("Dynamic Island")
        self.page_number = QLabel("1 / 3")
        header.addWidget(self.dot)
        header.addWidget(self.header_title)
        header.addStretch()
        header.addWidget(self.page_number)
        self.layout.addLayout(header)

        self.pages = QStackedWidget()
        self.layout.addWidget(self.pages)
        self.create_home_page()
        self.create_pc_page()
        self.create_temp_page()

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("‹")
        self.next_btn = QPushButton("›")
        self.page_name = QLabel("Главная")
        self.prev_btn.clicked.connect(lambda: self.change_page(-1))
        self.next_btn.clicked.connect(lambda: self.change_page(1))
        nav.addWidget(self.prev_btn)
        nav.addStretch()
        nav.addWidget(self.page_name)
        nav.addStretch()
        nav.addWidget(self.next_btn)
        self.layout.addLayout(nav)

        self.animation = QPropertyAnimation(self, b"geometry", self)
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(1000)

        self.installEventFilter(self)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

        self._set_expanded_content(False)
        self.update_stats()

    @staticmethod
    def _target_geometry(width: int, height: int) -> QRect:
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        return QRect(
            area.center().x() - width // 2,
            area.top() + DynamicIsland.TOP_MARGIN,
            width,
            height,
        )

    def _set_expanded_content(self, visible: bool) -> None:
        self.pages.setVisible(visible)
        self.prev_btn.setVisible(visible)
        self.next_btn.setVisible(visible)
        self.page_name.setVisible(visible)
        self.header_title.setText("Dynamic Island" if visible else "Island")
        self.page_number.setVisible(visible)

    def create_home_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        self.clock = QLabel("--:--:--")
        self.clock.setStyleSheet("font-size: 32px; font-weight: bold;")
        self.date = QLabel("")
        self.music = QLabel("♫  Музыка не воспроизводится")
        self.music.setStyleSheet("color: #AAAAAA;")
        self.notice = QLabel("Уведомления Windows")

        layout.addWidget(self.clock)
        layout.addWidget(self.date)
        layout.addSpacing(8)
        layout.addWidget(self.music)
        layout.addWidget(self.notice)

        self.pages.addWidget(page)

    def create_pc_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        self.cpu_label = QLabel("CPU: 0%")
        self.ram_label = QLabel("RAM: 0%")
        self.disk_label = QLabel("Диск: 0%")
        self.gpu_label = QLabel("GPU: нет данных")
        self.net_label = QLabel("Сеть: 0 KB/s")

        self.cpu_bar = self.make_bar()
        self.ram_bar = self.make_bar()
        self.disk_bar = self.make_bar()
        self.gpu_bar = self.make_bar()

        for label, bar in (
            (self.cpu_label, self.cpu_bar),
            (self.ram_label, self.ram_bar),
            (self.disk_label, self.disk_bar),
            (self.gpu_label, self.gpu_bar),
        ):
            layout.addWidget(label)
            layout.addWidget(bar)

        layout.addWidget(self.net_label)
        self.pages.addWidget(page)

    def create_temp_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        title = QLabel("ТЕМПЕРАТУРЫ")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")

        self.cpu_temp = QLabel("CPU: датчик недоступен")
        self.gpu_temp = QLabel("GPU: датчик недоступен")
        self.fan_speed = QLabel("Вентиляторы: данные недоступны")

        self.sensor_info = QLabel("Для датчиков температуры запустите LibreHardwareMonitor")
        self.sensor_info.setWordWrap(True)
        self.sensor_info.setStyleSheet("color: #888888; font-size: 10px;")

        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(self.cpu_temp)
        layout.addWidget(self.gpu_temp)
        layout.addWidget(self.fan_speed)
        layout.addStretch()
        layout.addWidget(self.sensor_info)

        self.pages.addWidget(page)

    @staticmethod
    def make_bar():
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        return bar

    def animate(self, width: int, height: int):
        self.animation.stop()
        self.animation.setStartValue(self.geometry())
        self.animation.setEndValue(self._target_geometry(width, height))
        self.animation.start()

    def expand(self):
        if not self.expanded:
            self.expanded = True
            self._set_expanded_content(True)
            self.animate(self.BIG_W, self.BIG_H)

    def collapse(self):
        if self.expanded:
            self.expanded = False
            self.animate(self.SMALL_W, self.SMALL_H)
            self._set_expanded_content(False)

    def change_page(self, direction: int):
        if not self.expanded:
            self.expand()

        self.page = (self.page + direction) % 3
        self.pages.setCurrentIndex(self.page)

        names = ["Главная", "Мониторинг ПК", "Температуры"]
        self.page_name.setText(names[self.page])
        self.page_number.setText(f"{self.page + 1} / 3")

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and self.expanded:
            if event.angleDelta().y():
                self.change_page(-1 if event.angleDelta().y() > 0 else 1)
                return True

        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

        elif event.type() == QEvent.Type.MouseButtonRelease and self.start_pos is not None:
            end_pos = event.globalPosition().toPoint()
            delta = end_pos - self.start_pos
            self.start_pos = None

            if abs(delta.x()) > 65 and self.expanded:
                self.change_page(-1 if delta.x() > 0 else 1)
            elif abs(delta.x()) < 8 and abs(delta.y()) < 8 and not isinstance(obj, QPushButton):
                if self.expanded:
                    self.collapse()
                else:
                    self.expand()

        return super().eventFilter(obj, event)

    def _init_nvml(self) -> bool:
        if self._nvml_handle is not None:
            return True
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml = pynvml
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            return True
        except Exception:
            self._nvml = None
            self._nvml_handle = None
            return False

    def get_temps(self):
        now = time.monotonic()
        if now - self._sensor_checked_at < 5:
            return self._sensor_cache

        self._sensor_checked_at = now
        cpu: Optional[float] = None
        gpu: Optional[float] = None
        fans = []

        try:
            import wmi
            hardware = wmi.WMI(namespace=r"root\LibreHardwareMonitor")
            for sensor in hardware.Sensor():
                if sensor.SensorType == "Temperature":
                    name = sensor.Name.lower()
                    if "cpu" in name and cpu is None:
                        cpu = float(sensor.Value)
                    elif "gpu" in name and gpu is None:
                        gpu = float(sensor.Value)
                elif sensor.SensorType == "Fan":
                    fans.append(f"{float(sensor.Value):.0f} RPM")
        except Exception:
            pass

        if gpu is None and self._init_nvml():
            try:
                gpu = float(self._nvml.nvmlDeviceGetTemperature(
                    self._nvml_handle, self._nvml.NVML_TEMPERATURE_GPU
                ))
            except Exception:
                pass

        self._sensor_cache = cpu, gpu, fans
        return self._sensor_cache

    def update_stats(self):
        now = datetime.datetime.now()
        self.clock.setText(now.strftime("%H:%M:%S"))
        self.date.setText(now.strftime("%d.%m.%Y"))

        cpu = psutil.cpu_percent()
        self.cpu_label.setText(f"CPU: {cpu:.0f}%")
        self.cpu_bar.setValue(int(cpu))

        ram = psutil.virtual_memory().percent
        self.ram_label.setText(f"RAM: {ram:.0f}%")
        self.ram_bar.setValue(int(ram))

        try:
            drive = os.getenv("SystemDrive", "C:") + "\\"
            disk = psutil.disk_usage(drive).percent
            self.disk_label.setText(f"Диск: {disk:.0f}%")
            self.disk_bar.setValue(int(disk))
        except (OSError, ValueError):
            self.disk_label.setText("Диск: нет данных")
            self.disk_bar.setValue(0)

        current = psutil.net_io_counters()
        elapsed = max(time.monotonic() - self.old_time, 0.001)
        speed = (
            max(0, current.bytes_sent + current.bytes_recv - self.old_net.bytes_sent - self.old_net.bytes_recv)
            / elapsed / 1024
        )
        self.net_label.setText(f"Сеть: {speed:.1f} KB/s")
        self.old_net = current
        self.old_time = time.monotonic()

        if self._init_nvml():
            try:
                usage = self._nvml.nvmlDeviceGetUtilizationRates(self._nvml_handle).gpu
                self.gpu_label.setText(f"GPU: {usage}%")
                self.gpu_bar.setValue(usage)
            except Exception:
                self.gpu_label.setText("GPU: нет данных")
                self.gpu_bar.setValue(0)
        else:
            self.gpu_label.setText("GPU: нет данных")
            self.gpu_bar.setValue(0)

        cpu_temp, gpu_temp, fans = self.get_temps()
        self.cpu_temp.setText(
            f"CPU: {cpu_temp:.0f} °C" if cpu_temp is not None else "CPU: датчик недоступен"
        )
        self.gpu_temp.setText(
            f"GPU: {gpu_temp:.0f} °C" if gpu_temp is not None else "GPU: датчик недоступен"
        )
        self.fan_speed.setText(
            "Вентиляторы: " + ", ".join(fans) if fans else "Вентиляторы: данные недоступны"
        )

    def enterEvent(self, event):
        self.expand()
        super().enterEvent(event)

    def leaveEvent(self, event):
        QTimer.singleShot(1200, self.check_collapse)
        super().leaveEvent(event)

    def check_collapse(self):
        if not self.underMouse():
            self.collapse()

    def closeEvent(self, event):
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Dynamic Island for Windows")
    island = DynamicIsland()
    island.show()
    sys.exit(app.exec())
