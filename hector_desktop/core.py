"""Application state and visual styling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import anndata
    from hector.predictor_support import CoverageReport


@dataclass
class LineageGroup:
    """One lineage branch from the ontology grouping."""
    group_name: str
    group_cl_id: str
    color: str
    member_cl_ids: list
    total_count: int = 0


class AppState:
    """Mutable state container shared across all widgets.

    Not a QObject — widgets that modify state are responsible for
    triggering their own UI updates.
    """

    def __init__(self) -> None:
        self.adata: Optional[anndata.AnnData] = None
        self.adata_original: Optional[anndata.AnnData] = None
        self.adata_path: Optional[Path] = None
        self.data_source: str = ""

        self.predictor = None
        self.model_name: str = "human"

        self.detected_species: Optional[str] = None
        self.coverage_report: Optional["CoverageReport"] = None

        self.results_df: Optional[pd.DataFrame] = None

        self.is_busy: bool = False

        self.ontology_groups: list[LineageGroup] = []
        self.ontology_display_names: dict[str, str] = {}
        self.ontology_color_map: dict[str, str] = {}

    @property
    def has_data(self) -> bool:
        return self.adata is not None

    @property
    def has_predictions(self) -> bool:
        return (
            self.adata is not None
            and "hector_prediction" in self.adata.obs.columns
        )

    @property
    def has_umap(self) -> bool:
        return (
            self.adata is not None
            and "X_umap" in self.adata.obsm
        )

    @property
    def has_tsne(self) -> bool:
        return (
            self.adata is not None
            and "X_tsne" in self.adata.obsm
        )

    @property
    def has_embedding(self) -> bool:
        return self.has_umap or self.has_tsne

    @property
    def active_embedding_key(self) -> str | None:
        """Return the obsm key for the most recently computed embedding."""
        if self.adata is None:
            return None
        # Prefer whichever was computed last (stored by workers)
        return getattr(self, "_active_embedding_key", None)

    @active_embedding_key.setter
    def active_embedding_key(self, value: str) -> None:
        self._active_embedding_key = value

    @property
    def n_cells(self) -> int:
        return self.adata.shape[0] if self.adata is not None else 0

    @property
    def n_genes(self) -> int:
        return self.adata.shape[1] if self.adata is not None else 0

    def umap_coords(self) -> Optional[np.ndarray]:
        if self.has_umap:
            return np.asarray(self.adata.obsm["X_umap"])
        return None

    def embedding_coords(self) -> Optional[np.ndarray]:
        """Return coordinates for the active embedding, if any."""
        key = self.active_embedding_key
        if key and self.adata is not None and key in self.adata.obsm:
            return np.asarray(self.adata.obsm[key])
        return self.umap_coords()


from pathlib import Path as _Path

_RES_DIR = _Path(__file__).resolve().parent / "resources"
_CHEVRON_DOWN = (_RES_DIR / "chevron-down.svg").as_posix()

ACCENT = "#4F6BED"
ACCENT_DARK = "#3D54CC"
ACCENT_LIGHT = "#E8EDFD"
SUCCESS = "#1DB88A"
SUCCESS_DARK = "#17A07A"
DANGER = "#DC2626"
WARNING = "#F59E0B"
AMBER = "#F59E0B"

BG = "#FAFBFC"
PLOT_BG = "#FAFAFA"
PANEL = "#FFFFFF"
SIDEBAR_BG = "#FFFFFF"
BORDER = "#E5E8EE"
BORDER_SOFT = "#EEF1F5"
STATUS_BG = "#1E293B"

INK = "#0F172A"
INK_2 = "#475569"
INK_3 = "#94A3B8"

import sys as _sys

if _sys.platform == "win32":
    FONT_FAMILY = "'Segoe UI', 'Arial'"
    MONO_FAMILY = "'Cascadia Mono', 'Consolas'"
else:
    FONT_FAMILY = "'Helvetica Neue', 'Helvetica'"
    MONO_FAMILY = "'Menlo', 'Courier New'"

CELL_TYPE_PALETTE = [
    "#E15759", "#4E79A7", "#59A14F", "#F28E2B", "#B07AA1",
    "#76B7B2", "#EE9DA7", "#9C755F", "#EDC948", "#9AA3AB",
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
    "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9",
    "#D35400", "#1ABC9C", "#8E44AD", "#2ECC71", "#E74C3C",
    "#3498DB", "#F39C12", "#16A085", "#C0392B", "#27AE60",
    "#2980B9", "#8B4513", "#FF69B4", "#00CED1", "#FFD700",
    "#DA70D6", "#00FA9A", "#CD853F", "#7B68EE", "#20B2AA",
]


def build_stylesheet() -> str:
    return f"""
    /* ── Global ── */
    QMainWindow, QWidget {{
        background: {BG};
        font-family: {FONT_FAMILY};
        font-size: 13px;
        color: {INK};
    }}

    /* ── Menu bar ── */
    QMenuBar {{
        background: {PANEL};
        border-bottom: 1px solid {BORDER};
        padding: 2px 8px;
        font-size: 12px;
        color: {INK_2};
    }}
    QMenuBar::item {{
        padding: 4px 10px;
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background: {BORDER_SOFT};
    }}
    QMenu {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 28px 6px 12px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background: {ACCENT};
        color: white;
    }}

    /* ── Buttons ── */
    QPushButton {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 500;
        color: {INK};
    }}
    QPushButton:hover {{
        background: {BORDER_SOFT};
        border-color: #D0D5DD;
    }}
    QPushButton:pressed {{
        background: {BORDER};
    }}
    QPushButton:disabled {{
        color: {INK_3};
        background: {BORDER_SOFT};
    }}
    QPushButton[cssClass="accent"] {{
        background: {ACCENT};
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        font-size: 13px;
        padding: 8px 16px;
    }}
    QPushButton[cssClass="accent"]:hover {{
        background: {ACCENT_DARK};
    }}
    QPushButton[cssClass="accent"]:disabled {{
        background: #B0BEC5;
        color: #F0F0F0;
    }}
    QPushButton[cssClass="success"] {{
        background: {SUCCESS};
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        font-size: 13px;
        padding: 8px 16px;
    }}
    QPushButton[cssClass="success"]:hover {{
        background: {SUCCESS_DARK};
    }}
    QPushButton[cssClass="success"]:disabled {{
        background: #B0BEC5;
        color: #F0F0F0;
    }}

    /* ── Inputs ── */
    QLineEdit, QSpinBox, QDoubleSpinBox {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 5px;
        padding: 5px 8px;
        font-size: 12px;
        color: {INK};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {ACCENT};
    }}
    QComboBox {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 5px;
        padding: 5px 28px 5px 8px;
        font-size: 12px;
        color: {INK};
        min-height: 18px;
    }}
    QComboBox:focus {{
        border-color: {ACCENT};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 28px;
        border: none;
        border-left: 1px solid {BORDER};
    }}
    QComboBox::down-arrow {{
        image: url({_CHEVRON_DOWN});
        width: 10px;
        height: 10px;
    }}
    QComboBox QAbstractItemView {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 4px;
        selection-background-color: {ACCENT_LIGHT};
        selection-color: {INK};
    }}

    /* ── Tab bar ── */
    QTabWidget::pane {{
        border: none;
        background: {PANEL};
    }}
    QTabBar {{
        background: transparent;
    }}
    QTabBar::tab {{
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: 500;
        color: {INK_3};
    }}
    QTabBar::tab:selected {{
        color: {ACCENT};
        border-bottom-color: {ACCENT};
        font-weight: 600;
    }}
    QTabBar::tab:hover:!selected {{
        color: {INK_2};
    }}

    /* ── Scroll area ── */
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        width: 6px;
        background: transparent;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {INK_3};
        border-radius: 3px;
        min-height: 30px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    /* ── Table ── */
    QTableView {{
        background: {PANEL};
        border: none;
        gridline-color: {BORDER_SOFT};
        font-size: 12px;
    }}
    QTableView::item {{
        padding: 4px 8px;
    }}
    QTableView::item:selected {{
        background: {ACCENT_LIGHT};
        color: {INK};
    }}
    QHeaderView::section {{
        background: {BG};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: 6px 8px;
        font-size: 11px;
        font-weight: 600;
        color: {INK_2};
    }}

    /* ── Progress bar ── */
    QProgressBar {{
        background: #334155;
        border: none;
        border-radius: 3px;
        height: 6px;
        text-align: center;
        font-size: 1px;
    }}
    QProgressBar::chunk {{
        background: {ACCENT};
        border-radius: 3px;
    }}

    /* ── Splitter ── */
    QSplitter::handle {{
        background: {BORDER};
        width: 3px;
    }}
    QSplitter::handle:hover {{
        background: {ACCENT};
    }}

    /* ── Group box (sidebar sections) ── */
    QGroupBox {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {BORDER_SOFT};
        margin-top: 8px;
        padding-top: 20px;
        font-size: 11px;
        font-weight: 700;
        color: {INK_2};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 4px;
        color: {INK_2};
        letter-spacing: 0.5px;
    }}

    /* ── Labels ── */
    QLabel[cssClass="field-label"] {{
        font-size: 11px;
        color: {INK_3};
        font-weight: 400;
        padding-bottom: 2px;
    }}
    QLabel[cssClass="section-subtitle"] {{
        font-size: 11px;
        color: {INK_3};
    }}
    QLabel[cssClass="info-value"] {{
        font-family: {MONO_FAMILY};
        font-size: 12px;
        color: {INK};
    }}
    QLabel[cssClass="status-text"] {{
        font-family: {MONO_FAMILY};
        font-size: 11px;
        color: #CBD5E1;
    }}

    /* ── Workflow step ── */
    QWidget[cssClass="workflow-step"] {{
        background: transparent;
        border-bottom: 1px solid {BORDER_SOFT};
    }}
    QWidget[cssClass="workflow-step-dimmed"] {{
        background: transparent;
        border-bottom: 1px solid {BORDER_SOFT};
    }}

    /* ── Step badge ── */
    QLabel[cssClass="badge-pending"] {{
        background: #E2E8F0;
        color: #94A3B8;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel[cssClass="badge-active"] {{
        background: {ACCENT};
        color: white;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel[cssClass="badge-running"] {{
        background: {AMBER};
        color: white;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel[cssClass="badge-done"] {{
        background: {SUCCESS};
        color: white;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 700;
    }}

    /* ── Step title ── */
    QLabel[cssClass="step-title"] {{
        font-size: 13px;
        font-weight: 600;
        color: {INK};
        letter-spacing: 0.5px;
    }}

    /* ── Success chip ── */
    QFrame[cssClass="success-chip"] {{
        background: #ECFDF5;
        border: 1px solid #A7F3D0;
        border-radius: 8px;
    }}

    /* ── Advanced disclosure ── */
    QPushButton[cssClass="disclosure"] {{
        background: transparent;
        border: none;
        font-size: 11px;
        color: {INK_3};
        text-align: left;
        padding: 4px 0;
    }}
    QPushButton[cssClass="disclosure"]:hover {{
        color: {INK_2};
    }}

    /* ── Wordmark ── */
    QLabel[cssClass="wordmark"] {{
        font-size: 20px;
        font-weight: 700;
        color: {ACCENT};
    }}
    QLabel[cssClass="wordmark-tagline"] {{
        font-size: 11px;
        color: {INK_3};
    }}
    """
