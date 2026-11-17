#!/usr/bin/env python3
"""
Консольный скрипт для замера скорости интернет-соединения
путем последовательного скачивания ресурса (например, тяжелого изображения или файла).
"""

import argparse
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

# Ресурс по умолчанию (высокоскоростной CDN Cloudflare для замера скорости, ~5 МБ)
DEFAULT_URL = "https://speed.cloudflare.com/__down?bytes=5000000"
DEFAULT_REQUESTS_COUNT = 10
DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_CHUNK_SIZE = 64 * 1024  # 64 КБ


@dataclass
class RequestResult:
    index: int
    bytes_downloaded: int
    duration_seconds: float
    status_code: int
    error: Optional[str] = None

    @property
    def speed_bytes_per_sec(self) -> float:
        if self.duration_seconds > 0:
            return self.bytes_downloaded / self.duration_seconds
        return 0.0

    @property
    def speed_mbps(self) -> float:
        """Скорость в Мегабитах в секунду (Mbps): 1 байт = 8 бит, 1 Мбит = 1 000 000 бит."""
        return (self.speed_bytes_per_sec * 8) / 1_000_000

    @property
    def speed_mbytes_per_sec(self) -> float:
        """Скорость в Мегабайтах в секунду (MB/s): 1 МБ = 1 000 000 байт (десятичные)."""
        return self.speed_bytes_per_sec / 1_000_000


def format_bytes(num_bytes: int) -> str:
    """Форматирует количество байт в человекочитаемый вид."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.2f} KB"
    else:
        return f"{num_bytes / (1024 * 1024):.2f} MB"


def build_request(url: str, no_cache: bool = False) -> urllib.request.Request:
    """Формирует HTTP-запрос с User-Agent и опциональными антикэш-заголовками."""
    target_url = url
    if no_cache:
        delimiter = "&" if "?" in target_url else "?"
        target_url = f"{target_url}{delimiter}_nocache={time.time_ns()}"

    headers = {
        "User-Agent": "SpeedTester/1.0 (Python speed test script)",
        "Accept": "*/*",
    }
    if no_cache:
        headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        headers["Pragma"] = "no-cache"

    return urllib.request.Request(target_url, headers=headers)


def perform_single_request(
    index: int,
    url: str,
    timeout: float,
    chunk_size: int,
    no_cache: bool = False,
) -> RequestResult:
    """Выполняет один сетевой запрос и дожидается полного скачивания данных."""
    req = build_request(url, no_cache=no_cache)
    start_time = time.perf_counter()
    bytes_count = 0
    status_code = 0

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.status
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                bytes_count += len(chunk)

        duration = time.perf_counter() - start_time
        return RequestResult(
            index=index,
            bytes_downloaded=bytes_count,
            duration_seconds=duration,
            status_code=status_code,
        )
    except urllib.error.HTTPError as e:
        duration = time.perf_counter() - start_time
        return RequestResult(
            index=index,
            bytes_downloaded=bytes_count,
            duration_seconds=duration,
            status_code=e.code,
            error=f"HTTP {e.code}: {e.reason}",
        )
    except urllib.error.URLError as e:
        duration = time.perf_counter() - start_time
        return RequestResult(
            index=index,
            bytes_downloaded=bytes_count,
            duration_seconds=duration,
            status_code=status_code,
            error=f"Сетевая ошибка: {e.reason}",
        )
    except TimeoutError:
        duration = time.perf_counter() - start_time
        return RequestResult(
            index=index,
            bytes_downloaded=bytes_count,
            duration_seconds=duration,
            status_code=status_code,
            error=f"Таймаут ожидания ({timeout}s)",
        )
    except Exception as e:
        duration = time.perf_counter() - start_time
        return RequestResult(
            index=index,
            bytes_downloaded=bytes_count,
            duration_seconds=duration,
            status_code=status_code,
            error=str(e),
        )


def print_banner(url: str, count: int, timeout: float, no_cache: bool):
    print("=" * 72)
    print("   ЗАМЕР СКОРОСТИ ИНТЕРНЕТА (SPEED TEST)")
    print("=" * 72)
    print(f" Целевой URL         : {url}")
    print(f" Количество запросов : {count} (последовательно)")
    print(f" Таймаут на запрос   : {timeout:.1f} сек.")
    print(f" Обход кэша          : {'Включен' if no_cache else 'Выключен'}")
    print("-" * 72)
    print(f"{'№':<4} | {'Статус':<8} | {'Размер':<12} | {'Время':<10} | {'Скорость':<24}")
    print("-" * 72)


def print_result_row(res: RequestResult):
    if res.error:
        print(f"[{res.index:02d}] | ОШИБКА   | {format_bytes(res.bytes_downloaded):<12} | {res.duration_seconds:6.3f} с    | {res.error}")
    else:
        speed_str = f"{res.speed_mbytes_per_sec:6.2f} MB/s  ({res.speed_mbps:6.2f} Mbps)"
        print(f"[{res.index:02d}] | {res.status_code:<8} | {format_bytes(res.bytes_downloaded):<12} | {res.duration_seconds:6.3f} с    | {speed_str}")


def print_summary(results: List[RequestResult], total_wall_time: float):
    print("=" * 72)
    print("                      ИТОГОВЫЕ РЕЗУЛЬТАТЫ")
    print("=" * 72)

    successful = [r for r in results if r.error is None and r.bytes_downloaded > 0]
    total_requests = len(results)
    success_count = len(successful)

    if success_count == 0:
        print("Все запросы завершились с ошибкой. Проверьте адрес и сетевое соединение.")
        print("=" * 72)
        return

    total_bytes = sum(r.bytes_downloaded for r in successful)
    total_download_time = sum(r.duration_seconds for r in successful)
    avg_request_time = total_download_time / success_count
    min_time = min(r.duration_seconds for r in successful)
    max_time = max(r.duration_seconds for r in successful)

    # Расчет общей средней скорости
    # 1) В Мегабайтах в секунду (MB/s, 10^6 байт/с)
    # 2) В Мебибайтах в секунду (MiB/s, 2^20 байт/с)
    # 3) В Мегабитах в секунду (Mbps, 10^6 бит/с, 1 байт = 8 бит)
    avg_speed_bytes_sec = total_bytes / total_download_time if total_download_time > 0 else 0
    avg_speed_mbytes_sec = avg_speed_bytes_sec / 1_000_000
    avg_speed_mebi_sec = avg_speed_bytes_sec / (1024 * 1024)
    avg_speed_mbps = (avg_speed_bytes_sec * 8) / 1_000_000

    print(f" Успешных запросов           : {success_count} из {total_requests}")
    print(f" Общий объём скачанных данных: {format_bytes(total_bytes)} ({total_bytes:,} байт)")
    print(f" Общее время скачивания      : {total_download_time:.3f} с (астрономическое: {total_wall_time:.3f} с)")
    print(f" Среднее время запроса       : {avg_request_time:.3f} с ({avg_request_time * 1000:.1f} мс)")
    print(f" Мин. / Макс. время запроса  : {min_time:.3f} с / {max_time:.3f} с")
    print("-" * 72)
    print(" СКОРОСТЬ СКАЧИВАНИЯ:")
    print(f"   ► {avg_speed_mbps:8.2f} Mbps (Мегабит в секунду — стандарт телекома/провайдеров)")
    print(f"   ► {avg_speed_mbytes_sec:8.2f} MB/s (Мегабайт в секунду, 10^6 байт/с)")
    print(f"   ► {avg_speed_mebi_sec:8.2f} MiB/s (Мебибайт в секунду, 2^20 байт/с)")
    print("=" * 72)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Консольный скрипт для замера скорости интернета (10 последовательных запросов к ресурсу).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_URL,
        help=f"URL ресурса для скачивания (тяжёлая картинка/файл).\nПо умолчанию: тестовый файл Cloudflare 5 МБ ({DEFAULT_URL})",
    )
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=DEFAULT_REQUESTS_COUNT,
        help=f"Количество последовательных запросов (по умолчанию: {DEFAULT_REQUESTS_COUNT})",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"Таймаут одного запроса в секундах (по умолчанию: {DEFAULT_TIMEOUT_SEC})",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Размер буфера чтения в байтах (по умолчанию: {DEFAULT_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Добавлять антикэш-параметр и HTTP-заголовки, предотвращающие кэширование",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Валидация URL
    parsed = urllib.parse.urlparse(args.url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        print(f"Ошибка: Некорректный URL '{args.url}'. URL должен начинаться с http:// или https://", file=sys.stderr)
        sys.exit(1)

    if args.count <= 0:
        print("Ошибка: Количество запросов должно быть больше 0.", file=sys.stderr)
        sys.exit(1)

    print_banner(args.url, args.count, args.timeout, args.no_cache)

    results: List[RequestResult] = []
    wall_start = time.perf_counter()

    for i in range(1, args.count + 1):
        res = perform_single_request(
            index=i,
            url=args.url,
            timeout=args.timeout,
            chunk_size=args.chunk_size,
            no_cache=args.no_cache,
        )
        results.append(res)
        print_result_row(res)

    wall_total = time.perf_counter() - wall_start
    print_summary(results, wall_total)


if __name__ == "__main__":
    main()
