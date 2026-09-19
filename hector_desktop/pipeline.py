"""Analysis workers and workflow widgets."""

from __future__ import annotations

import io
import re
import sys
from collections import Counter
from typing import Callable, Optional

import numpy as np
import pandas as pd



class _Tee(io.TextIOBase):
    """Forward writes to a parser callback and to the original stream."""

    def __init__(self, original, on_text: Callable[[str], None]) -> None:
        self._original = original
        self._on_text = on_text

    def write(self, text: str) -> int:
        self._on_text(text)
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass


class TqdmCapture:
    """Capture progress output from a wrapped operation."""

    _FRAC_RE = re.compile(r"(\d+)/(\d+)")
    _DESC_RE = re.compile(r"^\s*(.+?):\s*\d+%")

    def __init__(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._progress_cb = progress_callback
        self._log_cb = log_callback

    def _handle(self, text: str) -> None:
        if self._progress_cb and "\r" in text:
            m = self._FRAC_RE.search(text)
            if m:
                d = self._DESC_RE.search(text)
                desc = d.group(1).strip() if d else ""
                self._progress_cb(int(m.group(1)), int(m.group(2)), desc)
        if self._log_cb:
            stripped = text.strip()
            if stripped and "\r" not in text:
                self._log_cb(stripped)

    def __enter__(self) -> "TqdmCapture":
        self._orig_out, self._orig_err = sys.stdout, sys.stderr
        sys.stdout = _Tee(self._orig_out, self._handle)
        sys.stderr = _Tee(self._orig_err, self._handle)
        return self

    def __exit__(self, *exc) -> bool:
        sys.stdout, sys.stderr = self._orig_out, self._orig_err
        return False


_PREDICT_WINDOWS = {
    "encoding": (5, 70),
    "predicting": (75, 10),
    "knn": (85, 13),
}


def _normalize_predict_desc(desc: str) -> str:
    d = (desc or "").strip().lower()
    if "encod" in d:
        return "encoding"
    if "predict" in d:
        return "predicting"
    if "knn" in d:
        return "knn"
    return ""


def _predict_progress(desc: str, current: int, total: int) -> int | None:
    """Map a prediction tqdm update to the 0–100 bar, or None if unrecognized."""
    key = _normalize_predict_desc(desc)
    if key not in _PREDICT_WINDOWS:
        return None
    base, span = _PREDICT_WINDOWS[key]
    frac = min(max(current, 0) / max(total, 1), 1.0)
    return int(round(base + frac * span))


_PREDICT_LOG_MILESTONES = (
    ("encoder loaded", 1),
    ("Loaded Memory Bank", 2),
    ("Model loaded successfully", 3),
    ("Making predictions on", 4),
    ("Step 2", 5),
)


def _predict_log_milestone(message: str) -> int | None:
    """Map a model message to a progress milestone."""
    for needle, pct in _PREDICT_LOG_MILESTONES:
        if needle in message:
            return pct
    return None


def _tsne_iter_progress(message: str, total: int = 1000) -> int | None:
    """Parse sklearn t-SNE '[t-SNE] Iteration N:' lines into 0–100, else None."""
    import re as _re
    m = _re.search(r"Iteration\s+(\d+)\s*:", message)
    if not m:
        return None
    frac = min(int(m.group(1)) / max(total, 1), 1.0)
    return int(round(frac * 100))


def make_instrumented_hector(log_callback: Optional[Callable[[str], None]] = None):
    """Create an InstrumentedHECTOR class that forwards _log to a callback."""
    import hector

    class InstrumentedHECTOR(hector.HECTOR):
        def __init__(self, *args, _log_callback=None, **kwargs):
            self.__log_callback = _log_callback
            super().__init__(*args, **kwargs)

        def _log(self, message: str):
            if self.__log_callback:
                self.__log_callback(message)
            if sys.stdout is not None:
                super()._log(message)

    return InstrumentedHECTOR


def extract_ontology_groups(adata):
    """Build display groups from stored ontology results."""
    from hector_desktop.core import LineageGroup
    from hector.trajectory_ontology import ADAPTIVE_PALETTE, _generate_leaf_colors

    simplified = adata.uns.get('hector_simplified')
    if simplified is None:
        return [], {}, {}

    simplification_map = simplified.get('simplification_map', {})
    if not simplification_map:
        return [], {}, {}

    predicted_labels = adata.obs.get('hector_prediction')
    if predicted_labels is None:
        return [], {}, {}
    label_counts = Counter(predicted_labels)

    group_members: dict[str, list[str]] = {}
    for original, group_label in simplification_map.items():
        group_members.setdefault(group_label, []).append(original)

    raw_groups: list[tuple[str, list[str], int]] = []
    for group_label, members in group_members.items():
        total = sum(label_counts.get(m, 0) for m in members)
        raw_groups.append((group_label, members, total))
    raw_groups.sort(key=lambda g: g[2], reverse=True)

    display_names: dict[str, str] = {}
    color_map: dict[str, str] = {}
    groups: list[LineageGroup] = []

    for palette_idx, (group_label, members, total_count) in enumerate(raw_groups):
        if total_count == 0:
            continue

        group_name = group_label
        if not group_name.endswith('s'):
            group_name += 's'

        base_color = ADAPTIVE_PALETTE[palette_idx % len(ADAPTIVE_PALETTE)]
        leaf_colors = _generate_leaf_colors(base_color, len(members))
        for member, lc in zip(members, leaf_colors):
            color_map[member] = lc
            display_names[member] = member

        groups.append(LineageGroup(
            group_name=group_name,
            group_cl_id=group_label,
            color=base_color,
            member_cl_ids=members,
            total_count=total_count,
        ))

    return groups, display_names, color_map


"""QThread workers for long-running HECTOR operations."""


import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal


@dataclass
class GateOutcome:
    """Result of running the reference-gene coverage gate after a data load.

    Two-branch decision based on whether Ensembl IDs are present anywhere in
    ``adata.var`` or ``adata.var.index``:

      - **Found** → ``species_detected`` and ``coverage_report`` are set.
        The UI checks ``coverage_report.pct_found`` against the 90% threshold.
      - **Not found** → ``mapping_needed=True``. The UI asks the user to map
        symbols → Ensembl via ``GeneMappingWorker``.
    """

    species_detected: Optional[str] = None
    coverage_report: object = None  # CoverageReport (avoid runtime import here)
    mapping_needed: bool = False
    fatal_reason: Optional[str] = None  # set when the species' reference parquet is missing
    mapping_report: object = None  # filled in by GeneMappingWorker


def _run_gate(adata) -> GateOutcome:
    """Find Ensembl IDs anywhere in adata; compute coverage or signal need-to-map."""
    from hector.predictor_support import (
        _compute_coverage,
        _find_ensembl_id_array,
        _species_from_ensembl_ids,
    )

    found = _find_ensembl_id_array(adata)
    if found is None:
        return GateOutcome(mapping_needed=True)

    species = _species_from_ensembl_ids(found)
    try:
        report = _compute_coverage(adata, species)
    except (FileNotFoundError, ValueError) as exc:
        return GateOutcome(
            species_detected=species,
            fatal_reason=f"reference unavailable: {exc}",
        )
    return GateOutcome(species_detected=species, coverage_report=report)


def _resolve_cellranger_dir(path: str) -> str:
    """If *path* is a Cell Ranger parent (contains genome subdirs), return the subdir."""
    p = Path(path)
    if (p / "matrix.mtx").exists() or (p / "matrix.mtx.gz").exists():
        return path
    for child in sorted(p.iterdir()):
        if child.is_dir() and ((child / "matrix.mtx").exists() or (child / "matrix.mtx.gz").exists()):
            return str(child)
    return path


def _load_cellranger(path: str):
    """Load Cell Ranger data, trying hector first then falling back to scanpy."""
    try:
        from hector.predictor_support import load_cellranger_data
        return load_cellranger_data(path)
    except ImportError:
        import scanpy as sc
        if path.endswith(".h5"):
            return sc.read_10x_h5(path)
        return sc.read_10x_mtx(_resolve_cellranger_dir(path))


def _log_traceback(tb: str) -> None:
    """Record an unexpected worker error."""
    try:
        log_path = Path.home() / "hector_desktop_errors.log"
        with log_path.open("a") as fp:
            fp.write("\n--- worker error ---\n")
            fp.write(tb)
    except Exception:
        pass


def _worker_error(message: str) -> str:
    _log_traceback(traceback.format_exc())
    return message


class DataLoadWorker(QThread):
    """Loads h5ad or Cell Ranger data and runs the coverage gate on a worker thread."""

    finished = Signal(object, object)  # (adata, GateOutcome)
    error = Signal(str)

    def __init__(self, path: str, source: str, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._source = source

    def run(self) -> None:
        try:
            if self._source == "cellranger":
                adata = _load_cellranger(self._path)
            else:
                import anndata
                adata = anndata.read_h5ad(self._path)
            outcome = _run_gate(adata)
            self.finished.emit(adata, outcome)
        except Exception:
            self.error.emit(_worker_error("Data could not be loaded."))


class GeneMappingWorker(QThread):
    """Adds an Ensembl-ID column to adata.var in place and re-runs the gate."""

    finished = Signal(object, object)  # (adata, GateOutcome)
    error = Signal(str)

    def __init__(self, adata, species: str, parent=None) -> None:
        super().__init__(parent)
        self._adata = adata
        self._species = species

    def run(self) -> None:
        try:
            import hector

            mapping_report = hector.map_gene_symbols(self._adata, species=self._species)
            outcome = _run_gate(self._adata)
            outcome.mapping_report = mapping_report
            self.finished.emit(self._adata, outcome)
        except Exception:
            self.error.emit(_worker_error("Gene IDs could not be mapped."))


class ModelLoadWorker(QThread):
    """Downloads / loads a HECTOR model."""

    finished = Signal(object)
    error = Signal(str)
    log_message = Signal(str)

    def __init__(self, model_name: str, parent=None) -> None:
        super().__init__(parent)
        self._model_name = model_name

    def run(self) -> None:
        try:

            InstrumentedHECTOR = make_instrumented_hector()
            predictor = InstrumentedHECTOR(
                self._model_name,
                verbose=True,
                auto_download=True,
                _log_callback=lambda msg: self.log_message.emit(msg),
            )
            self.finished.emit(predictor)
        except Exception:
            self.error.emit(_worker_error("The model could not be loaded."))


class PredictWorker(QThread):
    """Runs prediction (model load + predict + write_predictions)."""

    finished = Signal(object, object, object)  # (results_df, predictor, adata)
    error = Signal(str)
    progress = Signal(int)
    log_message = Signal(str)

    def __init__(
        self,
        adata,
        *,
        model_name: str = "human",
        predict_kwargs: dict | None = None,
        qc_params: dict | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._adata = adata
        self._model_name = model_name
        self._predict_kwargs = predict_kwargs or {}
        self._qc_params = qc_params

    def run(self) -> None:
        try:
            self.log_message.emit("Loading model…")

            def on_log_milestone(message):
                self._on_log(message)
                val = _predict_log_milestone(message)
                if val is not None:
                    self.progress.emit(val)

            InstrumentedHECTOR = make_instrumented_hector()
            predictor = InstrumentedHECTOR(
                self._model_name,
                verbose=True,
                auto_download=True,
                _log_callback=on_log_milestone,
            )

            self._assert_reference_in_sync(predictor)

            resolved = predictor._resolve_expression_source(self._adata)
            source_name = resolved["name"]

            self.log_message.emit("Preparing data…")

            import anndata as _ad
            self._gui_adata = self._adata
            self._adata = _ad.AnnData(
                X=self._gui_adata.X,
                obs=self._gui_adata.obs.copy(),
                var=self._gui_adata.var.copy(),
                uns=dict(self._gui_adata.uns) if self._gui_adata.uns else {},
                obsm={k: v for k, v in self._gui_adata.obsm.items()},
                layers={k: v for k, v in self._gui_adata.layers.items()
                        if source_name == f"adata.layers['{k}']"},
            )
            if source_name == "adata.raw.X" and self._gui_adata.raw is not None:
                _raw_proxy = _ad.AnnData(
                    X=self._gui_adata.raw.X, var=self._gui_adata.raw.var,
                )
                self._adata.raw = _raw_proxy
                del _raw_proxy

            if self._qc_params is not None:
                import hector
                hector.filter_cells(self._adata, subset=True, **self._qc_params)

            self.log_message.emit("Running prediction…")

            def on_tqdm(current, total, desc):
                val = _predict_progress(desc, current, total)
                if val is not None:
                    self.progress.emit(val)

            with TqdmCapture(progress_callback=on_tqdm, log_callback=on_log_milestone):
                results_df = predictor.predict(
                    self._adata,
                    label_format="name",
                    **self._predict_kwargs,
                )

            self.progress.emit(98)
            self.log_message.emit("Writing predictions to AnnData…")
            predictor.write_predictions(self._adata, results_df)

            import hector
            hector.simplify_ontology_tree(
                predictor, self._adata,
                compute_transitions=False,
                min_cells_number=1,
                label_format="name",
            )
            self.progress.emit(100)

            del self._gui_adata
            import gc; gc.collect()

            self.finished.emit(results_df, predictor, self._adata)
        except Exception:
            if hasattr(self, "_gui_adata"):
                del self._gui_adata
            self.error.emit(_worker_error("Prediction could not be completed."))

    def _assert_reference_in_sync(self, predictor) -> None:
        """Refuse to predict if the bundled reference parquet disagrees with
        ``predictor.gene_ids`` — guards against the live model checkpoint
        updating without a matching package rebuild.
        """
        from hector.predictor_support import _load_reference_genes

        species = "human" if self._model_name == "human" else "mouse"
        try:
            ref = _load_reference_genes(species)
        except (FileNotFoundError, ValueError):
            return
        live = [str(g).split(".", 1)[0] for g in predictor.gene_ids]
        if live != ref:
            raise RuntimeError(
                f"Reference gene list mismatch for {species}: live model checkpoint "
                f"({len(live)} genes) disagrees with the bundled parquet "
                f"({len(ref)} genes). The model may have updated after this "
                f"version of HECTOR Desktop shipped. Please update the app."
            )

    def _on_log(self, message: str) -> None:
        self.log_message.emit(message)


class ProjectWorker(QThread):
    """Runs embedding projection (UMAP or t-SNE) in a background thread."""

    finished = Signal(str)  # emits the method name ("umap" or "tsne")
    error = Signal(str)
    progress = Signal(int)
    log_message = Signal(str)

    def __init__(
        self,
        predictor,
        adata,
        *,
        method: str = "umap",
        backend: str = "mlx",
        project_kwargs: dict | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._predictor = predictor
        self._adata = adata
        self._method = method.lower()
        self._backend = backend.lower()
        self._project_kwargs = project_kwargs or {}

    def run(self) -> None:
        try:

            display = "UMAP" if self._method == "umap" else "t-SNE"
            self.log_message.emit(f"Computing {display} ({self._backend})…")

            def on_tqdm(current, total, desc):
                frac = min(max(current, 0) / max(total, 1), 1.0)
                self.progress.emit(int(round(frac * 100)))

            def on_log(message):
                self.log_message.emit(message)
                if self._method == "tsne":
                    val = _tsne_iter_progress(message)
                    if val is not None:
                        self.progress.emit(val)

            with TqdmCapture(progress_callback=on_tqdm, log_callback=on_log):
                self._predictor.reduce_dimensions(
                    self._adata,
                    method=self._method,
                    backend=self._backend,
                    **self._project_kwargs,
                )

            self.progress.emit(100)
            self.finished.emit(self._method)
        except Exception:
            self.error.emit(_worker_error("Embedding could not be computed."))


class UpdateCheckWorker(QThread):
    """Lightweight background check for model updates on HuggingFace."""

    update_available = Signal(dict)
    no_update = Signal()
    error = Signal(str)

    def __init__(self, model_name: str = "human", parent=None) -> None:
        super().__init__(parent)
        self._model_name = model_name

    def run(self) -> None:
        try:
            import hector
            result = hector.check_for_update(self._model_name)
            if result["update_available"]:
                self.update_available.emit(result)
            else:
                self.no_update.emit()
        except Exception:
            self.error.emit(_worker_error("Model updates could not be checked."))


class ModelDownloadWorker(QThread):
    """Downloads the latest model from HuggingFace."""

    finished = Signal()
    error = Signal(str)
    log_message = Signal(str)

    def __init__(self, model_name: str = "human", parent=None) -> None:
        super().__init__(parent)
        self._model_name = model_name

    def run(self) -> None:
        try:
            import hector
            self.log_message.emit("Downloading model update…")
            hector.download_model(self._model_name, force_download=True)
            self.log_message.emit("Model updated successfully.")
            self.finished.emit()
        except Exception:
            self.error.emit(_worker_error("The model update could not be downloaded."))


from enum import Enum, auto

from PySide6.QtCore import Property, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from hector_desktop import core as style


class StepState(Enum):
    PENDING = auto()
    ACTIVE = auto()
    RUNNING = auto()
    DONE = auto()


class ToggleSwitch(QWidget):
    """iOS-style toggle switch."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._checked = checked
        self._thumb_x = 22.0 if checked else 2.0
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, v: bool) -> None:
        if v == self._checked:
            return
        self._checked = v
        anim = QPropertyAnimation(self, b"thumb_x", self)
        anim.setDuration(150)
        anim.setStartValue(self._thumb_x)
        anim.setEndValue(22.0 if v else 2.0)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self.toggled.emit(v)

    def setEnabled(self, v: bool) -> None:
        super().setEnabled(v)
        self.update()

    def _get_thumb_x(self) -> float:
        return self._thumb_x

    def _set_thumb_x(self, x: float) -> None:
        self._thumb_x = x
        self.update()

    thumb_x = Property(float, _get_thumb_x, _set_thumb_x)

    def mousePressEvent(self, ev) -> None:
        self.setChecked(not self._checked)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track_color = QColor(style.ACCENT) if self._checked else QColor("#CBD5E1")
        if not self.isEnabled():
            track_color = QColor("#E2E8F0")
        p.setBrush(track_color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRect(0, 0, 44, 24), 12, 12)
        thumb_color = QColor("white")
        if not self.isEnabled():
            thumb_color = QColor("#F1F5F9")
        p.setBrush(thumb_color)
        p.drawEllipse(int(self._thumb_x), 2, 20, 20)
        p.end()


class WorkflowStep(QWidget):
    """A numbered workflow step with state machine, progress bar, and success chip."""

    rerun_requested = Signal()

    def __init__(self, number: int, title: str, *, keep_content_on_done: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._number = number
        self._title = title
        self._state = StepState.PENDING
        self._keep_content_on_done = keep_content_on_done

        self.setStyleSheet(f"background: transparent; border-bottom: 1px solid {style.BORDER_SOFT};")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(0)

        header = QHBoxLayout()
        header.setSpacing(10)

        self._badge = QLabel(str(number))
        self._badge.setFixedSize(24, 24)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._badge)

        self._title_label = QLabel(title.upper())
        self._title_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {style.INK}; letter-spacing: 0.5px;"
        )
        header.addWidget(self._title_label)
        header.addStretch()

        main_layout.addLayout(header)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 12, 0, 0)
        self._content_layout.setSpacing(6)
        main_layout.addWidget(self._content)

        self._progress_widget = QFrame()
        self._progress_widget.setFixedHeight(44)
        self._progress_widget.setStyleSheet(
            f"QFrame {{ background: {style.ACCENT}; border-radius: 8px; }}"
        )
        progress_layout = QVBoxLayout(self._progress_widget)
        progress_layout.setContentsMargins(12, 6, 12, 6)
        progress_layout.setSpacing(4)

        self._progress_label = QLabel("Running…")
        self._progress_label.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: white; background: transparent; border: none;"
        )
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_layout.addWidget(self._progress_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,0.2); border: none; border-radius: 2px; }"
            "QProgressBar::chunk { background: rgba(255,255,255,0.5); border-radius: 2px; }"
        )
        progress_layout.addWidget(self._progress_bar)

        self._progress_widget.hide()
        main_layout.addWidget(self._progress_widget)

        self._success_chip = QFrame()
        self._success_chip.setStyleSheet(
            "QFrame { background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 8px; }"
        )
        chip_layout = QHBoxLayout(self._success_chip)
        chip_layout.setContentsMargins(12, 8, 8, 8)
        chip_layout.setSpacing(8)

        check = QLabel("✓")
        check.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {style.SUCCESS}; background: transparent; border: none;")
        chip_layout.addWidget(check)

        self._chip_text = QLabel("")
        self._chip_text.setStyleSheet("font-size: 11px; color: #166534; background: transparent; border: none;")
        self._chip_text.setWordWrap(True)
        chip_layout.addWidget(self._chip_text, 1)

        rerun_btn = QPushButton("Re-run")
        rerun_btn.setFixedSize(72, 28)
        rerun_btn.setToolTip("Re-run this step")
        rerun_btn.setStyleSheet(
            f"QPushButton {{ border-radius: 6px; border: 1px solid #BBF7D0; "
            f"background: white; color: {style.SUCCESS}; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: #F0FDF4; }}"
        )
        rerun_btn.clicked.connect(self.rerun_requested.emit)
        chip_layout.addWidget(rerun_btn)

        self._success_chip.hide()
        main_layout.addWidget(self._success_chip)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        self.set_state(StepState.PENDING)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    @property
    def state(self) -> StepState:
        return self._state

    def set_state(self, state: StepState) -> None:
        self._state = state
        badge_base = "font-size: 12px; font-weight: 700; border-radius: 12px;"

        if state == StepState.PENDING:
            self._badge.setText(str(self._number))
            self._badge.setStyleSheet(f"{badge_base} background: #E2E8F0; color: #94A3B8;")
            self._opacity.setOpacity(0.4)
            self._content.show()
            self._progress_widget.hide()
            self._success_chip.hide()
            self._set_content_enabled(False)

        elif state == StepState.ACTIVE:
            self._badge.setText(str(self._number))
            self._badge.setStyleSheet(f"{badge_base} background: {style.ACCENT}; color: white;")
            self._opacity.setOpacity(1.0)
            self._content.show()
            self._progress_widget.hide()
            self._success_chip.hide()
            self._set_content_enabled(True)

        elif state == StepState.RUNNING:
            self._badge.setText(str(self._number))
            self._badge.setStyleSheet(f"{badge_base} background: {style.AMBER}; color: white;")
            self._opacity.setOpacity(1.0)
            if self._keep_content_on_done:
                self._content.show()
                self._set_content_enabled(False)
            else:
                self._content.hide()
            self._progress_widget.show()
            self._success_chip.hide()

        elif state == StepState.DONE:
            self._badge.setText("✓")
            self._badge.setStyleSheet(f"{badge_base} background: {style.SUCCESS}; color: white;")
            self._opacity.setOpacity(1.0)
            if self._keep_content_on_done:
                self._content.show()
                self._set_content_enabled(True)
            else:
                self._content.hide()
            self._progress_widget.hide()
            if self._keep_content_on_done:
                self._success_chip.hide()
            else:
                self._success_chip.show()

    def set_progress_text(self, text: str) -> None:
        self._progress_label.setText(text)

    def set_success_text(self, text: str) -> None:
        self._chip_text.setText(text)

    def _set_content_enabled(self, enabled: bool) -> None:
        for i in range(self._content_layout.count()):
            item = self._content_layout.itemAt(i)
            if item and item.widget():
                item.widget().setEnabled(enabled)
            elif item and item.layout():
                for j in range(item.layout().count()):
                    sub = item.layout().itemAt(j)
                    if sub and sub.widget():
                        sub.widget().setEnabled(enabled)


import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hector_desktop import core as style
from hector_desktop.core import AppState

if TYPE_CHECKING:
    import anndata


_DEFAULT_QC = {"min_counts": 500, "min_genes": 200, "max_mito_pct": 10.0}


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"font-size: 11px; color: {style.INK_3}; font-weight: 400; padding-bottom: 2px;")
    return lbl


class WorkflowPanel(QWidget):
    open_h5ad_requested = Signal()
    open_cellranger_requested = Signal()
    run_prediction_requested = Signal()
    run_umap_requested = Signal()          # kept for back-compat
    run_embedding_requested = Signal(str)  # emits method name ("umap" or "tsne")

    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self._has_dataset = False
        self.setMinimumWidth(240)
        self.setMaximumWidth(480)
        self.setStyleSheet(f"background: {style.SIDEBAR_BG};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        wordmark_frame = QWidget()
        wordmark_frame.setStyleSheet(
            f"border-bottom: 1px solid {style.BORDER_SOFT}; background: {style.SIDEBAR_BG};"
        )
        wm_layout = QVBoxLayout(wordmark_frame)
        wm_layout.setContentsMargins(20, 20, 20, 16)
        wm_layout.setSpacing(2)

        title = QLabel("HECTOR")
        title.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {style.ACCENT};")
        wm_layout.addWidget(title)

        tagline = QLabel("Hierarchical Embedding and Contrastive Training for\nOntology-guided Recognition")
        tagline.setStyleSheet(f"font-size: 11px; color: {style.INK_3};")
        wm_layout.addWidget(tagline)

        outer.addWidget(wordmark_frame)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        self._steps_layout = QVBoxLayout(content)
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        self._steps_layout.setSpacing(0)

        self._build_step1_load_data()
        self._build_step2_predict()
        self._build_step3_visualize()

        self._steps_layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # Step 1 starts active, others pending
        self.step1.set_state(StepState.ACTIVE)


    def _build_step1_load_data(self) -> None:
        self.step1 = WorkflowStep(1, "Load Data", keep_content_on_done=True)
        lay = self.step1.content_layout

        # Source toggle
        toggle_row = QHBoxLayout()
        self.btn_h5ad = QPushButton("h5ad file")
        self.btn_cr = QPushButton("Cell Ranger folder")
        for btn in (self.btn_h5ad, self.btn_cr):
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 11px; border-radius: 4px; padding: 0 10px; }}"
                f"QPushButton:checked {{ background: {style.ACCENT}; color: white; border: none; }}"
            )
        self.btn_cr.setChecked(True)
        self.btn_h5ad.clicked.connect(lambda: self._set_source("h5ad"))
        self.btn_cr.clicked.connect(lambda: self._set_source("cellranger"))
        toggle_row.addWidget(self.btn_cr)
        toggle_row.addWidget(self.btn_h5ad)
        lay.addLayout(toggle_row)

        # File path
        lay.addWidget(_field_label("File path"))
        path_row = QHBoxLayout()
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setPlaceholderText("No file selected")
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.setFixedWidth(72)
        self.browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(self.file_path_edit, 1)
        path_row.addWidget(self.browse_btn)
        lay.addLayout(path_row)

        # Info card
        self.info_card = QFrame()
        self.info_card.setStyleSheet(
            f"QFrame {{ background: {style.ACCENT_LIGHT}; border: 1px solid {style.ACCENT}; "
            f"border-radius: 6px; padding: 2px 6px; }}"
        )
        self.info_card.hide()
        info_grid = QGridLayout(self.info_card)
        info_grid.setSpacing(0)
        info_grid.setContentsMargins(2, 0, 2, 0)

        self._info_header = QLabel("Dataset loaded")
        self._info_header.setStyleSheet(
            f"font-weight: 600; font-size: 11px; color: {style.ACCENT};"
        )
        info_grid.addWidget(self._info_header, 0, 0, 1, 4)

        self._info_labels = {}
        # (name, row, col, value_col_span) — coverage's long text spans the
        # remaining columns so it doesn't force column 1 wider than the genes
        # and layout cells need.
        fields = [
            ("cells", 1, 0, 1),
            ("genes", 1, 2, 1),
            ("size", 2, 0, 1),
            ("layout", 2, 2, 1),
            ("coverage", 3, 0, 3),
        ]
        for name, row, col, val_span in fields:
            key_lbl = QLabel(name)
            key_lbl.setStyleSheet(f"font-size: 11px; color: {style.INK_3};")
            val_lbl = QLabel("—")
            val_lbl.setStyleSheet(f"font-family: {style.MONO_FAMILY}; font-size: 12px; color: {style.INK};")
            info_grid.addWidget(key_lbl, row, col)
            info_grid.addWidget(val_lbl, row, col + 1, 1, val_span)
            self._info_labels[name] = val_lbl

        lay.addWidget(self.info_card)

        self._steps_layout.addWidget(self.step1)


    def _build_step2_predict(self) -> None:
        self.step2 = WorkflowStep(2, "Predict Cell Types", keep_content_on_done=True)
        lay = self.step2.content_layout

        # Reference model
        lay.addWidget(_field_label("Reference model"))
        self.model_combo = QComboBox()
        self.model_combo.addItem("human")
        self.model_combo.addItem("mouse")
        lay.addWidget(self.model_combo)

        # Quality filtering preset
        lay.addWidget(_field_label("Quality filtering"))
        self.qc_preset_combo = QComboBox()
        self.qc_preset_combo.addItem("Default (500 UMI / 200 genes / 10% mito)")
        self.qc_preset_combo.addItem("Custom")
        self.qc_preset_combo.currentIndexChanged.connect(self._on_qc_preset_changed)
        lay.addWidget(self.qc_preset_combo)

        # Custom QC fields (hidden by default)
        self._custom_qc_widget = QWidget()
        custom_grid = QGridLayout(self._custom_qc_widget)
        custom_grid.setSpacing(6)
        custom_grid.setContentsMargins(0, 4, 0, 0)

        self.min_counts_spin = QSpinBox()
        self.min_counts_spin.setRange(0, 50000)
        self.min_counts_spin.setValue(500)
        custom_grid.addWidget(_field_label("Min UMI/cell"), 0, 0)
        custom_grid.addWidget(self.min_counts_spin, 1, 0)

        self.min_genes_spin = QSpinBox()
        self.min_genes_spin.setRange(0, 10000)
        self.min_genes_spin.setValue(200)
        custom_grid.addWidget(_field_label("Min genes/cell"), 0, 1)
        custom_grid.addWidget(self.min_genes_spin, 1, 1)

        self.max_mito_spin = QDoubleSpinBox()
        self.max_mito_spin.setRange(0.0, 100.0)
        self.max_mito_spin.setSingleStep(1.0)
        self.max_mito_spin.setValue(10.0)
        self.max_mito_spin.setDecimals(1)
        custom_grid.addWidget(_field_label("Max mito %"), 0, 2)
        custom_grid.addWidget(self.max_mito_spin, 1, 2)

        self._custom_qc_widget.hide()
        lay.addWidget(self._custom_qc_widget)

        # Advanced disclosure
        self._adv_btn = QPushButton("▶  Advanced")
        self._adv_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; font-size: 13px; "
            f"color: {style.INK_2}; text-align: left; padding: 6px 0; }}"
            f"QPushButton:hover {{ color: {style.INK}; }}"
        )
        self._adv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._adv_btn.clicked.connect(self._toggle_advanced)
        lay.addWidget(self._adv_btn)

        self._adv_widget = QWidget()
        adv_lay = QVBoxLayout(self._adv_widget)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        adv_lay.setSpacing(6)

        # GRIT toggle
        grit_row = QHBoxLayout()
        grit_lbl = QLabel("GRIT refinement")
        grit_lbl.setStyleSheet("font-size: 12px;")
        self.grit_check = ToggleSwitch(checked=True)
        grit_row.addWidget(grit_lbl, 1)
        grit_row.addWidget(self.grit_check)
        adv_lay.addLayout(grit_row)
        grit_sub = QLabel("Iterative cluster cleanup")
        grit_sub.setStyleSheet(f"font-size: 11px; color: {style.INK_3};")
        adv_lay.addWidget(grit_sub)

        # Score uncertainty toggle
        score_row = QHBoxLayout()
        score_lbl = QLabel("Score uncertainty")
        score_lbl.setStyleSheet("font-size: 12px;")
        self.score_check = ToggleSwitch(checked=False)
        score_row.addWidget(score_lbl, 1)
        score_row.addWidget(self.score_check)
        adv_lay.addLayout(score_row)
        score_sub = QLabel("Slower — adds entropy column")
        score_sub.setStyleSheet(f"font-size: 11px; color: {style.INK_3};")
        adv_lay.addWidget(score_sub)

        # Batch size
        adv_lay.addWidget(_field_label("Batch size"))
        self.batch_size_edit = QLineEdit("auto")
        self.batch_size_edit.setPlaceholderText("auto")
        adv_lay.addWidget(self.batch_size_edit)

        self._adv_widget.hide()
        self._adv_expanded = False
        lay.addWidget(self._adv_widget)

        # Predict button
        self.predict_btn = QPushButton("▶  Run prediction")
        self.predict_btn.setFixedHeight(36)
        self._style_action_btn(self.predict_btn, done=False)
        self.predict_btn.clicked.connect(self.run_prediction_requested.emit)
        lay.addWidget(self.predict_btn)

        # Wire re-run
        self.step2.rerun_requested.connect(self._on_rerun_prediction)

        self._steps_layout.addWidget(self.step2)


    def _build_step3_visualize(self) -> None:
        self.step3 = WorkflowStep(3, "Visualize", keep_content_on_done=True)
        lay = self.step3.content_layout

        lay.addWidget(_field_label("Embedding"))
        self.embedding_combo = QComboBox()
        # Explicit backend choice: "(MLX)" -> in-house Metal engine,
        # "(scanpy)" -> CPU. reduce_dimensions() honors the chosen backend per method.
        if sys.platform == "darwin":
            self.embedding_combo.addItem("UMAP (MLX)", "umap:mlx")
        self.embedding_combo.addItem("UMAP (scanpy)", "umap:scanpy")
        if sys.platform == "darwin":
            self.embedding_combo.addItem("t-SNE (MLX)", "tsne:mlx")
        self.embedding_combo.addItem("t-SNE (scanpy)", "tsne:scanpy")
        self.embedding_combo.currentIndexChanged.connect(self._on_embedding_changed)
        lay.addWidget(self.embedding_combo)

        self.umap_btn = QPushButton("▶  Generate UMAP")
        self.umap_btn.setFixedHeight(36)
        self._style_action_btn(self.umap_btn, done=False)
        self.umap_btn.clicked.connect(self._on_generate_clicked)
        lay.addWidget(self.umap_btn)

        self.step3.rerun_requested.connect(self._on_rerun_embedding)

        self._steps_layout.addWidget(self.step3)



    def _style_source_toggles(self, *, done: bool) -> None:
        color = style.SUCCESS if done else style.ACCENT
        for btn in (self.btn_cr, self.btn_h5ad):
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 11px; border-radius: 4px; padding: 0 10px; }}"
                f"QPushButton:checked {{ background: {color}; color: white; border: none; }}"
            )

    def _style_action_btn(self, btn: QPushButton, *, done: bool) -> None:
        bg, bg_hover = (style.SUCCESS, style.SUCCESS_DARK) if done else (style.ACCENT, style.ACCENT_DARK)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: white; border: none;
                border-radius: 8px; font-weight: 600; font-size: 13px;
            }}
            QPushButton:hover {{ background: {bg_hover}; }}
            QPushButton:disabled {{ background: #B0BEC5; color: #E0E0E0; }}
        """)

    def _set_source(self, src: str) -> None:
        self.btn_h5ad.setChecked(src == "h5ad")
        self.btn_cr.setChecked(src == "cellranger")

    def _on_browse(self) -> None:
        if self.btn_cr.isChecked():
            self.open_cellranger_requested.emit()
        else:
            self.open_h5ad_requested.emit()

    def _on_qc_preset_changed(self, index: int) -> None:
        self._custom_qc_widget.setVisible(index == 1)

    def _toggle_advanced(self) -> None:
        self._adv_expanded = not self._adv_expanded
        self._adv_widget.setVisible(self._adv_expanded)
        arrow = "▼" if self._adv_expanded else "▶"
        self._adv_btn.setText(f"{arrow}  Advanced")

    def _on_embedding_changed(self, index: int) -> None:
        display = self.embedding_combo.currentText()
        self.umap_btn.setText(f"▶  Generate {display}")

    def _on_generate_clicked(self) -> None:
        key = self.embedding_combo.currentData() or "umap:mlx"
        self.run_embedding_requested.emit(key)
        method = key.partition(":")[0]
        if method == "umap":
            self.run_umap_requested.emit()

    def _on_rerun_prediction(self) -> None:
        self.predict_btn.setText("▶  Run prediction")
        self._style_action_btn(self.predict_btn, done=False)
        self.step2.set_state(StepState.ACTIVE)
        self.umap_btn.setText(f"▶  Generate {self.embedding_combo.currentText()}")
        self._style_action_btn(self.umap_btn, done=False)
        self.step3.set_state(StepState.PENDING)

    def _on_rerun_embedding(self) -> None:
        self.umap_btn.setText(f"▶  Generate {self.embedding_combo.currentText()}")
        self._style_action_btn(self.umap_btn, done=False)
        self.step3.set_state(StepState.ACTIVE)


    def on_data_loaded(self, adata, path: str) -> None:
        self.file_path_edit.setText(Path(path).name)

        self._info_labels["cells"].setText(f"{adata.shape[0]:,}")
        self._info_labels["genes"].setText(f"{adata.shape[1]:,}")

        try:
            p = Path(path)
            if p.is_dir():
                size_bytes = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            else:
                size_bytes = os.path.getsize(path)
            size_mb = size_bytes / (1024 * 1024)
            self._info_labels["size"].setText(f"{size_mb:.1f} MB")
        except OSError:
            self._info_labels["size"].setText("—")

        import scipy.sparse as sp

        if sp.issparse(adata.X):
            self._info_labels["layout"].setText(type(adata.X).__name__[:3].upper())
        else:
            self._info_labels["layout"].setText("dense")

        self.info_card.show()
        self.browse_btn.show()
        self._has_dataset = True
        self._style_source_toggles(done=True)
        self.step1.set_state(StepState.DONE)
        self.predict_btn.setText("▶  Run prediction")
        self._style_action_btn(self.predict_btn, done=False)
        self.step2.set_state(StepState.ACTIVE)
        display = self.embedding_combo.currentText().split(" (")[0]
        self.umap_btn.setText(f"▶  Generate {display}")
        self._style_action_btn(self.umap_btn, done=False)
        self.step3.set_state(StepState.PENDING)

    def on_loading_started(self, filename: str) -> None:
        self.browse_btn.hide()
        self._style_source_toggles(done=False)
        self.step1.set_progress_text(f"Loading {filename}…")
        self.step1.set_state(StepState.RUNNING)

    def on_prediction_started(self) -> None:
        self.predict_btn.hide()
        self.step2.set_progress_text("Running prediction…")
        self.step2.set_state(StepState.RUNNING)

    def on_predictions_ready(self, n_cells: int = 0, n_types: int = 0, elapsed_sec: float = 0) -> None:
        text = f"Predicted {n_cells:,} cells across {n_types} types · {elapsed_sec:.0f}s"
        self.step2.set_success_text(text)
        self.step2.set_state(StepState.DONE)
        self.predict_btn.setText("✓  Re-run prediction")
        self._style_action_btn(self.predict_btn, done=True)
        self.predict_btn.show()
        display = self.embedding_combo.currentText().split(" (")[0]
        self.umap_btn.setText(f"▶  Generate {display}")
        self._style_action_btn(self.umap_btn, done=False)
        self.step3.set_state(StepState.ACTIVE)

    def on_embedding_started(self) -> None:
        self.umap_btn.hide()
        method = self.embedding_combo.currentText().split(" (")[0]
        self.step3.set_progress_text(f"Computing {method}…")
        self.step3.set_state(StepState.RUNNING)

    def on_embedding_ready(self, method: str = "UMAP", elapsed_sec: float = 0) -> None:
        text = f"{method} embedding computed · {elapsed_sec:.0f}s"
        self.step3.set_success_text(text)
        self.step3.set_state(StepState.DONE)
        self.umap_btn.setText(f"✓  Re-generate {method}")
        self._style_action_btn(self.umap_btn, done=True)
        self.umap_btn.show()

    def set_controls_enabled(self, enabled: bool) -> None:
        self.browse_btn.setEnabled(enabled)

    def get_prediction_params(self) -> dict:
        params = {
            "model_name": self.model_combo.currentText(),
            "use_grit": self.grit_check.isChecked(),
            "top_k": 3,
        }
        batch_text = self.batch_size_edit.text().strip()
        if batch_text and batch_text.lower() != "auto":
            try:
                params["batch_size"] = int(batch_text)
            except ValueError:
                pass
        return params

    def get_qc_params(self) -> dict | None:
        if self.qc_preset_combo.currentIndex() == 0:
            return dict(_DEFAULT_QC)
        return {
            "min_counts": self.min_counts_spin.value(),
            "min_genes": self.min_genes_spin.value(),
            "max_mito_pct": self.max_mito_spin.value(),
        }

    def get_embedding_method(self) -> str:
        return self.embedding_combo.currentData() or "umap:mlx"

    def on_worker_error(self) -> None:
        if self.step1.state == StepState.RUNNING:
            # A failed load leaves step 1 stuck mid-run with Browse hidden, so
            # there is no way to pick another folder without restarting the app.
            # Put step 1 back where it was: DONE if an earlier dataset is still
            # loaded (this load failed, that one is untouched), ACTIVE if not.
            self.browse_btn.show()
            self._style_source_toggles(done=self._has_dataset)
            self.step1.set_state(
                StepState.DONE if self._has_dataset else StepState.ACTIVE
            )
        if self.step2.state == StepState.RUNNING:
            self.step2.set_state(StepState.ACTIVE)
            self.predict_btn.setText("▶  Run prediction")
            self._style_action_btn(self.predict_btn, done=False)
            self.predict_btn.show()
        if self.step3.state == StepState.RUNNING:
            self.step3.set_state(StepState.ACTIVE)
            display = self.embedding_combo.currentText().split(" (")[0]
            self.umap_btn.setText(f"▶  Generate {display}")
            self._style_action_btn(self.umap_btn, done=False)
            self.umap_btn.show()

    def update_cell_count(self, n_cells: int) -> None:
        self._info_labels["cells"].setText(f"{n_cells:,}")

    def set_coverage_status(self, text: str, ok: bool = True) -> None:
        """Update the reference-gene coverage line in the step-1 info card.

        ``ok=False`` paints the value red so a failing gate is obvious.
        """
        lbl = self._info_labels["coverage"]
        lbl.setText(text)
        color = style.INK if ok else "#c0392b"
        lbl.setStyleSheet(
            f"font-family: {style.MONO_FAMILY}; font-size: 12px; color: {color};"
        )
