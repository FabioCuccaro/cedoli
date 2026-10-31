# Eseguibile unico per Windows (funziona anche su macOS e Linux, utile per provarlo).
# uv run --group build pyinstaller packaging/BustaChiara.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

a = Analysis(
    ["BustaChiara.py"],
    pathex=["../src"],
    # Template HTML, glossario e regole fiscali; pdfminer porta con sé le tabelle dei caratteri.
    # I metadati del pacchetto portano il numero di versione mostrato nell'app.
    datas=collect_data_files("bp") + collect_data_files("pdfminer") + copy_metadata("busta-paga-beautify"),
    # I parser e i comandi sono importati al bisogno: li includiamo tutti.
    hiddenimports=collect_submodules("bp"),
    excludes=["tkinter", "pytest", "reportlab"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="BustaChiara",
    icon="BustaChiara.ico",  # generata da icona.svg, il logo dell'app
    console=True,  # la finestra resta aperta mentre l'app è in uso; si chiude da sola con "Chiudi l'app"
    upx=False,
)
