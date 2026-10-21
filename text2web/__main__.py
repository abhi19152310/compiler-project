"""Run with: python -m text2web examples/fest.sp --output build/fest --debug"""

import argparse
import json
from pathlib import Path
import sys

from .codegen import write_output
from .compiler import compile_source


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile controlled English into a static webpage.")
    parser.add_argument("source", type=Path, help="UTF-8 .sp sentence file")
    parser.add_argument("--output", type=Path, default=Path("build/output"))
    parser.add_argument("--debug", action="store_true", help="Show tokens, AST, and symbols")
    parser.add_argument("--force", action="store_true", help="Replace index.html and style.css in output")
    parser.add_argument("--natural", action="store_true", help="Use English interpretation and the configured local model fallback")
    args = parser.parse_args()
    try:
        from .nlp import interpreter_from_env
        result = compile_source(args.source.read_text(encoding="utf-8-sig"), nlp_converter=interpreter_from_env() if args.natural else None)
        if args.debug:
            print(json.dumps(result.debug_data(), indent=2, ensure_ascii=True))
        if not result.success:
            for error in sorted(result.diagnostics, key=lambda d: d.line):
                print(f"Line {error.line} [{error.phase}]: {error.message}", file=sys.stderr)
            count = len(result.diagnostics)
            print(f"{count} {'error' if count == 1 else 'errors'} - no files written", file=sys.stderr)
            return 1
        write_output(result, args.output, overwrite=args.force, asset_root=args.source.parent)
    except (OSError, UnicodeError) as error:
        print(f"File error: {error}", file=sys.stderr)
        return 2
    print("All sentences understood - 0 errors")
    print(f"Wrote index.html and style.css ({args.output / 'index.html'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
