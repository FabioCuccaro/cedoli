"""busta_paga_beautify: analisi locale delle buste paga."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Unica fonte: la versione in pyproject.toml (anche nell'eseguibile, che ne porta i metadati).
    __version__ = version("busta-paga-beautify")
except PackageNotFoundError:
    __version__ = "sviluppo"
