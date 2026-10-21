"""Local Flask demonstration UI; compiler logic lives in the text2web package."""

from pathlib import Path
import re
from uuid import uuid4

from flask import Flask, abort, make_response, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from text2web import compile_source, compile_update
from text2web.codegen import write_output
from text2web.assets import IMAGE_EXTENSIONS, is_supported_image, local_asset_path
from text2web.nlp import interpreter_from_env
from text2web.workspace import StaleRevision, WorkspaceStore

ROOT = Path(__file__).resolve().parent
MAX_SOURCE_BYTES = 128 * 1024


def _read_image_uploads():
    uploads = {}
    for upload in request.files.getlist("assets"):
        filename = secure_filename(upload.filename or "")
        if not filename:
            continue
        extension = Path(filename).suffix.lower()
        data = upload.read()
        if extension not in IMAGE_EXTENSIONS or not is_supported_image(data, extension):
            return None, f"{filename} is not a supported PNG, JPEG, GIF, or WebP image."
        if filename in uploads:
            return None, f"More than one uploaded file has the name {filename}."
        uploads[filename] = data
    return uploads, None


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=10 * 1024 * 1024, OUTPUT_ROOT=ROOT / "build" / "web")
    if test_config:
        app.config.update(test_config)
    interpreter = app.config.get('NLP_CONVERTER') or interpreter_from_env()
    store = WorkspaceStore(app.config.get('STATE_DB', Path(app.config['OUTPUT_ROOT']).parent / 'workspaces.sqlite3'))
    app.extensions['workspace_store'] = store

    @app.route("/", methods=["GET", "POST"])
    def index():
        sample_source = (ROOT / "examples" / "natural-review.sp").read_text(encoding="utf-8")
        source = sample_source
        result = None
        build_id = None
        file_error = None
        cookie_key = request.cookies.get('text2web_workspace', '')
        workspace_key = cookie_key if re.fullmatch(r'[0-9a-f]{32}', cookie_key) else uuid4().hex
        saved = store.load(workspace_key)
        revision = saved['revision'] if saved else 0
        followup_source = ''
        if request.method == 'GET' and saved:
            source, result, build_id = saved['source'], saved['result'], saved['build_id']
        if request.method == "POST":
            source = request.form.get("source", "")
            updating = request.form.get('mode', 'new') == 'update'
            followup_source = source if updating else ''
            if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
                result = None
                file_error = "Source instructions cannot exceed 128 KB."
            elif updating and not saved:
                file_error = 'Create a page before applying a follow-up instruction.'
            elif updating and request.form.get('revision') != str(revision):
                file_error = 'This page changed in another tab. Reload before applying your instruction.'
            elif saved and len((saved['source'] + source).encode('utf-8')) > MAX_SOURCE_BYTES and updating:
                file_error = 'Page history cannot exceed 128 KB. Start a new page.'
            else:
                result = compile_update(saved['result'], source, nlp_converter=interpreter) if updating else compile_source(source, nlp_converter=interpreter)
            if result and result.success:
                uploads, file_error = _read_image_uploads()
                if uploads is not None:
                    assets = {}
                    missing = []
                    for element in result.symbols:
                        if element.type != "image":
                            continue
                        asset_path = local_asset_path(element.properties["src"])
                        if asset_path is None:
                            continue
                        filename = secure_filename(asset_path.name)
                        previous_asset = None
                        if updating and saved:
                            previous_asset = Path(app.config['OUTPUT_ROOT']) / saved['build_id'] / Path(*asset_path.parts)
                        if filename in uploads:
                            assets[asset_path.as_posix()] = uploads[filename]
                        elif previous_asset and previous_asset.is_file():
                            assets[asset_path.as_posix()] = previous_asset.read_bytes()
                        else:
                            missing.append(asset_path.name)
                    if missing:
                        file_error = "Upload the image file(s) referenced by your instructions: " + ", ".join(sorted(set(missing)))
                    else:
                        candidate = uuid4().hex
                        try:
                            write_output(
                                result, Path(app.config["OUTPUT_ROOT"]) / candidate,
                                assets=assets,
                            )
                            history = saved['source'] + '\n' + source if updating else source
                            revision = store.save(workspace_key, expected=revision, result=result, source=history, build_id=candidate)
                            saved = {'source': history, 'result': result, 'build_id': candidate, 'revision': revision}
                            build_id = candidate
                            if updating:
                                source, followup_source = history, ''
                        except StaleRevision as error:
                            file_error = str(error)
                        except OSError:
                            file_error = "Compilation succeeded, but output files could not be saved. Check folder permissions."
            if updating and not build_id and saved:
                source = saved['source']
        response = make_response(render_template(
            "index.html", source=source, sample_source=sample_source,
            result=result, build_id=build_id, file_error=file_error,
            has_workspace=bool(saved), revision=revision, followup_source=followup_source, nlp_label=interpreter.label,
            is_followup=request.method == 'POST' and request.form.get('mode') == 'update',
            debug=result.debug_data() if result else None,
        ))
        if saved:
            response.set_cookie('text2web_workspace', workspace_key, httponly=True, samesite='Lax', max_age=30 * 24 * 3600)
        return response

    @app.get("/build/<build_id>/<path:filename>")
    def output(build_id, filename):
        allowed = filename in {"index.html", "style.css"}
        image_file = Path(filename).suffix.lower() in IMAGE_EXTENSIONS
        if not re.fullmatch(r"[0-9a-f]{32}", build_id) or not (allowed or image_file):
            abort(404)
        response = send_from_directory(
            Path(app.config["OUTPUT_ROOT"]) / build_id, filename,
            as_attachment=request.args.get("download") == "1",
        )
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'self'; img-src 'self' http: https:; frame-ancestors 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
