[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

$required = @(
    'AGENTS.md',
    'README.md',
    'skills/audit/SKILL.md',
    'skills/github-publish/SKILL.md',
    'skills/project-handover/SKILL.md'
)

$missing = $required | Where-Object { -not (Test-Path -LiteralPath (Join-Path $Root $_)) }
if ($missing) {
    throw "Missing foundation files: $($missing -join ', ')"
}

$forbiddenPatterns = @(
    '(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*["'']?[A-Za-z0-9_\-]{16,}',
    'C:\\Users\\[^\\\s]+'
)

$files = Get-ChildItem -LiteralPath $Root -Recurse -File |
    Where-Object { $_.FullName -notmatch '\\.git\\|\\private\\' }

$findings = foreach ($file in $files) {
    foreach ($pattern in $forbiddenPatterns) {
        Select-String -LiteralPath $file.FullName -Pattern $pattern -AllMatches | ForEach-Object {
            [PSCustomObject]@{ File = $_.Path; Line = $_.LineNumber; Match = $_.Matches[0].Value }
        }
    }
}

if ($findings) {
    $findings | Format-Table -AutoSize | Out-String | Write-Error
    throw 'Potential private data found in the public foundation.'
}

Write-Host "Foundation layout verified: $Root"
