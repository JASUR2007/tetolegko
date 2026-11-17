#!/usr/bin/env node
/**
 * Консольный скрипт для замера скорости интернет-соединения на Node.js
 * (10 последовательных запросов к тяжелому файлу/картинке без внешних зависимостей).
 */

import { performance } from 'node:perf_hooks';
import process from 'node:process';

const DEFAULT_URL = 'https://speed.cloudflare.com/__down?bytes=5000000';
const DEFAULT_REQUESTS_COUNT = 10;
const DEFAULT_TIMEOUT_MS = 30000;

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function parseCliArgs() {
  const rawArgs = process.argv.slice(2);
  const options = {
    url: DEFAULT_URL,
    count: DEFAULT_REQUESTS_COUNT,
    timeoutMs: DEFAULT_TIMEOUT_MS,
    noCache: false,
  };

  for (let i = 0; i < rawArgs.length; i++) {
    const arg = rawArgs[i];
    if (arg === '-h' || arg === '--help') {
      printHelp();
      process.exit(0);
    } else if (arg === '-n' || arg === '--count') {
      const val = parseInt(rawArgs[++i], 10);
      if (!Number.isNaN(val) && val > 0) options.count = val;
    } else if (arg === '-t' || arg === '--timeout') {
      const val = parseFloat(rawArgs[++i]);
      if (!Number.isNaN(val) && val > 0) options.timeoutMs = val * 1000;
    } else if (arg === '--no-cache') {
      options.noCache = true;
    } else if (!arg.startsWith('-')) {
      options.url = arg;
    }
  }

  return options;
}

function printHelp() {
  console.log(`
Использование:
  node speedtest.js [URL] [опции]

Опции:
  URL                    Адрес ресурса (по умолчанию: тестовый файл Cloudflare 5 МБ)
  -n, --count <число>    Количество запросов (по умолчанию: 10)
  -t, --timeout <сек>    Таймаут одного запроса в секундах (по умолчанию: 30)
  --no-cache             Добавлять антикэш-заголовки и параметры
  -h, --help             Показать справку
`);
}

async function performSingleRequest(index, url, timeoutMs, noCache) {
  let targetUrl = url;
  if (noCache) {
    const delim = targetUrl.includes('?') ? '&' : '?';
    targetUrl = `${targetUrl}${delim}_nocache=${Date.now()}`;
  }

  const headers = {
    'User-Agent': 'SpeedTester/1.0 (Node.js speed test script)',
    'Accept': '*/*',
  };
  if (noCache) {
    headers['Cache-Control'] = 'no-cache, no-store, must-revalidate';
    headers['Pragma'] = 'no-cache';
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const startTime = performance.now();
  let downloadedBytes = 0;
  let statusCode = 0;

  try {
    const response = await fetch(targetUrl, {
      signal: controller.signal,
      headers,
    });
    statusCode = response.status;

    if (!response.ok) {
      const durationSeconds = (performance.now() - startTime) / 1000;
      clearTimeout(timeoutId);
      return {
        index,
        statusCode,
        bytes: 0,
        durationSeconds,
        speedMbps: 0,
        speedMBps: 0,
        error: `HTTP ${statusCode}: ${response.statusText || 'Error'}`,
      };
    }

    if (!response.body) {
      const buffer = await response.arrayBuffer();
      downloadedBytes = buffer.byteLength;
    } else {
      const reader = response.body.getReader();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) {
          downloadedBytes += value.byteLength;
        }
      }
    }

    const durationSeconds = (performance.now() - startTime) / 1000;
    clearTimeout(timeoutId);

    const speedBytesSec = durationSeconds > 0 ? downloadedBytes / durationSeconds : 0;
    const speedMbps = (speedBytesSec * 8) / 1_000_000;
    const speedMBps = speedBytesSec / 1_000_000;

    return {
      index,
      statusCode,
      bytes: downloadedBytes,
      durationSeconds,
      speedMbps,
      speedMBps,
      error: null,
    };
  } catch (err) {
    clearTimeout(timeoutId);
    const durationSeconds = (performance.now() - startTime) / 1000;
    let errMsg = err.name === 'AbortError' ? `Таймаут (${timeoutMs / 1000}s)` : err.message;
    return {
      index,
      statusCode,
      bytes: downloadedBytes,
      durationSeconds,
      speedMbps: 0,
      speedMBps: 0,
      error: errMsg,
    };
  }
}

async function main() {
  const options = parseCliArgs();

  try {
    const parsed = new URL(options.url);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      throw new Error('Протокол должен быть http: или https:');
    }
  } catch (err) {
    console.error(`Ошибка: Некорректный URL '${options.url}' (${err.message})`);
    process.exit(1);
  }

  console.log('='.repeat(72));
  console.log('   ЗАМЕР СКОРОСТИ ИНТЕРНЕТА (SPEED TEST - NODE.JS)');
  console.log('='.repeat(72));
  console.log(` Целевой URL         : ${options.url}`);
  console.log(` Количество запросов : ${options.count} (последовательно)`);
  console.log(` Таймаут на запрос   : ${(options.timeoutMs / 1000).toFixed(1)} сек.`);
  console.log(` Обход кэша          : ${options.noCache ? 'Включен' : 'Выключен'}`);
  console.log('-'.repeat(72));
  console.log(
    `${'№'.padEnd(4)} | ${'Статус'.padEnd(8)} | ${'Размер'.padEnd(12)} | ${'Время'.padEnd(10)} | ${'Скорость'.padEnd(24)}`
  );
  console.log('-'.repeat(72));

  const results = [];
  const wallStart = performance.now();

  for (let i = 1; i <= options.count; i++) {
    const res = await performSingleRequest(i, options.url, options.timeoutMs, options.noCache);
    results.push(res);

    const idxStr = `[${String(i).padStart(2, '0')}]`;
    if (res.error) {
      console.log(
        `${idxStr} | ${'ОШИБКА'.padEnd(8)} | ${formatBytes(res.bytes).padEnd(12)} | ${res.durationSeconds.toFixed(3).padStart(6)} с    | ${res.error}`
      );
    } else {
      const speedStr = `${res.speedMBps.toFixed(2).padStart(6)} MB/s  (${res.speedMbps.toFixed(2).padStart(6)} Mbps)`;
      console.log(
        `${idxStr} | ${String(res.statusCode).padEnd(8)} | ${formatBytes(res.bytes).padEnd(12)} | ${res.durationSeconds.toFixed(3).padStart(6)} с    | ${speedStr}`
      );
    }
  }

  const wallDuration = (performance.now() - wallStart) / 1000;
  printSummary(results, wallDuration);
}

function printSummary(results, wallDuration) {
  console.log('='.repeat(72));
  console.log('                      ИТОГОВЫЕ РЕЗУЛЬТАТЫ');
  console.log('='.repeat(72));

  const successful = results.filter((r) => !r.error && r.bytes > 0);
  const totalRequests = results.length;
  const successCount = successful.length;

  if (successCount === 0) {
    console.log('Все запросы завершились с ошибкой. Проверьте адрес и сетевое соединение.');
    console.log('='.repeat(72));
    return;
  }

  const totalBytes = successful.reduce((acc, r) => acc + r.bytes, 0);
  const totalDownloadTime = successful.reduce((acc, r) => acc + r.durationSeconds, 0);
  const avgRequestTime = totalDownloadTime / successCount;
  const minTime = Math.min(...successful.map((r) => r.durationSeconds));
  const maxTime = Math.max(...successful.map((r) => r.durationSeconds));

  const avgSpeedBytesSec = totalDownloadTime > 0 ? totalBytes / totalDownloadTime : 0;
  const avgSpeedMBps = avgSpeedBytesSec / 1_000_000;
  const avgSpeedMiBps = avgSpeedBytesSec / (1024 * 1024);
  const avgSpeedMbps = (avgSpeedBytesSec * 8) / 1_000_000;

  console.log(` Успешных запросов           : ${successCount} из ${totalRequests}`);
  console.log(` Общий объём скачанных данных: ${formatBytes(totalBytes)} (${totalBytes.toLocaleString('ru-RU')} байт)`);
  console.log(` Общее время скачивания      : ${totalDownloadTime.toFixed(3)} с (астрономическое: ${wallDuration.toFixed(3)} с)`);
  console.log(` Среднее время запроса       : ${avgRequestTime.toFixed(3)} с (${(avgRequestTime * 1000).toFixed(1)} мс)`);
  console.log(` Мин. / Макс. время запроса  : ${minTime.toFixed(3)} с / ${maxTime.toFixed(3)} с`);
  console.log('-'.repeat(72));
  console.log(' СКОРОСТЬ СКАЧИВАНИЯ:');
  console.log(`   ► ${avgSpeedMbps.toFixed(2).padStart(8)} Mbps (Мегабит в секунду — стандарт телекома/провайдеров)`);
  console.log(`   ► ${avgSpeedMBps.toFixed(2).padStart(8)} MB/s (Мегабайт в секунду, 10^6 байт/с)`);
  console.log(`   ► ${avgSpeedMiBps.toFixed(2).padStart(8)} MiB/s (Мебибайт в секунду, 2^20 байт/с)`);
  console.log('='.repeat(72));
}

main().catch((err) => {
  console.error('Непредвиденная ошибка:', err);
  process.exit(1);
});
