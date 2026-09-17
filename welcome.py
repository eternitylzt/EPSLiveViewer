"""Empty-document landing page; no document renderer or background activity."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QScrollArea, QFrame, QAbstractItemView, QHeaderView)
from datetime import datetime
from pathlib import Path
from branding import logo_pixmap
from config import APP_NAME, APP_VERSION, PROJECT_URL
from i18n import current_language, bilingual as L


class WelcomePage(QScrollArea):
    open_requested = pyqtSignal()
    recent_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28,24,28,12)
        layout.addStretch(2)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(256))
        logo.setScaledContents(True)
        logo.setFixedSize(112,112)
        layout.addWidget(logo,0,Qt.AlignmentFlag.AlignCenter)
        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size:32px;font-weight:600;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(14)
        layout.addWidget(title)
        self.features = QLabel()
        self.features.setWordWrap(True)
        self.features.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.features.setStyleSheet("font-size:16px;padding:10px;")
        layout.addWidget(self.features)
        self.hint = QLabel()
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        layout.addSpacing(12)
        layout.addWidget(self.hint)
        self.open = QPushButton()
        self.open.setMinimumSize(200,42)
        self.open.clicked.connect(self.open_requested)
        row = QHBoxLayout()
        row.addStretch();row.addWidget(self.open);row.addStretch()
        layout.addSpacing(12)
        layout.addLayout(row)
        self.recent_title = QLabel()
        self.recent_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recents = QTableWidget(0,4)
        self.recents.setMinimumWidth(720)
        self.recents.setMaximumWidth(900)
        self.recents.setMinimumHeight(100)
        self.recents.setMaximumHeight(190)
        self.recents.verticalHeader().hide()
        self.recents.setShowGrid(False)
        self.recents.setAlternatingRowColors(True)
        self.recents.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.recents.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.recents.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.recents.horizontalHeader()
        header.setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        self.recents.itemActivated.connect(lambda item:self.recent_requested.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.recents.setToolTip(L("双击打开，或选中后按 Enter", "Double-click to open, or select and press Enter"))
        layout.addSpacing(12)
        layout.addWidget(self.recent_title)
        layout.addWidget(self.recents,0,Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(2)
        self.footer = QLabel()
        self.footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.footer.setOpenExternalLinks(True)
        self.footer.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.footer.setWordWrap(True)
        self.footer.setStyleSheet("font-size:12px;padding:12px;")
        layout.addWidget(self.footer)
        self.retranslate()

    @staticmethod
    def _size_text(size):
        if not isinstance(size,(int,float)) or size < 0:
            return "—"
        units=("B","KB","MB","GB")
        value=float(size)
        for unit in units:
            if value < 1024 or unit=="GB":
                return f"{value:.1f} {unit}" if unit!="B" else f"{int(value)} B"
            value/=1024

    def set_recent_files(self, entries, visible=True):
        self.recents.setRowCount(0)
        for row,entry in enumerate(entries[:10]):
            if isinstance(entry,str):
                path=Path(entry)
                try:size=path.stat().st_size
                except OSError:size=None
                opened=""
            else:
                path=Path(entry.get("path",""))
                size=entry.get("size")
                opened=str(entry.get("opened",""))
            try:
                moment=datetime.fromisoformat(opened).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                moment="—"
            values=(path.name,self._size_text(size),moment,str(path.parent))
            self.recents.insertRow(row)
            for column,value in enumerate(values):
                item=QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole,str(path))
                item.setToolTip(str(path))
                self.recents.setItem(row,column,item)
        has_entries=self.recents.rowCount()>0
        self.recent_title.setVisible(visible and has_entries)
        self.recents.setVisible(visible and has_entries)

    def retranslate(self):
        en = current_language() == "en"
        self.recents.setToolTip(L("双击打开，或选中后按 Enter", "Double-click to open, or select and press Enter"))
        self.recents.setHorizontalHeaderLabels(
            ("File","Size","Last opened","Location") if en else
            ("文件","大小","最近打开时间","文件位置"))
        self.recent_title.setText("Recent Files" if en else "最近打开")
        self.features.setText("Live preview · Vector export · Lightweight text editing" if en else
                              "实时预览 · 矢量导出 · 轻量文字编辑")
        self.hint.setText(("Open or drop an EPS / PS / PDF / PNG / JPG file\nCompare figures, adjust colors, and create animations."
                           if en else "打开或拖入 EPS / PS / PDF / PNG / JPG 文件\n对比科研图、调整配色、制作视频与动图"))
        self.open.setText("Open File…" if en else "打开文件…")
        self.footer.setText(f'{APP_VERSION} &nbsp; · &nbsp; Windows / macOS / Linux<br>'
                            f'<a href="{PROJECT_URL}">github.com/eternitylzt/EPSLiveViewer</a><br>'
                            'Zhentong Li &nbsp; · &nbsp; <a href="mailto:eternitylzt@gmail.com">eternitylzt@gmail.com</a>')
