from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.agent_framework.tool_modules.registry import create_default_registry
from app.agent_framework.tool_modules.xhs_web import XHS_CREATOR_URL

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def invoke_tool(name: str, args: dict, *, approval_granted: bool) -> dict:
    raw = create_default_registry().invoke(
        name,
        args,
        context={"approval_granted": approval_granted},
    )
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {"status": "INVALID_TOOL_RESULT", "raw": parsed}


def _read_text_arg(value: str | None, file_value: str | None, *, label: str) -> str:
    if value:
        return value
    if file_value:
        return Path(file_value).expanduser().read_text(encoding="utf-8").strip()
    raise ValueError(f"{label} is required unless the matching --skip-* option is set.")


def _split_hashtag_text(text: str) -> list[str]:
    return [item.strip() for item in text.replace(",", "\n").splitlines() if item.strip()]


def _collect_images(args: argparse.Namespace, note: dict[str, Any]) -> list[str]:
    images: list[str] = []
    images.extend(str(item) for item in note.get("image_paths") or [])
    images.extend(args.image or [])
    for group in args.images or []:
        images.extend(group)
    for raw_dir in args.images_dir or []:
        directory = Path(raw_dir).expanduser()
        images.extend(
            str(path)
            for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
    return images


def _collect_hashtags(args: argparse.Namespace, note: dict[str, Any]) -> list[str]:
    hashtags: list[str] = []
    hashtags.extend(str(item) for item in note.get("hashtags") or [])
    hashtags.extend(args.hashtag or [])
    for group in args.hashtags or []:
        hashtags.extend(group)
    if args.hashtags_file:
        hashtags.extend(_split_hashtag_text(Path(args.hashtags_file).read_text(encoding="utf-8")))
    return hashtags


def _load_note(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    parsed = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("--note-json must point to a JSON object.")
    return parsed


def _append_result(
    *,
    results: list[dict[str, Any]],
    steps: list[str],
    name: str,
    args: dict,
    approval_granted: bool,
    dry_run: bool,
) -> dict[str, Any]:
    steps.append(name)
    if dry_run:
        result = {"status": "DRY_RUN", "args": args}
    else:
        result = invoke_tool(name, args, approval_granted=approval_granted)
    results.append({"tool": name, "args": args, "result": result})
    return result


def run_prefill_note(args: argparse.Namespace) -> dict[str, Any]:
    note = _load_note(args.note_json)
    job_id = args.job_id
    title = note.get("title") or None
    body = note.get("body") or None
    if not args.skip_title:
        title = _read_text_arg(args.title or title, args.title_file, label="title")
    if not args.skip_body:
        body = _read_text_arg(args.body or body, args.body_file, label="body")

    image_paths = _collect_images(args, note)
    hashtags = _collect_hashtags(args, note)
    if not args.skip_upload and not image_paths:
        raise ValueError("At least one image is required unless --skip-upload is set.")
    if not args.skip_hashtags and not hashtags:
        raise ValueError("At least one hashtag is required unless --skip-hashtags is set.")

    steps: list[str] = []
    results: list[dict[str, Any]] = []
    final_result: dict[str, Any] = {"status": "OK"}

    def run(name: str, tool_args: dict, *, approval_granted: bool) -> dict[str, Any]:
        result = _append_result(
            results=results,
            steps=steps,
            name=name,
            args=tool_args,
            approval_granted=approval_granted,
            dry_run=args.dry_run,
        )
        status = str(result.get("status") or "")
        if status not in {"OK", "DRY_RUN", "READY_FOR_HUMAN_CONFIRMATION"}:
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
        return result

    if not args.skip_open:
        run(
            "xhs_open_creator",
            {"job_id": job_id, "new_tab": args.new_tab, "url": args.url},
            approval_granted=True,
        )
    if not args.skip_start_note:
        run("xhs_start_note", {"job_id": job_id}, approval_granted=True)
    if not args.skip_upload:
        run(
            "xhs_upload_images",
            {"job_id": job_id, "image_paths": image_paths},
            approval_granted=True,
        )
    if not args.skip_title:
        run("xhs_fill_title", {"job_id": job_id, "title": title}, approval_granted=True)
    if not args.skip_body:
        run("xhs_fill_body", {"job_id": job_id, "body": body}, approval_granted=True)
    if not args.skip_hashtags:
        run("xhs_fill_hashtags", {"job_id": job_id, "hashtags": hashtags}, approval_granted=True)
    if not args.skip_preview:
        run("xhs_take_preview_screenshot", {"job_id": job_id}, approval_granted=False)
    if not args.skip_stop:
        final_result = run("xhs_stop_before_publish", {"job_id": job_id}, approval_granted=False)

    return {
        "status": final_result.get("status", "OK"),
        "job_id": job_id,
        "steps": steps,
        "results": results,
        "screenshot": final_result.get("screenshot"),
        "artifact_dir": final_result.get("artifact_dir")
        or (results[-1]["result"].get("artifact_dir") if results else None),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xhs", description="Xiaohongshu workflow CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prefill = subparsers.add_parser(
        "prefill-note",
        help="Upload images, prefill an image note, and stop before publish.",
    )
    prefill.add_argument("--job-id", default="xhs-cli", help="Artifact job id.")
    prefill.add_argument("--note-json", help="JSON object with title/body/hashtags/image_paths.")
    prefill.add_argument("--title")
    prefill.add_argument("--title-file")
    prefill.add_argument("--body")
    prefill.add_argument("--body-file")
    prefill.add_argument("--image", action="append", help="Repeatable image path.")
    prefill.add_argument("--images", action="append", nargs="+", help="One or more image paths.")
    prefill.add_argument("--images-dir", action="append", help="Directory of png/jpg/jpeg images.")
    prefill.add_argument("--hashtag", action="append", help="Repeatable hashtag.")
    prefill.add_argument("--hashtags", action="append", nargs="+", help="One or more hashtags.")
    prefill.add_argument("--hashtags-file", help="Newline or comma separated hashtags.")
    prefill.add_argument("--url", default=XHS_CREATOR_URL)
    tab_group = prefill.add_mutually_exclusive_group()
    tab_group.add_argument("--new-tab", dest="new_tab", action="store_true", default=True)
    tab_group.add_argument("--reuse-tab", dest="new_tab", action="store_false")
    prefill.add_argument("--skip-open", action="store_true")
    prefill.add_argument("--skip-start-note", action="store_true")
    prefill.add_argument("--skip-upload", action="store_true")
    prefill.add_argument("--skip-title", action="store_true")
    prefill.add_argument("--skip-body", action="store_true")
    prefill.add_argument("--skip-hashtags", action="store_true")
    prefill.add_argument("--skip-preview", action="store_true")
    prefill.add_argument("--skip-stop", action="store_true")
    prefill.add_argument("--dry-run", action="store_true")
    prefill.add_argument("--pretty", action="store_true")
    prefill.add_argument("--output", help="Optional path to write the final JSON payload.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prefill-note":
            payload = run_prefill_note(args)
        else:
            parser.error(f"Unknown command: {args.command}")
    except Exception as exc:  # noqa: BLE001 - CLI should return structured failures.
        payload = {"status": "ERROR", "error": str(exc)}
        text = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2 if getattr(args, "pretty", False) else None,
        )
        print(text)
        return 1

    text = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).expanduser().write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
