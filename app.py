import hashlib
import io
import os
import re
import unicodedata
from pathlib import Path

import qrcode
import qrcode.image.svg
from flask import (
    Flask,
    Response,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

CIA_DIR = Path(os.environ.get("CIA_DIR", "/cia"))
PORT = int(os.environ.get("PORT", 8000))

app = Flask(__name__)

# Символы, которые встречаются в релизных именах и которые libctru/FBI
# не всегда умеет правильно обработать в URL при скачивании по HTTP.
CHAR_REPLACEMENTS = {
    "™": "(TM)",
    "®": "(R)",
    "©": "(C)",
    "–": "-",
    "—": "-",
    "‑": "-",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "…": "...",
}


def sanitize_filename(name: str) -> str:
    stem, ext = os.path.splitext(name)

    for bad, good in CHAR_REPLACEMENTS.items():
        stem = stem.replace(bad, good)

    # Разложить оставшийся юникод на составляющие и отбросить всё,
    # что не раскладывается в ASCII (акценты, иероглифы и т.п.)
    stem = unicodedata.normalize("NFKD", stem)
    stem = stem.encode("ascii", "ignore").decode("ascii")

    # Оставить только безопасный для URL/FS набор символов
    stem = re.sub(r"[^A-Za-z0-9._ \-()\[\]]", "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = re.sub(r"_+", "_", stem)

    if not stem:
        stem = "file"

    return f"{stem}{ext.lower()}"


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


app.jinja_env.filters["human_size"] = human_size


def scan_files():
    files = []
    if not CIA_DIR.exists():
        return files

    for path in sorted(CIA_DIR.rglob("*.[cC][iI][aA]")):
        if not path.is_file():
            continue
        rel = path.relative_to(CIA_DIR)
        file_id = hashlib.sha1(str(rel).encode("utf-8")).hexdigest()[:16]
        safe_name = sanitize_filename(path.name)
        files.append(
            {
                "id": file_id,
                "rel_path": str(rel),
                "dir": str(rel.parent) if str(rel.parent) != "." else "",
                "name": path.name,
                "safe_name": safe_name,
                "needs_rename": safe_name != path.name,
                "size": path.stat().st_size,
            }
        )
    return files


def find_file(file_id: str):
    for f in scan_files():
        if f["id"] == file_id:
            return f
    return None


def build_download_url(f: dict) -> str:
    return url_for(
        "download",
        file_id=f["id"],
        filename=f["safe_name"],
        _external=True,
    )


@app.route("/")
def index():
    files = scan_files()
    return render_template("index.html", files=files, cia_dir=str(CIA_DIR))


@app.route("/file/<file_id>")
def file_page(file_id):
    f = find_file(file_id)
    if not f:
        abort(404)
    return render_template("file.html", f=f, download_url=build_download_url(f))


@app.route("/qr/<file_id>.svg")
def qr_svg(file_id):
    f = find_file(file_id)
    if not f:
        abort(404)

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(build_download_url(f))
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)

    buf = io.BytesIO()
    img.save(buf)
    return Response(
        buf.getvalue(),
        mimetype="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@app.route("/download/<file_id>/<path:filename>")
def download(file_id, filename):
    # filename в URL нужен только чтобы FBI видела расширение .cia в ссылке —
    # реальный файл ищется исключительно по file_id.
    f = find_file(file_id)
    if not f:
        abort(404)

    path = CIA_DIR / f["rel_path"]
    return send_file(
        path,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=f["safe_name"],
        conditional=True,
    )


@app.route("/rename/<file_id>", methods=["POST"])
def rename(file_id):
    f = find_file(file_id)
    if not f:
        abort(404)

    src = CIA_DIR / f["rel_path"]
    parent = src.parent
    dst = parent / f["safe_name"]

    if dst != src:
        stem, ext = os.path.splitext(f["safe_name"])
        counter = 1
        while dst.exists():
            dst = parent / f"{stem} ({counter}){ext}"
            counter += 1
        src.rename(dst)

    return redirect(url_for("index"))


if __name__ == "__main__":
    from waitress import serve

    serve(app, host="0.0.0.0", port=PORT)
