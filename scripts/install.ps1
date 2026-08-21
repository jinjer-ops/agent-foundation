[CmdletBinding()]
param(
    [string]$FoundationRoot,
    [string]$PrivateRoot = (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'agent-private'),
    [switch]$IncludePrivateOverlay
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($FoundationRoot)) {
    $FoundationRoot = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        (Get-Location).Path
    } else {
        Split-Path -Parent $PSScriptRoot
    }
}
$userProfilePath = [Environment]::GetFolderPath('UserProfile')
$codexHome = Join-Path $userProfilePath '.codex'
$claudeHome = Join-Path $userProfilePath '.claude'
$sharedRules = Join-Path $FoundationRoot 'AGENTS.md'
$privateRules = Join-Path $PrivateRoot 'AGENTS.md'

if (-not (Test-Path -LiteralPath $sharedRules)) {
    throw "Shared rules not found: $sharedRules"
}

New-Item -ItemType Directory -Force -Path $codexHome, $claudeHome | Out-Null

# Codex does not support Claude-style @ imports in AGENTS.md, so build a clearly
# marked cache. The editable sources remain in agent-foundation and agent-private.
$codexContent = @(
    '# GENERATED FILE — edit agent-foundation/AGENTS.md, not this file.',
    '',
    (Get-Content -Raw -LiteralPath $sharedRules)
)
if ($IncludePrivateOverlay) {
    if (-not (Test-Path -LiteralPath $privateRules)) { throw "Private overlay not found: $privateRules" }
    $codexContent += @('', '# Local-only overlay', '', (Get-Content -Raw -LiteralPath $privateRules))
}
Set-Content -LiteralPath (Join-Path $codexHome 'AGENTS.md') -Value ($codexContent -join "`n") -Encoding utf8

$claudeContent = @(
    '# GENERATED FILE — edit agent-foundation/AGENTS.md, not this file.',
    "@$sharedRules"
)
if ($IncludePrivateOverlay) { $claudeContent += "@$privateRules" }
Set-Content -LiteralPath (Join-Path $claudeHome 'CLAUDE.md') -Value ($claudeContent -join "`n") -Encoding utf8

foreach ($skillName in @('audit', 'github-publish', 'project-handover')) {
    $source = Join-Path (Join-Path $FoundationRoot 'skills') $skillName
    foreach ($skillRoot in @(
        (Join-Path $codexHome 'skills'),
        (Join-Path $claudeHome 'skills')
    )) {
        New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
        $target = Join-Path $skillRoot $skillName
        if (Test-Path -LiteralPath $target) {
            $item = Get-Item -LiteralPath $target -Force
            if ($item.LinkType -ne 'Junction' -and $item.LinkType -ne 'SymbolicLink') {
                throw "Refusing to replace existing non-link skill: $target"
            }
            Remove-Item -LiteralPath $target -Force
        }
        New-Item -ItemType Junction -Path $target -Target $source | Out-Null
    }
}

Write-Host 'Installed shared agent foundation adapters. Restart each agent session to reload global guidance.'
