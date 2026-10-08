param(
    [Parameter(Mandatory = $true)]
    [string[]]$Root,

    [int]$MaxDepth = 5,
    [switch]$SkipOwnerInfo
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$argsList = @()
foreach ($item in $Root) {
    $argsList += "--root"
    $argsList += $item
}
$argsList += "--max-depth"
$argsList += "$MaxDepth"

if ($SkipOwnerInfo) {
    $argsList += "--skip-owner-info"
}

py -3.13 -m storage_crawler.main @argsList
