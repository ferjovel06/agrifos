param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$expectedPorts = @(54331, 54332, 54334, 8010)
$listeners = @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in $expectedPorts })
foreach ($port in $expectedPorts) {
    $matches = @($listeners | Where-Object { $_.LocalPort -eq $port })
    if ($matches.Count -ne 1 -or $matches[0].LocalAddress -ne '127.0.0.1') {
        throw "FAIL: expected exactly one loopback listener on port $port."
    }
}
$listeners | Select-Object LocalAddress, LocalPort, OwningProcess |
    ConvertTo-Json | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Output 'PASS: Windows confirms four native TCP listeners on 127.0.0.1.'
