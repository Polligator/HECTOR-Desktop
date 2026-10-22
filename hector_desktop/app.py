"""Application window and startup flow."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QStatusBar,
    QWidget,
)

from hector_desktop import core as style
from hector_desktop import __version__
from hector_desktop.core import AppState
from hector_desktop.memory import release_dataset_memory
from hector_desktop.pipeline import WorkflowPanel
from hector_desktop.views import TabPanel
from hector_desktop.pipeline import DataLoadWorker, GateOutcome, GeneMappingWorker, ModelDownloadWorker, ModelLoadWorker, PredictWorker, ProjectWorker, UpdateCheckWorker


def _clamp_progress(value: int, last: int) -> int:
    """Clamp a progress value to [0, 100] and never decrease within one
    operation, so a tqdm bar restarting at 0 (e.g. a new phase's first emit)
    cannot rewind the bar below the milestone it already reached."""
    return max(last, max(0, min(100, value)))


class MainWindow(QMainWindow):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._active_worker = None
        self._last_progress = 0

        self.setWindowTitle("HECTOR Desktop — Single-Cell Prediction & Visualization")
        self.setMinimumSize(1100, 700)
        self.resize(1400, 860)

        self._build_menu_bar()
        self._build_central()
        self._build_status_bar()
        self._connect_signals()

        QTimer.singleShot(3000, self._auto_check_for_updates)


    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        self._act_open_h5ad = file_menu.addAction("Open h5ad…")
        self._act_open_h5ad.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open_cr = file_menu.addAction("Open Cell Ranger folder…")
        file_menu.addSeparator()
        self._act_save = file_menu.addAction("Save h5ad…")
        self._act_save.setShortcut(QKeySequence.StandardKey.Save)
        self._act_save.setEnabled(False)
        self._act_export = file_menu.addAction("Export CSV…")
        self._act_export.setEnabled(False)
        file_menu.addSeparator()
        self._act_quit = file_menu.addAction("Quit")
        self._act_quit.setShortcut(QKeySequence.StandardKey.Quit)

        run_menu = mb.addMenu("Run")
        self._act_predict = run_menu.addAction("Run Prediction")
        self._act_predict.setShortcut(QKeySequence("Ctrl+R"))
        self._act_predict.setEnabled(False)
        self._act_embedding = run_menu.addAction("Generate Embedding")
        self._act_embedding.setShortcut(QKeySequence("Ctrl+U"))
        self._act_embedding.setEnabled(False)

        model_menu = mb.addMenu("Model")
        self._act_check_update = model_menu.addAction("Check for Updates…")
        self._act_import_model = model_menu.addAction("Import Model File…")
        model_menu.addSeparator()
        self._act_model_info = model_menu.addAction("Model Info")

        help_menu = mb.addMenu("Help")
        help_menu.addAction("About HECTOR Desktop").triggered.connect(self._show_about)


    def _build_central(self) -> None:
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.sidebar = WorkflowPanel(self.state)
        self.tab_panel = TabPanel(self.state)

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.tab_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setHandleWidth(3)
        self.splitter.setSizes([335, 1065])

        self.setCentralWidget(self.splitter)


    def _build_status_bar(self) -> None:
        sb = QStatusBar()
        sb.setStyleSheet(
            f"QStatusBar {{ background: {style.STATUS_BG}; border: none; "
            f"padding: 4px 12px; }}"
        )
        self.setStatusBar(sb)

        self._info_style = f"font-family: {style.MONO_FAMILY}; font-size: 11px; color: #CBD5E1;"

        self.status_label = QLabel("● Idle — load data and run prediction")
        self._set_status_style("idle")

        self.cell_count_label = QLabel("")
        self.cell_count_label.setStyleSheet(self._info_style)

        self.device_label = QLabel("")
        self.device_label.setStyleSheet(self._info_style)

        self.ram_label = QLabel("RAM … / … GB")
        self.ram_label.setMinimumWidth(110)
        self.ram_label.setStyleSheet(self._info_style)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(150)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,0.10); border: none; "
            "border-radius: 4px; color: #CBD5E1; font-size: 10px; }"
            f"QProgressBar::chunk {{ background: {style.ACCENT}; border-radius: 4px; }}"
        )
        self.progress_bar.hide()

        right_info = QWidget()
        right_info.setStyleSheet("background: transparent;")
        right_layout = QHBoxLayout(right_info)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)
        right_layout.addWidget(self.progress_bar)
        right_layout.addWidget(self.cell_count_label)
        right_layout.addWidget(self.device_label)
        right_layout.addWidget(self.ram_label)

        sb.addWidget(self.status_label, 1)
        sb.addPermanentWidget(right_info)

        QTimer.singleShot(500, self._detect_device)
        self._ram_timer = QTimer(self)
        self._ram_timer.timeout.connect(self._update_ram)
        self._ram_timer.start(5000)
        QTimer.singleShot(600, self._update_ram)

    def _detect_device(self) -> None:
        chip = ""
        if platform.system() == "Darwin":
            try:
                chip = subprocess.check_output(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    text=True, timeout=2,
                ).strip()
                if not chip:
                    chip = f"Apple {platform.machine()}"
            except Exception:
                chip = f"Apple {platform.machine()}"

        gpu_str = self._detect_gpu()

        parts = [p for p in [f"device {chip}" if chip else "", gpu_str] if p]
        self.device_label.setText("  ·  ".join(parts) if parts else "")

    def _detect_gpu(self) -> str:
        """Describe the compute device HECTOR actually runs on, for the status bar.

        `import mlx.core` succeeding does NOT mean the app uses MLX: HECTOR only
        enables its MLX/Metal backend on Apple Silicon (see hector/__init__.py's
        `_HECTOR_USE_MLX`, gated on `sys.platform == 'darwin'`). Off Apple Silicon
        it runs on TensorFlow even when an MLX CUDA build happens to be importable,
        so reporting "MLX" there is wrong. We read HECTOR's own flag as the source
        of truth and fall back to replicating its gate if hector isn't imported yet.
        """
        hector = sys.modules.get("hector")
        if hector is not None:
            use_mlx = bool(getattr(hector, "_HECTOR_USE_MLX", False))
        else:
            use_mlx = platform.system() == "Darwin"
            if use_mlx:
                try:
                    import mlx.core  # noqa: F401
                except ImportError:
                    use_mlx = False

        if use_mlx:
            return "MLX Metal GPU"

        try:
            import tensorflow as tf
            gpus = tf.config.list_physical_devices("GPU")
            if not gpus:
                return "CPU only"
            names = []
            for g in gpus:
                try:
                    details = tf.config.experimental.get_device_details(g)
                    names.append(details.get("device_name", ""))
                except Exception:
                    names.append("")
            names = [n for n in names if n]
            return "  ·  ".join(dict.fromkeys(names)) if names else "GPU available"
        except Exception:
            return self._gpu_name()

    def _gpu_name(self) -> str:
        """Best-effort NVIDIA GPU model name, framework-independent."""
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                text=True, timeout=2,
            ).strip()
            names = [n.strip() for n in out.splitlines() if n.strip()]
            return "  ·  ".join(dict.fromkeys(names)) if names else ""
        except Exception:
            return ""

    def _update_ram(self) -> None:
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            usage_gb = proc.memory_info().rss / (1024 ** 3)
            total_gb = psutil.virtual_memory().total / (1024 ** 3)
        except Exception:
            try:
                import resource
                usage_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if platform.system() == "Darwin":
                    usage_gb = usage_bytes / (1024 ** 3)
                else:
                    usage_gb = usage_bytes * 1024 / (1024 ** 3)
                total_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3)
            except Exception:
                return
        self.ram_label.setText(f"RAM {usage_gb:.1f} / {total_gb:.0f} GB")


    def _connect_signals(self) -> None:
        self._act_open_h5ad.triggered.connect(self._on_open_h5ad)
        self._act_open_cr.triggered.connect(self._on_open_cellranger)
        self._act_save.triggered.connect(self._on_save_h5ad)
        self._act_export.triggered.connect(self._on_export_csv)
        self._act_quit.triggered.connect(self.close)
        self._act_predict.triggered.connect(self._on_run_prediction)
        self._act_embedding.triggered.connect(self._on_run_embedding_from_menu)

        self._act_check_update.triggered.connect(self._on_check_for_updates)
        self._act_import_model.triggered.connect(self._on_import_model_file)
        self._act_model_info.triggered.connect(self._on_show_model_info)

        self.sidebar.open_h5ad_requested.connect(self._on_open_h5ad)
        self.sidebar.open_cellranger_requested.connect(self._on_open_cellranger)
        self.sidebar.run_prediction_requested.connect(self._on_run_prediction)
        self.sidebar.run_embedding_requested.connect(self._on_run_embedding)
        self.tab_panel.save_h5ad_requested.connect(self._on_save_h5ad)


    def _on_open_h5ad(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open h5ad file", "", "AnnData files (*.h5ad);;All files (*)"
        )
        if path:
            self._load_data(path, "h5ad")

    def _on_open_cellranger(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Cell Ranger output directory"
        )
        if path:
            self._load_data(path, "cellranger")

    def _load_data(self, path: str, source: str) -> None:
        if self.state.is_busy:
            return
        self._set_busy(True, f"Loading {Path(path).name}…")
        self.sidebar.on_loading_started(Path(path).name)
        worker = DataLoadWorker(path, source)
        worker.finished.connect(
            lambda adata, outcome: self._on_data_loaded(adata, outcome, path, source)
        )
        worker.error.connect(self._on_worker_error)
        self._start_worker(worker)

    def _on_data_loaded(self, adata, outcome: GateOutcome, path: str, source: str) -> None:
        release_dataset_memory(self.state, self.tab_panel)

        self.state.adata = adata
        self.state.adata_original = adata
        self.state.adata_path = Path(path)
        self.state.data_source = source
        self.state.results_df = None
        self.state.detected_species = outcome.species_detected
        self.state.coverage_report = outcome.coverage_report

        if outcome.species_detected:
            idx = self.sidebar.model_combo.findText(outcome.species_detected)
            if idx >= 0:
                self.sidebar.model_combo.setCurrentIndex(idx)

        self.sidebar.on_data_loaded(adata, path)
        self.tab_panel.on_data_loaded()
        self._act_save.setEnabled(True)
        # A freshly loaded dataset has no predictions yet. Embedding colours by
        # the prediction and on_embedding_ready reads _current_color_map (just
        # cleared) unguarded, so it must stay disabled until this dataset is
        # predicted — re-enabled in _on_predict_finished.
        self._act_embedding.setEnabled(False)

        n = f"{self.state.n_cells:,}"
        g = f"{self.state.n_genes:,}"
        self.cell_count_label.setText(f"showing {n} / {n}")

        if outcome.mapping_needed:
            self._set_busy(False, f"● Dataset loaded — {n} cells, {g} genes (no Ensembl IDs)")
            self._prompt_symbol_mapping(adata, path, source)
            return

        if outcome.fatal_reason is not None:
            self._fail_gate(
                "Reference unavailable.",
                detail=outcome.fatal_reason,
                status_text=f"● Loaded but unusable — {n} cells, {g} genes",
            )
            return

        report = outcome.coverage_report
        if report is not None and report.pct_found < 90:
            self.sidebar.set_coverage_status(
                f"{report.pct_found:.1f}% ({report.n_found:,}/{report.n_required:,})",
                ok=False,
            )
            self._fail_gate(
                f"Reference gene coverage too low ({report.pct_found:.1f}%).",
                detail=(
                    f"Only {report.n_found:,} of HECTOR's {report.n_required:,} "
                    f"{report.species} reference genes were found in your file "
                    f"(need ≥90%).\n\n"
                    "Likely causes: wrong species, wrong reference build, or the "
                    "file has been heavily filtered.\n\n"
                    f"First missing IDs: {', '.join(report.missing_sample[:5])}"
                ),
                status_text=f"● Loaded but coverage too low — {report.pct_found:.1f}%",
            )
            return

        if report is not None:
            self.sidebar.set_coverage_status(
                f"{report.pct_found:.1f}% ({report.n_found:,}/{report.n_required:,})",
                ok=True,
            )
        self._act_predict.setEnabled(True)
        self._set_busy(False, f"● Dataset loaded — {n} cells, {g} genes")


    def _fail_gate(self, headline: str, *, detail: str, status_text: str) -> None:
        """Disable predict, show a hard-stop modal, and update the status bar."""
        self._act_predict.setEnabled(False)
        self._set_busy(False, status_text)
        QMessageBox.critical(self, "Cannot run prediction", f"{headline}\n\n{detail}")

    def _prompt_symbol_mapping(self, adata, path: str, source: str) -> None:
        """Ask the user which species, then spawn GeneMappingWorker."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Gene symbols detected")
        box.setText(
            "Your file uses gene symbols (e.g. ACTB) instead of Ensembl IDs "
            "(e.g. ENSG00000075624).\n\n"
            "HECTOR can translate them automatically, but the lookup depends on "
            "the species. Which is this data?"
        )
        human_btn = box.addButton("Human", QMessageBox.ButtonRole.AcceptRole)
        mouse_btn = box.addButton("Mouse", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()

        clicked = box.clickedButton()
        if clicked is cancel_btn or clicked is None:
            self._act_predict.setEnabled(False)
            self.sidebar.set_coverage_status("symbols — not mapped", ok=False)
            return

        species = "human" if clicked is human_btn else "mouse"
        idx = self.sidebar.model_combo.findText(species)
        if idx >= 0:
            self.sidebar.model_combo.setCurrentIndex(idx)
        self._run_gene_mapping(adata, species, path, source)

    def _run_gene_mapping(self, adata, species: str, path: str, source: str) -> None:
        self._set_busy(True, f"Mapping gene symbols → {species} Ensembl IDs…")
        worker = GeneMappingWorker(adata, species)
        worker.finished.connect(
            lambda new_adata, outcome: self._on_mapping_finished(
                new_adata, outcome, path, source
            )
        )
        worker.error.connect(self._on_worker_error)
        self._start_worker(worker)

    def _on_mapping_finished(self, new_adata, outcome: GateOutcome, path: str, source: str) -> None:
        # Show the mapping report dialog first, then run the same _on_data_loaded gate.
        report = outcome.mapping_report
        if report is not None:
            QMessageBox.information(
                self,
                "Gene mapping complete",
                f"Mapped {report['n_mapped']:,} of {report['n_input']:,} symbols "
                f"to {report['species']} Ensembl IDs.\n\n"
                f"  Ambiguous (left empty): {report['n_ambiguous']:,}\n"
                f"  Unmapped (left empty):  {report['n_unmapped']:,}",
            )
        self._on_data_loaded(new_adata, outcome, path, source)


    def _on_run_prediction(self) -> None:
        if self.state.is_busy or not self.state.has_data:
            return
        self._set_busy(True, "Preparing data…", show_progress=True)
        self.sidebar.on_prediction_started()

        qc_params = self.sidebar.get_qc_params()
        params = self.sidebar.get_prediction_params()
        model_name = params.pop("model_name", "human")

        import time
        self._predict_start_time = time.monotonic()

        worker = PredictWorker(
            self.state.adata_original,
            model_name=model_name,
            predict_kwargs=params,
            qc_params=qc_params,
        )
        worker.progress.connect(self._on_progress)
        worker.log_message.connect(self._on_log)
        worker.finished.connect(self._on_predict_finished)
        worker.error.connect(self._on_worker_error)
        self._start_worker(worker)

    def _on_predict_finished(self, results_df, predictor, adata) -> None:
        import time
        elapsed = time.monotonic() - self._predict_start_time

        self.state.adata = adata
        self.state.results_df = results_df
        self.state.predictor = predictor

        self.sidebar.update_cell_count(adata.shape[0])
        n = f"{adata.shape[0]:,}"
        total = f"{self.state.adata_original.shape[0]:,}"
        self.cell_count_label.setText(f"showing {n} / {total}")

        from hector_desktop.pipeline import extract_ontology_groups
        groups, display_names, ontology_color_map = extract_ontology_groups(adata)
        self.state.ontology_groups = groups
        self.state.ontology_display_names = display_names
        self.state.ontology_color_map = ontology_color_map

        self.tab_panel.on_predictions_ready(
            results_df, self.state.adata,
            groups=groups,
            display_names=display_names,
            ontology_color_map=ontology_color_map,
        )

        n_cells = len(results_df)
        if "top_1_prediction" in results_df.columns:
            n_types = results_df["top_1_prediction"].nunique()
        elif "hector_prediction" in self.state.adata.obs.columns:
            n_types = self.state.adata.obs["hector_prediction"].nunique()
        else:
            n_types = 0
        self.sidebar.on_predictions_ready(n_cells, n_types, elapsed)

        self._act_export.setEnabled(True)
        self._act_embedding.setEnabled(True)

        n = f"{n_cells:,}"
        self._set_busy(False, f"● Prediction complete — {n} cells annotated")


    def _on_run_embedding_from_menu(self) -> None:
        """Triggered from the Run menu — reads the current dropdown selection."""
        method = self.sidebar.get_embedding_method()
        self._on_run_embedding(method)

    def _on_run_embedding(self, key: str = "umap:mlx") -> None:
        if self.state.is_busy or self.state.predictor is None:
            return
        method, _, backend = key.partition(":")
        backend = backend or "mlx"
        display = "UMAP" if method == "umap" else "t-SNE"
        self._set_busy(True, f"Computing {display} ({backend})…", show_progress=True)
        self.sidebar.on_embedding_started()

        import time
        self._embedding_start_time = time.monotonic()

        worker = ProjectWorker(
            self.state.predictor,
            self.state.adata,
            method=method,
            backend=backend,
            project_kwargs={"random_state": 42},
        )
        worker.progress.connect(self._on_progress)
        worker.log_message.connect(self._on_log)
        worker.finished.connect(self._on_embedding_finished)
        worker.error.connect(self._on_worker_error)
        self._start_worker(worker)

    def _on_embedding_finished(self, method: str) -> None:
        import time
        elapsed = time.monotonic() - self._embedding_start_time

        display = "UMAP" if method == "umap" else "t-SNE"
        obsm_key = "X_umap" if method == "umap" else "X_tsne"
        self.state.active_embedding_key = obsm_key

        self.tab_panel.on_embedding_ready(self.state.adata, method)
        self.sidebar.on_embedding_ready(display, elapsed)
        self._set_busy(False, f"● {display} complete")


    def _on_save_h5ad(self) -> None:
        if not self.state.has_data:
            return
        default = str(self.state.adata_path) if self.state.adata_path else ""
        compressed = "Compressed h5ad (*.h5ad)"
        uncompressed = "Uncompressed h5ad (*.h5ad)"
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save annotated h5ad", default, f"{uncompressed};;{compressed}"
        )
        if path:
            compression = "gzip" if selected_filter == compressed else None
            self._set_busy(True, "Saving…")
            try:
                self.state.adata.write_h5ad(path, compression=compression)
                suffix = " (compressed)" if compression else ""
                self._set_busy(False, f"● Saved to {Path(path).name}{suffix}")
            except Exception as exc:
                self._set_busy(False)
                QMessageBox.critical(self, "Save Error", str(exc))

    def _on_export_csv(self) -> None:
        if self.state.results_df is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export predictions CSV", "", "CSV files (*.csv)"
        )
        if path:
            try:
                self.state.results_df.to_csv(path, index=True)
                self.status_label.setText(f"● Exported to {Path(path).name}")
            except Exception as exc:
                QMessageBox.critical(self, "Export Error", str(exc))


    def _start_worker(self, worker) -> None:
        self._active_worker = worker
        worker.start()

    def _on_progress(self, value: int) -> None:
        self._last_progress = _clamp_progress(value, self._last_progress)
        self.progress_bar.setValue(self._last_progress)
        self.progress_bar.show()

    def _on_log(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_worker_error(self, message: str) -> None:
        self._set_busy(False, "● Error")
        self._set_status_style("error")
        self.sidebar.on_worker_error()
        QMessageBox.critical(self, "Error", message)

    def _set_busy(self, busy: bool, message: str = "", *, show_progress: bool = False) -> None:
        self.state.is_busy = busy
        self.sidebar.set_controls_enabled(not busy)
        if busy:
            self._last_progress = 0
            self.progress_bar.setValue(0)
            # Operations with measurable progress (predict / embed) show the bar
            # from the start; data load and others stay bar-less.
            self.progress_bar.setVisible(show_progress)
            self._set_status_style("busy")
        else:
            self.progress_bar.hide()
            self._set_status_style("done")
        if message:
            self.status_label.setText(message)

    def _set_status_style(self, state: str) -> None:
        base = f"font-family: {style.MONO_FAMILY}; font-size: 10px; padding-left: 10px;"
        if state == "busy":
            self.status_label.setStyleSheet(f"{base} color: {style.WARNING}; font-weight: 600;")
        elif state == "done":
            self.status_label.setStyleSheet(f"{base} color: {style.SUCCESS}; font-weight: 500;")
        elif state == "error":
            self.status_label.setStyleSheet(f"{base} color: {style.DANGER}; font-weight: 600;")
        else:
            self.status_label.setStyleSheet(f"{base} color: #CBD5E1;")


    def _auto_check_for_updates(self) -> None:
        """Silent background check on startup — errors are swallowed."""
        worker = UpdateCheckWorker()
        worker.update_available.connect(self._on_update_available)
        self._update_worker = worker
        worker.start()

    def _on_update_available(self, result: dict) -> None:
        local = result.get("local_version") or "unknown"
        reply = QMessageBox.information(
            self,
            "Model Update Available",
            f"A new model version is available on HuggingFace.\n\n"
            f"Current local version: {local}\n\n"
            f"Would you like to download the update now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._download_model_update()

    def _on_check_for_updates(self) -> None:
        """Manual check triggered from Model menu."""
        self._act_check_update.setEnabled(False)
        model_name = self.sidebar.model_combo.currentText()
        self.status_label.setText(f"Checking for {model_name} model updates…")

        worker = UpdateCheckWorker(model_name)
        worker.update_available.connect(self._on_update_available)
        worker.no_update.connect(self._on_no_update)
        worker.error.connect(self._on_update_check_error)
        self._update_worker = worker
        worker.start()

    def _on_no_update(self) -> None:
        self._act_check_update.setEnabled(True)
        self.status_label.setText("● Model is up to date")
        self._set_status_style("done")
        QMessageBox.information(self, "No Updates", "Your model is already up to date.")

    def _on_update_check_error(self, message: str) -> None:
        self._act_check_update.setEnabled(True)
        self.status_label.setText("● Update check failed")
        self._set_status_style("idle")
        QMessageBox.warning(
            self,
            "Update Check Failed",
            "Could not check for updates. Please verify your internet connection.\n\n"
            f"Details: {message[:200]}",
        )

    def _download_model_update(self) -> None:
        model_name = self.sidebar.model_combo.currentText()
        self._set_busy(True, f"Downloading {model_name} model update…")
        worker = ModelDownloadWorker(model_name)
        worker.log_message.connect(self._on_log)
        worker.finished.connect(self._on_model_update_finished)
        worker.error.connect(self._on_worker_error)
        self._start_worker(worker)

    def _on_model_update_finished(self) -> None:
        self._act_check_update.setEnabled(True)
        self._set_busy(False, "● Model updated successfully")
        QMessageBox.information(
            self,
            "Update Complete",
            "The model has been updated. The new model will be used for the next prediction.",
        )

    def _on_import_model_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Model File", "", "HDF5 model files (*.h5);;All files (*)"
        )
        if not path:
            return
        try:
            import hector
            model_name = self.sidebar.model_combo.currentText()
            result = hector.import_model_file(path, model_name=model_name)
            version = result.get("checkpoint_version") or "unknown"
            QMessageBox.information(
                self,
                "Model Imported",
                f"{model_name.capitalize()} model file imported successfully.\n\n"
                f"Checkpoint version: {version}\n\n"
                f"The imported model will be used for the next prediction.",
            )
            self.status_label.setText(f"● {model_name.capitalize()} model imported (version {version})")
            self._set_status_style("done")
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", str(exc))

    def _on_show_model_info(self) -> None:
        try:
            import json
            from hector import (
                _resolve_cached_model_path,
                _metadata_path,
                read_checkpoint_version,
            )

            model_name = self.sidebar.model_combo.currentText()
            cached = _resolve_cached_model_path(model_name)
            meta_path = _metadata_path(cached)

            if not cached.exists():
                QMessageBox.information(
                    self, "Model Info", f"No {model_name} model is currently cached locally."
                )
                return

            version = "unknown"
            commit = "unknown"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                version = meta.get("checkpoint_version") or "unknown"
                commit = meta.get("commit_sha") or "unknown"
                if len(commit) > 12:
                    commit = commit[:12] + "…"

            if version == "unknown":
                version = read_checkpoint_version(cached) or "unknown"

            size_mb = cached.stat().st_size / (1024 * 1024)

            QMessageBox.information(
                self,
                "Model Info",
                f"<b>Model:</b> {model_name}<br>"
                f"<b>Checkpoint version:</b> {version}<br>"
                f"<b>HuggingFace commit:</b> {commit}<br>"
                f"<b>File size:</b> {size_mb:.1f} MB",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))


    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About HECTOR Desktop",
            "<h3>HECTOR Desktop</h3>"
            "<p>Single-cell prediction and embedding visualization.</p>"
            f"<p>Version {__version__}</p>",
        )


import sys

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QThread, Signal, Qt, QObject
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget

def _pkg_dir() -> Path:
    """Package directory — works both normally and inside a PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "hector_desktop"
    return Path(__file__).parent

_PKG_DIR = _pkg_dir()
_LOGO_PATH = str(_PKG_DIR / "resources" / "Logo.png")
_ICON_PATH = str(_PKG_DIR / "resources" / "hector.icns")


# Minimum time the splash screen stays visible, in milliseconds. If the backend
# import finishes sooner, the main window waits out the remainder so the splash
# does not just flash by on fast machines.
_SPLASH_MIN_MS = 2500

from hector_desktop import core as style
from hector_desktop import __version__


class _ImportWorker(QThread):
    """Imports the inference backend in a background thread."""

    progress = Signal(str)
    finished = Signal()
    error = Signal(str)

    def run(self) -> None:
        try:
            self.progress.emit("Loading model runtime…")
            import hector  # noqa: F401
            self.progress.emit("Ready")
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class _SplashScreen(QWidget):
    """Minimal splash shown during TF import."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedSize(500, 260)
        self.setStyleSheet(
            f"background: {style.PANEL}; border-radius: 14px; "
            f"border: 1px solid {style.BORDER};"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 20)
        layout.setSpacing(4)

        no_border = "border: none;"

        logo_lbl = QLabel()
        logo_lbl.setStyleSheet(no_border)
        logo_pix = QPixmap(_LOGO_PATH).scaled(
            150, 150, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        logo_lbl.setPixmap(logo_pix)
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_lbl)

        tagline = QLabel("Hierarchical Embedding and Contrastive Training for\nOntology-guided Recognition")
        tagline.setStyleSheet(
            f"font-size: 15px; font-style: italic; font-weight: 400; "
            f"color: {style.INK_2}; {no_border}"
        )
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)

        version_str = __version__
        version = QLabel(f"v{version_str}")
        version.setStyleSheet(f"font-size: 12px; color: {style.INK_3}; {no_border}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        layout.addStretch()

        self.status = QLabel("Initializing…")
        self.status.setStyleSheet(f"font-size: 14px; color: {style.INK_3}; {no_border}")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setFixedHeight(4)
        layout.addWidget(self.progress)

        self._center_on_screen()

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2 + geo.x()
            y = (geo.height() - self.height()) // 2 + geo.y()
            self.move(x, y)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("HECTOR Desktop")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(style.build_stylesheet())
    app.setWindowIcon(QIcon(_ICON_PATH))

    splash = _SplashScreen()
    splash.show()
    splash.raise_()
    splash.activateWindow()
    app.processEvents()

    shown_at = QElapsedTimer()
    shown_at.start()

    worker = _ImportWorker()

    def on_progress(msg: str) -> None:
        splash.status.setText(msg)

    def on_ready() -> None:
        from hector_desktop.core import AppState

        state = AppState()
        win = MainWindow(state)
        app._main_window = win  # prevent GC

        def reveal() -> None:
            win.show()
            win.raise_()
            win.activateWindow()
            splash.close()

        remaining = _SPLASH_MIN_MS - shown_at.elapsed()
        if remaining > 0:
            QTimer.singleShot(int(remaining), reveal)
        else:
            reveal()

    def on_error(msg: str) -> None:
        splash.status.setText(f"Error: {msg}")
        splash.progress.setRange(0, 1)
        splash.progress.setValue(0)

    worker.progress.connect(on_progress)
    worker.finished.connect(on_ready)
    worker.error.connect(on_error)
    worker.start()

    app._import_worker = worker  # prevent GC

    return app.exec()
