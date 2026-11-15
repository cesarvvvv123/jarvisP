# Ambil versi terbaru Jarvis dari GitHub (branch main). Dipanggil jarvis.bat sebelum start.
# Aman: --ff-only tidak pernah menimpa perubahan lokal (git menolak kalau bentrok).
# Exit code: 0 = tidak ada perubahan / dilewati, 1 = gagal (pakai versi yang ada), 2 = berhasil diperbarui.
$ErrorActionPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot
if (-not (Get-Command git)) { exit 0 }
if (-not (Test-Path .git)) { exit 0 }
$branch = git rev-parse --abbrev-ref HEAD
if ($branch -ne 'main') {
    Write-Host "[update] Dilewati: sedang di branch $branch, bukan main."
    exit 0
}
New-Item -ItemType Directory -Force logs | Out-Null
$log = Join-Path $PSScriptRoot 'logs\update.log'
$old = git rev-parse HEAD
Write-Host '[update] Cek pembaruan...'
Add-Content $log ("=== " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
$out = git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=5 pull --ff-only -q origin main 2>&1
$code = $LASTEXITCODE
if ($out) { Add-Content $log ($out | Out-String) }
if ($code -ne 0) {
    Write-Host '[update] Gagal ambil pembaruan, pakai versi yang ada. Lihat logs\update.log'
    exit 1
}
if ((git rev-parse HEAD) -ne $old) {
    Write-Host '[update] Diperbarui ke versi terbaru.'
    Add-Content $log ("diperbarui: " + $old.Substring(0, 7) + " -> " + (git rev-parse --short HEAD))
    exit 2
}
Write-Host '[update] Sudah versi terbaru.'
exit 0
