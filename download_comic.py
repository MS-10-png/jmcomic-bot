from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from plugins import jm_api as jm_api_module
from plugins.jm_api import MissingDependencyError, jm_api


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "downloads"
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(value: object, fallback: str = "untitled") -> str:
    name = INVALID_FILENAME_CHARS.sub("_", str(value)).strip().strip(".")
    return name[:100] or fallback


def print_info(message: str) -> None:
    print(f"[信息] {message}")


def print_ok(message: str) -> None:
    print(f"[完成] {message}")


def print_error(message: str) -> None:
    print(f"[错误] {message}")


def check_dependencies() -> bool:
    ok = True
    try:
        jm_api.ensure_requests()
    except MissingDependencyError as exc:
        print_error("缺少依赖 requests，请先执行：python -m pip install requests pycryptodome")
        ok = False

    if jm_api_module.AES is None:
        print_error("缺少依赖 pycryptodome，无法解密 JM API 响应，请先执行：python -m pip install requests pycryptodome")
        ok = False

    return ok


def normalize_comic_id(comic_id: str) -> str:
    comic_id = comic_id.strip()
    if comic_id.lower().startswith("jm"):
        comic_id = comic_id[2:]
    return comic_id


def image_suffix(image_url: str) -> str:
    suffix = Path(urlsplit(image_url).path).suffix
    if suffix and len(suffix) <= 8:
        return suffix
    return ".jpg"


def write_metadata(download_dir: Path, comic_id: str, comic_info: dict) -> None:
    metadata = {
        "id": comic_id,
        "title": comic_info.get("title", ""),
        "description": comic_info.get("description", ""),
        "updateTime": comic_info.get("updateTime", ""),
        "chapters": comic_info.get("chapters", {}),
        "tags": comic_info.get("tags", {}),
    }
    (download_dir / "info.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def download_one_comic(
    comic_id: str,
    output_dir: Path,
    page_limit: int | None,
    overwrite: bool,
    refresh: bool,
) -> Path:
    comic_id = normalize_comic_id(comic_id)
    if not comic_id:
        raise ValueError("漫画编号不能为空")

    if refresh:
        jm_api.refresh_api_domains()
        jm_api.refresh_img_url()

    print_info(f"获取漫画信息：{comic_id}")
    comic_info = jm_api.load_comic_info(comic_id)
    title = comic_info.get("title") or comic_id
    download_dir = output_dir / f"{safe_filename(comic_id)}_{safe_filename(title)}"
    download_dir.mkdir(parents=True, exist_ok=True)
    write_metadata(download_dir, comic_id, comic_info)

    cover_path = download_dir / "cover.jpg"
    if overwrite or not cover_path.exists() or cover_path.stat().st_size == 0:
        print_info("下载封面")
        jm_api.download_image(comic_info["cover"], cover_path)

    total_downloaded = 0
    chapters = comic_info.get("chapters") or {}
    print_info(f"开始下载：{title}，章节数：{len(chapters)}")

    for chapter_index, (chapter_id, chapter_title) in enumerate(chapters.items(), start=1):
        chapter_dir = download_dir / f"{chapter_index:03d}_{safe_filename(chapter_title, f'chapter_{chapter_id}')}"
        chapter_dir.mkdir(parents=True, exist_ok=True)

        print_info(f"读取章节 {chapter_index}/{len(chapters)}：{chapter_title}")
        images = jm_api.load_chapter_images(chapter_id).get("images") or []

        for image_index, image_url in enumerate(images, start=1):
            if page_limit is not None and total_downloaded >= page_limit:
                print_ok(f"达到本次页数限制：{page_limit}")
                return download_dir

            image_path = chapter_dir / f"{image_index:03d}{image_suffix(image_url)}"
            if not overwrite and image_path.exists() and image_path.stat().st_size > 0:
                print_info(f"跳过已存在：{chapter_title} 第 {image_index}/{len(images)} 页")
                jm_api.ensure_image_decoded(image_url, image_path)
            else:
                print_info(f"下载：{chapter_title} 第 {image_index}/{len(images)} 页")
                jm_api.download_image(image_url, image_path)

            total_downloaded += 1

    print_ok(f"下载完成，共处理 {total_downloaded} 张图片")
    return download_dir


def parse_page_limit(value: str | None) -> int | None:
    if value is None:
        return None

    raw = value.strip().lower()
    if raw in {"", "all", "全部", "0"}:
        return None

    page_limit = int(raw)
    if page_limit < 1:
        return None
    return page_limit


def collect_comic_ids(args: argparse.Namespace) -> list[str]:
    comic_ids = [comic_id.strip() for comic_id in args.comic_ids if comic_id.strip()]
    if comic_ids:
        return comic_ids

    print("请输入要下载的漫画编号。多个编号可以用空格分隔，直接回车退出。")
    raw = input("漫画编号: ").strip()
    return [comic_id.strip() for comic_id in raw.split() if comic_id.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="输入 JM 漫画编号，直接下载到电脑本地。")
    parser.add_argument("comic_ids", nargs="*", help="漫画编号，例如 123456 或 jm123456")
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"下载保存目录，默认：{DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--limit",
        help="只下载前 N 张图片；默认下载全部。可填 all / 全部 / 0 表示全部。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="重新下载并覆盖已存在图片。",
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="跳过启动时刷新 JM 域名和图片地址。",
    )
    return parser


def main() -> int:
    os.chdir(ROOT)
    args = build_parser().parse_args()

    print("JM 漫画编号下载器")
    print(f"项目目录：{ROOT}")
    print(f"保存目录：{Path(args.output).resolve()}")
    print()

    if not check_dependencies():
        print()
        print_error("依赖检查未通过，已停止。")
        return 1

    try:
        page_limit = parse_page_limit(args.limit)
    except ValueError:
        print_error("--limit 只能填写数字、all、全部或 0")
        return 1

    comic_ids = collect_comic_ids(args)
    if not comic_ids:
        print_info("没有输入漫画编号，已退出。")
        return 0

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    failed = 0
    for comic_id in comic_ids:
        print()
        try:
            download_dir = download_one_comic(
                comic_id=comic_id,
                output_dir=output_dir,
                page_limit=page_limit,
                overwrite=args.overwrite,
                refresh=not args.no_refresh,
            )
            print_ok(f"保存位置：{download_dir}")
        except Exception as exc:
            failed += 1
            print_error(f"{comic_id} 下载失败：{exc}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
