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
DEFAULT_CHUNK_SIZE = 64 * 1024  # 64 КиБ


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
        """Скорость в Мегабайтах в секунду (MB/s): 1 МБ = 1 000 000 байт (десятичные СИ)."""
        return self.speed_bytes_per_sec / 1_000_000

    @property
    def speed_mebi_per_sec(self) -> float:
        """Скорость в Мебибайтах в секунду (MiB/s): 1 МиБ = 1 048 576 байт (двоичные IEC)."""
        return self.speed_bytes_per_sec / (1024 * 1024)


def format_bytes(num_bytes: int) -> str:
    """Форматирует количество байт в стандарте IEC (B, KiB, MiB): 1 KiB = 1024 B, 1 MiB = 1024 KiB."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.2f} KiB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MiB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GiB"


def build_request(url: str, no_cache: bool = False) -> urllib.request.Request:
    """Формирует HTTP-запрос с User-Agent, Accept-Encoding: identity и опциональными антикэш-заголовками."""
    target_url = url
    if no_cache:
        delimiter = "&" if "?" in target_url else "?"
        target_url = f"{target_url}{delimiter}_nocache={time.time_ns()}"

    headers = {
        "User-Agent": "SpeedTester/1.0 (Python speed test script)",
        "Accept": "*/*",
        # Запрашиваем несжатые данные, чтобы измерять реальные байты сети
        "Accept-Encoding": "identity",
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
    """Выполняет один сетевой запрос с контролем общего дедлайна и проверкой Content-Length."""
    req = build_request(url, no_cache=no_cache)
    start_time = time.perf_counter()
    bytes_count = 0
    status_code = 0

    try:
        # 1. Открытие соединения с контролем оставшегося лимита времени
        elapsed = time.perf_counter() - start_time
        if elapsed >= timeout:
            raise TimeoutError(f"Превышен общий лимит времени на запрос ({timeout:.2f} с)")

        with urllib.request.urlopen(req, timeout=max(0.001, timeout - elapsed)) as response:
            status_code = response.status

            # Извлекаем ожидаемый размер по Content-Length
            content_length_header = response.headers.get("Content-Length")
            expected_bytes = int(content_length_header) if content_length_header and content_length_header.isdigit() else None

            # 2. Чтение данных по частям с проверкой общего дедлайна на каждой итерации
            while True:
                elapsed = time.perf_counter() - start_time
                remaining = timeout - elapsed
                if remaining <= 0:
                    raise TimeoutError(f"Превышен общий лимит времени на запрос ({timeout:.2f} с)")

                # Устанавливаем оставшийся таймаут на сокет для предотвращения блокировки read()
                try:
                    sock = getattr(getattr(response, "fp", None), "raw", None)
                    if sock and hasattr(sock, "_sock") and sock._sock:
                        sock._sock.settimeout(max(0.001, remaining))
                except Exception:
                    pass

                chunk = response.read(chunk_size)
                if not chunk:
                    break
                bytes_count += len(chunk)

            # 3. Валидация полноты скачанных данных по Content-Length
            if expected_bytes is not None and bytes_count != expected_bytes:
                raise ValueError(
                    f"Неполный ответ: получено {bytes_count} байт из заявленных {expected_bytes} (Content-Length)"
                )

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
    except TimeoutError as te:
        duration = time.perf_counter() - start_time
        return RequestResult(
            index=index,
            bytes_downloaded=bytes_count,
            duration_seconds=duration,
            status_code=status_code,
            error=str(te),
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
    print(f" Общий таймаут       : {timeout:.1f} сек. на запрос")
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


def print_summary(results: List[RequestResult], total_wall_time: float) -> bool:
    print("=" * 72)
    print("                      ИТОГОВЫЕ РЕЗУЛЬТАТЫ")
    print("=" * 72)

    successful = [r for r in results if r.error is None and r.bytes_downloaded > 0]
    total_requests = len(results)
    success_count = len(successful)

    if success_count == 0:
        print("Все запросы завершились с ошибкой. Проверьте адрес и сетевое соединение.")
        print("=" * 72)
        return False

    total_bytes = sum(r.bytes_downloaded for r in successful)
    total_download_time = sum(r.duration_seconds for r in successful)
    avg_request_time = total_download_time / success_count
    min_time = min(r.duration_seconds for r in successful)
    max_time = max(r.duration_seconds for r in successful)

    avg_speed_bytes_sec = total_bytes / total_download_time if total_download_time > 0 else 0
    avg_speed_mbytes_sec = avg_speed_bytes_sec / 1_000_000
    avg_speed_mebi_sec = avg_speed_bytes_sec / (1024 * 1024)
    avg_speed_mbps = (avg_speed_bytes_sec * 8) / 1_000_000
    total_mb_decimal = total_bytes / 1_000_000

    print(f" Успешных запросов           : {success_count} из {total_requests}")
    print(f" Общий объём скачанных данных: {format_bytes(total_bytes)} ({total_mb_decimal:.2f} MB / {total_bytes:,} байт)")
    print(f" Общее время скачивания      : {total_download_time:.3f} с (астрономическое: {total_wall_time:.3f} с)")
    print(f" Среднее время запроса       : {avg_request_time:.3f} с ({avg_request_time * 1000:.1f} мс)")
    print(f" Мин. / Макс. время запроса  : {min_time:.3f} с / {max_time:.3f} с")
    print("-" * 72)
    print(" СКОРОСТЬ СКАЧИВАНИЯ:")
    print(f"   - {avg_speed_mbps:8.2f} Mbps (Мегабит в секунду - стандарт телекома/провайдеров)")
    print(f"   - {avg_speed_mbytes_sec:8.2f} MB/s (Мегабайт в секунду, десятичные 10^6 байт/с)")
    print(f"   - {avg_speed_mebi_sec:8.2f} MiB/s (Мебибайт в секунду, двоичные 2^20 байт/с)")
    print("=" * 72)
    return True


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
        help=f"Количество последовательных запросов > 0 (по умолчанию: {DEFAULT_REQUESTS_COUNT})",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"Общий таймаут выполнения запроса в секундах (по умолчанию: {DEFAULT_TIMEOUT_SEC})",
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

    # Валидация входных аргументов
    if args.count <= 0:
        print(f"Ошибка: Количество запросов (-n/--count) должно быть больше 0 (получено {args.count}).", file=sys.stderr)
        sys.exit(1)

    if args.timeout <= 0:
        print(f"Ошибка: Таймаут (-t/--timeout) должен быть больше 0 (получено {args.timeout}).", file=sys.stderr)
        sys.exit(1)

    parsed = urllib.parse.urlparse(args.url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        print(f"Ошибка: Некорректный URL '{args.url}'. URL должен начинаться с http:// или https://", file=sys.stderr)
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
    has_success = print_summary(results, wall_total)

    # Если все запросы провалились - возвращаем ненулевой код завершения
    if not has_success:
        sys.exit(1)


if __name__ == "__main__":
    main()
