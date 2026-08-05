import sys
import os
import time
from PySide6.QtCore import QObject, Signal, Slot, QTimer, Qt
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction

from pynput import keyboard as pynput_keyboard

import database
import config
from recorder import RecorderThread
from transcriber import TranscriberThread, ClipboardCorrectionLearner, paste_text
from widgets import CapsuleWidget, SettingsWindow


class GlobalHotkeyListener(QObject):
    start_recording = Signal()
    stop_recording = Signal()

    def __init__(self):
        super().__init__()
        self.active_keys = set()
        self.is_recording = False
        self.listener = None

    def start(self):
        self.listener = pynput_keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release
        )
        self.listener.start()

    def stop(self):
        if self.listener:
            self.listener.stop()

    def on_press(self, key):
        try:
            # Normalize keys
            # Win key can be Key.cmd, Key.cmd_l, Key.cmd_r
            # Ctrl key can be Key.ctrl, Key.ctrl_l, Key.ctrl_r
            is_ctrl = key in (pynput_keyboard.Key.ctrl, pynput_keyboard.Key.ctrl_l, pynput_keyboard.Key.ctrl_r)
            is_win = key in (pynput_keyboard.Key.cmd, pynput_keyboard.Key.cmd_l, pynput_keyboard.Key.cmd_r)

            if is_ctrl:
                self.active_keys.add('ctrl')
            elif is_win:
                self.active_keys.add('win')

            if 'ctrl' in self.active_keys and 'win' in self.active_keys:
                if not self.is_recording:
                    self.is_recording = True
                    self.start_recording.emit()
        except Exception as e:
            print(f"Hotkey press hook error: {e}")

    def on_release(self, key):
        try:
            is_ctrl = key in (pynput_keyboard.Key.ctrl, pynput_keyboard.Key.ctrl_l, pynput_keyboard.Key.ctrl_r)
            is_win = key in (pynput_keyboard.Key.cmd, pynput_keyboard.Key.cmd_l, pynput_keyboard.Key.cmd_r)

            if is_ctrl:
                self.active_keys.discard('ctrl')
            elif is_win:
                self.active_keys.discard('win')

            if self.is_recording:
                # Release triggers transcription when either key is let go
                if 'ctrl' not in self.active_keys or 'win' not in self.active_keys:
                    self.is_recording = False
                    self.stop_recording.emit()
        except Exception as e:
            print(f"Hotkey release hook error: {e}")


class VoiceFlowApp(QObject):
    def __init__(self, app_instance):
        super().__init__()
        self.app = app_instance
        
        # Ensure database is active
        database.init_db()

        # Instantiate UI Windows
        self.settings_window = SettingsWindow()
        self.capsule = CapsuleWidget(self.settings_window)

        # Thread containers
        self.recorder_thread = None
        self.transcriber_thread = None

        # Instantiate & configure reinforcement learning engine
        self.learner = ClipboardCorrectionLearner()
        self.learner.start_monitoring()
        self.learner.correction_learned.connect(self.on_correction_learned)

        # Global Hotkey Listener
        self.hotkey_listener = GlobalHotkeyListener()
        self.hotkey_listener.start_recording.connect(self.on_start_recording)
        self.hotkey_listener.stop_recording.connect(self.on_stop_recording)
        self.hotkey_listener.start()

        # System Tray Integration
        self.setup_tray()

        # Show UI elements on startup
        self.capsule.show()
        self.settings_window.show()

        # Connect theme changes to keep UI components synchronized
        self.settings_window.theme_changed.connect(self.on_theme_changed)

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        
        # Load rounded icon from path if exists
        if os.path.exists(config.LOGO_PATH):
            # Load and scale to small tray icon size
            from widgets import get_rounded_pixmap
            rounded_px = get_rounded_pixmap(config.LOGO_PATH, size=24, radius=4)
            self.tray_icon.setIcon(QIcon(rounded_px))
        else:
            self.tray_icon.setIcon(QIcon())
            
        self.tray_icon.setToolTip("Voice Flow")

        # Tray Menu
        self.tray_menu = QMenu()
        
        open_action = QAction("Open Voice Flow Settings", self)
        open_action.triggered.connect(self.show_settings)
        self.tray_menu.addAction(open_action)
        
        self.tray_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.exit_app)
        self.tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()
        
        # Open settings window on clicking tray icon
        self.tray_icon.activated.connect(self.on_tray_activated)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.show_settings()

    def show_settings(self):
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def on_theme_changed(self, new_theme):
        # Redraw capsule with updated color styling
        self.capsule.update()

    @Slot()
    def on_start_recording(self):
        if self.capsule.state != "idle":
            return
            
        print("Starting recording...")
        self.capsule.set_state("recording")

        # Setup recording thread
        self.recorder_thread = RecorderThread()
        self.recorder_thread.audio_level.connect(self.capsule.update_audio_level)
        self.recorder_thread.recording_finished.connect(self.on_recording_finished)
        self.recorder_thread.recording_error.connect(self.on_recording_error)
        self.recorder_thread.start()

    @Slot()
    def on_stop_recording(self):
        if self.capsule.state != "recording" or not self.recorder_thread:
            return

        print("Stopping recording...")
        self.capsule.set_state("transcribing", "Processing...")
        self.recorder_thread.stop()

    @Slot(str)
    def on_recording_finished(self, wav_path):
        print(f"Recording saved, initiating transcription on {wav_path}...")
        self.capsule.set_state("transcribing", "Transcribing...")
        
        # Setup transcription worker thread
        self.transcriber_thread = TranscriberThread(wav_path)
        self.transcriber_thread.finished.connect(self.on_transcription_finished)
        self.transcriber_thread.error.connect(self.on_transcription_error)
        self.transcriber_thread.start()

    @Slot(str)
    def on_recording_error(self, error_msg):
        print(f"Recorder error: {error_msg}")
        self.capsule.set_state("error", error_msg)
        QTimer.singleShot(2000, lambda: self.capsule.set_state("idle"))

    @Slot(str, str)
    def on_transcription_finished(self, raw_text, corrected_text):
        print(f"Transcribed Raw: {raw_text} | Corrected: {corrected_text}")
        
        # Save transcription to local history database
        history_id = database.add_history_entry(raw_text, corrected_text)
        
        # Paste text into focused window
        paste_text(corrected_text)
        
        # Register paste metadata to listen for clipboard corrections (Reinforcement learning)
        self.learner.register_paste(history_id, corrected_text)

        # Update capsule to success state
        self.capsule.set_state("success", "Copied & Pasted!")
        QTimer.singleShot(1500, lambda: self.capsule.set_state("idle"))
        
        # Refresh history listing in settings GUI
        self.settings_window.refresh_history()

    @Slot(str)
    def on_transcription_error(self, error_msg):
        print(f"Transcriber error: {error_msg}")
        self.capsule.set_state("error", error_msg)
        QTimer.singleShot(2000, lambda: self.capsule.set_state("idle"))

    @Slot(str, str)
    def on_correction_learned(self, original, corrected):
        print(f"Reinforcement Learning: Learned mapping correction \"{original}\" -> \"{corrected}\"")
        # Visual notification in the capsule widget
        self.capsule.set_state("success", f"Learned: {original} → {corrected}")
        QTimer.singleShot(3000, lambda: self.capsule.set_state("idle"))
        
        # Refresh widgets to display newly added dictionary correction rules
        self.settings_window.refresh_dictionary()

    def exit_app(self):
        print("Shutting down Voice Flow...")
        self.hotkey_listener.stop()
        self.tray_icon.hide()
        self.app.quit()


def main():
    # Register Windows AppUserModelID so Windows Taskbar displays custom Voice Flow logo instead of python.exe icon
    if sys.platform == "win32":
        try:
            import ctypes
            myappid = "voiceflow.typist.app.1.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    # Fix High DPI scaling issues on Windows
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    
    # Set application-wide icon for taskbar with curved edges
    if os.path.exists(config.LOGO_PATH):
        from widgets import get_app_icon
        app.setWindowIcon(get_app_icon(config.LOGO_PATH))

    app.setQuitOnLastWindowClosed(False) # Keep running when SettingsWindow is closed
    
    flow_app = VoiceFlowApp(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
