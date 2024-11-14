import sys
import subprocess
import pyudev
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QComboBox, QLabel, QFileDialog, \
    QMessageBox, QProgressBar, QRadioButton
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QPainter, QColor


class ProgressBarWithText(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(self.font())

        progress_text = f"{self.value()}%"
        text_width = painter.fontMetrics().width(progress_text)

        x_position = (self.width() - text_width) // 2
        y_position = self.height() // 2 + 5

        painter.drawText(x_position, y_position, progress_text)


class UsbWriter(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle('Sufur - ISO to USB')
        self.setGeometry(100, 100, 500, 350)

        self.layout = QVBoxLayout()

        self.label = QLabel("Выберите флешку:", self)
        self.layout.addWidget(self.label)

        self.combo_box = QComboBox(self)
        self.layout.addWidget(self.combo_box)

        self.select_iso_button = QPushButton("Выбрать ISO файл", self)
        self.select_iso_button.clicked.connect(self.select_iso_file)
        self.layout.addWidget(self.select_iso_button)

        self.iso_label = QLabel("Не выбран ISO файл", self)
        self.layout.addWidget(self.iso_label)

        self.label_type = QLabel("Тип записи:", self)
        self.layout.addWidget(self.label_type)

        self.radio_clean = QRadioButton("Чистая запись (форматировать)", self)
        self.radio_clean.setChecked(True)
        self.layout.addWidget(self.radio_clean)

        self.radio_append = QRadioButton("Записать на существующие данные", self)
        self.layout.addWidget(self.radio_append)

        self.progress_bar = ProgressBarWithText(self)
        self.progress_bar.setRange(0, 100)
        self.layout.addWidget(self.progress_bar)

        self.start_button = QPushButton("Начать запись", self)
        self.start_button.clicked.connect(self.start_recording)
        self.layout.addWidget(self.start_button)

        self.setLayout(self.layout)

        self.iso_path = ""
        self.device = ""

        self.populate_devices()

        self.monitor_thread = MonitorThread(self.populate_devices)
        self.monitor_thread.start()

    def populate_devices(self):
        devices = self.get_usb_devices()
        self.combo_box.clear()

        if devices:
            self.combo_box.addItems(devices)
        else:
            self.combo_box.addItem("Не найдена флешка. Подключите флешку.")

    def get_usb_devices(self):
        devices = []
        context = pyudev.Context()
        for device in context.list_devices(subsystem='block'):
            if device.get('ID_BUS') == 'usb' and device.get ('ID_TYPE') == 'disk':
                devices.append(device.device_node)
        return devices

    def select_iso_file(self):
        iso_file, _ = QFileDialog.getOpenFileName(self, 'Выберите ISO файл', '', 'ISO Files (*.iso)')
        if iso_file:
            self.iso_path = iso_file
            self.iso_label.setText(f"Выбран ISO файл: {iso_file.split('/')[-1]}")

    def start_recording(self):
        self.device = self.combo_box.currentText()
        if self.device == "Не найдена флешка. Подключите флешку.":
            self.show_error_message("Ошибка", "Пожалуйста, подключите флешку.")
            return

        if not self.iso_path:
            self.show_error_message("Ошибка", "Пожалуйста, выберите ISO файл.")
            return

        confirmation = QMessageBox.question(self, 'Подтверждение',
                                            f"Вы уверены, что хотите записать ISO файл на флешку {self.device}?",
                                            QMessageBox.Yes | QMessageBox.No)

        if confirmation == QMessageBox.Yes:
            self.format_device(self.device)

    def format_device(self, device):
        if self.radio_clean.isChecked():
            self.show_confirmation_format(device)

    def show_confirmation_format(self, device):
        confirmation = QMessageBox.question(self, 'Подтверждение форматирования',
                                            f"Вы уверены, что хотите отформатировать флешку {device}?",
                                            QMessageBox.Yes | QMessageBox.No)

        if confirmation == QMessageBox.Yes:
            self.write_to_device(device)

    def write_to_device(self, device):
        self.worker = WriteWorker(device, self.iso_path, self.progress_bar)
        self.worker.write_finished.connect(self.show_success_message)
        self.worker.start()

    def show_error_message(self, title, message):
        QMessageBox.critical(self, title, message)

    def show_success_message(self):
        QMessageBox.information(self, 'Готово', 'Запись на флешку завершена успешно!')


class WriteWorker(QThread):
    write_finished = pyqtSignal()

    def __init__(self, device, iso_path, progress_bar):
        super().__init__()
        self.device = device
        self.iso_path = iso_path
        self.progress_bar = progress_bar

    def run(self):
        self.format_device()
        self.write_iso()

    def format_device(self):
        subprocess.run(['sudo', 'mkfs.vfat', '-I', self.device])

    def write_iso(self):
        command = f"sudo dd if={self.iso_path} of={self.device} bs=4M status=progress"
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        while process.poll() is None:
            line = process.stdout.readline()
            if line:
                if b'%' in line:
                    parts = line.split()
                    progress = int(parts[-1].decode('utf-8').strip('%'))
                    self.progress_bar.setValue(progress)

        self.write_finished.emit()


class MonitorThread(QThread):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def run(self):
        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem='block')

        for device in monitor:
            try:
                if isinstance(device, pyudev.Device):
                    if device.action == 'add':
                        if 'usb' in device.get('ID_BUS', ''):
                            self.callback()
                    elif device.action == 'remove':
                        if 'usb' in device.get('ID_BUS', ''):
                            self.callback()
            except Exception as e:
                print(f"Ошибка при мониторинге устройства: {e}")
                continue


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = UsbWriter()
    window.show()
    sys.exit(app.exec_())