@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PYRSS=C:\Users\Administrator\.workbuddy\binaries\python\envs\rss\Scripts\python.exe"
set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"

echo ================================================
echo   AI 日报看板 - 一键更新（RSS 抓取 + 生成）
echo ================================================
echo.

if not exist "%PYRSS%" (
  echo [x] 找不到 RSS 虚拟环境: %PYRSS%
  echo     它应该包含 feedparser。请先重建该 venv。
  pause & exit /b 1
)

echo [1/5] 从 RSS 抓取最新资讯（零 token）...
"%PYRSS%" fetch_rss.py --hours 48 -o "data\today.json"
if errorlevel 1 (
  echo.
  echo [x] 抓取失败。
  pause & exit /b 1
)

echo.
echo [2/5] 生成 HTML 页面...
"%PY%" build.py "data\today.json" -o "data\latest.html"
if errorlevel 1 (
  echo [x] 生成失败。
  pause & exit /b 1
)

echo.
echo [3/5] 归档当天副本...
"%PY%" -c "import shutil,pathlib,datetime; d=datetime.date.today().isoformat(); src=pathlib.Path('data/latest.html'); dst=pathlib.Path('data')/f'{d}.html'; shutil.copyfile(src,dst); print(f'  已归档 data\\{d}.html')"
if errorlevel 1 (
  echo [x] 归档失败。
  pause & exit /b 1
)

echo.
echo [4/5] 校验产物...
"%PY%" -c "import sys,pathlib,re; t=pathlib.Path('data/latest.html').read_text(encoding='utf-8'); n=t.count('<article class=\"card'); s=t.count('<section class=\"section\"'); bad=t.count('\ufffd'); h=re.search(r'<h1>(.*?)</h1>',t); h=re.sub(r'<[^>]+>','',h.group(1)) if h else '?'; CN=re.compile(r'[\u4e00-\u9fff]'); LT=re.compile(r'[A-Za-z]'); tt=re.findall(r'<h3 class=\"card-title\">(.*?)</h3>',t); en=[x for x in tt if len(CN.findall(x))/max(len(x),1)<0.15 and len(LT.findall(x))>=8]; print(f'  卡片 {n} 张 / 板块 {s} 个 / 乱码 {bad} 处 / 英文标题 {len(en)} 条'); print(f'  主标题: {h}'); [print(f'   [EN] {x[:60]}') for x in en]; sys.exit(1 if (n==0 or s<4 or bad or en) else 0)"
if errorlevel 1 (
  echo.
  echo [x] 校验未通过，页面可能不完整。
  pause & exit /b 1
)

echo.
echo [5/5] 清理过期归档（保留最近 30 天）...
"%PY%" clean_cache.py --days 30
if errorlevel 1 (
  echo [!] 清理有文件失败，但不影响页面生成，继续。
)

echo.
echo [v] 完成！正在打开页面...
start "" "data\latest.html"
echo.
echo 产物: %~dp0data\latest.html
echo 数据: %~dp0data\today.json
echo.
echo 提示：clean_cache.py --days N 可调整保留天数（默认 30）
