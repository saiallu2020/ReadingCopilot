from __future__ import annotations
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTextEdit, QHBoxLayout, QSlider, QDialogButtonBox, QWidget, QFormLayout)
from PySide6.QtCore import Qt

class ProfileDialog(QDialog):
    def __init__(self, parent=None, global_profile: str = "", document_goal: str = "", density: float = 0.10):
        super().__init__(parent)
        self.setWindowTitle("Profile & Document Goal")
        self.resize(700, 600)

        self._global_profile_edit = QTextEdit()
        self._global_profile_edit.setPlainText(global_profile)
        self._global_profile_edit.setPlaceholderText("150-word background, skills, general learning/investment goals...")
        self._document_goal_edit = QTextEdit()
        self._document_goal_edit.setPlainText(document_goal)
        self._document_goal_edit.setPlaceholderText("150-word description of what you want from THIS document...")

        self._density_slider = QSlider(Qt.Orientation.Horizontal)
        self._density_slider.setMinimum(1)   # 1%
        self._density_slider.setMaximum(50)  # 50%
        self._density_slider.setValue(int(density * 100))
        self._density_label = QLabel(self._density_text())
        self._density_slider.valueChanged.connect(lambda _: self._density_label.setText(self._density_text()))

        form = QFormLayout()
        form.addRow(QLabel("Global Profile (≈150 words)"), self._global_profile_edit)
        form.addRow(QLabel("Document Goal (≈150 words)"), self._document_goal_edit)
        density_container = QWidget()
        h = QHBoxLayout(density_container)
        h.addWidget(self._density_slider)
        h.addWidget(self._density_label)
        form.addRow(QLabel("Highlight Density Target"), density_container)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _density_text(self) -> str:
        return f"{self._density_slider.value()}% of text (target)"

    def global_profile(self) -> str:
        return self._global_profile_edit.toPlainText().strip()

    def document_goal(self) -> str:
        return self._document_goal_edit.toPlainText().strip()

    def density(self) -> float:
        return self._density_slider.value() / 100.0
