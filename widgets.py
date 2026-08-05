import sys
import os
import math
from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QPropertyAnimation, QEasingCurve, Signal, Slot
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QIcon, QPixmap, QPainterPath, QLinearGradient, QRadialGradient
from PySide6.QtWidgets import (QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTabWidget, QListWidget, QListWidgetItem, 
                             QLineEdit, QDialog, QMessageBox, QSlider, QFrame, 
                             QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QApplication, QStackedWidget, QScrollArea)

import database
from config import ORANGE, DARK_BG, DARK_CARD, DARK_TEXT, DARK_BORDER, LIGHT_BG, LIGHT_CARD, LIGHT_TEXT, LIGHT_BORDER, LOGO_PATH

def get_rounded_pixmap(image_path, size=80, radius=12, padding=6):
    pixmap = QPixmap(image_path)
    if pixmap.isNull():
        target = QPixmap(size, size)
        target.fill(Qt.transparent)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor(ORANGE))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, size, size, radius, radius)
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Arial", int(size * 0.4), QFont.Bold))
        painter.drawText(target.rect(), Qt.AlignCenter, "VF")
        painter.end()
        return target
        
    target = QPixmap(size, size)
    target.fill(Qt.transparent)
    
    painter = QPainter(target)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    
    card_rect = target.rect().adjusted(2, 2, -2, -3)
    
    # 1. Outer Deep Shadow under card
    shadow_path = QPainterPath()
    shadow_path.addRoundedRect(target.rect().adjusted(2, 4, -2, -1), radius, radius)
    painter.fillPath(shadow_path, QBrush(QColor(0, 0, 0, 110)))
    
    # 2. Glowing Orange Backlight Halo
    radial_glow = QRadialGradient(size / 2.0, size / 2.0, size * 0.55)
    radial_glow.setColorAt(0.0, QColor(255, 102, 0, 160))
    radial_glow.setColorAt(0.6, QColor(255, 102, 0, 50))
    radial_glow.setColorAt(1.0, QColor(255, 102, 0, 0))
    painter.setBrush(QBrush(radial_glow))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(target.rect().adjusted(2, 2, -2, -2))
    
    # 3. Main Glass/White Card Base with 3D gradient
    card_path = QPainterPath()
    card_path.addRoundedRect(card_rect, radius, radius)
    
    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0.0, QColor("#FFFFFF"))
    grad.setColorAt(0.85, QColor("#F4F4F9"))
    grad.setColorAt(1.0, QColor("#E4E4EC"))
    
    painter.fillPath(card_path, QBrush(grad))
    
    # 4. 3D Metallic Rim Highlight & Inner Shadow
    pen = QPen(QColor(255, 255, 255, 240), 1.2)
    painter.setPen(pen)
    painter.drawRoundedRect(card_rect, radius, radius)
    
    bevel_pen = QPen(QColor(0, 0, 0, 35), 1.0)
    painter.setPen(bevel_pen)
    painter.drawRoundedRect(card_rect.adjusted(0, 0, 0, -1), radius, radius)
    
    # 5. Scale, Clip to Curved Edges, and Center Microphone Logo Image
    inner_size = size - 2 * padding
    scaled_logo = pixmap.scaled(inner_size, inner_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    x = (size - scaled_logo.width()) // 2
    y = (size - scaled_logo.height()) // 2
    
    # Clip path to give the logo image itself smooth curved edges
    logo_path = QPainterPath()
    logo_radius = max(4, int(radius * 0.75))
    logo_path.addRoundedRect(x, y, scaled_logo.width(), scaled_logo.height(), logo_radius, logo_radius)
    
    painter.save()
    painter.setClipPath(logo_path)
    painter.drawPixmap(x, y, scaled_logo)
    painter.restore()
    
    painter.end()
    return target


def get_app_icon(image_path):
    """
    Generates a high-res curved-edge application icon for Windows Taskbar and system windows.
    """
    if not image_path or not os.path.exists(image_path):
        return QIcon()
    pixmap = get_rounded_pixmap(image_path, size=256, radius=52, padding=16)
    return QIcon(pixmap)


class CapsuleWidget(QWidget):
    def __init__(self, settings_window=None):
        super().__init__()
        self.settings_window = settings_window
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.Tool |
            Qt.WindowDoesNotAcceptFocus |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        # State: "idle", "recording", "transcribing", "success", "error"
        self.state = "idle"
        self.status_text = ""
        
        # Animations
        self.pulse_val = 0.0
        self.pulse_dir = 1
        
        self.loading_angle = 0
        self.idle_angle = 0
        self.success_frame = 0
        self.error_frame = 0
        self.shake_offset = QPoint(0, 0)
        
        self.audio_history = [0.0] * 12  # Audio level bars
        
        # Idle Transparency timer
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self.fade_to_idle)
        self.idle_timeout_ms = database.get_setting("idle_timeout", 5000)
        self.is_idle = False
        
        # Pulse timer for animations
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.update_animation)
        self.anim_timer.start(30)
        
        # Hover effect
        self.setMouseTracking(True)
        
        # Window size properties (perfectly compact circle!)
        self.normal_width = 46
        self.normal_height = 46
        self.expanded_width = 46
        self.expanded_height = 46
        
        self.resize(self.normal_width, self.normal_height)
        self.center_on_screen()
        
        # Restart idle timer
        self.reset_idle_timer()

    def enterEvent(self, event):
        self.reset_idle()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.reset_idle_timer()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Open main app window on double click
            if self.settings_window:
                self.settings_window.show()
                self.settings_window.raise_()
                self.settings_window.activateWindow()
            event.accept()

    def center_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        w = self.width()
        h = self.height()
        # Bottom center, 70px from the screen bottom
        self.move((screen.width() - w) // 2, screen.height() - h - 70)

    def set_state(self, state, text=""):
        self.state = state
        self.status_text = text
        self.reset_idle()
        
        if state == "success":
            self.success_frame = 0
        elif state == "error":
            self.error_frame = 0
            
        # Bouncy organic resize transitions
        if state == "recording":
            self.animate_size(52, 52)
        elif state == "transcribing":
            self.animate_size(50, 50)
        elif state == "success":
            self.animate_size(54, 54)
        elif state == "error":
            self.animate_size(48, 48)
        else:
            self.animate_size(46, 46)
            self.reset_idle_timer()
            
        self.update()

    def animate_size(self, target_w, target_h):
        # We need to maintain center alignment while resizing
        self.target_size = QSize(target_w, target_h)
        curr_geometry = self.geometry()
        curr_center = curr_geometry.center()
        
        self.size_anim = QPropertyAnimation(self, b"size")
        self.size_anim.setDuration(180)
        self.size_anim.setStartValue(self.size())
        self.size_anim.setEndValue(self.target_size)
        self.size_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        # Adjust position during animation to keep it centered
        def on_value_changed(value):
            new_w = value.width()
            new_h = value.height()
            self.move(curr_center.x() - new_w // 2, curr_center.y() - new_h // 2)
            
        self.size_anim.valueChanged.connect(on_value_changed)
        self.size_anim.start()

    def update_audio_level(self, level):
        # Shift history
        self.audio_history.pop(0)
        # Normalize and store level
        self.audio_history.append(min(1.0, level * 10.0))
        self.update()

    def update_animation(self):
        # Breathe pulse
        self.pulse_val += 0.05 * self.pulse_dir
        if self.pulse_val >= 1.0:
            self.pulse_val = 1.0
            self.pulse_dir = -1
        elif self.pulse_val <= 0.0:
            self.pulse_val = 0.0
            self.pulse_dir = 1
            
        # Spin idle/transcribing
        self.idle_angle = (self.idle_angle + 2) % 360
        if self.state == "transcribing":
            self.loading_angle = (self.loading_angle + 10) % 360
            
        # Success frame animation (0 to 15 frames)
        if self.state == "success":
            if self.success_frame < 15:
                self.success_frame += 1
                
        # Error shake animation
        if self.state == "error":
            self.error_frame += 1
            if self.error_frame < 10:
                import random
                # Vibrate shaking
                dx = random.randint(-4, 4)
                dy = random.randint(-4, 4)
                self.shake_offset = QPoint(dx, dy)
            else:
                self.shake_offset = QPoint(0, 0)
            
        self.update()

    def reset_idle(self):
        self.is_idle = False
        self.setWindowOpacity(database.get_setting("opacity_active", 1.0))
        self.idle_timer.stop()

    def reset_idle_timer(self):
        self.reset_idle()
        if self.state == "idle":
            self.idle_timeout_ms = database.get_setting("idle_timeout", 5000)
            self.idle_timer.start(self.idle_timeout_ms)

    def fade_to_idle(self):
        if self.state == "idle":
            self.is_idle = True
            
            # Smoothly fade to idle opacity
            self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
            self.fade_anim.setDuration(400)
            self.fade_anim.setStartValue(self.windowOpacity())
            self.fade_anim.setEndValue(database.get_setting("opacity_idle", 0.15))
            self.fade_anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        # Apply shake offset for error state
        if self.state == "error" and hasattr(self, 'shake_offset'):
            painter.translate(self.shake_offset)
            
        theme = database.get_setting("theme", "dark")
        is_dark = theme == "dark"
        
        bg_color = QColor(DARK_BG if is_dark else LIGHT_BG)
        border_color = QColor(ORANGE)
        
        # Adjust rect to leave room for outer glow shadow
        rect = self.rect().adjusted(6, 6, -6, -6)
        radius = rect.height() / 2
        
        # Draw soft outer glow shadow
        shadow_opacity = 0.15 if self.is_idle else 0.45
        for i in range(1, 6):
            alpha = int(45 * shadow_opacity * (6 - i) / 5)
            painter.setPen(QPen(QColor(0, 0, 0, alpha), i * 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, radius, radius)
            
        # Draw capsule body background
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(rect, radius, radius)
        
        # State-based insane animations (No Text!)
        if self.state == "idle":
            # Idle animation: Rotating dashboard + breathing center orange dot
            painter.save()
            center = rect.center()
            
            # Draw outer thin rotating dashed circle
            pen = QPen(QColor(ORANGE), 1.5, Qt.DashLine)
            painter.setPen(pen)
            painter.translate(center.x(), center.y())
            painter.rotate(self.idle_angle)
            painter.drawEllipse(QPoint(0, 0), rect.width() / 2 - 2, rect.height() / 2 - 2)
            painter.restore()
            
            # Breathing center dot
            dot_alpha = int(120 + self.pulse_val * 135)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 102, 0, dot_alpha)))
            painter.drawEllipse(rect.center(), 5, 5)
            
        elif self.state == "recording":
            # Recording animation: Glowing expanding reactor + audio-reactive waveform
            center = rect.center()
            level = self.audio_history[-1]  # Latest audio level (0.0 to 1.0)
            
            # 1. Pulsing outer glow ring
            glow_radius = rect.width() / 2 - 2 + level * 5
            pen_width = 1.0 + level * 3.0
            painter.setPen(QPen(QColor(255, 50, 0, 100 + int(self.pulse_val * 100)), pen_width))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, glow_radius, glow_radius)
            
            # 2. Concentric inner reactive circle
            inner_radius = 8 + level * 6
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 60, 0, 180)))
            painter.drawEllipse(center, inner_radius, inner_radius)
            
            # 3. Dynamic radial spikes shooting out from the core
            painter.save()
            painter.translate(center.x(), center.y())
            # Slowly rotate the spikes
            painter.rotate(self.idle_angle * 1.5)
            num_spikes = 8
            for idx in range(num_spikes):
                angle = idx * (360 / num_spikes)
                painter.rotate(360 / num_spikes)
                
                # Length of spike reacts to audio level + a small base offset
                val_idx = min(len(self.audio_history) - 1, idx)
                spike_len = 3 + self.audio_history[val_idx] * 9
                
                pen = QPen(QColor(ORANGE), 2, Qt.SolidLine, Qt.RoundCap)
                painter.setPen(pen)
                # Draw spike starting from core radius
                painter.drawLine(0, int(inner_radius + 2), 0, int(inner_radius + 2 + spike_len))
            painter.restore()
            
        elif self.state == "transcribing":
            # Transcribing: Counter-rotating concentric rings loader (Insane spin!)
            center = rect.center()
            
            # Outer Ring (Clockwise)
            painter.save()
            painter.translate(center.x(), center.y())
            painter.rotate(self.loading_angle)
            pen = QPen(QColor(ORANGE), 2)
            painter.setPen(pen)
            painter.drawArc(-12, -12, 24, 24, 0, 270 * 16)
            painter.restore()
            
            # Inner Ring (Counter-Clockwise)
            painter.save()
            painter.translate(center.x(), center.y())
            painter.rotate(-self.loading_angle * 1.8)
            pen = QPen(QColor(255, 136, 51, 150), 1.5, Qt.DashLine)
            painter.setPen(pen)
            painter.drawEllipse(QPoint(0, 0), 8, 8)
            painter.restore()
            
        elif self.state == "success":
            # Success: Morphing tick drawing and ripple green circle
            center = rect.center()
            frame = self.success_frame  # 0 to 15
            
            # 1. Emerald green background expansion
            green_alpha = max(0, 255 - frame * 15)
            if green_alpha > 0:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(0, 255, 102, green_alpha)))
                # Expands outward
                r_exp = (rect.width() / 2) * (frame / 15.0)
                painter.drawEllipse(center, r_exp, r_exp)
                
            # 2. Main green border ring
            painter.setPen(QPen(QColor("#00FF66"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, rect.width() / 2 - 2, rect.height() / 2 - 2)
            
            # 3. Animate the tick drawing itself
            painter.setPen(QPen(QColor("#00FF66"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            cx, cy = center.x(), center.y()
            
            # Tick coordinates
            p1 = QPoint(cx - 7, cy - 1)
            p2 = QPoint(cx - 2, cy + 4)
            p3 = QPoint(cx + 7, cy - 5)
            
            if frame < 5:
                # Still growing first leg
                t = frame / 5.0
                curr_p = p1 + (p2 - p1) * t
                painter.drawLine(p1, curr_p)
            else:
                # First leg done, drawing second leg
                painter.drawLine(p1, p2)
                t = min(1.0, (frame - 5) / 10.0)
                curr_p = p2 + (p3 - p2) * t
                painter.drawLine(p2, curr_p)
                
        elif self.state == "error":
            # Error: Flashing warning cross + red shake
            center = rect.center()
            
            # Flashing red border
            flash_red = QColor(255, 51, 51, 200 if (self.error_frame % 2 == 0) else 100)
            painter.setPen(QPen(flash_red, 2.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, rect.width() / 2 - 2, rect.height() / 2 - 2)
            
            # Draw cross
            painter.setPen(QPen(QColor("#FF3333"), 3.5, Qt.SolidLine, Qt.RoundCap))
            cx, cy = center.x(), center.y()
            painter.drawLine(cx - 6, cy - 6, cx + 6, cy + 6)
            painter.drawLine(cx - 6, cy + 6, cx + 6, cy - 6)
            
        painter.end()


class HistoryEditDialog(QDialog):
    def __init__(self, entry_id, current_text, theme="dark", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Correct Transcription")
        self.setModal(True)
        self.setMinimumWidth(400)
        self.entry_id = entry_id
        
        layout = QVBoxLayout(self)
        
        self.label = QLabel("Edit the transcription. Voice Flow will learn your corrections:")
        layout.addWidget(self.label)
        
        self.textbox = QLineEdit(current_text)
        self.textbox.setMinimumHeight(40)
        layout.addWidget(self.textbox)
        
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save & Learn")
        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)
        
        # QSS styling based on mode
        is_dark = theme == "dark"
        bg = "#0A0A0A" if is_dark else "#F9F9FB"
        card = "#141414" if is_dark else "#FFFFFF"
        card_border = "#1E1E1E" if is_dark else "#E5E5EA"
        txt_primary = "#FFFFFF" if is_dark else "#1C1C1E"
        
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg};
                color: {txt_primary};
            }}
            QLabel {{
                color: {txt_primary};
                font-family: 'Segoe UI', -apple-system, Arial, sans-serif;
                font-size: 10.5pt;
                font-weight: 500;
            }}
            QLineEdit {{
                background-color: {card};
                color: {txt_primary};
                border: 1px solid {card_border};
                border-radius: 8px;
                padding: 8px 12px;
                font-family: 'Segoe UI';
                font-size: 11pt;
            }}
            QLineEdit:focus {{
                border: 1px solid {ORANGE};
            }}
            QPushButton {{
                background-color: {ORANGE};
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
                font-family: 'Segoe UI';
                font-weight: bold;
                font-size: 10pt;
            }}
            QPushButton:hover {{
                background-color: #FF8833;
            }}
            QPushButton[text="Cancel"] {{
                background-color: transparent;
                color: {txt_primary};
                border: 1px solid {card_border};
            }}
            QPushButton[text="Cancel"]:hover {{
                border-color: {ORANGE};
                color: {ORANGE};
                background-color: transparent;
            }}
        """)

    def get_text(self):
        return self.textbox.text().strip()


class SettingsWindow(QMainWindow):
    theme_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Voice Flow")
        self.resize(760, 580)
        
        # Frameless and translucent setup
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowSystemMenuHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        # Solid canvas back screen setup
        self.current_theme = database.get_setting("theme", "dark")
        self.app_icon = get_app_icon(LOGO_PATH)
        self.setWindowIcon(self.app_icon)
        
        # Central widget is a transparent container
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # Main layout of central widget (10px margin for shadow rendering)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        
        # The inner window frame that has rounded corners, background color, and border
        self.window_frame = QFrame()
        self.window_frame.setObjectName("windowFrame")
        
        # Premium soft drop shadow effect
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(15)
        self.shadow.setColor(QColor(0, 0, 0, 120))
        self.shadow.setOffset(0, 4)
        self.window_frame.setGraphicsEffect(self.shadow)
        
        self.main_layout.addWidget(self.window_frame)
        
        # Layout inside the window frame: Horizontal layout splits Sidebar (left) and Content (right)
        self.window_layout = QHBoxLayout(self.window_frame)
        self.window_layout.setContentsMargins(12, 12, 12, 12)
        self.window_layout.setSpacing(12)
        
        # ==========================================
        # LEFT: Sidebar Container
        # ==========================================
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(200)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(15, 25, 15, 25)
        self.sidebar_layout.setSpacing(10)
        
        # Sidebar Logo and Title
        self.logo_layout = QHBoxLayout()
        self.logo_label = QLabel()
        self.logo_pixmap = get_rounded_pixmap(LOGO_PATH, size=46, radius=10, padding=4)
        self.logo_label.setPixmap(self.logo_pixmap)
        self.logo_label.setFixedSize(46, 46)
        
        # Deep Orange Ambient Shadow Effect
        self.logo_shadow = QGraphicsDropShadowEffect(self)
        self.logo_shadow.setBlurRadius(14)
        self.logo_shadow.setColor(QColor(255, 102, 0, 140))
        self.logo_shadow.setOffset(0, 3)
        self.logo_label.setGraphicsEffect(self.logo_shadow)
        
        self.logo_layout.addWidget(self.logo_label)
        
        self.logo_text_layout = QVBoxLayout()
        self.logo_text_layout.setSpacing(0)
        self.logo_title = QLabel("Voice Flow")
        self.logo_title.setObjectName("logoTitle")
        self.logo_sub = QLabel("Voice Typist")
        self.logo_sub.setObjectName("logoSub")
        self.logo_text_layout.addWidget(self.logo_title)
        self.logo_text_layout.addWidget(self.logo_sub)
        self.logo_layout.addLayout(self.logo_text_layout)
        self.logo_layout.addStretch()
        self.sidebar_layout.addLayout(self.logo_layout)
        
        self.sidebar_layout.addSpacing(25)
        
        # Sidebar Menu Title
        menu_title = QLabel("NAVIGATION")
        menu_title.setObjectName("menuTitle")
        self.sidebar_layout.addWidget(menu_title)
        
        # Sidebar Buttons (Checkable, acting as tabs)
        self.btn_history = QPushButton("   History")
        self.btn_history.setObjectName("sidebarBtn")
        self.btn_history.setCheckable(True)
        self.btn_history.setChecked(True)
        self.btn_history.setMinimumHeight(38)
        
        self.btn_dict = QPushButton("   Dictionary")
        self.btn_dict.setObjectName("sidebarBtn")
        self.btn_dict.setCheckable(True)
        self.btn_dict.setMinimumHeight(38)
        
        self.btn_settings = QPushButton("   Settings")
        self.btn_settings.setObjectName("sidebarBtn")
        self.btn_settings.setCheckable(True)
        self.btn_settings.setMinimumHeight(38)
        
        # Button Group list
        self.menu_buttons = [self.btn_history, self.btn_dict, self.btn_settings]
        for btn in self.menu_buttons:
            self.sidebar_layout.addWidget(btn)
            
        self.btn_history.clicked.connect(lambda: self.switch_page(0))
        self.btn_dict.clicked.connect(lambda: self.switch_page(1))
        self.btn_settings.clicked.connect(lambda: self.switch_page(2))
        
        self.sidebar_layout.addStretch()
        
        # Sidebar Bottom Label
        self.status_badge = QLabel("RL Engine Active")
        self.status_badge.setObjectName("statusBadge")
        self.sidebar_layout.addWidget(self.status_badge, alignment=Qt.AlignCenter)
        
        self.window_layout.addWidget(self.sidebar)
        
        # ==========================================
        # RIGHT: Content Container (Top Bar + View Stack)
        # ==========================================
        self.content_container = QWidget()
        self.content_container.setObjectName("contentContainer")
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(20, 10, 20, 20)
        self.content_layout.setSpacing(10)
        
        # Custom Top Bar (Window Controls & Drag handle)
        self.top_bar = QHBoxLayout()
        self.top_bar.addStretch()
        
        self.btn_minimize = QPushButton("—")
        self.btn_minimize.setObjectName("windowCtrlBtn")
        self.btn_minimize.setFixedSize(38, 30)
        self.btn_minimize.clicked.connect(self.showMinimized)
        
        self.btn_maximize = QPushButton("⬜")
        self.btn_maximize.setObjectName("windowCtrlBtn")
        self.btn_maximize.setFixedSize(38, 30)
        self.btn_maximize.clicked.connect(self.toggle_maximize)
        
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("windowCloseBtn")
        self.btn_close.setFixedSize(38, 30)
        self.btn_close.clicked.connect(self.hide)
        
        self.top_bar.addWidget(self.btn_minimize)
        self.top_bar.addWidget(self.btn_maximize)
        self.top_bar.addWidget(self.btn_close)
        self.content_layout.addLayout(self.top_bar)
        
        # Stacked view widget
        self.view_stack = QStackedWidget()
        self.content_layout.addWidget(self.view_stack)
        
        # Pages layouts
        self.init_history_tab()
        self.init_dictionary_tab()
        self.init_settings_tab()
        
        self.view_stack.addWidget(self.history_tab)
        self.view_stack.addWidget(self.dict_tab)
        self.view_stack.addWidget(self.settings_tab)
        
        self.window_layout.addWidget(self.content_container)
        
        self.apply_theme(self.current_theme)

    def switch_page(self, index):
        for i, btn in enumerate(self.menu_buttons):
            btn.setChecked(i == index)
        self.view_stack.setCurrentIndex(index)
        if index == 0:
            self.refresh_history()
        elif index == 1:
            self.refresh_dictionary()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_history()
        self.refresh_dictionary()

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.btn_maximize.setText("⬜")
        else:
            self.showMaximized()
            self.btn_maximize.setText("❐")
        self.apply_theme(self.current_theme)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            if pos.x() < 200 or pos.y() < 45:
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            if hasattr(self, 'drag_position'):
                if self.isMaximized():
                    self.showNormal()
                    self.btn_maximize.setText("⬜")
                    self.apply_theme(self.current_theme)
                self.move(event.globalPosition().toPoint() - self.drag_position)
                event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.apply_theme(self.current_theme)

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def init_history_tab(self):
        self.history_tab = QWidget()
        layout = QVBoxLayout(self.history_tab)
        
        # Header controls
        ctrl_layout = QHBoxLayout()
        lbl = QLabel("Transcription History")
        lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        ctrl_layout.addWidget(lbl)
        ctrl_layout.addStretch()
        
        self.save_learn_btn = QPushButton("Save & Learn")
        self.save_learn_btn.setObjectName("saveLearnAllBtn")
        self.save_learn_btn.clicked.connect(self.save_all_history_edits)
        ctrl_layout.addWidget(self.save_learn_btn)
        
        ctrl_layout.addSpacing(6)
        
        self.clear_hist_btn = QPushButton("Clear All")
        self.clear_hist_btn.setObjectName("clearAllBtn")
        self.clear_hist_btn.clicked.connect(self.clear_history)
        ctrl_layout.addWidget(self.clear_hist_btn)
        layout.addLayout(ctrl_layout)
        
        # History list
        self.history_list = QListWidget()
        self.history_list.setSelectionMode(QListWidget.NoSelection)
        self.history_list.setSpacing(6)
        layout.addWidget(self.history_list)
        
        # Handled by QStackedWidget
        
        self.refresh_history()

    def save_single_history_entry_from_sender(self):
        sender = self.sender()
        if sender:
            entry_id = sender.property("entryId")
            if entry_id is not None:
                self.save_single_history_entry(entry_id)

    def refresh_history(self):
        self.history_list.clear()
        self.history_inputs = {}
        entries = database.get_history()
        
        for e in entries:
            item = QListWidgetItem(self.history_list)
            
            # Custom widget for item
            card = QFrame()
            card.setObjectName("historyCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.setSpacing(8)
            
            # Header with Date and Save button
            header = QHBoxLayout()
            date_lbl = QLabel(e["timestamp"])
            date_lbl.setObjectName("historyDate")
            header.addWidget(date_lbl)
            header.addStretch()
            
            save_card_btn = QPushButton("Save")
            save_card_btn.setObjectName("historyEditBtn")
            save_card_btn.setProperty("entryId", e["id"])
            save_card_btn.clicked.connect(self.save_single_history_entry_from_sender)
            header.addWidget(save_card_btn)
            card_layout.addLayout(header)
            
            # Content: Editable QLineEdit for corrected text
            corrected = e["corrected_text"]
            raw = e["raw_text"]
            
            text_input = QLineEdit(corrected)
            text_input.setObjectName("historyEditInput")
            text_input.setProperty("entryId", e["id"])
            text_input.returnPressed.connect(self.save_single_history_entry_from_sender)
            card_layout.addWidget(text_input)
            
            # Save references
            self.history_inputs[e["id"]] = (text_input, e["corrected_text"])
            
            if raw.lower() != corrected.lower():
                raw_lbl = QLabel(f"Originally heard: \"{raw}\"")
                raw_lbl.setWordWrap(True)
                raw_lbl.setObjectName("historyRawText")
                card_layout.addWidget(raw_lbl)
                
            item.setSizeHint(card.sizeHint())
            self.history_list.addItem(item)
            self.history_list.setItemWidget(item, card)

    def save_single_history_entry(self, entry_id):
        print(f"[Voice Flow] save_single_history_entry called for ID={entry_id}")
        if hasattr(self, 'history_inputs') and entry_id in self.history_inputs:
            text_input, old_text = self.history_inputs[entry_id]
            new_text = text_input.text().strip()
            print(f"[Voice Flow] old_text='{old_text}', new_text='{new_text}'")
            if new_text:
                print(f"[Voice Flow] Updating history ID={entry_id} in database...")
                database.update_history_entry(entry_id, new_text)
                print(f"[Voice Flow] Deleting history ID={entry_id} from database...")
                database.delete_history_entry(entry_id)
                self.refresh_history()
                self.refresh_dictionary()
            else:
                print("[Voice Flow] Text is empty, skipping save.")

    def save_all_history_edits(self):
        print("[Voice Flow] save_all_history_edits called")
        if not hasattr(self, 'history_inputs'):
            print("[Voice Flow] No history inputs dictionary found.")
            return
        
        # Save and learn all history entries
        for entry_id, (text_input, old_text) in self.history_inputs.items():
            new_text = text_input.text().strip()
            if new_text:
                print(f"[Voice Flow] Saving and learning history ID={entry_id}...")
                database.update_history_entry(entry_id, new_text)
                
        # Automatically clear history database after learning
        print("[Voice Flow] Clearing history database after learning...")
        database.clear_history()
        
        # Refresh UI
        self.refresh_history()
        self.refresh_dictionary()

    def clear_history(self):
        reply = QMessageBox.question(self, "Clear History", "Are you sure you want to clear all history?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            database.clear_history()
            self.refresh_history()

    def init_dictionary_tab(self):
        self.dict_tab = QWidget()
        layout = QVBoxLayout(self.dict_tab)
        
        # Word Adding section (Single "Word" text box next to "Add Word")
        add_layout = QHBoxLayout()
        self.word_input = QLineEdit()
        self.word_input.setPlaceholderText("Word...")
        
        add_btn = QPushButton("Add Word")
        add_btn.clicked.connect(self.add_word)
        
        add_layout.addWidget(self.word_input)
        add_layout.addWidget(add_btn)
        layout.addLayout(add_layout)
        
        # Learned Dictionary List
        self.dict_list = QListWidget()
        self.dict_list.setSelectionMode(QListWidget.NoSelection)
        self.dict_list.setSpacing(4)
        layout.addWidget(self.dict_list)
        
        # Handled by QStackedWidget
        
        self.refresh_dictionary()

    def refresh_dictionary(self):
        self.dict_list.clear()
        entries = database.get_dictionary()
        
        for e in entries:
            item = QListWidgetItem(self.dict_list)
            
            card = QFrame()
            card.setObjectName("dictCard")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            
            # Words representation (Clean rendering: hides phrase -> replacement mapping if they match case-insensitively)
            if e['phrase'] == e['replacement'].lower():
                map_lbl = QLabel(f"\"{e['replacement']}\"")
            else:
                map_lbl = QLabel(f"\"{e['phrase']}\"  →  \"{e['replacement']}\"")
            map_lbl.setObjectName("dictMappingText")
            card_layout.addWidget(map_lbl)
            card_layout.addStretch()
            
            # Label marking how it was added
            badge = QLabel("Learned" if e["learned"] else "Manual")
            badge.setObjectName("learnedBadge" if e["learned"] else "manualBadge")
            card_layout.addWidget(badge)
            
            # Delete button
            del_btn = QPushButton("Delete")
            del_btn.setObjectName("dictDeleteBtn")
            del_btn.clicked.connect(self.make_delete_handler(e["phrase"]))
            card_layout.addWidget(del_btn)
            
            item.setSizeHint(card.sizeHint())
            self.dict_list.addItem(item)
            self.dict_list.setItemWidget(item, card)

    def make_delete_handler(self, phrase):
        return lambda: self.delete_word(phrase)

    def add_word(self):
        word = self.word_input.text().strip()
        
        if word:
            # Save word as a self-mapping custom vocabulary word
            if database.add_dictionary_entry(word.lower(), word, learned=0):
                self.word_input.clear()
                self.refresh_dictionary()
            else:
                QMessageBox.warning(self, "Invalid Entry", "Could not add word. Make sure it is unique.")
        else:
            QMessageBox.warning(self, "Empty Field", "Please type a word.")

    def delete_word(self, phrase):
        database.delete_dictionary_entry(phrase)
        self.refresh_dictionary()

    def init_settings_tab(self):
        self.settings_tab = QWidget()
        main_layout = QVBoxLayout(self.settings_tab)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Scroll Area for responsive card browsing
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(14)
        
        # 1. Section Header: Title & Subtitle
        header_layout = QVBoxLayout()
        header_layout.setSpacing(2)
        title_lbl = QLabel("Settings & Preferences")
        title_lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        
        subtitle_lbl = QLabel("Customize appearance, idle opacity, hotkeys, and AI features.")
        subtitle_lbl.setObjectName("settingSubText")
        subtitle_lbl.setFont(QFont("Segoe UI", 9))
        
        header_layout.addWidget(title_lbl)
        header_layout.addWidget(subtitle_lbl)
        layout.addLayout(header_layout)
        
        # 2. Card 1: Appearance & Theme
        theme_card = QFrame()
        theme_card.setObjectName("settingGroupCard")
        theme_card_layout = QHBoxLayout(theme_card)
        theme_card_layout.setContentsMargins(16, 14, 16, 14)
        
        theme_info = QVBoxLayout()
        theme_info.setSpacing(2)
        t_lbl = QLabel("Appearance Theme")
        t_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        t_sub = QLabel("Switch between dark glass and light glass aesthetic modes")
        t_sub.setObjectName("settingSubText")
        t_sub.setFont(QFont("Segoe UI", 8.5))
        theme_info.addWidget(t_lbl)
        theme_info.addWidget(t_sub)
        
        theme_card_layout.addLayout(theme_info)
        theme_card_layout.addStretch()
        
        self.theme_btn = QPushButton("🌙  Dark Mode" if self.current_theme == "dark" else "☀️  Light Mode")
        self.theme_btn.setObjectName("themeTogglePill")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.clicked.connect(self.toggle_theme)
        theme_card_layout.addWidget(self.theme_btn)
        
        layout.addWidget(theme_card)
        
        # 3. Card 2: Floating Capsule Behavior & Interactive Simulator Dashboard
        capsule_card = QFrame()
        capsule_card.setObjectName("settingGroupCard")
        capsule_card_layout = QVBoxLayout(capsule_card)
        capsule_card_layout.setContentsMargins(18, 18, 18, 18)
        capsule_card_layout.setSpacing(16)
        
        # Section Header with Icon & Subtitle
        cap_header_layout = QHBoxLayout()
        cap_title_layout = QVBoxLayout()
        cap_title_layout.setSpacing(2)
        
        cap_title = QLabel("🔮 Floating Capsule Behavior & Transparency")
        cap_title.setFont(QFont("Segoe UI", 10.5, QFont.Bold))
        cap_sub = QLabel("Configure real-time idle fading, opacity thresholds, and animation delays.")
        cap_sub.setObjectName("settingSubText")
        cap_sub.setFont(QFont("Segoe UI", 8.5))
        
        cap_title_layout.addWidget(cap_title)
        cap_title_layout.addWidget(cap_sub)
        cap_header_layout.addLayout(cap_title_layout)
        cap_header_layout.addStretch()
        
        capsule_card_layout.addLayout(cap_header_layout)
        
        # Split Layout: Left side = Controls & Presets, Right side = Live Interactive Capsule Preview Card
        body_split_layout = QHBoxLayout()
        body_split_layout.setSpacing(16)
        
        # LEFT COLUMN: Sliders & Quick Preset Buttons
        left_controls_layout = QVBoxLayout()
        left_controls_layout.setSpacing(14)
        
        # --- Control A: Opacity Level ---
        trans_box = QFrame()
        trans_box.setObjectName("settingSubCard")
        trans_box_layout = QVBoxLayout(trans_box)
        trans_box_layout.setContentsMargins(14, 12, 14, 12)
        trans_box_layout.setSpacing(8)
        
        t_header = QHBoxLayout()
        t_lbl = QLabel("Idle Opacity Level")
        t_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.trans_val_lbl = QLabel(f"{int(database.get_setting('opacity_idle', 0.15)*100)}%")
        self.trans_val_lbl.setObjectName("settingValBadge")
        t_header.addWidget(t_lbl)
        t_header.addStretch()
        t_header.addWidget(self.trans_val_lbl)
        trans_box_layout.addLayout(t_header)
        
        # Quick Presets Row for Opacity
        opacity_presets_layout = QHBoxLayout()
        opacity_presets_layout.setSpacing(6)
        
        op_ghost_btn = QPushButton("👻 Ghost 10%")
        op_subtle_btn = QPushButton("✨ Subtle 25%")
        op_solid_btn = QPushButton("👁️ Solid 50%")
        op_opaque_btn = QPushButton("🎯 Opaque 80%")
        
        for btn, val in [(op_ghost_btn, 10), (op_subtle_btn, 25), (op_solid_btn, 50), (op_opaque_btn, 80)]:
            btn.setObjectName("presetPillBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, v=val: self.trans_slider.setValue(v))
            opacity_presets_layout.addWidget(btn)
            
        trans_box_layout.addLayout(opacity_presets_layout)
        
        # Custom Opacity Slider
        self.trans_slider = QSlider(Qt.Horizontal)
        self.trans_slider.setMinimum(5)
        self.trans_slider.setMaximum(90)
        self.trans_slider.setValue(int(database.get_setting("opacity_idle", 0.15) * 100))
        self.trans_slider.valueChanged.connect(self.change_idle_opacity)
        trans_box_layout.addWidget(self.trans_slider)
        
        left_controls_layout.addWidget(trans_box)
        
        # --- Control B: Idle Timeout ---
        timeout_box = QFrame()
        timeout_box.setObjectName("settingSubCard")
        timeout_box_layout = QVBoxLayout(timeout_box)
        timeout_box_layout.setContentsMargins(14, 12, 14, 12)
        timeout_box_layout.setSpacing(8)
        
        to_header = QHBoxLayout()
        to_lbl = QLabel("Idle Fade Delay")
        to_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.timeout_val_lbl = QLabel(f"{int(database.get_setting('idle_timeout', 5000)/1000)}s")
        self.timeout_val_lbl.setObjectName("settingValBadge")
        to_header.addWidget(to_lbl)
        to_header.addStretch()
        to_header.addWidget(self.timeout_val_lbl)
        timeout_box_layout.addLayout(to_header)
        
        # Quick Presets Row for Timeout
        timeout_presets_layout = QHBoxLayout()
        timeout_presets_layout.setSpacing(6)
        
        to_2s_btn = QPushButton("⚡ Fast 2s")
        to_5s_btn = QPushButton("⏱️ Std 5s")
        to_10s_btn = QPushButton("⏳ Slow 10s")
        to_20s_btn = QPushButton("♾️ Max 20s")
        
        for btn, val in [(to_2s_btn, 2), (to_5s_btn, 5), (to_10s_btn, 10), (to_20s_btn, 20)]:
            btn.setObjectName("presetPillBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, v=val: self.timeout_slider.setValue(v))
            timeout_presets_layout.addWidget(btn)
            
        timeout_box_layout.addLayout(timeout_presets_layout)
        
        # Custom Timeout Slider
        self.timeout_slider = QSlider(Qt.Horizontal)
        self.timeout_slider.setMinimum(1)
        self.timeout_slider.setMaximum(30)
        self.timeout_slider.setValue(int(database.get_setting("idle_timeout", 5000) / 1000))
        self.timeout_slider.valueChanged.connect(self.change_idle_timeout)
        timeout_box_layout.addWidget(self.timeout_slider)
        
        left_controls_layout.addWidget(timeout_box)
        
        body_split_layout.addLayout(left_controls_layout, stretch=3)
        
        # RIGHT COLUMN: Live Interactive Capsule Preview Card
        preview_card = QFrame()
        preview_card.setObjectName("livePreviewCard")
        preview_card.setFixedWidth(210)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(12, 14, 12, 14)
        preview_layout.setSpacing(10)
        
        pv_title = QLabel("LIVE PREVIEW")
        pv_title.setObjectName("previewHeaderTitle")
        pv_title.setFont(QFont("Segoe UI", 8, QFont.Bold))
        preview_layout.addWidget(pv_title, alignment=Qt.AlignCenter)
        
        # Mini Desktop Container simulating transparent desktop background
        desktop_sim = QFrame()
        desktop_sim.setObjectName("desktopSimBox")
        desktop_layout = QVBoxLayout(desktop_sim)
        desktop_layout.setContentsMargins(10, 20, 10, 20)
        desktop_layout.setAlignment(Qt.AlignCenter)
        
        # Simulated Mini Capsule Widget
        self.mini_capsule = QFrame()
        self.mini_capsule.setObjectName("miniCapsuleWidget")
        self.mini_capsule.setFixedSize(140, 34)
        
        mc_layout = QHBoxLayout(self.mini_capsule)
        mc_layout.setContentsMargins(8, 4, 8, 4)
        mc_dot = QLabel("●")
        mc_dot.setStyleSheet(f"color: {ORANGE}; font-size: 8pt;")
        mc_text = QLabel("Voice Flow")
        mc_text.setFont(QFont("Segoe UI", 8.5, QFont.Bold))
        mc_text.setStyleSheet("color: #FFFFFF;")
        
        mc_layout.addWidget(mc_dot)
        mc_layout.addWidget(mc_text)
        mc_layout.addStretch()
        
        desktop_layout.addWidget(self.mini_capsule)
        preview_layout.addWidget(desktop_sim)
        
        # Initialize mini capsule opacity effect
        self.mini_opacity_effect = QGraphicsOpacityEffect(self.mini_capsule)
        self.mini_opacity_effect.setOpacity(database.get_setting('opacity_idle', 0.15))
        self.mini_capsule.setGraphicsEffect(self.mini_opacity_effect)
        
        # Live status info
        self.preview_status_lbl = QLabel(f"Idle Opacity: {int(database.get_setting('opacity_idle', 0.15)*100)}%")
        self.preview_status_lbl.setObjectName("previewStatusText")
        self.preview_status_lbl.setFont(QFont("Segoe UI", 8))
        preview_layout.addWidget(self.preview_status_lbl, alignment=Qt.AlignCenter)
        
        # Quick Test Animation Button
        test_fade_btn = QPushButton("⚡ Simulate Fade")
        test_fade_btn.setObjectName("testFadeBtn")
        test_fade_btn.setCursor(Qt.PointingHandCursor)
        test_fade_btn.clicked.connect(self.simulate_idle_fade)
        preview_layout.addWidget(test_fade_btn)
        
        body_split_layout.addWidget(preview_card, stretch=2)
        capsule_card_layout.addLayout(body_split_layout)
        
        layout.addWidget(capsule_card)
        
        # 4. Card 3: Global Hotkey & Reinforcement Learning Info
        info_card = QFrame()
        info_card.setObjectName("settingGroupCard")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(16, 16, 16, 16)
        info_layout.setSpacing(10)
        
        hotkey_layout = QHBoxLayout()
        hk_lbl = QLabel("Global Voice Activation Hotkey")
        hk_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        hotkey_layout.addWidget(hk_lbl)
        hotkey_layout.addStretch()
        
        hk_badge = QLabel("Ctrl + Win")
        hk_badge.setObjectName("kbdBadge")
        hotkey_layout.addWidget(hk_badge)
        info_layout.addLayout(hotkey_layout)
        
        hk_sub = QLabel("Press and hold Ctrl + Win to dictate anywhere on your PC.")
        hk_sub.setObjectName("settingSubText")
        hk_sub.setFont(QFont("Segoe UI", 8.5))
        info_layout.addWidget(hk_sub)
        
        # Inner RL Explanation Box
        info_box = QFrame()
        info_box.setObjectName("infoBox")
        box_layout = QVBoxLayout(info_box)
        box_layout.setContentsMargins(12, 12, 12, 12)
        box_layout.setSpacing(6)
        
        info_title = QLabel("⚡ Reinforcement Learning System")
        info_title.setFont(QFont("Segoe UI", 9.5, QFont.Bold))
        info_title.setStyleSheet(f"color: {ORANGE};")
        
        info_body = QLabel(
            "Voice Flow automatically learns from your edits!\n\n"
            "• Method 1: Edit any entry in the 'History' tab and click 'Save'. The new words and corrections will be automatically learned.\n"
            "• Method 2: Copy your manual edits (Ctrl+C) within 15s of dictating text. Voice Flow compares the copy with the paste and registers the correction."
        )
        info_body.setWordWrap(True)
        info_body.setObjectName("infoBodyText")
        
        box_layout.addWidget(info_title)
        box_layout.addWidget(info_body)
        info_layout.addWidget(info_box)
        
        layout.addWidget(info_card)
        layout.addStretch()
        
        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def toggle_theme(self):
        new_theme = "light" if self.current_theme == "dark" else "dark"
        self.apply_theme(new_theme)
        database.save_setting("theme", new_theme)
        self.theme_btn.setText("🌙  Dark Mode" if new_theme == "dark" else "☀️  Light Mode")
        self.theme_changed.emit(new_theme)

    def change_idle_opacity(self, value):
        opacity = value / 100.0
        database.save_setting("opacity_idle", opacity)
        self.trans_val_lbl.setText(f"{value}%")
        if hasattr(self, 'preview_status_lbl'):
            self.preview_status_lbl.setText(f"Idle Opacity: {value}%")
        if hasattr(self, 'mini_opacity_effect'):
            self.mini_opacity_effect.setOpacity(opacity)

    def change_idle_timeout(self, value):
        timeout = value * 1000
        database.save_setting("idle_timeout", timeout)
        self.timeout_val_lbl.setText(f"{value}s")

    def simulate_idle_fade(self):
        if hasattr(self, 'mini_opacity_effect'):
            anim = QPropertyAnimation(self.mini_opacity_effect, b"opacity")
            anim.setDuration(900)
            anim.setStartValue(1.0)
            target = self.trans_slider.value() / 100.0
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.InOutQuad)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
            self._preview_anim = anim

    def apply_theme(self, theme_name):
        self.current_theme = theme_name
        is_dark = theme_name == "dark"
        is_max = self.isMaximized()
        
        # Dynamic rounded corners based on window states
        radius = 0 if is_max else 16
        inner_radius = 15
        
        # Adjust layout padding when maximized to fill whole screen
        if hasattr(self, 'main_layout'):
            margin = 0 if is_max else 10
            self.main_layout.setContentsMargins(margin, margin, margin, margin)
            
        if hasattr(self, 'window_layout'):
            # Keep panel margins and spacing intact so they float as panels even when maximized
            panel_margin = 12
            panel_spacing = 12
            self.window_layout.setContentsMargins(panel_margin, panel_margin, panel_margin, panel_margin)
            self.window_layout.setSpacing(panel_spacing)
            
        # Disable drop shadow when maximized
        if hasattr(self, 'shadow'):
            self.shadow.setEnabled(not is_max)
        
        # Solid Black Background Screen with Glassmorphism Panels
        bg = "#000000" if is_dark else "#F0F0F4"
        card = "rgba(255, 255, 255, 0.05)" if is_dark else "rgba(0, 0, 0, 0.03)"
        card_border = "rgba(255, 255, 255, 0.10)" if is_dark else "rgba(0, 0, 0, 0.08)"
        glass_border = "rgba(255, 255, 255, 0.15)" if is_dark else "rgba(0, 0, 0, 0.12)"
        txt_primary = "#FFFFFF" if is_dark else "#1C1C1E"
        txt_secondary = "#9898A0" if is_dark else "#7C7C80"
        slider_groove = "rgba(255, 255, 255, 0.1)" if is_dark else "rgba(0, 0, 0, 0.1)"
        learned_badge_bg = "rgba(255, 102, 0, 0.15)" if is_dark else "rgba(255, 102, 0, 0.12)"
        
        # Sidebar & Content Glassmorphic theme colors
        sidebar_bg = "rgba(18, 18, 24, 0.65)" if is_dark else "rgba(255, 255, 255, 0.65)"
        content_bg = "rgba(18, 18, 24, 0.65)" if is_dark else "rgba(255, 255, 255, 0.65)"
        sidebar_btn_hover = "rgba(255, 255, 255, 0.06)" if is_dark else "rgba(0, 0, 0, 0.05)"
        sidebar_btn_checked = "rgba(255, 102, 0, 0.16)" if is_dark else "rgba(255, 102, 0, 0.14)"
        status_bg = "rgba(16, 185, 129, 0.12)" if is_dark else "rgba(16, 185, 129, 0.15)"
        status_txt = "#10B981" if is_dark else "#047857"
        
        # Primary stylesheet
        stylesheet = f"""
            QMainWindow {{
                background-color: transparent;
            }}
            QWidget {{
                background-color: transparent;
                color: {txt_primary};
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Arial, sans-serif;
            }}
            #windowFrame {{
                background-color: {bg};
                border: 1px solid {glass_border};
                border-radius: {radius}px;
            }}
            #sidebar {{
                background-color: {sidebar_bg};
                border: 1px solid {glass_border};
                border-radius: {inner_radius}px;
            }}
            #contentContainer {{
                background-color: {content_bg};
                border: 1px solid {glass_border};
                border-radius: {inner_radius}px;
            }}
            #logoTitle {{
                font-size: 13pt;
                font-weight: 800;
                color: {ORANGE};
                background: transparent;
            }}
            #logoSub {{
                font-size: 8.5pt;
                color: {txt_secondary};
                background: transparent;
                font-weight: 500;
            }}
            #menuTitle {{
                font-size: 7.5pt;
                font-weight: bold;
                color: {txt_secondary};
                margin-top: 10px;
                background: transparent;
                letter-spacing: 1px;
            }}
            #sidebarBtn {{
                background-color: transparent;
                color: {txt_secondary};
                border: none;
                border-radius: 8px;
                text-align: left;
                padding-left: 14px;
                font-weight: 600;
                font-size: 9.5pt;
            }}
            #sidebarBtn:hover {{
                background-color: {sidebar_btn_hover};
                color: {txt_primary};
            }}
            #sidebarBtn:checked {{
                background-color: {sidebar_btn_checked};
                color: {ORANGE};
                border-left: 3.5px solid {ORANGE};
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                font-weight: bold;
            }}
            #statusBadge {{
                font-size: 8pt;
                font-weight: bold;
                color: {status_txt};
                background-color: {status_bg};
                border: 1px solid {status_txt};
                border-radius: 12px;
                padding: 4px 14px;
            }}
            #windowCtrlBtn {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                color: {txt_secondary};
                font-size: 9.5pt;
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            }}
            #windowCtrlBtn:hover {{
                background-color: {sidebar_btn_hover};
                color: {txt_primary};
            }}
            #windowCtrlBtn:pressed {{
                background-color: {sidebar_btn_checked};
            }}
            #windowCloseBtn {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                color: {txt_secondary};
                font-size: 9.5pt;
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            }}
            #windowCloseBtn:hover {{
                background-color: #EF4444;
                color: #FFFFFF;
            }}
            #windowCloseBtn:pressed {{
                background-color: #DC2626;
                color: #FFFFFF;
            }}
            QListWidget {{
                border: none;
                background-color: transparent;
            }}
            #historyCard, #dictCard {{
                background-color: {card};
                border: 1px solid {card_border};
                border-radius: 12px;
                margin-bottom: 2px;
            }}
            #historyDate {{
                font-size: 8.5pt;
                color: {ORANGE};
                font-weight: bold;
                opacity: 0.9;
            }}
            #historyEditBtn, #dictDeleteBtn {{
                background-color: {card_border};
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 8.5pt;
                font-weight: bold;
                color: {txt_primary};
            }}
            #historyEditBtn:hover, #dictDeleteBtn:hover {{
                background-color: {ORANGE};
                color: #FFFFFF;
            }}
            #historyText {{
                font-size: 10.5pt;
                font-weight: 600;
                color: {txt_primary};
            }}
            #historyRawText {{
                font-size: 9pt;
                color: {txt_secondary};
                font-style: italic;
            }}
            QLineEdit {{
                background-color: {card};
                color: {txt_primary};
                border: 1px solid {card_border};
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 10pt;
            }}
            QLineEdit:focus {{
                border: 1px solid {ORANGE};
                background-color: {bg};
            }}
            QPushButton {{
                background-color: {ORANGE};
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 9.5pt;
            }}
            QPushButton:hover {{
                background-color: #FF8833;
            }}
            #historyEditInput {{
                background-color: transparent;
                border: 1px solid {card_border};
                border-radius: 8px;
                color: {txt_primary};
                padding: 6px 12px;
                font-size: 10.5pt;
                font-weight: 500;
            }}
            #historyEditInput:focus {{
                border: 1px solid {ORANGE};
                background-color: {card};
            }}
            #saveLearnAllBtn {{
                background-color: {ORANGE};
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 9.5pt;
            }}
            #saveLearnAllBtn:hover {{
                background-color: #FF8833;
            }}
            #clearAllBtn, #themeBtn {{
                background-color: transparent;
                color: {txt_primary};
                border: 1px solid {card_border};
            }}
            #clearAllBtn:hover, #themeBtn:hover {{
                border-color: {ORANGE};
                color: {ORANGE};
                background-color: transparent;
            }}
            #learnedBadge {{
                background-color: {learned_badge_bg};
                color: {ORANGE};
                border: 1px solid {ORANGE};
                border-radius: 10px;
                padding: 2px 10px;
                font-size: 8pt;
                font-weight: bold;
            }}
            #manualBadge {{
                background-color: {card_border};
                color: {txt_secondary};
                border: none;
                border-radius: 10px;
                padding: 2px 10px;
                font-size: 8pt;
                font-weight: bold;
            }}
            #settingGroupCard {{
                background-color: {card};
                border: 1px solid {card_border};
                border-radius: 12px;
            }}
            #settingSubText {{
                color: {txt_secondary};
            }}
            #settingValBadge {{
                color: {ORANGE};
                font-weight: bold;
                font-size: 9pt;
                background-color: {learned_badge_bg};
                border: 1px solid {ORANGE};
                border-radius: 8px;
                padding: 2px 8px;
            }}
            #kbdBadge {{
                background-color: {card_border};
                color: {txt_primary};
                font-weight: bold;
                font-size: 9pt;
                border: 1px solid {glass_border};
                border-radius: 6px;
                padding: 3px 10px;
                font-family: 'Consolas', 'Segoe UI', monospace;
            }}
            #themeTogglePill {{
                background-color: {card_border};
                color: {txt_primary};
                border: 1px solid {glass_border};
                border-radius: 14px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 9pt;
            }}
            #themeTogglePill:hover {{
                border-color: {ORANGE};
                color: {ORANGE};
                background-color: {sidebar_btn_checked};
            }}
            #settingSubCard {{
                background-color: {bg};
                border: 1px solid {card_border};
                border-radius: 10px;
            }}
            #presetPillBtn {{
                background-color: {card_border};
                color: {txt_secondary};
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 4px 6px;
                font-size: 8pt;
                font-weight: 500;
            }}
            #presetPillBtn:hover {{
                border-color: {ORANGE};
                color: {ORANGE};
                background-color: {sidebar_btn_checked};
            }}
            #livePreviewCard {{
                background-color: {bg};
                border: 1px solid {card_border};
                border-radius: 12px;
            }}
            #previewHeaderTitle {{
                color: {ORANGE};
                letter-spacing: 1px;
            }}
            #desktopSimBox {{
                background-color: rgba(0, 0, 0, 0.45);
                border: 1px dashed {card_border};
                border-radius: 8px;
            }}
            #miniCapsuleWidget {{
                background-color: {ORANGE};
                border-radius: 17px;
            }}
            #previewStatusText {{
                color: {txt_secondary};
            }}
            #testFadeBtn {{
                background-color: transparent;
                color: {ORANGE};
                border: 1px solid {ORANGE};
                border-radius: 8px;
                padding: 5px 10px;
                font-weight: bold;
                font-size: 8pt;
            }}
            #testFadeBtn:hover {{
                background-color: {ORANGE};
                color: #FFFFFF;
            }}
            #cardDivider {{
                background-color: {card_border};
                border: none;
                height: 1px;
            }}
            #infoBox {{
                background-color: {card};
                border-left: 4px solid {ORANGE};
                border-top: none;
                border-right: none;
                border-bottom: none;
                border-radius: 8px;
            }}
            #infoBodyText {{
                font-size: 9pt;
                color: {txt_secondary};
                line-height: 15px;
            }}
            QSlider::groove:horizontal {{
                border: none;
                height: 6px;
                background: {slider_groove};
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ORANGE};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {ORANGE};
                width: 14px;
                height: 14px;
                margin-top: -4px;
                border-radius: 7px;
            }}
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {card_border};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {ORANGE};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
            }}
        """
        self.setStyleSheet(stylesheet)
        self.logo_pixmap = get_rounded_pixmap(LOGO_PATH, size=42, radius=8, padding=3)
        self.logo_label.setPixmap(self.logo_pixmap)
        
        # Trigger update of child listings to refresh themes of list items
        self.refresh_history()
        self.refresh_dictionary()
