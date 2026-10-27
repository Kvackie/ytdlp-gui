"""Write build/version_info.txt: the version details shown in the Windows exe's file properties."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ytdlp_gui import APP_NAME, __version__  # noqa: E402

numbers = [int(n) for n in re.findall(r"\d+", __version__)[:3]]
numbers += [0] * (4 - len(numbers))
tuple_text = ", ".join(str(n) for n in numbers)

text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tuple_text}), prodvers=({tuple_text})),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'ytdlp-gui'),
      StringStruct('OriginalFilename', 'ytdlp-gui.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
out = ROOT / "build" / "version_info.txt"
out.parent.mkdir(exist_ok=True)
out.write_text(text, encoding="utf-8")
print("written", out)
