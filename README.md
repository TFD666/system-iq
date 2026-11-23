[IO.File]::WriteAllText((Join-Path (Get-Location).Path "README.md"), (Get-Clipboard -Raw), (New-Object Text.UTF8Encoding $false))
(Select-String -Path README.md -Pattern "^## ").Count
Select-String -Path README.md -Pattern "keep-alive|demo video|coming soon|\\\\"
git diff --stat