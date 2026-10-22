"""Results views for predictions, embeddings, and quality metrics."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt

from hector_desktop.core import LineageGroup


class TreeNode:
    """Internal node for the tree model."""

    __slots__ = (
        "display_name", "full_name", "cl_id", "color", "count",
        "percentage", "visible", "focused", "parent", "children",
        "is_group",
    )

    def __init__(
        self,
        display_name: str,
        full_name: str,
        cl_id: str,
        color: str,
        count: int,
        percentage: float,
        is_group: bool = False,
        parent: TreeNode | None = None,
    ) -> None:
        self.display_name = display_name
        self.full_name = full_name
        self.cl_id = cl_id
        self.color = color
        self.count = count
        self.percentage = percentage
        self.visible = True
        self.focused = False
        self.parent = parent
        self.children: list[TreeNode] = []
        self.is_group = is_group

    def row(self) -> int:
        if self.parent and self.parent.children:
            return self.parent.children.index(self)
        return 0


class CellTypeTreeModel(QAbstractItemModel):
    """Two-level tree model for the hierarchical cell type legend.

    Level 0: lineage groups (T cells, B cells, ...)
    Level 1: individual cell types within each group
    """

    NAME_COL = 0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._root = TreeNode("root", "", "", "", 0, 0.0, is_group=True)
        self._total_cells = 0
        self._total_types = 0
        self._max_pct = 0.0

    @property
    def total_types(self) -> int:
        return self._total_types

    @property
    def max_pct(self) -> float:
        return self._max_pct

    def clear(self) -> None:
        self.beginResetModel()
        self._root = TreeNode("root", "", "", "", 0, 0.0, is_group=True)
        self._total_cells = 0
        self._total_types = 0
        self._max_pct = 0.0
        self.endResetModel()

    def populate(
        self,
        labels: np.ndarray,
        groups: list[LineageGroup],
        display_names: dict[str, str],
        color_map: dict[str, str],
    ) -> None:
        """Build the tree from lineage groups and predicted labels."""
        self.beginResetModel()
        self._root.children.clear()

        counts = Counter(labels)
        self._total_cells = len(labels)
        self._total_types = len(counts)
        self._max_pct = (
            100.0 * max(counts.values()) / self._total_cells
            if self._total_cells > 0 and counts
            else 0.0
        )

        grouped_cl_ids: set[str] = set()

        for grp in groups:
            pct = 100.0 * grp.total_count / self._total_cells if self._total_cells > 0 else 0.0
            group_node = TreeNode(
                display_name=grp.group_name,
                full_name=grp.group_name,
                cl_id=grp.group_cl_id,
                color=grp.color,
                count=grp.total_count,
                percentage=pct,
                is_group=True,
                parent=self._root,
            )

            members_sorted = sorted(
                grp.member_cl_ids,
                key=lambda cl: counts.get(cl, 0),
                reverse=True,
            )
            for cl_id in members_sorted:
                c = counts.get(cl_id, 0)
                if c == 0:
                    continue
                p = 100.0 * c / self._total_cells if self._total_cells > 0 else 0.0
                name = display_names.get(cl_id, cl_id)
                child = TreeNode(
                    display_name=name,
                    full_name=name,
                    cl_id=cl_id,
                    color=color_map.get(cl_id, grp.color),
                    count=c,
                    percentage=p,
                    is_group=False,
                    parent=group_node,
                )
                group_node.children.append(child)
                grouped_cl_ids.add(cl_id)

            if group_node.children:
                self._root.children.append(group_node)

        # Collect ungrouped cell types into an "Other" group
        ungrouped = [
            cl_id for cl_id in counts
            if cl_id not in grouped_cl_ids and counts[cl_id] > 0
        ]
        if ungrouped:
            ungrouped.sort(key=lambda cl: counts[cl], reverse=True)
            other_count = sum(counts[cl] for cl in ungrouped)
            other_pct = 100.0 * other_count / self._total_cells if self._total_cells > 0 else 0.0
            other_group = TreeNode(
                display_name="Other",
                full_name="Other",
                cl_id="",
                color="#94A3B8",
                count=other_count,
                percentage=other_pct,
                is_group=True,
                parent=self._root,
            )
            for cl_id in ungrouped:
                c = counts[cl_id]
                p = 100.0 * c / self._total_cells if self._total_cells > 0 else 0.0
                name = display_names.get(cl_id, cl_id)
                child = TreeNode(
                    display_name=name,
                    full_name=name,
                    cl_id=cl_id,
                    color=color_map.get(cl_id, "#94A3B8"),
                    count=c,
                    percentage=p,
                    is_group=False,
                    parent=other_group,
                )
                other_group.children.append(child)
            self._root.children.append(other_group)

        self.endResetModel()

    def populate_flat(
        self,
        labels: np.ndarray,
        color_map: dict[str, str],
        display_names: dict[str, str] | None = None,
    ) -> None:
        """Fallback: flat list without grouping."""
        self.beginResetModel()
        self._root.children.clear()

        counts = Counter(labels)
        self._total_cells = len(labels)
        self._total_types = len(counts)
        self._max_pct = (
            100.0 * max(counts.values()) / self._total_cells
            if self._total_cells > 0 and counts
            else 0.0
        )
        names = display_names or {}

        sorted_types = sorted(counts.keys(), key=lambda k: -counts[k])
        for cl_id in sorted_types:
            c = counts[cl_id]
            p = 100.0 * c / self._total_cells if self._total_cells > 0 else 0.0
            name = names.get(cl_id, cl_id)
            node = TreeNode(
                display_name=name,
                full_name=name,
                cl_id=cl_id,
                color=color_map.get(cl_id, "#CCCCCC"),
                count=c,
                percentage=p,
                is_group=False,
                parent=self._root,
            )
            self._root.children.append(node)

        self.endResetModel()


    def set_visibility(self, cl_id: str, visible: bool) -> None:
        node = self._find_node_by_cl_id(cl_id)
        if node:
            node.visible = visible
            idx = self._index_for_node(node)
            self.dataChanged.emit(idx, idx)

    def set_group_visibility(self, group_cl_id: str, visible: bool) -> None:
        for group in self._root.children:
            if group.is_group and group.cl_id == group_cl_id:
                group.visible = visible
                for child in group.children:
                    child.visible = visible
                top_left = self._index_for_node(group)
                if group.children:
                    bottom_right = self._index_for_node(group.children[-1])
                else:
                    bottom_right = top_left
                self.dataChanged.emit(top_left, bottom_right)
                break

    def set_all_visible(self, visible: bool) -> None:
        for group in self._root.children:
            group.visible = visible
            for child in group.children:
                child.visible = visible
        if self._root.children:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._root.children) - 1, 0),
            )

    def set_focused(self, cl_id: str | None) -> None:
        for group in self._root.children:
            group.focused = (group.cl_id == cl_id) if cl_id else False
            for child in group.children:
                child.focused = (child.cl_id == cl_id) if cl_id else False
        if self._root.children:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._root.children) - 1, 0),
            )

    def get_group_member_ids(self, group_cl_id: str) -> list[str]:
        for group in self._root.children:
            if group.is_group and group.cl_id == group_cl_id:
                return [child.cl_id for child in group.children]
        return []

    def all_type_cl_ids(self) -> list[str]:
        result = []
        for group in self._root.children:
            if group.is_group:
                result.extend(child.cl_id for child in group.children)
            else:
                result.append(group.cl_id)
        return result


    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            node = self._root.children[row] if row < len(self._root.children) else None
        else:
            parent_node: TreeNode = parent.internalPointer()
            node = parent_node.children[row] if row < len(parent_node.children) else None
        if node is None:
            return QModelIndex()
        return self.createIndex(row, column, node)

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node: TreeNode = index.internalPointer()
        parent_node = node.parent
        if parent_node is None or parent_node is self._root:
            return QModelIndex()
        return self.createIndex(parent_node.row(), 0, parent_node)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return len(self._root.children)
        node: TreeNode = parent.internalPointer()
        return len(node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        node: TreeNode = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            return node.display_name
        if role == Qt.ItemDataRole.ToolTipRole:
            return node.full_name
        if role == Qt.ItemDataRole.UserRole:
            return node
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


    def _find_node_by_cl_id(self, cl_id: str) -> TreeNode | None:
        for group in self._root.children:
            if group.cl_id == cl_id:
                return group
            for child in group.children:
                if child.cl_id == cl_id:
                    return child
        return None

    def _index_for_node(self, node: TreeNode) -> QModelIndex:
        if node is self._root or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.row(), 0, node)


from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from hector_desktop import core as style

DOT_SIZE = 12
DOT_LEFT_MARGIN = 8
DOT_RIGHT_MARGIN = 8
NAME_RIGHT_MARGIN = 4
BAR_HEIGHT = 3
ROW_HEIGHT_GROUP = 44
ROW_HEIGHT_CHILD = 32
CHILD_INDENT = 20
ARROW_SIZE = 6
ARROW_LEFT = 6


class CellTypeDelegate(QStyledItemDelegate):
    """Paints legend rows and detects dot-area clicks."""

    dot_clicked = Signal(str, bool)
    row_clicked = Signal(str, bool)

    def __init__(self, max_pct_ref: callable, parent=None) -> None:
        super().__init__(parent)
        self._max_pct_ref = max_pct_ref
        self._name_font = QFont(style.FONT_FAMILY.split(",")[0].strip("' "), 11)
        self._small_font = QFont(style.FONT_FAMILY.split(",")[0].strip("' "), 10)
        self._group_font = QFont(style.FONT_FAMILY.split(",")[0].strip("' "), 11)
        self._group_font.setBold(True)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        node: TreeNode = index.data(Qt.ItemDataRole.UserRole)
        if node and node.is_group:
            return QSize(option.rect.width(), ROW_HEIGHT_GROUP)
        return QSize(option.rect.width(), ROW_HEIGHT_CHILD)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        node: TreeNode = index.data(Qt.ItemDataRole.UserRole)
        if node is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect

        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor(style.ACCENT_LIGHT))
        elif node.focused:
            painter.fillRect(rect, QColor(style.ACCENT_LIGHT))

        x = rect.x()

        if node.is_group:
            # Draw expand/collapse arrow
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            arrow_cx = x + ARROW_LEFT + ARROW_SIZE // 2
            arrow_cy = rect.y() + rect.height() // 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(style.INK_3))
            view = option.widget
            expanded = view.isExpanded(index) if view else True
            if expanded:
                tri = QPolygonF([
                    QPointF(arrow_cx - ARROW_SIZE / 2, arrow_cy - ARROW_SIZE / 3),
                    QPointF(arrow_cx + ARROW_SIZE / 2, arrow_cy - ARROW_SIZE / 3),
                    QPointF(arrow_cx, arrow_cy + ARROW_SIZE / 2),
                ])
            else:
                tri = QPolygonF([
                    QPointF(arrow_cx - ARROW_SIZE / 3, arrow_cy - ARROW_SIZE / 2),
                    QPointF(arrow_cx + ARROW_SIZE / 2, arrow_cy),
                    QPointF(arrow_cx - ARROW_SIZE / 3, arrow_cy + ARROW_SIZE / 2),
                ])
            painter.drawPolygon(tri)
            x += ARROW_LEFT + ARROW_SIZE + 4

        x += DOT_LEFT_MARGIN
        if not node.is_group and node.parent and node.parent.is_group:
            x += CHILD_INDENT

        # Dot / square
        dot_y = rect.y() + (rect.height() - DOT_SIZE) // 2
        dot_rect = QRect(x, dot_y, DOT_SIZE, DOT_SIZE)

        color = QColor(node.color)
        if node.visible:
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(color, 1.5))

        if node.is_group:
            painter.drawRoundedRect(QRectF(dot_rect), 2, 2)
        else:
            painter.drawEllipse(dot_rect)

        x += DOT_SIZE + DOT_RIGHT_MARGIN

        text_color = QColor(style.INK) if node.visible else QColor(style.INK_3)
        count_color = QColor(style.INK_2) if node.visible else QColor(style.INK_3)

        text_right = rect.right() - 8
        font = self._group_font if node.is_group else self._name_font
        fm = QFontMetrics(font)

        # Line 1: name (left) + "1,007 · 36.6%" (right)
        info_text = f"{node.count:,} · {node.percentage:.1f}%"
        info_fm = QFontMetrics(self._small_font)
        info_w = info_fm.horizontalAdvance(info_text) + 4

        if node.is_group:
            line1_y = rect.y()
            line1_h = rect.height() // 2 + 4
        else:
            line1_y = rect.y()
            line1_h = rect.height()

        name_avail = text_right - x - info_w - NAME_RIGHT_MARGIN
        if name_avail > 0:
            elided = fm.elidedText(node.display_name, Qt.TextElideMode.ElideRight, name_avail)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(
                QRect(x, line1_y, name_avail, line1_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided,
            )

        painter.setFont(self._small_font)
        painter.setPen(count_color)
        painter.drawText(
            QRect(x, line1_y, text_right - x, line1_h),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, info_text,
        )

        # Line 2 (groups only): "20 types" right-aligned
        if node.is_group and node.children:
            line2_y = line1_y + line1_h - 2
            line2_h = rect.height() - line1_h
            sub_text = f"{len(node.children)} types"
            painter.setFont(self._small_font)
            painter.setPen(QColor(style.INK_3))
            painter.drawText(
                QRect(x, line2_y, text_right - x, line2_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, sub_text,
            )

        # Mini percentage bar (child rows only)
        if not node.is_group:
            bar_x = x
            bar_y = rect.bottom() - BAR_HEIGHT - 3
            bar_w = text_right - x - info_w - 8
            max_pct = self._max_pct_ref()

            if bar_w > 4:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(style.BORDER_SOFT))
                painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, BAR_HEIGHT), 1, 1)

                frac = min(node.percentage / max_pct, 1.0) if max_pct > 0 else 0
                fill_w = max(2, int(bar_w * frac))
                painter.setBrush(QColor(node.color))
                painter.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, BAR_HEIGHT), 1, 1)

        painter.restore()

    def dot_rect_for_index(self, option_rect: QRect, is_group: bool, has_group_parent: bool) -> QRect:
        """Return the dot's bounding rect for hit-testing."""
        x = option_rect.x()
        if is_group:
            x += ARROW_LEFT + ARROW_SIZE + 4
        x += DOT_LEFT_MARGIN
        if not is_group and has_group_parent:
            x += CHILD_INDENT
        dot_y = option_rect.y() + (option_rect.height() - DOT_SIZE) // 2
        return QRect(x, dot_y, DOT_SIZE, DOT_SIZE)


from enum import Enum

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt



class SortMode(Enum):
    ABUNDANCE = "abundance"
    ALPHA = "A->Z"


class CellTypeSortFilterProxy(QSortFilterProxyModel):
    """Proxy that filters by name substring and sorts by abundance or alphabetically."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._sort_mode = SortMode.ABUNDANCE
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setRecursiveFilteringEnabled(True)

    @property
    def sort_mode(self) -> SortMode:
        return self._sort_mode

    def set_sort_mode(self, mode: SortMode) -> None:
        self._sort_mode = mode
        self.invalidate()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        pattern = self.filterRegularExpression().pattern()
        if not pattern:
            return True

        source_model = self.sourceModel()
        idx = source_model.index(source_row, 0, source_parent)
        if not idx.isValid():
            return False

        node: TreeNode = idx.data(Qt.ItemDataRole.UserRole)
        if node is None:
            return False

        query = pattern.lower()

        if query in node.display_name.lower():
            return True

        if node.is_group:
            for row in range(source_model.rowCount(idx)):
                child_idx = source_model.index(row, 0, idx)
                child_node: TreeNode = child_idx.data(Qt.ItemDataRole.UserRole)
                if child_node and query in child_node.display_name.lower():
                    return True

        return False

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_node: TreeNode = left.data(Qt.ItemDataRole.UserRole)
        right_node: TreeNode = right.data(Qt.ItemDataRole.UserRole)

        if left_node is None or right_node is None:
            return False

        if self._sort_mode == SortMode.ABUNDANCE:
            return left_node.count > right_node.count
        else:
            return left_node.display_name.lower() < right_node.display_name.lower()

    def visible_type_count(self) -> int:
        """Count how many leaf (non-group) items pass the filter."""
        count = 0
        for row in range(self.rowCount()):
            idx = self.index(row, 0)
            node: TreeNode = self.data(idx, Qt.ItemDataRole.UserRole)
            if node and node.is_group:
                count += self.rowCount(idx)
            elif node:
                count += 1
        return count


from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from hector_desktop import core as style


class _SummaryTableModel(QAbstractTableModel):
    """Read-only model for the per-cell-type summary table."""

    _COLUMNS = ["Cell Type", "Count", "Percentage", "Mean Score"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._df = pd.DataFrame(columns=self._COLUMNS)

    def set_dataframe(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._df)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._df.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            val = self._df.iloc[index.row(), index.column()]
            if isinstance(val, float):
                return f"{val:.2f}"
            if isinstance(val, (int, np.integer)):
                return f"{val:,}"
            return str(val)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if index.column() >= 1:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._COLUMNS[section]
        return str(section + 1)


class PredictionsSummary(QWidget):
    """Predictions overview: composition bar chart, per-type summary table, and CSV download."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results_df: Optional[pd.DataFrame] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._placeholder = QLabel("Run a prediction to see results.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(f"font-size: 14px; color: {style.INK_3};")
        layout.addWidget(self._placeholder)

        self._content = QWidget()
        self._content.hide()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        # Horizontal split: chart left, table right
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)

        # Bar chart
        self.fig = Figure(figsize=(5, 4), dpi=100, facecolor=style.PANEL)
        self.canvas = FigureCanvasQTAgg(self.fig)
        splitter.addWidget(self.canvas)

        # Summary table
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(4)

        table_header = QLabel("Per-type summary")
        table_header.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {style.INK_2};")
        table_layout.addWidget(table_header)

        self._model = _SummaryTableModel()
        self._view = QTableView()
        self._view.setModel(self._model)
        self._view.setSortingEnabled(True)
        self._view.setAlternatingRowColors(True)
        self._view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._view.horizontalHeader().setStretchLastSection(True)
        self._view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._view.verticalHeader().setDefaultSectionSize(26)
        self._view.verticalHeader().hide()
        table_layout.addWidget(self._view)
        splitter.addWidget(table_container)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        content_layout.addWidget(splitter, 1)

        layout.addWidget(self._content, 1)

    def clear(self) -> None:
        self._results_df = None
        self._model.set_dataframe(pd.DataFrame(columns=_SummaryTableModel._COLUMNS))
        self.fig.clear()
        self.canvas.draw_idle()
        self._content.hide()
        self._placeholder.show()

    def set_data(self, results_df: pd.DataFrame, adata) -> None:
        self._results_df = results_df
        self._placeholder.hide()
        self._content.show()

        obs = adata.obs
        labels = obs["hector_prediction"].values
        has_scores = "hector_prediction_confidence" in obs.columns
        scores = obs["hector_prediction_confidence"].values.astype(float) if has_scores else None

        # Build per-type summary
        types, counts = np.unique(labels, return_counts=True)
        order = np.argsort(-counts)
        types, counts = types[order], counts[order]
        total = counts.sum()
        pcts = 100.0 * counts / total

        mean_scores = []
        if has_scores:
            for t in types:
                mean_scores.append(float(np.mean(scores[labels == t])))
        else:
            mean_scores = [np.nan] * len(types)

        summary_df = pd.DataFrame({
            "Cell Type": types,
            "Count": counts,
            "Percentage": pcts,
            "Mean Score": mean_scores,
        })
        self._model.set_dataframe(summary_df)
        self._view.resizeColumnsToContents()

        self._plot_composition(types, counts, pcts, total)

    def _plot_composition(
        self, types: np.ndarray, counts: np.ndarray, pcts: np.ndarray, total: int,
    ) -> None:
        self.fig.clear()
        ax = self.fig.add_subplot(111)

        threshold = 0.5
        main_mask = pcts >= threshold
        main_types = types[main_mask]
        main_counts = counts[main_mask]

        other_count = int(counts[~main_mask].sum())
        n_other = int((~main_mask).sum())

        palette = style.CELL_TYPE_PALETTE
        colors = [palette[i % len(palette)] for i in range(len(main_types))]

        chart_labels = list(main_types)
        chart_counts = list(main_counts)
        if n_other > 0:
            chart_labels.append(f"Other ({n_other} types)")
            chart_counts.append(other_count)
            colors.append(style.INK_3)

        y_pos = np.arange(len(chart_labels))
        ax.barh(y_pos, chart_counts, color=colors, edgecolor="white", linewidth=0.5)

        ax.set_yticks(y_pos)
        ax.set_yticklabels(chart_labels, fontsize=9)
        ax.invert_yaxis()
        ax.set_xlabel("Number of cells", fontsize=10)
        ax.set_title("Cell type composition", fontsize=11, fontweight="bold")
        ax.tick_params(axis="x", labelsize=8)

        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)

        self.fig.tight_layout()
        self.canvas.draw_idle()



from typing import Optional

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from hector_desktop import core as style


class QCPanel(QWidget):
    """Displays prediction quality metrics after a prediction run."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._placeholder = QLabel("Run a prediction to see QC metrics.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(f"font-size: 14px; color: {style.INK_3};")
        layout.addWidget(self._placeholder)

        self._stats_label = QLabel()
        self._stats_label.setStyleSheet("font-size: 12px;")
        self._stats_label.setWordWrap(True)
        self._stats_label.hide()
        layout.addWidget(self._stats_label)

        self.fig = Figure(figsize=(6, 3), dpi=100, facecolor=style.PANEL)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.hide()
        layout.addWidget(self.canvas)

        layout.addStretch()

    def clear(self) -> None:
        self._stats_label.clear()
        self._stats_label.hide()
        self.fig.clear()
        self.canvas.draw_idle()
        self.canvas.hide()
        self._placeholder.show()

    def update_metrics(self, adata) -> None:
        """Compute and display QC metrics from annotated adata."""
        self._placeholder.hide()

        obs = adata.obs
        lines = []
        lines.append(f"<b>Total cells:</b> {len(obs):,}")

        if "hector_prediction_confidence" in obs.columns:
            scores = obs["hector_prediction_confidence"].values.astype(float)
            lines.append(f"<b>Median confidence:</b> {np.median(scores):.3f}")
            lines.append(
                f"<b>Cells above 0.9:</b> {np.sum(scores >= 0.9):,} "
                f"({100 * np.mean(scores >= 0.9):.1f}%)"
            )
            lines.append(
                f"<b>Cells below 0.5:</b> {np.sum(scores < 0.5):,} "
                f"({100 * np.mean(scores < 0.5):.1f}%)"
            )
            self._plot_histogram(scores)

        if "is_low_quality" in obs.columns:
            n_lq = obs["is_low_quality"].sum()
            lines.append(
                f"<b>Low quality flagged:</b> {n_lq:,} "
                f"({100 * n_lq / len(obs):.1f}%)"
            )

        if "hector_prediction" in obs.columns:
            n_types = obs["hector_prediction"].nunique()
            lines.append(f"<b>Unique cell types:</b> {n_types}")

        self._stats_label.setText("<br>".join(lines))
        self._stats_label.show()

    def _plot_histogram(self, scores: np.ndarray) -> None:
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.hist(scores, bins=50, color=style.ACCENT, alpha=0.7, edgecolor="white", linewidth=0.5)
        ax.set_xlabel("Prediction confidence", fontsize=10)
        ax.set_ylabel("Cells", fontsize=10)
        ax.set_title("Confidence distribution", fontsize=11, fontweight="bold")
        ax.tick_params(labelsize=8)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        self.fig.tight_layout()
        self.canvas.show()
        self.canvas.draw_idle()


from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import QToolTip, QVBoxLayout, QWidget

from hector_desktop import core as style

_DIM_OPACITY = 15 / 255.0
_FULL_OPACITY = 190 / 255.0


class UmapCanvas(QWidget):
    """Renders an interactive 2-D embedding scatter plot (UMAP or t-SNE).

    Supports hover tooltips, click-to-highlight, pan/zoom, recoloring,
    and per-type visibility toggling.
    """

    point_clicked = Signal(str, int)
    point_hovered = Signal(str, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground(style.PLOT_BG)
        self._x_label = "UMAP 1"
        self._y_label = "UMAP 2"
        self._plot_widget.setLabel("bottom", self._x_label)
        self._plot_widget.setLabel("left", self._y_label)
        self._plot_widget.setAspectLocked(True)
        self._plot_widget.getAxis("bottom").setPen(pg.mkPen(style.BORDER))
        self._plot_widget.getAxis("left").setPen(pg.mkPen(style.BORDER))
        self._plot_widget.getAxis("bottom").setTextPen(pg.mkPen(style.INK_3))
        self._plot_widget.getAxis("left").setTextPen(pg.mkPen(style.INK_3))
        layout.addWidget(self._plot_widget)

        self._scatter: Optional[pg.ScatterPlotItem] = None
        self._scatters: dict[str, pg.ScatterPlotItem] = {}
        self._coords: Optional[np.ndarray] = None
        self._labels: Optional[np.ndarray] = None
        self._scores: Optional[np.ndarray] = None
        self._visible_types: set[str] = set()
        self._point_size: float = 2.5
        self._color_map: dict[str, str] = {}
        self._highlighted_type: str | None = None
        self._is_categorical: bool = True
        self._type_masks: dict[str, np.ndarray] = {}

        self._placeholder = pg.TextItem(
            "Run a prediction first\n\n"
            "Predictions populate the cell type labels\n"
            "used to color this plot.",
            color=style.INK_3, anchor=(0.5, 0.5),
        )
        self._placeholder.setFont(pg.QtGui.QFont(style.FONT_FAMILY.split(",")[0].strip("' "), 13))
        self._plot_widget.addItem(self._placeholder)
        self._placeholder.setPos(0, 0)
        self._plot_widget.hideAxis("bottom")
        self._plot_widget.hideAxis("left")

    def clear(self) -> None:
        self._remove_all_scatters()
        self._scatter = None
        self._coords = None
        self._labels = None
        self._scores = None
        self._visible_types = set()
        self._color_map = {}
        self._highlighted_type = None
        self._is_categorical = True
        self._type_masks = {}
        if self._placeholder is None:
            self._placeholder = pg.TextItem(
                "Run a prediction first\n\n"
                "Predictions populate the cell type labels\n"
                "used to color this plot.",
                color=style.INK_3, anchor=(0.5, 0.5),
            )
            self._placeholder.setFont(pg.QtGui.QFont(style.FONT_FAMILY.split(",")[0].strip("' "), 13))
            self._plot_widget.addItem(self._placeholder)
            self._placeholder.setPos(0, 0)
            self._plot_widget.hideAxis("bottom")
            self._plot_widget.hideAxis("left")
        self._plot_widget.autoRange()

    def plot(
        self,
        coords: np.ndarray,
        labels: np.ndarray,
        color_map: dict[str, str],
        point_size: float | None = None,
    ) -> None:
        if point_size is not None:
            self._point_size = point_size

        self._coords = np.asarray(coords)
        self._labels = np.asarray(labels)
        self._color_map = color_map
        self._visible_types = set(color_map.keys())
        self._highlighted_type = None
        self._is_categorical = True

        if self._placeholder is not None:
            self._plot_widget.removeItem(self._placeholder)
            self._placeholder = None
            self._plot_widget.showAxis("bottom")
            self._plot_widget.showAxis("left")

        self._remove_all_scatters()
        self._build_per_type_scatters(coords, labels, color_map)

        # Keep a single _scatter reference for hover/click compatibility
        self._scatter = self._scatters.get(
            next(iter(self._scatters)) if self._scatters else "", None
        )
        self._plot_widget.autoRange()

    def recolor(
        self,
        values: np.ndarray,
        color_map: dict | None = None,
        is_categorical: bool = True,
    ) -> None:
        if not self._scatters and self._scatter is None:
            return
        if self._coords is None:
            return

        if is_categorical and color_map:
            self._labels = np.asarray(values)
            self._color_map = color_map
            self._visible_types = set(color_map.keys())
            self._is_categorical = True

            self._remove_all_scatters()
            self._build_per_type_scatters(self._coords, values, color_map)
            self._scatter = self._scatters.get(
                next(iter(self._scatters)) if self._scatters else "", None
            )
        else:
            self._is_categorical = False
            vals = np.asarray(values, dtype=float)
            vmin, vmax = np.nanmin(vals), np.nanmax(vals)
            if vmax > vmin:
                normed = (vals - vmin) / (vmax - vmin)
            else:
                normed = np.zeros_like(vals)
            cmap = pg.colormap.get("viridis")
            rgba = cmap.map(normed, mode="byte")
            self._scores = vals

            existing = self._scatters.get("__continuous__")
            if existing is not None and len(self._scatters) == 1:
                existing.setBrush(rgba)
            else:
                self._remove_all_scatters()
                self._type_masks = {}
                scatter = pg.ScatterPlotItem(
                    x=self._coords[:, 0],
                    y=self._coords[:, 1],
                    size=self._point_size,
                    pen=pg.mkPen(None),
                    brush=rgba,
                    pxMode=True,
                    hoverable=True,
                    hoverSize=self._point_size + 4,
                    hoverPen=pg.mkPen(color="w", width=1.5),
                    tip=None,
                    data=np.arange(len(vals)),
                )
                scatter.sigClicked.connect(self._on_click)
                scatter.sigHovered.connect(self._on_hover)
                self._plot_widget.addItem(scatter)
                self._scatters["__continuous__"] = scatter
                self._scatter = scatter

        self._highlighted_type = None

    def set_point_size(self, size: float) -> None:
        self._point_size = size
        for s in self._scatters.values():
            s.setSize(size)

    def set_type_visible(self, type_name: str, visible: bool) -> None:
        if not self._scatters or self._labels is None:
            return
        if visible:
            self._visible_types.add(type_name)
        else:
            self._visible_types.discard(type_name)
        self._apply_visibility()

    def set_all_visible(self, visible: bool) -> None:
        if self._labels is None:
            return
        if visible:
            self._visible_types = set(str(lbl) for lbl in np.unique(self._labels))
        else:
            self._visible_types.clear()
        self._apply_visibility()

    def highlight_type(self, type_name: str) -> None:
        if not self._scatters or self._labels is None:
            return
        self._highlighted_type = type_name
        for name, s in self._scatters.items():
            if name == type_name:
                s.setOpacity(_FULL_OPACITY)
            else:
                s.setOpacity(_DIM_OPACITY)

    def highlight_types(self, type_names: list[str]) -> None:
        """Focus multiple types — dims everything not in the list."""
        if not self._scatters or self._labels is None:
            return
        self._highlighted_type = type_names[0] if type_names else None
        name_set = set(type_names)
        for name, s in self._scatters.items():
            if name in name_set:
                s.setOpacity(_FULL_OPACITY)
            else:
                s.setOpacity(_DIM_OPACITY)

    def clear_highlight(self) -> None:
        if not self._scatters:
            return
        self._highlighted_type = None
        if self._is_categorical:
            for s in self._scatters.values():
                s.setOpacity(_FULL_OPACITY)

    def save_figure(
        self,
        path: str,
        dpi: int = 300,
        groups: list | None = None,
        method: str = "umap",
    ) -> None:
        if self._coords is None or self._labels is None:
            return

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D

        fig, ax = plt.subplots(figsize=(14, 10))

        ax.scatter(
            self._coords[:, 0],
            self._coords[:, 1],
            c=[self._color_map.get(str(lbl), "#CCCCCC") for lbl in self._labels],
            s=self._point_size ** 2 * 0.8,
            alpha=0.6,
            edgecolors="none",
            rasterized=True,
        )

        ax.set_xlabel(self._x_label, fontsize=12)
        ax.set_ylabel(self._y_label, fontsize=12)
        ax.set_aspect("equal", adjustable="datalim")
        ax.tick_params(labelsize=9)

        if groups:
            handles = [
                Line2D(
                    [0], [0],
                    marker="o",
                    color="none",
                    markerfacecolor=g.color,
                    markersize=7,
                    label=f"{g.group_name}  ({g.total_count:,})",
                )
                for g in sorted(groups, key=lambda g: -g.total_count)
            ]
            ax.legend(
                handles=handles,
                loc="center left",
                bbox_to_anchor=(1.02, 0.5),
                fontsize=8,
                title="Lineage",
                title_fontsize=10,
                frameon=True,
                fancybox=False,
                edgecolor="#CCCCCC",
            )

        plt.tight_layout()
        plt.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
        plt.close(fig)

    def set_scores(self, scores: np.ndarray) -> None:
        self._scores = np.asarray(scores)

    def set_axis_labels(self, x_label: str, y_label: str) -> None:
        """Update axis labels (e.g. 'UMAP 1'/'UMAP 2' or 't-SNE 1'/'t-SNE 2')."""
        self._x_label = x_label
        self._y_label = y_label
        self._plot_widget.setLabel("bottom", x_label)
        self._plot_widget.setLabel("left", y_label)


    def _build_per_type_scatters(
        self,
        coords: np.ndarray,
        labels: np.ndarray,
        color_map: dict[str, str],
    ) -> None:
        labels_str = np.asarray(labels, dtype=str)
        unique_labels = np.unique(labels_str)
        self._type_masks = {}

        no_pen = pg.mkPen(None)
        hover_pen = pg.mkPen(color="w", width=1.5)
        hover_size = self._point_size + 4

        for lbl in unique_labels:
            mask = labels_str == lbl
            self._type_masks[lbl] = mask
            hex_c = color_map.get(lbl, "#CCCCCC")
            c = QColor(hex_c)
            c.setAlpha(190)

            indices = np.where(mask)[0]
            scatter = pg.ScatterPlotItem(
                x=coords[mask, 0],
                y=coords[mask, 1],
                size=self._point_size,
                pen=no_pen,
                brush=pg.mkBrush(c),
                pxMode=True,
                hoverable=True,
                hoverSize=hover_size,
                hoverPen=hover_pen,
                tip=None,
                data=indices,
            )
            scatter.setOpacity(_FULL_OPACITY)
            scatter.sigClicked.connect(self._on_click)
            scatter.sigHovered.connect(self._on_hover)
            self._plot_widget.addItem(scatter)
            self._scatters[lbl] = scatter

    def _remove_all_scatters(self) -> None:
        for s in self._scatters.values():
            self._plot_widget.removeItem(s)
        self._scatters.clear()
        if self._scatter is not None:
            try:
                self._plot_widget.removeItem(self._scatter)
            except Exception:
                pass
            self._scatter = None

    def _apply_visibility(self) -> None:
        if not self._scatters or self._labels is None:
            return
        for name, s in self._scatters.items():
            if name in self._visible_types:
                s.show()
                s.setOpacity(_FULL_OPACITY)
            else:
                s.hide()

    def _on_hover(self, item, points, event) -> None:
        if len(points) == 0:
            QToolTip.hideText()
            return
        spot = points[0]
        idx = spot.data()
        if idx is None or self._labels is None:
            return
        lbl = str(self._labels[idx])
        QToolTip.showText(QCursor.pos(), lbl, self)
        self.point_hovered.emit(lbl, int(idx))

    def _on_click(self, item, points, event) -> None:
        if len(points) == 0:
            return
        spot = points[0]
        idx = spot.data()
        if idx is None or self._labels is None:
            return
        lbl = str(self._labels[idx])
        if self._highlighted_type == lbl:
            self.clear_highlight()
            self.point_clicked.emit("", -1)
        else:
            self.highlight_type(lbl)
            self.point_clicked.emit(lbl, int(idx))


import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from hector_desktop import core as style
from hector_desktop.core import LineageGroup


class GradientBar(QWidget):
    """Vertical viridis gradient bar with min/max labels."""

    _VIRIDIS_STOPS = [
        (0.0, "#440154"),
        (0.2, "#443983"),
        (0.4, "#31688e"),
        (0.6, "#21918c"),
        (0.8, "#35b779"),
        (1.0, "#fde725"),
    ]

    def __init__(self, vmin: float, vmax: float, column_name: str, parent=None) -> None:
        super().__init__(parent)
        self._vmin = vmin
        self._vmax = vmax
        self._column_name = column_name
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        label_h = 20
        bar_x = 20
        bar_w = 24
        bar_top = label_h + 4
        bar_bottom = h - label_h - 4
        bar_h = bar_bottom - bar_top

        if bar_h < 10:
            painter.end()
            return

        grad = QLinearGradient(0, bar_bottom, 0, bar_top)
        for pos, hex_color in self._VIRIDIS_STOPS:
            grad.setColorAt(pos, QColor(hex_color))

        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            float(bar_x), float(bar_top), float(bar_w), float(bar_h), 3.0, 3.0
        )

        painter.setPen(QColor(style.INK_2))
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)

        text_x = bar_x + bar_w + 8
        painter.drawText(text_x, bar_top + 12, f"{self._vmax:.2g}")
        painter.drawText(text_x, bar_bottom, f"{self._vmin:.2g}")

        painter.setPen(QColor(style.INK_3))
        font.setPixelSize(10)
        painter.setFont(font)
        mid_y = (bar_top + bar_bottom) // 2
        mid_val = (self._vmin + self._vmax) / 2
        painter.drawText(text_x, mid_y + 4, f"{mid_val:.2g}")

        painter.end()


class LegendPanel(QWidget):
    """Hierarchical cell type legend with search, sort, focus, and show/hide."""

    type_toggled = Signal(str, bool)
    all_toggled = Signal(bool)
    type_highlight_requested = Signal(str)
    group_highlight_requested = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.setMaximumWidth(420)
        self._color_map: dict[str, str] = {}
        self._highlighted_type: str | None = None
        self._highlighted_group: str | None = None
        self._gradient_widget: GradientBar | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        header_row = QHBoxLayout()
        self._header = QLabel("CELL TYPES")
        self._header.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {style.INK_2}; letter-spacing: 0.5px;"
        )
        header_row.addWidget(self._header, 1)

        self._all_btn = QLabel("All")
        self._all_btn.setStyleSheet(
            f"font-size: 10px; color: {style.ACCENT}; font-weight: 600;"
        )
        self._all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._all_btn.mousePressEvent = lambda e: self._toggle_all(True)

        self._none_btn = QLabel("None")
        self._none_btn.setStyleSheet(
            f"font-size: 10px; color: {style.ACCENT}; font-weight: 600;"
        )
        self._none_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._none_btn.mousePressEvent = lambda e: self._toggle_all(False)

        header_row.addWidget(self._all_btn)
        header_row.addWidget(self._none_btn)
        outer.addLayout(header_row)

        sort_row = QHBoxLayout()
        sort_row.addStretch()
        sort_label = QLabel("Sort")
        sort_label.setStyleSheet(f"font-size: 10px; color: {style.INK_3};")
        sort_row.addWidget(sort_label)
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["abundance", "A→Z"])
        self._sort_combo.setFixedHeight(22)
        self._sort_combo.setFixedWidth(110)
        self._sort_combo.setStyleSheet("font-size: 10px;")
        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self._sort_combo)
        outer.addLayout(sort_row)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search cell types...")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setFixedHeight(26)
        self._search_edit.setStyleSheet(
            f"QLineEdit {{ font-size: 11px; padding: 2px 6px; "
            f"border: 1px solid {style.BORDER}; border-radius: 4px; "
            f"background: {style.BG}; }}"
            f"QLineEdit:focus {{ border-color: {style.ACCENT}; }}"
        )
        self._search_edit.textChanged.connect(self._on_search_changed)
        outer.addWidget(self._search_edit)

        self._clear_focus_chip = QLabel("✕ Clear focus")
        self._clear_focus_chip.setStyleSheet(
            f"font-size: 10px; color: {style.ACCENT}; font-weight: 500; "
            f"padding: 3px 8px; background: {style.ACCENT_LIGHT}; border-radius: 10px;"
        )
        self._clear_focus_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_focus_chip.mousePressEvent = lambda e: self._clear_focus()
        self._clear_focus_chip.hide()
        outer.addWidget(self._clear_focus_chip)

        self._model = CellTypeTreeModel(self)
        self._proxy = CellTypeSortFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        self._delegate = CellTypeDelegate(
            max_pct_ref=lambda: self._model.max_pct,
            parent=self,
        )

        self._tree = QTreeView()
        self._tree.setModel(self._proxy)
        self._tree.setItemDelegate(self._delegate)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(0)
        self._tree.setMouseTracking(True)
        self._tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tree.setSelectionMode(QTreeView.SelectionMode.NoSelection)
        self._tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tree.setStyleSheet(
            f"QTreeView {{ border: none; background: transparent; }}"
            f"QTreeView::item {{ border: none; }}"
            f"QTreeView::branch {{ background: transparent; }}"
        )
        self._tree.clicked.connect(self._on_tree_clicked)

        # Sticky header overlay
        self._sticky_header = QLabel(self)
        self._sticky_header.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {style.INK_2}; "
            f"background: {style.PANEL}; padding: 6px 8px; "
            f"border-bottom: 1px solid {style.BORDER_SOFT};"
        )
        self._sticky_header.hide()

        self._tree.verticalScrollBar().valueChanged.connect(self._update_sticky_header)

        outer.addWidget(self._tree, 1)

        self._instruction = QLabel("Click a row to focus · Click the dot to show / hide")
        self._instruction.setStyleSheet(
            f"font-size: 9px; color: {style.INK_3}; padding: 4px 0;"
        )
        self._instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._instruction)

        self._gradient_container = QWidget()
        gradient_layout = QVBoxLayout(self._gradient_container)
        gradient_layout.setContentsMargins(0, 0, 0, 0)
        self._gradient_container.hide()
        outer.addWidget(self._gradient_container)


    def clear(self) -> None:
        self._model.clear()
        self._color_map = {}
        self._highlighted_type = None
        self._highlighted_group = None
        self._search_edit.clear()
        self._clear_focus_chip.hide()
        self._sticky_header.hide()
        self._header.setText("CELL TYPES")
        self._show_categorical_mode()

    def populate(
        self,
        labels: np.ndarray,
        scores: np.ndarray | None = None,
        color_map: dict[str, str] | None = None,
        header: str | None = None,
        groups: list[LineageGroup] | None = None,
        display_names: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build legend from label array. Returns the color map used."""
        self._show_categorical_mode()

        if groups and display_names and color_map:
            self._model.populate(labels, groups, display_names, color_map)
            self._color_map = color_map
        elif color_map:
            self._model.populate_flat(labels, color_map, display_names)
            self._color_map = color_map
        else:
            palette = style.CELL_TYPE_PALETTE
            unique = list(dict.fromkeys(labels))
            self._color_map = {
                name: palette[i % len(palette)]
                for i, name in enumerate(unique)
            }
            self._model.populate_flat(labels, self._color_map)

        header_text = header if header else "CELL TYPES"
        self._header.setText(f"{header_text} · {self._model.total_types}")
        placeholder = f"Search {header_text.lower()}..." if header else "Search cell types..."
        self._search_edit.setPlaceholderText(placeholder)
        self._search_edit.clear()

        if groups and display_names and color_map:
            self._tree.collapseAll()
        else:
            self._tree.expandAll()
        self._highlighted_type = None
        self._highlighted_group = None
        self._clear_focus_chip.hide()

        return self._color_map

    def show_gradient(self, vmin: float, vmax: float, column_name: str) -> None:
        """Show a continuous gradient colorbar instead of categorical items."""
        self._show_gradient_mode()
        self._header.setText(column_name.upper())

        layout = self._gradient_container.layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self._gradient_widget = GradientBar(vmin, vmax, column_name)
        layout.addWidget(self._gradient_widget)
        layout.addStretch()

    @property
    def color_map(self) -> dict[str, str]:
        return self._color_map

    def scroll_to_type(self, type_name: str) -> None:
        node = self._model._find_node_by_cl_id(type_name)
        if node:
            source_idx = self._model._index_for_node(node)
            proxy_idx = self._proxy.mapFromSource(source_idx)
            if proxy_idx.isValid():
                self._tree.scrollTo(proxy_idx)

    def highlight_type(self, type_name: str | None) -> None:
        old = self._highlighted_type
        self._highlighted_type = type_name
        self._highlighted_group = None
        self._model.set_focused(type_name)
        self._clear_focus_chip.setVisible(type_name is not None)


    def _on_tree_clicked(self, proxy_index) -> None:
        source_index = self._proxy.mapToSource(proxy_index)
        node: TreeNode = source_index.data(Qt.ItemDataRole.UserRole)
        if node is None:
            return

        visual_rect = self._tree.visualRect(proxy_index)
        cursor_pos = self._tree.viewport().mapFromGlobal(self._tree.cursor().pos())

        # Group arrow area — toggle expand/collapse
        if node.is_group:
            arrow_right = visual_rect.x() + ARROW_LEFT + ARROW_SIZE + 4
            if cursor_pos.x() < arrow_right:
                self._tree.setExpanded(proxy_index, not self._tree.isExpanded(proxy_index))
                return

        dot_rect = self._delegate.dot_rect_for_index(
            visual_rect,
            node.is_group,
            node.parent is not None and node.parent.is_group if node.parent else False,
        )

        if dot_rect.contains(cursor_pos):
            new_visible = not node.visible
            if node.is_group:
                self._model.set_group_visibility(node.cl_id, new_visible)
                for child in node.children:
                    self.type_toggled.emit(child.cl_id, new_visible)
            else:
                self._model.set_visibility(node.cl_id, new_visible)
                self.type_toggled.emit(node.cl_id, new_visible)
        else:
            if node.is_group:
                if self._highlighted_group == node.cl_id:
                    self._clear_focus()
                else:
                    self._highlighted_group = node.cl_id
                    self._highlighted_type = None
                    member_ids = self._model.get_group_member_ids(node.cl_id)
                    self._model.set_focused(None)
                    for child in node.children:
                        child.focused = True
                    node.focused = True
                    self._clear_focus_chip.show()
                    self.group_highlight_requested.emit(member_ids)
            else:
                if self._highlighted_type == node.cl_id:
                    self._clear_focus()
                else:
                    self._highlighted_type = node.cl_id
                    self._highlighted_group = None
                    self._model.set_focused(node.cl_id)
                    self._clear_focus_chip.show()
                    self.type_highlight_requested.emit(node.cl_id)

    def _clear_focus(self) -> None:
        self._highlighted_type = None
        self._highlighted_group = None
        self._model.set_focused(None)
        self._clear_focus_chip.hide()
        self.type_highlight_requested.emit("")

    def _update_sticky_header(self) -> None:
        """Show a pinned group header when the group's first child scrolls past the top."""
        if not self._tree.isVisible():
            self._sticky_header.hide()
            return

        viewport = self._tree.viewport()
        top_index = self._tree.indexAt(viewport.rect().topLeft())
        if not top_index.isValid():
            self._sticky_header.hide()
            return

        source_index = self._proxy.mapToSource(top_index)
        node: TreeNode = source_index.data(Qt.ItemDataRole.UserRole)
        if node is None:
            self._sticky_header.hide()
            return

        if not node.is_group and node.parent and node.parent.is_group:
            group = node.parent
            self._sticky_header.setText(f"■ {group.display_name}  ·  {group.count:,} cells")
            color = group.color
            self._sticky_header.setStyleSheet(
                f"font-size: 11px; font-weight: 700; color: {style.INK_2}; "
                f"background: {style.PANEL}; padding: 6px 8px; "
                f"border-bottom: 1px solid {style.BORDER_SOFT}; "
                f"border-left: 3px solid {color};"
            )
            self._sticky_header.setFixedWidth(self._tree.viewport().width())
            self._sticky_header.move(self._tree.pos().x(), self._tree.pos().y())
            self._sticky_header.raise_()
            self._sticky_header.show()
        else:
            self._sticky_header.hide()

    def _on_search_changed(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)
        if text:
            self._tree.expandAll()
        visible = self._proxy.visible_type_count()
        total = self._model.total_types
        base = self._header.text().split("·")[0].strip()
        if text:
            self._header.setText(f"{base} · {visible} / {total}")
        else:
            self._header.setText(f"{base} · {total}")

    def _on_sort_changed(self, text: str) -> None:
        mode = SortMode.ALPHA if text == "A→Z" else SortMode.ABUNDANCE
        self._proxy.set_sort_mode(mode)
        self._proxy.sort(0)

    def _toggle_all(self, visible: bool) -> None:
        self._model.set_all_visible(visible)
        self.all_toggled.emit(visible)

    def _show_categorical_mode(self) -> None:
        self._all_btn.show()
        self._none_btn.show()
        self._search_edit.show()
        self._sort_combo.show()
        self._tree.show()
        self._instruction.show()
        self._gradient_container.hide()

    def _show_gradient_mode(self) -> None:
        self._all_btn.hide()
        self._none_btn.hide()
        self._search_edit.hide()
        self._sort_combo.hide()
        self._tree.hide()
        self._instruction.hide()
        self._clear_focus_chip.hide()
        self._gradient_container.show()


from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from hector_desktop import core as style
from hector_desktop.core import AppState

if TYPE_CHECKING:
    import anndata


class TabPanel(QWidget):
    """Right-side panel containing the tab bar, toolbar, and content."""

    save_h5ad_requested = Signal()

    _EMBEDDING_TAB_INDEX = 1

    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self._obs_columns: list[str] = []
        self._active_method: str = "umap"  # current embedding method

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toolbar = QWidget()
        self.toolbar.setFixedHeight(40)
        self.toolbar.setStyleSheet(
            f"background: {style.PANEL}; border-bottom: 1px solid {style.BORDER};"
        )
        tb_layout = QHBoxLayout(self.toolbar)
        tb_layout.setContentsMargins(12, 0, 12, 0)
        tb_layout.setSpacing(12)

        # Tabs in toolbar row
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        tb_layout.addWidget(self.tabs, 0)

        tb_layout.addStretch()

        # Color-by
        self._color_by_label = QLabel("Color by")
        tb_layout.addWidget(self._color_by_label)
        self.color_by_combo = QComboBox()
        self.color_by_combo.setFixedWidth(180)
        self.color_by_combo.addItem("Cell type")
        self.color_by_combo.setEnabled(False)
        self.color_by_combo.currentTextChanged.connect(self._on_color_by_changed)
        tb_layout.addWidget(self.color_by_combo)

        # Point size
        self._point_size_label = QLabel("Point size")
        tb_layout.addWidget(self._point_size_label)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(1, 80)
        self.size_slider.setValue(25)
        self.size_slider.setFixedWidth(80)
        self.size_slider.valueChanged.connect(self._on_point_size_changed)
        tb_layout.addWidget(self.size_slider)

        self.size_label = QLabel("2.5")
        self.size_label.setFixedWidth(28)
        self.size_label.setStyleSheet(f"font-size: 11px; color: {style.INK_3};")
        tb_layout.addWidget(self.size_label)

        layout.addWidget(self.toolbar)

        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._content_splitter.setHandleWidth(3)

        # Predictions tab (index 0)
        self.predictions_summary = PredictionsSummary()
        self.tabs.addTab(self.predictions_summary, "Predictions")

        # Embedding tab (index 1)
        self.umap_canvas = UmapCanvas()
        self.tabs.addTab(self.umap_canvas, "Embedding plot")

        # QC tab (index 2)
        self.qc_panel = QCPanel()
        self.tabs.addTab(self.qc_panel, "QC metrics")

        self._content_splitter.addWidget(self.tabs)

        # Legend (right side) — hidden until UMAP is generated
        self.legend = LegendPanel()
        self.legend.type_toggled.connect(self._on_legend_toggled)
        self.legend.all_toggled.connect(self._on_legend_all_toggled)
        self.legend.type_highlight_requested.connect(self._on_legend_highlight)
        self.legend.group_highlight_requested.connect(self._on_legend_group_highlight)
        self.umap_canvas.point_clicked.connect(self._on_umap_point_clicked)
        self._content_splitter.addWidget(self.legend)
        self.legend.hide()

        self._content_splitter.setStretchFactor(0, 1)
        self._content_splitter.setStretchFactor(1, 0)

        layout.addWidget(self._content_splitter, 1)

        export_bar = QWidget()
        export_bar.setStyleSheet(
            f"background: {style.PANEL}; border-top: 1px solid {style.BORDER};"
        )
        export_row = QHBoxLayout(export_bar)
        export_row.setContentsMargins(16, 8, 16, 8)
        export_row.setSpacing(12)
        export_row.addStretch()

        self._save_h5ad_btn = QPushButton("Save .h5ad")
        self._save_h5ad_btn.setEnabled(False)
        self._save_h5ad_btn.clicked.connect(self.save_h5ad_requested.emit)
        export_row.addWidget(self._save_h5ad_btn)

        self._export_csv_btn = QPushButton("Export predictions as CSV")
        self._export_csv_btn.setEnabled(False)
        self._export_csv_btn.clicked.connect(self._on_export_csv)
        export_row.addWidget(self._export_csv_btn)

        self._export_embedding_btn = QPushButton("Export Embedding")
        self._export_embedding_btn.setEnabled(False)
        self._export_embedding_btn.clicked.connect(self._on_export_embedding)
        export_row.addWidget(self._export_embedding_btn)

        export_row.addStretch()
        layout.addWidget(export_bar)

        # Initial toolbar visibility
        self._update_toolbar_visibility()


    def on_data_loaded(self) -> None:
        self.predictions_summary.clear()
        self.umap_canvas.clear()
        self.qc_panel.clear()
        self.legend.clear()
        self.legend.hide()

        self.color_by_combo.blockSignals(True)
        self.color_by_combo.clear()
        self.color_by_combo.addItem("Cell type")
        self.color_by_combo.setEnabled(False)
        self.color_by_combo.blockSignals(False)
        self._obs_columns = ["Cell type"]

        self._export_csv_btn.setEnabled(False)
        self._export_embedding_btn.setEnabled(False)
        self._save_h5ad_btn.setEnabled(True)

        self.tabs.setCurrentIndex(0)

    def on_predictions_ready(
        self,
        results_df: pd.DataFrame,
        adata: anndata.AnnData,
        groups: list | None = None,
        display_names: dict | None = None,
        ontology_color_map: dict | None = None,
    ) -> None:
        self.predictions_summary.set_data(results_df, adata)

        labels = adata.obs["hector_prediction"].values
        self._current_scores = adata.obs["hector_prediction_confidence"].values if "hector_prediction_confidence" in adata.obs.columns else None

        self._current_color_map = self.legend.populate(
            labels,
            self._current_scores,
            color_map=ontology_color_map,
            groups=groups,
            display_names=display_names,
        )
        self._current_labels = labels

        # Populate color-by with all obs columns
        self.color_by_combo.blockSignals(True)
        self.color_by_combo.clear()
        self.color_by_combo.addItem("Cell type")
        self._obs_columns = ["Cell type"]
        for col in adata.obs.columns:
            if col == "hector_prediction":
                continue
            self.color_by_combo.addItem(col)
            self._obs_columns.append(col)
        self.color_by_combo.setEnabled(True)
        self.color_by_combo.blockSignals(False)

        self.qc_panel.update_metrics(adata)
        self._save_h5ad_btn.setEnabled(True)
        self._export_csv_btn.setEnabled(True)
        self.tabs.setCurrentIndex(0)

        self._ontology_groups = groups
        self._ontology_display_names = display_names
        self._ontology_color_map = ontology_color_map

    def on_umap_ready(self, adata: anndata.AnnData) -> None:
        self.on_embedding_ready(adata, "umap")

    def on_embedding_ready(self, adata: anndata.AnnData, method: str = "umap") -> None:
        self._active_method = method
        obsm_key = "X_umap" if method == "umap" else "X_tsne"
        display = "UMAP" if method == "umap" else "t-SNE"

        coords = np.asarray(adata.obsm[obsm_key])
        labels = adata.obs["hector_prediction"].values

        # Update axis labels on the canvas
        self.umap_canvas.set_axis_labels(f"{display} 1", f"{display} 2")

        self.umap_canvas.plot(
            coords, labels, self._current_color_map,
            point_size=self.size_slider.value() / 10.0,
        )
        if "hector_prediction_confidence" in adata.obs.columns:
            self.umap_canvas.set_scores(adata.obs["hector_prediction_confidence"].values)

        self.legend.show()
        self._content_splitter.setSizes([720, 300])
        self._export_embedding_btn.setEnabled(True)
        self.tabs.setCurrentIndex(self._EMBEDDING_TAB_INDEX)


    def _on_tab_changed(self, index: int) -> None:
        self._update_toolbar_visibility()

    def _update_toolbar_visibility(self) -> None:
        on_embedding = self.tabs.currentIndex() == self._EMBEDDING_TAB_INDEX
        for w in (
            self._color_by_label, self.color_by_combo,
            self._point_size_label, self.size_slider, self.size_label,
        ):
            w.setVisible(on_embedding)
        if hasattr(self, "legend"):
            self.legend.setVisible(on_embedding and self.state.has_embedding)

    def _on_color_by_changed(self, text: str) -> None:
        if not self.state.has_embedding or not self.state.has_predictions:
            return
        adata = self.state.adata
        if text == "Cell type":
            labels = adata.obs["hector_prediction"].values
            cmap = getattr(self, '_ontology_color_map', None)
            groups = getattr(self, '_ontology_groups', None)
            display_names = getattr(self, '_ontology_display_names', None)
            self._current_color_map = self.legend.populate(
                labels,
                self._current_scores,
                color_map=cmap,
                groups=groups,
                display_names=display_names,
            )
            self.umap_canvas.recolor(labels, self._current_color_map, is_categorical=True)
            self.legend.setEnabled(True)
        elif text in adata.obs.columns:
            col_data = adata.obs[text]
            if pd.api.types.is_numeric_dtype(col_data):
                values = col_data.values.astype(float)
                self.umap_canvas.recolor(values, is_categorical=False)
                vmin, vmax = float(np.nanmin(values)), float(np.nanmax(values))
                self.legend.show_gradient(vmin, vmax, text)
                self.legend.setEnabled(True)
            else:
                cat_values = col_data.astype(str).values
                unique_vals = list(dict.fromkeys(cat_values))
                palette = style.CELL_TYPE_PALETTE
                cat_color_map = {v: palette[i % len(palette)] for i, v in enumerate(unique_vals)}
                self.umap_canvas.recolor(cat_values, cat_color_map, is_categorical=True)
                self.legend.populate(cat_values, color_map=cat_color_map, header=text.upper())
                self.legend.setEnabled(True)

    def _on_point_size_changed(self, value: int) -> None:
        size = value / 10.0
        self.size_label.setText(f"{size:.1f}")
        self.umap_canvas.set_point_size(size)

    def _on_export_csv(self) -> None:
        if self.state.results_df is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export predictions CSV", "", "CSV files (*.csv)"
        )
        if path:
            try:
                self.state.results_df.to_csv(path, index=True)
            except Exception as exc:
                QMessageBox.critical(self, "Export Error", str(exc))

    def _on_export_embedding(self) -> None:
        display = "UMAP" if self._active_method == "umap" else "t-SNE"
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {display} plot", "",
            "PNG images (*.png);;PDF vector (*.pdf);;SVG vector (*.svg);;All files (*)",
        )
        if path:
            self.umap_canvas.save_figure(
                path,
                groups=getattr(self, "_ontology_groups", None),
                method=self._active_method,
            )

    def _on_legend_toggled(self, type_name: str, visible: bool) -> None:
        self.umap_canvas.set_type_visible(type_name, visible)

    def _on_legend_all_toggled(self, visible: bool) -> None:
        self.umap_canvas.set_all_visible(visible)

    def _on_umap_point_clicked(self, type_name: str, index: int) -> None:
        if type_name:
            self.legend.scroll_to_type(type_name)
            self.legend.highlight_type(type_name)
        else:
            self.legend.highlight_type(None)

    def _on_legend_highlight(self, type_name: str) -> None:
        if type_name:
            self.umap_canvas.highlight_type(type_name)
        else:
            self.umap_canvas.clear_highlight()

    def _on_legend_group_highlight(self, type_names: list) -> None:
        if type_names:
            self.umap_canvas.highlight_types(type_names)
        else:
            self.umap_canvas.clear_highlight()
