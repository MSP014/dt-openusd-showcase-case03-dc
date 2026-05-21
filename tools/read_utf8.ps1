param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Path,
    [int]$TotalCount = 0
)

$resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop

if ($TotalCount -gt 0) {
    Get-Content -LiteralPath $resolved -Encoding utf8 -TotalCount $TotalCount
}
else {
    Get-Content -LiteralPath $resolved -Encoding utf8
}
