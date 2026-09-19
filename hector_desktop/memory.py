"""Release dataset memory before loading another dataset."""

from __future__ import annotations

import gc

_TAB_PANEL_DATASET_ATTRS = (
    "_current_labels",
    "_current_scores",
    "_current_color_map",
    "_ontology_groups",
    "_ontology_display_names",
    "_ontology_color_map",
)


def release_dataset_memory(state, tab_panel=None) -> None:
    """Release data-specific references and the MLX cache."""
    state.adata = None
    state.adata_original = None
    state.results_df = None

    if tab_panel is not None:
        for attr in _TAB_PANEL_DATASET_ATTRS:
            if hasattr(tab_panel, attr):
                setattr(tab_panel, attr, None)

    gc.collect()

    try:
        import mlx.core as mx

        mx.clear_cache()
    except Exception:
        pass
