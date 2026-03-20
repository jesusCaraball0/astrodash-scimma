"""
Compatibility shim for unpickling dash_twins_umap.pkl.

The UMAP pickle was serialized with a UMAPWrapper class from
astrodash.explorer.umap_wrapper. This module provides that class
so pickle.load() can deserialize the file. The wrapper delegates
transform() to the inner umap.UMAP reducer.
"""


class UMAPWrapper:
    """Thin wrapper around umap.UMAP used during pickle serialization."""

    def transform(self, X):
        return self.reducer.transform(X)
